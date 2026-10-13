"""Agent-based pedestrian simulation with JuPedSim (LGPL-3.0).

Each pedestrian is a JuPedSim agent moving in the continuous walkable geometry
with the Collision-Free Speed Model (Tordeux et al. 2016) or the Social Force
Model (Helbing & Molnar 1995). Collision avoidance and local interaction are
handled by JuPedSim. This module adds the operational layer:

* Poisson arrivals at entry gates (with scheduled reductions/closures); arrivals
  that cannot be placed because the gate area is full wait in an entry queue,
* trip plans (holding area -> destination -> exit) resolved on the pedestrian
  network and given to JuPedSim as waypoint journeys,
* dwelling in holding/bathing areas (direct steering to a point in the area),
* diversions, mid-run corridor closures and evacuation re-routing.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import jupedsim as jps
import numpy as np
import shapely
from shapely.geometry import Point

from ..geo.catalog import SURFACE_SPEED_FACTOR
from ..geo.routing import RoutingError
from ..geo.site_model import Grid, SiteModel
from .config import ScenarioConfig
from .planning import LegSpec, TripPlanner
from .recorder import Recorder

ENGINE_NAME = "jupedsim"
POOL_POINTS = 24  # interior target points per area


class Cancelled(Exception):
    pass


@dataclass
class AgentState:
    plan: list[LegSpec]
    leg: int
    state: str  # move | approach | dwell
    speed: float
    entry_gate: str | None
    arrival_t: float
    spawn_t: float
    path: list[int] = field(default_factory=list)
    dwell_until: float = 0.0
    area: str | None = None
    exit_target: str | None = None
    evacuee: bool = False
    zone_at_trigger: str | None = None


def _sample_in(poly, rng, n=1, tries=200):
    minx, miny, maxx, maxy = poly.bounds
    pts = []
    for _ in range(tries):
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        if poly.contains(Point(x, y)):
            pts.append((x, y))
            if len(pts) >= n:
                break
    return pts


class JuPedSimEngine:
    name = ENGINE_NAME

    @staticmethod
    def version() -> str:
        return f"JuPedSim {jps.__version__}"

    def run(self, model: SiteModel, cfg: ScenarioConfig, thresholds: dict, progress=None, cancelled=None) -> dict:
        t_wall = time.time()
        rng = np.random.default_rng(cfg.seed)
        planner = TripPlanner(model, cfg)
        dt = cfg.time_step_s
        walk = model.walkable
        if cfg.pedestrian_model == "SocialForceModel":
            sim_model = jps.SocialForceModel()
        else:
            sim_model = jps.CollisionFreeSpeedModel()
        sim = jps.Simulation(model=sim_model, geometry=walk, dt=dt)
        events: list[dict] = []
        warnings = list(model.warnings)
        warn_counts: dict[str, int] = {}
        unroutable: dict[str, int] = {}

        def warn(msg: str):
            if msg not in warn_counts:
                warnings.append(msg)
            warn_counts[msg] = warn_counts.get(msg, 0) + 1

        # ---------------------------------------------------- stages/journeys
        wp_stage: dict[tuple, int] = {}
        exit_stage: dict[str, int] = {}
        journeys: dict[tuple, tuple[int, int]] = {}
        ds_stage = sim.add_direct_steering_stage()
        ds_journey = sim.add_journey(jps.JourneyDescription([ds_stage]))
        walk_inner = walk.buffer(-cfg.agent_radius_m - 0.05)

        def waypoint(pt: tuple[float, float], radius: float) -> int:
            key = (round(pt[0], 1), round(pt[1], 1), round(radius, 1))
            if key not in wp_stage:
                p = Point(pt)
                if not walk_inner.contains(p):  # nudge into the walkable area
                    q = shapely.ops.nearest_points(walk_inner, p)[0] if not walk_inner.is_empty else p
                    pt = (q.x, q.y)
                wp_stage[key] = sim.add_waypoint_stage(pt, radius)
            return wp_stage[key]

        def exit_for(target_id: str) -> int:
            if target_id not in exit_stage:
                if target_id in model.gates:
                    g = model.gates[target_id]
                    poly = g.point.buffer(max(g.width / 2.0, 1.5)).intersection(walk)
                else:  # assembly point: arriving inside the area counts as evacuated
                    poly = model.areas[target_id].polygon.intersection(walk).buffer(-1.0)
                    if poly.is_empty:
                        poly = model.areas[target_id].polygon.intersection(walk)
                if poly.geom_type == "MultiPolygon":
                    poly = max(poly.geoms, key=lambda q: q.area)
                exit_stage[target_id] = sim.add_exit_stage(poly)
            return exit_stage[target_id]

        area_pool: dict[str, list[tuple[float, float]]] = {}
        area_geom: dict[str, object] = {}
        for a in model.areas.values():
            usable = a.polygon.intersection(walk).buffer(-0.6)
            if usable.is_empty:
                usable = a.polygon.intersection(walk)
            area_geom[a.id] = usable
            shapely.prepare(usable)
            area_pool[a.id] = _sample_in(usable, rng, POOL_POINTS) or [(usable.centroid.x, usable.centroid.y)]

        # slow zones (stairs / ghat steps): desired speed is scaled while inside them
        slow_zones = []
        for g_, fac in model.speed_zones:
            shapely.prepare(g_)
            slow_zones.append((g_, fac))

        def node_xy(n: int) -> tuple[float, float]:
            p = model.nodes[n]
            return (p.x, p.y)

        def waypoints_for(path: list[int], leg: LegSpec) -> list[int]:
            stages = []
            inner = path[1:] if len(path) > 1 else []
            for i, n in enumerate(inner):
                kind = model.node_kind.get(n, "")
                last = i == len(inner) - 1
                if kind.startswith("area:") or kind.startswith("gate:"):
                    if last:
                        break
                    continue
                link = model.link_between(path[i], n)
                stages.append(waypoint(node_xy(n), min(max(1.0, link.width * 0.4), 4.0)))
            return stages

        def journey_for(stage_ids: list[int]) -> tuple[int, int]:
            key = tuple(stage_ids)
            if key not in journeys:
                jd = jps.JourneyDescription(stage_ids)
                for a_, b_ in zip(stage_ids[:-1], stage_ids[1:]):
                    jd.set_transition_for_stage(a_, jps.Transition.create_fixed_transition(b_))
                journeys[key] = (sim.add_journey(jd), stage_ids[0])
            return journeys[key]

        agents: dict[int, AgentState] = {}
        evacuating = False

        def start_leg(aid: int | None, st: AgentState, src: int, t: float, pos=None,
                      path: list[int] | None = None) -> tuple[int, int, tuple] | None:
            """Plan the current leg; switch the agent (or return journey for a new agent)."""
            leg = st.plan[st.leg]
            if leg.kind == "dwell" and pos is not None and area_geom[leg.target_id].contains(Point(pos)):
                st.state, st.area = "dwell", leg.target_id
                st.dwell_until = t + leg.dwell_s * rng.uniform(0.75, 1.25)
                tgt = area_pool[leg.target_id][rng.integers(len(area_pool[leg.target_id]))]
                return _assign(aid, ds_journey, ds_stage, tgt)
            if path is None:
                path = planner.sample_route(src, leg, t, rng, evacuating=st.evacuee)
            st.path = path
            stages = waypoints_for(path, leg)
            if leg.kind == "dwell":
                pool = area_pool[leg.target_id]
                stages.append(waypoint(pool[rng.integers(len(pool))], 1.5))
                st.state, st.area = "approach", leg.target_id
            else:
                tid = planner.node_target_id(path[-1])
                st.exit_target = tid
                stages.append(exit_for(tid))
                st.state = "move"
            jid, sid = journey_for(stages)
            return _assign(aid, jid, sid, None)

        def _assign(aid, jid, sid, target):
            if aid is None:
                return jid, sid, target
            sim.switch_agent_journey(aid, jid, sid)
            if target is not None:
                sim.agent(aid).target = target
            return jid, sid, target

        def add_agent(pos, st: AgentState, src_node: int, t: float) -> int | None:
            jid, sid, target = start_leg(None, st, src_node, t, pos)
            if cfg.pedestrian_model == "SocialForceModel":
                params = jps.SocialForceModelAgentParameters(position=pos, journey_id=jid, stage_id=sid,
                                                             desired_speed=st.speed, radius=cfg.agent_radius_m)
            else:
                params = jps.CollisionFreeSpeedModelAgentParameters(position=pos, journey_id=jid, stage_id=sid,
                                                                    desired_speed=st.speed, radius=cfg.agent_radius_m)
            aid = sim.add_agent(params)
            if target is not None:
                sim.agent(aid).target = target
            agents[aid] = st
            return aid

        ws = cfg.walking_speed

        def draw_speed() -> float:
            for _ in range(20):
                v = rng.normal(ws.mean, ws.sd)
                if ws.min <= v <= ws.max:
                    return float(v)
            return float(np.clip(ws.mean, ws.min, ws.max))

        # ---------------------------------------------------- initial population
        for ip in cfg.initial_population:
            a = model.areas[ip.zone_id]
            if ip.count == 0:
                continue
            try:
                pos = jps.distribute_by_number(polygon=_largest(area_geom[a.id]), number_of_agents=ip.count,
                                               distance_to_agents=2 * cfg.agent_radius_m + 0.15,
                                               distance_to_polygon=cfg.agent_radius_m + 0.1, seed=int(rng.integers(1 << 30)))
            except Exception as exc:
                raise ValueError(f"initial population of {ip.count} does not fit into '{a.id}' ({exc})") from exc
            for p in pos:
                st = AgentState(plan=[LegSpec("dwell", a.id, ip.dwell_s), LegSpec("exit", None)], leg=0,
                                state="dwell", speed=draw_speed(), entry_gate=None, arrival_t=0.0, spawn_t=0.0)
                add_agent(p, st, a.node, 0.0)

        # ---------------------------------------------------- arrivals
        spawn_geom = {}
        for d in cfg.demand:
            g = model.gates[d.gate_id]
            reg = g.point.buffer(max(g.width / 2.0, 3.0)).intersection(walk_inner)
            if reg.is_empty:
                raise ValueError(f"entry gate {g.id} has no free walkable space around it")
            spawn_geom[d.gate_id] = reg
        queues: dict[str, list[float]] = {d.gate_id: [] for d in cfg.demand}
        arrivals_cum: dict[str, int] = {d.gate_id: 0 for d in cfg.demand}
        restr = cfg.entry_restrictions

        def rate_at(d, t):
            if t < d.start_s or (d.end_s is not None and t >= d.end_s):
                return 0.0
            mult = 1.0
            for r in restr:
                if r.gate_id == d.gate_id and t >= r.start_s and (r.end_s is None or t < r.end_s):
                    mult = min(mult, r.rate_multiplier)
            return d.rate_per_min / 60.0 * mult

        # ---------------------------------------------------- recording
        grid = Grid.for_model(model, cfg.density_grid_cell_m)
        rec = Recorder(model, grid, cfg.output_interval_s, thresholds["limits"].get("default", 2.0))
        queue_series: dict[str, list[int]] = {g: [] for g in queues}
        arrivals_series: dict[str, list[int]] = {g: [] for g in queues}
        exit_counts: dict[str, int] = {}
        exit_series: dict[str, list[int]] = {}
        queued_series: list[int] = []
        trips: list[dict] = []
        evac_info: dict | None = None
        turned_away = 0

        n_steps = int(round(cfg.duration_s / dt))
        out_every = max(1, int(round(cfg.output_interval_s / dt)))
        check_every = max(1, int(round(0.5 / dt)))
        div = cfg.diversion
        ev = cfg.evacuation
        div_done = False
        pending_geom = None
        last_xy: dict[int, tuple[float, float]] = {}

        def record(t):
            ids, xs, ys, moving = [], [], [], []
            for ag in sim.agents():
                if ag.id not in agents:  # reported as removed; JuPedSim drops it next iteration
                    continue
                ids.append(ag.id)
                x, y = ag.position
                xs.append(x)
                ys.append(y)
                moving.append(agents[ag.id].state != "dwell")
            ids_a = np.array(ids, dtype=int)
            xs_a, ys_a = np.array(xs), np.array(ys)
            # pedestrians who want to move but progress < 0.3 m/s are counted as queued/congested
            nq = 0
            for i, aid in enumerate(ids):
                if moving[i] and aid in last_xy:
                    px, py = last_xy[aid]
                    if math.hypot(xs[i] - px, ys[i] - py) < 0.3 * cfg.output_interval_s:
                        nq += 1
            last_xy.clear()
            last_xy.update({aid: (xs[i], ys[i]) for i, aid in enumerate(ids)})
            queued_series.append(nq)
            rec.record_frame(t, xs_a, ys_a, ids=ids_a)
            for gid in queues:
                queue_series[gid].append(len(queues[gid]))
                arrivals_series[gid].append(arrivals_cum[gid])
            for gid in exit_series:
                exit_series[gid].append(exit_counts.get(gid, 0))

        for g_ in [g for g in model.exit_gates()] + [model.areas[a] for a in (ev.assembly_point_ids if ev else []) if a in model.areas]:
            exit_series.setdefault(g_.id, [])

        record(0.0)
        for step in range(1, n_steps + 1):
            t = step * dt
            # arrivals
            if not (evacuating and ev and ev.stop_arrivals):
                for d in cfg.demand:
                    lam = rate_at(d, t) * dt
                    if lam > 0:
                        k = rng.poisson(lam)
                        if k:
                            queues[d.gate_id].extend([t] * k)
                            arrivals_cum[d.gate_id] += k
            # place queued arrivals into the simulation if there is space
            for gid, q in queues.items():
                placed = 0
                while q and placed < 20:
                    cand = _sample_in(spawn_geom[gid], rng, 1, tries=30)
                    if not cand or any(True for _ in sim.agents_in_range(cand[0], 2 * cfg.agent_radius_m + 0.1)):
                        break
                    st = AgentState(plan=planner.sample_arrival_plan(t, rng), leg=0, state="move", speed=draw_speed(),
                                    entry_gate=gid, arrival_t=q.pop(0), spawn_t=t)
                    try:
                        add_agent(cand[0], st, model.gates[gid].node, t)
                    except RoutingError as exc:
                        # no route: the arrival stays in the entry queue (stranded at the gate)
                        q.insert(0, st.arrival_t)
                        unroutable[gid] = unroutable.get(gid, 0) + 1
                        warn(f"{gid}: arrivals cannot reach their destination ({exc})")
                        break
                    placed += 1

            sim.iterate()
            for aid in sim.removed_agents():
                st = agents.pop(aid, None)
                if st is None:
                    continue
                last_xy.pop(aid, None)
                tgt = st.exit_target or "unknown"
                exit_counts[tgt] = exit_counts.get(tgt, 0) + 1
                exit_series.setdefault(tgt, [0] * len(rec.times))
                trips.append({"entry": st.entry_gate, "exit": tgt, "arrival_t": st.arrival_t, "spawn_t": st.spawn_t,
                              "exit_t": t, "evacuee": st.evacuee, "zone": st.zone_at_trigger})

            # diversion / closure
            if div and not div_done and t >= div.activation_s:
                div_done = True
                closed = planner.closed_div
                n_rr = 0
                if div.reroute_existing and closed:
                    for aid, st in list(agents.items()):
                        if st.state == "dwell":
                            continue
                        if any((lk := _link(model, u, v)) is not None and lk.corridor_id in closed
                               for u, v in zip(st.path[:-1], st.path[1:])):
                            pos = sim.agent(aid).position
                            src = planner.nearest_node(*pos, planner.g_div)
                            try:
                                start_leg(aid, st, src, t, pos)
                                n_rr += 1
                            except RoutingError:
                                warn("some pedestrians have no alternative route after the closure")
                events.append({"t": t, "type": "diversion", "text": f"Diversion activated; closed {sorted(closed) or 'none'}; {n_rr} pedestrians re-routed"})
                if closed:
                    pending_geom = _without(model, closed)

            if ev and not evacuating and t >= ev.trigger_s:
                evacuating = True
                turned_away = sum(len(q) for q in queues.values())
                for q in queues.values():
                    q.clear()
                evac_info = self._trigger_evacuation(sim, agents, planner, start_leg, t, rng, ev, warnings)
                events.append({"t": t, "type": "evacuation", "text": f"Evacuation triggered: {evac_info['evacuees']} evacuees, strategy {ev.strategy}"})
                if planner.closed_evac:
                    pending_geom = _without(model, planner.closed_evac)

            if step % check_every == 0:
                ids_l = list(agents.keys())
                if pending_geom is not None and ids_l:
                    xy = np.array([sim.agent(a).position for a in ids_l])
                    if shapely.contains_xy(pending_geom, xy[:, 0], xy[:, 1]).all():
                        try:
                            sim.switch_geometry(pending_geom)
                            events.append({"t": t, "type": "closure", "text": "Closed corridors physically removed from the walkable area"})
                        except Exception as exc:  # pragma: no cover - engine specific
                            warnings.append(f"closure enforced by routing only ({exc})")
                        pending_geom = None
                for aid in ids_l:
                    st = agents[aid]
                    ag = sim.agent(aid)
                    if st.state == "approach":
                        if area_geom[st.area].contains(Point(ag.position)):
                            leg = st.plan[st.leg]
                            st.state = "dwell"
                            st.dwell_until = t + leg.dwell_s * rng.uniform(0.75, 1.25)
                            pool = area_pool[st.area]
                            _assign(aid, ds_journey, ds_stage, pool[rng.integers(len(pool))])
                    elif st.state == "dwell" and t >= st.dwell_until and not st.evacuee:
                        st.leg += 1
                        if st.leg >= len(st.plan):
                            st.plan.append(LegSpec("exit", None))
                        src = model.areas[st.area].node
                        try:
                            start_leg(aid, st, src, t, ag.position)
                        except RoutingError as exc:
                            warn(f"pedestrians in {model.areas[st.area].name} cannot continue ({exc})")
                            st.dwell_until = t + 30
                    if slow_zones:
                        f = 1.0
                        p = Point(ag.position)
                        for g_, fac in slow_zones:
                            if g_.contains(p):
                                f = min(f, fac)
                        ag.model.desired_speed = st.speed * f

            if step % out_every == 0:
                record(t)
            if progress and step % 200 == 0:
                progress(step / n_steps, f"t={t:.0f}s, {sim.agent_count()} agents")
            if cancelled and step % 50 == 0 and cancelled():
                raise Cancelled()

        remaining = [{"entry": st.entry_gate, "arrival_t": st.arrival_t, "spawn_t": st.spawn_t, "evacuee": st.evacuee,
                      "zone": st.zone_at_trigger} for st in agents.values()]
        return {
            "engine": ENGINE_NAME,
            "engine_version": self.version(),
            "method": f"Agent-based simulation (JuPedSim {cfg.pedestrian_model})",
            "method_type": "agent_based",
            "rec": rec,
            "grid": grid,
            "queues": queue_series,
            "arrivals": arrivals_series,
            "exits": exit_series,
            "queued": queued_series,
            "trips": trips,
            "remaining": remaining,
            "remaining_count": float(len(remaining)),
            "turned_away": turned_away,
            "unroutable": unroutable,
            "events": events,
            "warnings": warnings[:200],
            "evacuation": evac_info,
            "wall_time_s": time.time() - t_wall,
        }

    # ------------------------------------------------------------------
    def _trigger_evacuation(self, sim, agents, planner: TripPlanner, start_leg, t, rng, ev, warnings) -> dict:
        model = planner.model
        g = planner.g_evac
        zones = ev.affected_zone_ids
        node_of: dict[int, int] = {}
        sources: dict[int, float] = {}
        node_zone: dict[int, str | None] = {}
        all_zone_ids = list(model.zones.keys())
        for aid, st in agents.items():
            x, y = sim.agent(aid).position
            zone = planner.zone_of(x, y, zones) if zones else planner.zone_of(x, y, all_zone_ids)
            if zones and zone is None:
                continue
            st.zone_at_trigger = zone
            n = planner.nearest_node(x, y, g)
            node_of[aid] = n
            sources[n] = sources.get(n, 0) + 1
            if zone and n not in node_zone:
                node_zone[n] = zone
        routes, plan = planner.evac_routes(sources, node_zone)
        unreachable = 0
        for aid, n in node_of.items():
            st = agents[aid]
            opts = routes.get(n) or []
            if not opts:
                unreachable += 1
                continue
            p = np.array([w for _, w in opts])
            path = opts[rng.choice(len(opts), p=p / p.sum())][0]
            target = planner.node_target_id(path[-1])
            st.evacuee = True
            st.plan = [LegSpec("exit", target)]
            st.leg = 0
            st.state = "move"
            try:
                start_leg(aid, st, n, t, None, path=path)
            except RoutingError:
                unreachable += 1
        return {
            "trigger_s": t,
            "evacuees": len(node_of),
            "unreachable": unreachable,
            "strategy": ev.strategy,
            "ccrp_estimate_s": plan.clearance_time_s if plan else None,
            "ccrp_sink_load": {planner.node_target_id(k): v for k, v in (plan.sink_load.items() if plan else [])},
        }


def _largest(geom):
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda q: q.area)
    return geom


def _link(model: SiteModel, u: int, v: int):
    try:
        return model.link_between(u, v)
    except KeyError:
        return None


def _without(model: SiteModel, closed: set[str]):
    """Walkable area with the given corridors removed (keeps parts shared with
    other corridors or walkable polygons)."""
    keep = [c.polygon for c in model.corridors.values() if c.enabled and c.id not in closed]
    keep += [a.polygon for a in model.areas.values()]
    removed = shapely.union_all([model.corridors[c].polygon for c in closed if c in model.corridors])
    cut = removed.difference(shapely.union_all(keep)) if keep else removed
    out = model.walkable.difference(cut)
    if out.geom_type == "MultiPolygon":
        out = shapely.MultiPolygon([g for g in out.geoms if g.area > 1.0])
    return out
