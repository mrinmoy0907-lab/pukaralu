"""Trip planning shared by both simulation engines.

A pedestrian's trip is a list of ``LegSpec`` targets (holding area -> destination
-> exit). The concrete network path of each leg is resolved when the leg starts,
using the network state at that time (so diversions and closures activated
during the run affect later legs).
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
from shapely.geometry import Point

from ..geo.routing import CCRPResult, RoutingError, ccrp, nearest_target, route_options
from ..geo.site_model import SiteModel
from .config import Destination, ScenarioConfig


class PlanningError(ValueError):
    pass


@dataclass(frozen=True)
class LegSpec:
    kind: str  # "dwell" | "exit"
    target_id: str | None  # area id for dwell; gate id (or None = nearest) for exit
    dwell_s: float = 0.0


class TripPlanner:
    def __init__(self, model: SiteModel, cfg: ScenarioConfig):
        self.model = model
        self.cfg = cfg
        v = cfg.walking_speed.mean
        self.closed_base: set[str] = set()
        self.g_base = model.graph(mean_speed=v)
        div = cfg.diversion
        self.closed_div = set(div.close_corridors) if div else set()
        self.g_div = model.graph(closed_corridors=self.closed_div, mean_speed=v) if div else self.g_base
        ev = cfg.evacuation
        if ev:
            closed = set(ev.close_corridors) | (self.closed_div if div and div.activation_s <= ev.trigger_s else set())
            # applied only after the trigger (by the engines and the CCRP estimate)
            self.evac_cap_factor = {r.corridor_id: r.capacity_factor for r in ev.capacity_reductions
                                    if r.capacity_factor}
            self.closed_evac = closed
            self.g_evac = model.graph(closed_corridors=closed, allow_emergency=ev.use_emergency_corridors, mean_speed=v)
        else:
            self.closed_evac = set()
            self.g_evac = None
            self.evac_cap_factor = {}
        self._route_cache: dict = {}
        self.validate()

    # ------------------------------------------------------------ validation
    def validate(self) -> None:
        m, cfg = self.model, self.cfg
        errors: list[str] = []

        def _area(aid, what):
            a = m.areas.get(aid)
            if a is None:
                errors.append(f"{what}: unknown area '{aid}'")
            elif a.node is None:
                errors.append(f"{what}: area '{aid}' has no usable walkable area / network connection")
            return a

        for d in cfg.demand:
            g = m.gates.get(d.gate_id)
            if g is None:
                errors.append(f"demand: unknown gate '{d.gate_id}'")
            elif not g.is_entry:
                errors.append(f"demand: gate '{d.gate_id}' is not an enabled entry gate")
            elif g.node is None:
                errors.append(f"demand: gate '{d.gate_id}' is not connected to the network")
        for dest in cfg.destinations + (cfg.diversion.destinations if cfg.diversion else []):
            _area(dest.target_id, "destination")
        hs = 0.0
        for h in cfg.holding_stops:
            a = _area(h.holding_id, "holding stop")
            hs += h.share
            if a is not None and a.pk_type != "holding_area":
                errors.append(f"holding stop '{h.holding_id}' is a {a.pk_type}, not a holding area")
        if hs > 1.0 + 1e-6:
            errors.append("holding stop shares must sum to <= 1 (the remainder walks directly)")
        for p in cfg.initial_population:
            if p.zone_id not in m.areas:
                errors.append(f"initial population: '{p.zone_id}' is not a walkable area polygon")
        for gid in cfg.exit_gate_ids:
            if gid not in m.gates or not m.gates[gid].is_exit:
                errors.append(f"exit '{gid}' is not an enabled exit gate")
        if cfg.evacuation:
            for r in cfg.evacuation.capacity_reductions:
                if r.corridor_id not in m.corridors:
                    errors.append(f"capacity reduction: unknown corridor '{r.corridor_id}'")
        for o in cfg.corridor_overrides:
            if o.corridor_id not in m.corridors:
                errors.append(f"corridor override: unknown corridor '{o.corridor_id}'")
        for cid in self.closed_div | self.closed_evac:
            if cid not in m.corridors:
                errors.append(f"closure: unknown corridor '{cid}'")
        if not self.normal_exits() and (cfg.demand or cfg.initial_population):
            errors.append("no enabled exit gate is connected to the network")
        if cfg.evacuation:
            if not self.evac_targets():
                errors.append("evacuation: no reachable exit or assembly point")
            for z in cfg.evacuation.affected_zone_ids:
                if z not in m.zones:
                    errors.append(f"evacuation: unknown zone '{z}'")
            for a in cfg.evacuation.assignments:
                if a.zone_id not in m.zones:
                    errors.append(f"evacuation assignment: unknown zone '{a.zone_id}'")
                if a.exit_gate_id not in m.gates and a.exit_gate_id not in m.areas:
                    errors.append(f"evacuation assignment: unknown exit '{a.exit_gate_id}'")
        if errors:
            raise PlanningError("; ".join(errors))

    # ------------------------------------------------------------ helpers
    def graph_at(self, t: float, evacuating: bool = False) -> nx.DiGraph:
        if evacuating and self.g_evac is not None:
            return self.g_evac
        if self.cfg.diversion and t >= self.cfg.diversion.activation_s:
            return self.g_div
        return self.g_base

    def closed_at(self, t: float) -> set[str]:
        if self.cfg.diversion and t >= self.cfg.diversion.activation_s:
            return self.closed_div
        return set()

    def normal_exits(self) -> list[int]:
        ids = self.cfg.exit_gate_ids
        gates = [g for g in self.model.exit_gates() if not g.emergency_exit and (not ids or g.id in ids)]
        return [g.node for g in gates]

    def evac_targets(self) -> list[int]:
        ev = self.cfg.evacuation
        if ev is None:
            return []
        gates = [g for g in self.model.exit_gates() if (not ev.exit_gate_ids or g.id in ev.exit_gate_ids)
                 and (ev.use_emergency_corridors or not g.emergency_exit)]
        nodes = [g.node for g in gates]
        for aid in ev.assembly_point_ids:
            a = self.model.areas.get(aid)
            if a is not None and a.node is not None:
                nodes.append(a.node)
        return nodes

    def target_node(self, leg: LegSpec) -> int | None:
        if leg.kind == "dwell":
            return self.model.areas[leg.target_id].node
        if leg.target_id and leg.target_id in self.model.gates:
            return self.model.gates[leg.target_id].node
        if leg.target_id and leg.target_id in self.model.areas:
            return self.model.areas[leg.target_id].node
        return None

    def node_target_id(self, node: int) -> str | None:
        kind = self.model.node_kind.get(node, "")
        return kind.split(":", 1)[1] if ":" in kind else None

    # ------------------------------------------------------------ trip plans
    def _destinations_at(self, t: float) -> list[Destination]:
        if self.cfg.diversion and t >= self.cfg.diversion.activation_s and self.cfg.diversion.destinations:
            return self.cfg.diversion.destinations
        return self.cfg.destinations

    def arrival_plan_options(self, t: float) -> list[tuple[list[LegSpec], float]]:
        """All trip plans for an arrival at time t with their probabilities."""
        dests = self._destinations_at(t)
        tot = sum(d.share for d in dests)
        hold = [(h, h.share) for h in self.cfg.holding_stops]
        direct = max(0.0, 1.0 - sum(s for _, s in hold))
        out = []
        for d in dests:
            pd = d.share / tot
            end = [LegSpec("dwell", d.target_id, d.dwell_s), LegSpec("exit", None)]
            for h, s in hold:
                out.append(([LegSpec("dwell", h.holding_id, h.dwell_s)] + end, pd * s))
            if direct > 1e-9:
                out.append((end, pd * direct))
        return out

    def sample_arrival_plan(self, t: float, rng: np.random.Generator) -> list[LegSpec]:
        opts = self.arrival_plan_options(t)
        if not opts:
            return [LegSpec("exit", None)]
        p = np.array([w for _, w in opts])
        return opts[rng.choice(len(opts), p=p / p.sum())][0]

    def leg_routes(self, src: int, leg: LegSpec, t: float, evacuating: bool = False) -> list[tuple[list[int], float]]:
        """Possible node paths for a leg starting at node ``src`` with probabilities."""
        g = self.graph_at(t, evacuating)
        key = (id(g), src, leg)
        if key in self._route_cache:
            return self._route_cache[key]
        dst = self.target_node(leg)
        if dst is None:  # nearest exit
            targets = self.evac_targets() if evacuating else self.normal_exits()
            res = nearest_target(g, src, targets)
            if res is None:
                raise RoutingError(f"no reachable exit from node {src}")
            dst = res[0]
        rc = self.cfg.route_choice
        opts = route_options(g, src, dst, rc.strategy, rc.k, rc.logit_theta)
        self._route_cache[key] = opts
        return opts

    def sample_route(self, src: int, leg: LegSpec, t: float, rng: np.random.Generator,
                     evacuating: bool = False) -> list[int]:
        opts = self.leg_routes(src, leg, t, evacuating)
        if len(opts) == 1:
            return opts[0][0]
        p = np.array([w for _, w in opts])
        return opts[rng.choice(len(opts), p=p / p.sum())][0]

    # ------------------------------------------------------------ evacuation
    def zone_of(self, x: float, y: float, zone_ids: list[str]) -> str | None:
        pt = Point(x, y)
        for z in zone_ids:
            zz = self.model.zones.get(z)
            if zz is not None and zz["polygon"].contains(pt):
                return z
        return None

    def evac_routes(self, sources: dict[int, float], node_zone: dict[int, str | None]) -> tuple[dict[int, list], CCRPResult | None]:
        """Route distribution per source node for the configured evacuation strategy.

        Also returns the CCRP planning estimate (computed for every strategy as
        a reference value; it is a capacity-based estimate, not a simulation)."""
        ev = self.cfg.evacuation
        g = self.g_evac
        targets = self.evac_targets()
        assigned = {a.zone_id: a.exit_gate_id for a in ev.assignments}
        out: dict[int, list] = {}
        plan = ccrp(self.model, g, sources, targets, mean_speed=self.cfg.walking_speed.mean,
                    cap_factor=self.evac_cap_factor) if sources else None
        for src in sources:
            if ev.strategy == "capacity_aware" and plan is not None and plan.split(src):
                out[src] = plan.split(src)
                continue
            zone = node_zone.get(src)
            tgt_id = assigned.get(zone) if ev.strategy == "assigned" and zone else None
            if tgt_id:
                tnode = self.model.gates[tgt_id].node if tgt_id in self.model.gates else self.model.areas[tgt_id].node
                try:
                    out[src] = route_options(g, src, tnode, "shortest_time")
                    continue
                except RoutingError:
                    pass  # fall back to nearest reachable target
            res = nearest_target(g, src, targets)
            out[src] = [(res[1], 1.0)] if res else []
        return out, plan

    def nearest_node(self, x: float, y: float, g: nx.DiGraph) -> int:
        best, bd = None, float("inf")
        for n in g.nodes:
            p = self.model.nodes[n]
            d = (p.x - x) ** 2 + (p.y - y) ** 2
            if d < bd and not self.model.node_kind.get(n, "").startswith("gate:"):
                best, bd = n, d
        return best
