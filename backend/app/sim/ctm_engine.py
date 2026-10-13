"""Macroscopic pedestrian flow model: multi-commodity Cell Transmission Model.

Method (documented in docs/MODELS.md):

* Every directed network link is divided into cells of length dx >= v_f * dt
  (Daganzo 1994, 1995). Each cell holds a number of pedestrians per commodity
  (a commodity is one routed trip leg, so destinations are preserved).
* Triangular fundamental diagram per link, parameterised from Weidmann (1993):
  free speed v_f (mean desired speed x surface factor), capacity Q = J_max * W
  (J_max = 1.22 p/(m s)), jam density k_j = 5.4 p/m2, congested wave speed
  w = Q / (W (k_j - k_c)) with k_c = Q / (W v_f).
* Sending S_i = min(N_i * min(1, v_f dt/dx), Q dt); receiving
  R_i = min(Q dt, (w dt/dx) (N_jam,i - N_i)); cell flow y = min(S_i, R_i+1),
  composition proportional to the commodities present (FIFO mixing).
* Nodes: demand-proportional merge and FIFO diverge (a link's outflow is
  limited by its most restrictive downstream target).
* The two directions of a two-way corridor share the jam storage of each cell
  (counterflow cannot exceed jam density); each direction keeps the full-width
  flow capacity.
* Areas (holding areas, ghats, plazas ...) are reservoirs: pedestrians who dwell
  there are stored up to a storage limit (0.8 x jam density x usable area) and
  leave at rate N/dwell (first-order, i.e. exponentially distributed dwell).
* Entry gates are point queues; exits are sinks.

This is an aggregate estimate. It does not represent individual pedestrians,
local collision avoidance, or counterflow friction (each direction of a
two-way corridor is given the full width).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import Point

from ..geo.routing import RoutingError, route_options
from ..geo.site_model import JAM_DENSITY, SPECIFIC_FLOW_MAX, Grid, SiteModel
from .config import ScenarioConfig
from .planning import LegSpec, TripPlanner
from .recorder import Recorder

ENGINE_NAME = "macro_ctm"
MODEL_VERSION = "ctm-1.0"
STORAGE_FACTOR = 0.8  # reservoir storage = STORAGE_FACTOR * jam density * usable area


class Cancelled(Exception):
    pass


@dataclass
class Commodity:
    id: int
    links: list[int]
    end: str  # "dwell" | "exit"
    target: str | None  # area id (dwell) or gate/area id (exit)
    dwell_s: float = 0.0
    then: tuple = ()  # remaining LegSpecs after the dwell
    evac: bool = False
    next_of: dict = field(default_factory=dict)


@dataclass
class LinkState:
    id: int
    n: int
    dx: float
    width: float
    vf: float
    q: float  # capacity persons / s (may change during the run)
    N: np.ndarray  # (n, P)
    centres: np.ndarray  # (n, 2)
    pts: np.ndarray  # (n, m, 2) sample points spread over each cell's footprint

    @property
    def njam(self) -> float:
        return JAM_DENSITY * self.width * self.dx


class CTMEngine:
    name = ENGINE_NAME

    @staticmethod
    def version() -> str:
        return f"Pushkaralu CTM {MODEL_VERSION}"

    def run(self, model: SiteModel, cfg: ScenarioConfig, thresholds: dict, progress=None, cancelled=None) -> dict:
        t_wall = time.time()
        rng = np.random.default_rng(cfg.seed)
        planner = TripPlanner(model, cfg)
        dt = cfg.time_step_s
        vmean = cfg.walking_speed.mean
        events: list[dict] = []
        warnings = list(model.warnings)
        warn_counts: dict[str, int] = {}
        unroutable: dict[str, float] = {}

        def warn(msg: str):
            if msg not in warn_counts:
                warnings.append(msg)
            warn_counts[msg] = warn_counts.get(msg, 0) + 1

        # ------------------------------------------------------------ links
        P = 16
        links: dict[int, LinkState] = {}
        for lk in model.links.values():
            vf = vmean * lk.speed_factor
            n = max(1, int(lk.length // (vf * dt)))
            dx = lk.length / n
            centres = np.array([lk.geom.interpolate((i + 0.5) * dx).coords[0] for i in range(n)])
            links[lk.id] = LinkState(lk.id, n, dx, lk.width, vf, lk.capacity_pps, np.zeros((n, P)), centres,
                                     _cell_points(lk.geom, n, dx, lk.width))
        # opposite direction of two-way corridors: they share the physical storage (jam density)
        by_end = {(lk.u, lk.v): lk.id for lk in model.links.values()}
        opposite = {lid: by_end.get((model.links[lid].v, model.links[lid].u)) for lid in links}
        opposite = {a: b for a, b in opposite.items() if b is not None and links[b].n == links[a].n}
        out_links: dict[int, list[int]] = {n: [] for n in model.nodes}
        in_links: dict[int, list[int]] = {n: [] for n in model.nodes}
        for lk in model.links.values():
            out_links[lk.u].append(lk.id)
            in_links[lk.v].append(lk.id)

        commodities: list[Commodity] = []
        cache: dict = {}

        def grow():
            nonlocal P
            newP = P * 2
            for ls in links.values():
                ls.N = np.pad(ls.N, ((0, 0), (0, newP - P)))
            for d in (node_queue, entry_queue, reservoir_by_c):
                for k in d:
                    d[k] = np.pad(d[k], (0, newP - P))
            P = newP

        def make_commodity(path_nodes: list[int], end: str, target, dwell=0.0, then=(), evac=False, first_link=None) -> int:
            lks = [first_link] if first_link is not None else []
            lks += [model.link_between(u, v).id for u, v in zip(path_nodes[:-1], path_nodes[1:])]
            key = (tuple(lks), end, target, round(dwell, 3), then, evac)
            if key in cache:
                return cache[key]
            c = Commodity(len(commodities), lks, end, target, dwell, then, evac)
            c.next_of = {a: b for a, b in zip(lks[:-1], lks[1:])}
            if lks:
                c.next_of[lks[-1]] = None
            commodities.append(c)
            cache[key] = c.id
            if c.id >= P:
                grow()
            return c.id

        def blocked_commodity() -> int:
            key = ("blocked",)
            if key not in cache:
                c = Commodity(len(commodities), [], "blocked", None)
                commodities.append(c)
                cache[key] = c.id
                if c.id >= P:
                    grow()
            return cache[key]

        def chain(src: int, legs: tuple, t: float, evac=False) -> list[tuple[int, float]]:
            """Commodity options for walking leg legs[0] from node src."""
            leg = legs[0]
            rest = legs[1:]
            out = []
            for path, pr in planner.leg_routes(src, leg, t, evacuating=evac):
                if leg.kind == "dwell":
                    out.append((make_commodity(path, "dwell", leg.target_id, leg.dwell_s, rest, evac), pr))
                else:
                    out.append((make_commodity(path, "exit", planner.node_target_id(path[-1]), evac=evac), pr))
            return out

        # ------------------------------------------------------------ queues and reservoirs
        node_queue: dict[int, np.ndarray] = {}  # pedestrians waiting at a node (inside an area)
        entry_queue: dict[int, np.ndarray] = {}  # outside the site at entry gates
        reservoir_by_c: dict[int, np.ndarray] = {}  # dwelling pedestrians per area node, by commodity
        area_of_node = {a.node: a for a in model.areas.values() if a.node is not None}
        storage = {a.node: STORAGE_FACTOR * JAM_DENSITY * a.usable_area for a in area_of_node.values()}
        gate_of_node = {g.node: g for g in model.gates.values() if g.node is not None}

        def vec():
            return np.zeros(P)

        # initial population: dwell in their area then follow remaining legs
        for ip in cfg.initial_population:
            a = model.areas[ip.zone_id]
            cid = make_commodity([a.node], "dwell", a.id, ip.dwell_s, (LegSpec("exit", None),))
            reservoir_by_c.setdefault(a.node, vec())
            reservoir_by_c[a.node] = _fit(reservoir_by_c[a.node], P)
            reservoir_by_c[a.node][cid] += ip.count

        # ------------------------------------------------------------ recording
        grid = Grid.for_model(model, cfg.density_grid_cell_m)
        rec = Recorder(model, grid, cfg.output_interval_s, thresholds["limits"].get("default", 2.0), keep_agents=False)
        area_pts: dict[int, np.ndarray] = {}
        for node, a in area_of_node.items():
            usable = a.polygon.intersection(model.walkable)
            # 2x2 sample points per density-grid cell, aligned with the grid, so area
            # populations map uniformly (no aliasing stripes)
            area_pts[node] = _aligned_points(usable, grid)
        # connector links inside areas converge on the area's centre point; for density
        # mapping their contents are added to the area(s) they belong to and spread uniformly
        area_link_share: dict[int, list[int]] = {}
        for lk in model.links.values():
            if lk.kind == "area":
                owners = [n for n in (lk.u, lk.v) if n in area_pts and len(area_pts[n])]
                if owners:
                    area_link_share[lk.id] = owners
        sec_links = _section_links(model)
        sec_acc: dict[str, float] = {cid: 0.0 for cid in sec_links}

        queue_series = {d.gate_id: [] for d in cfg.demand}
        arrivals_series = {d.gate_id: [] for d in cfg.demand}
        arrivals_cum = {d.gate_id: 0.0 for d in cfg.demand}
        entered_cum = {d.gate_id: 0.0 for d in cfg.demand}
        entered_series = {d.gate_id: [] for d in cfg.demand}
        exit_cum: dict[str, float] = {g.id: 0.0 for g in model.exit_gates()}
        ev = cfg.evacuation
        for aid in (ev.assembly_point_ids if ev else []):
            exit_cum.setdefault(aid, 0.0)
        exit_series: dict[str, list] = {k: [] for k in exit_cum}
        queued_series: list[float] = []
        link_frames: list[list[float]] = []
        evac_exited = 0.0
        turned_away = 0.0
        restr = cfg.entry_restrictions

        def rate_at(d, t):
            if t < d.start_s or (d.end_s is not None and t >= d.end_s):
                return 0.0
            mult = 1.0
            for r in restr:
                if r.gate_id == d.gate_id and t >= r.start_s and (r.end_s is None or t < r.end_s):
                    mult = min(mult, r.rate_multiplier)
            return d.rate_per_min / 60.0 * mult

        def record(t: float):
            xs, ys, ws = [], [], []
            congested = 0.0
            dens_links = []
            extra: dict[int, float] = {}
            for lid, ls in links.items():
                tot = ls.N.sum(1)
                k = tot / (ls.width * ls.dx)
                kc = (ls.q / ls.width) / ls.vf if ls.q > 0 else 0
                congested += float(tot[k > max(kc, 0.5)].sum())
                dens_links.append(round(float(k.mean()), 3))
                owners = area_link_share.get(lid)
                if owners:
                    for n_ in owners:
                        extra[n_] = extra.get(n_, 0.0) + float(tot.sum()) / len(owners)
                    continue
                m = ls.pts.shape[1]
                xs.append(ls.pts[:, :, 0].ravel())
                ys.append(ls.pts[:, :, 1].ravel())
                ws.append(np.repeat(tot / m, m))
            for node, pts in area_pts.items():
                n_here = float(reservoir_by_c.get(node, np.zeros(1)).sum() + node_queue.get(node, np.zeros(1)).sum())
                n_here += extra.get(node, 0.0)
                # always include the points (weight 0 when empty) so the point set is static
                xs.append(pts[:, 0])
                ys.append(pts[:, 1])
                ws.append(np.full(len(pts), n_here / len(pts) if len(pts) else 0.0))
                congested += float(node_queue.get(node, np.zeros(1)).sum())
            x = np.concatenate(xs) if xs else np.zeros(0)
            y = np.concatenate(ys) if ys else np.zeros(0)
            w = np.concatenate(ws) if ws else np.zeros(0)
            flows = {cid: sec_acc[cid] for cid in sec_acc}
            rec.record_frame(t, x, y, weights=w, section_flow=flows, static_points=True)
            for cid in sec_acc:
                sec_acc[cid] = 0.0
            queued_series.append(round(congested, 2))
            link_frames.append(dens_links)
            for gid in queue_series:
                gnode = model.gates[gid].node
                queue_series[gid].append(round(float(entry_queue.get(gnode, np.zeros(1)).sum()), 2))
                arrivals_series[gid].append(round(arrivals_cum[gid], 2))
                entered_series[gid].append(round(entered_cum[gid], 2))
            for k in exit_series:
                exit_series[k].append(round(exit_cum.get(k, 0.0), 2))

        # ------------------------------------------------------------ main loop
        n_steps = int(round(cfg.duration_s / dt))
        out_every = max(1, int(round(cfg.output_interval_s / dt)))
        div = cfg.diversion
        div_done = False
        evacuating = False
        closed: set[str] = set()
        evac_info = None
        link_ids = list(links.keys())
        record(0.0)
        for step in range(1, n_steps + 1):
            t = step * dt
            # arrivals -> entry queues (expected values: the macroscopic model is deterministic)
            if not (evacuating and ev and ev.stop_arrivals):
                for d in cfg.demand:
                    a_ = rate_at(d, t) * dt
                    if a_ <= 0:
                        continue
                    g = model.gates[d.gate_id]
                    q = entry_queue.setdefault(g.node, vec())
                    q = entry_queue[g.node] = _fit(q, P)
                    for plan, pp in planner.arrival_plan_options(t):
                        try:
                            opts = chain(g.node, tuple(plan), t)
                        except RoutingError as exc:
                            # no route: arrivals stay in the entry queue (stranded at the gate)
                            warn(f"{d.gate_id}: arrivals cannot reach their destination ({exc})")
                            unroutable[d.gate_id] = unroutable.get(d.gate_id, 0.0) + a_ * pp
                            opts = [(blocked_commodity(), 1.0)]
                        for cid, pr in opts:
                            q = entry_queue[g.node] = _fit(entry_queue[g.node], P)
                            q[cid] += a_ * pp * pr
                    arrivals_cum[d.gate_id] += a_

            # diversion / closures
            if div and not div_done and t >= div.activation_s:
                div_done = True
                closed = set(planner.closed_div)
                if closed and div.reroute_existing:
                    n_rr = self._reroute(model, planner, links, node_queue, entry_queue, commodities, make_commodity, closed, t, P)
                else:
                    n_rr = 0.0
                events.append({"t": t, "type": "diversion", "text": f"Diversion activated; closed {sorted(closed) or 'none'}; {n_rr:.0f} pedestrians re-routed"})

            if ev and not evacuating and t >= ev.trigger_s:
                evacuating = True
                if ev.stop_arrivals:
                    turned_away = sum(float(q.sum()) for q in entry_queue.values())
                    for k in entry_queue:
                        entry_queue[k][:] = 0
                closed = set(planner.closed_evac)
                for cid_, f in planner.evac_cap_factor.items():
                    for lk in model.links.values():
                        if lk.corridor_id == cid_:
                            links[lk.id].q = lk.capacity_pps * f
                evac_info = self._trigger_evac(model, planner, links, node_queue, reservoir_by_c, commodities,
                                               make_commodity, t, ev, P, warnings)
                events.append({"t": t, "type": "evacuation", "text": f"Evacuation triggered: {evac_info['evacuees']:.0f} evacuees, strategy {ev.strategy}"})

            # ---------- sending / receiving
            S = {}
            R = {}
            for lid in link_ids:
                ls = links[lid]
                if ls.N.shape[1] < P:
                    ls.N = _fit2(ls.N, P)
                tot = ls.N.sum(1)
                ratio = min(1.0, ls.vf * dt / ls.dx)
                S[lid] = np.minimum(tot * ratio, ls.q * dt)
                opp = opposite.get(lid)
                occupied = tot + (links[opp].N.sum(1)[::-1] if opp is not None else 0.0)
                kc = (ls.q / ls.width) / ls.vf if ls.q > 0 else 0.0
                w = ls.q / (ls.width * max(JAM_DENSITY - kc, 0.1)) if ls.q > 0 else 0.0
                alpha = min(1.0, w * dt / ls.dx)
                R[lid] = np.minimum(ls.q * dt, alpha * np.maximum(ls.njam - occupied, 0.0))
            closed_links = {lk.id for lk in model.links.values() if lk.corridor_id in closed}
            for lid in closed_links:  # closed corridors accept nobody new
                R[lid][0] = 0.0

            # ---------- internal cell flows (computed from start-of-step state)
            internal = {}
            for lid in link_ids:
                ls = links[lid]
                if ls.n > 1:
                    y = np.minimum(S[lid][:-1], R[lid][1:])
                    tot = ls.N[:-1].sum(1)
                    comp = np.divide(ls.N[:-1], tot[:, None], out=np.zeros_like(ls.N[:-1]), where=tot[:, None] > 1e-12)
                    internal[lid] = y[:, None] * comp

            # ---------- node flows
            inflow_first: dict[int, np.ndarray] = {}
            outflow_last: dict[int, np.ndarray] = {}
            for node in model.nodes:
                senders = []  # (key, vector by commodity)
                for lid in in_links[node]:
                    ls = links[lid]
                    tot = ls.N[-1].sum()
                    if tot <= 1e-12 or S[lid][-1] <= 0:
                        continue
                    senders.append((("link", lid), S[lid][-1] * ls.N[-1] / tot))
                if node in node_queue and node_queue[node].sum() > 1e-12:
                    senders.append((("nq", node), _fit(node_queue[node], P).copy()))
                if node in entry_queue and entry_queue[node].sum() > 1e-12:
                    senders.append((("eq", node), _fit(entry_queue[node], P).copy()))
                if not senders:
                    continue
                # demand per target
                demand: dict = {}
                routing: list = []
                for key, v in senders:
                    for cid in np.flatnonzero(v > 1e-12):
                        c = commodities[cid]
                        if c.end == "blocked":
                            continue
                        if key[0] == "link":
                            nxt = c.next_of.get(key[1], None)
                        else:
                            nxt = c.links[0] if c.links else None
                        if nxt is not None:
                            tgt = ("link", nxt)
                        elif c.end == "dwell" and node in storage:
                            tgt = ("res", node)
                        elif c.end == "exit":
                            tgt = ("sink", c.target)
                        else:
                            tgt = ("res", node)
                        demand[tgt] = demand.get(tgt, 0.0) + v[cid]
                        routing.append((key, cid, tgt, v[cid]))
                alpha = {}
                for tgt, dmd in demand.items():
                    if tgt[0] == "link":
                        cap = R[tgt[1]][0]
                    elif tgt[0] == "res":
                        cap = max(storage.get(node, 1e9) - reservoir_by_c.get(node, np.zeros(1)).sum(), 0.0)
                    else:
                        cap = math.inf
                    alpha[tgt] = 1.0 if dmd <= cap else cap / dmd
                # FIFO: a link's outflow is limited by its most restrictive target
                phi = {}
                for key, cid, tgt, amt in routing:
                    if key[0] == "link":
                        phi[key] = min(phi.get(key, 1.0), alpha[tgt])
                for key, cid, tgt, amt in routing:
                    f = amt * (phi[key] if key[0] == "link" else alpha[tgt])
                    if f <= 0:
                        continue
                    if key[0] == "link":
                        outflow_last.setdefault(key[1], np.zeros(P))[cid] += f
                    elif key[0] == "nq":
                        node_queue[node][cid] -= f
                    else:
                        entry_queue[node][cid] -= f
                        g = gate_of_node.get(node)
                        if g is not None and g.id in entered_cum:
                            entered_cum[g.id] += f
                    if tgt[0] == "link":
                        inflow_first.setdefault(tgt[1], np.zeros(P))[cid] += f
                    elif tgt[0] == "res":
                        r = reservoir_by_c.setdefault(node, np.zeros(P))
                        r = reservoir_by_c[node] = _fit(r, P)
                        r[cid] += f
                    else:
                        exit_cum[tgt[1]] = exit_cum.get(tgt[1], 0.0) + f
                        exit_series.setdefault(tgt[1], [0.0] * len(rec.times))
                        if commodities[cid].evac:
                            evac_exited += f

            # ---------- apply
            for lid in link_ids:
                ls = links[lid]
                if lid in internal:
                    ls.N[:-1] -= internal[lid]
                    ls.N[1:] += internal[lid]
                if lid in outflow_last:
                    ls.N[-1] -= outflow_last[lid][: ls.N.shape[1]]
                if lid in inflow_first:
                    ls.N[0] += inflow_first[lid][: ls.N.shape[1]]
                np.maximum(ls.N, 0.0, out=ls.N)
            for cid_, lids in sec_links.items():
                for lid in lids:
                    ls = links[lid]
                    if ls.n > 1 and lid in internal:
                        sec_acc[cid_] += float(internal[lid][ls.n // 2 - 1].sum()) if ls.n >= 2 else 0.0
                    elif lid in outflow_last:
                        sec_acc[cid_] += float(outflow_last[lid].sum())

            # ---------- reservoir releases (first-order dwell)
            for node, r in list(reservoir_by_c.items()):
                for cid in np.flatnonzero(r > 1e-9):
                    c = commodities[cid]
                    if evacuating and c.evac:
                        continue
                    frac = 1.0 if c.dwell_s <= 0 else 1.0 - math.exp(-dt / c.dwell_s)
                    amt = r[cid] * frac
                    if amt <= 1e-12:
                        continue
                    if not c.then:
                        legs = (LegSpec("exit", None),)
                    else:
                        legs = c.then
                    try:
                        opts = chain(node, legs, t)
                    except RoutingError as exc:
                        warn(f"pedestrians in {area_of_node[node].name} cannot continue ({exc})")
                        continue
                    r[cid] -= amt
                    nq = node_queue.setdefault(node, np.zeros(P))
                    nq = node_queue[node] = _fit(nq, P)
                    for c2, pr in opts:
                        nq = node_queue[node] = _fit(node_queue[node], P)
                        nq[c2] += amt * pr

            if step % out_every == 0:
                record(t)
            if progress and step % 100 == 0:
                progress(step / n_steps, f"t={t:.0f}s")
            if cancelled and step % 50 == 0 and cancelled():
                raise Cancelled()

        in_site = sum(float(ls.N.sum()) for ls in links.values()) + sum(float(v.sum()) for v in node_queue.values()) \
            + sum(float(v.sum()) for v in reservoir_by_c.values())
        if evac_info is not None:
            evac_info["exited"] = evac_exited
        return {
            "engine": ENGINE_NAME,
            "engine_version": self.version(),
            "method": "Macroscopic flow model (multi-commodity Cell Transmission Model, Weidmann fundamental diagram)",
            "method_type": "macroscopic",
            "rec": rec,
            "grid": grid,
            "queues": queue_series,
            "arrivals": arrivals_series,
            "entered": entered_series,
            "exits": exit_series,
            "queued": queued_series,
            "trips": [],
            "remaining": [],
            "remaining_count": in_site,
            "turned_away": turned_away,
            "unroutable": unroutable,
            "events": events,
            "warnings": warnings[:200],
            "evacuation": evac_info,
            "link_frames": link_frames,
            "wall_time_s": time.time() - t_wall,
        }

    # ------------------------------------------------------------------
    def _reroute(self, model, planner, links, node_queue, entry_queue, commodities, make_commodity, closed, t, P) -> float:
        """Move pedestrians whose remaining route uses a closed corridor onto a new route."""
        g = planner.graph_at(t)
        moved = 0.0
        closed_links = {lk.id for lk in model.links.values() if lk.corridor_id in closed}
        for lid, ls in links.items():
            v_node = model.links[lid].v
            for cid in np.flatnonzero(ls.N.sum(0) > 1e-9):
                c = commodities[cid]
                idx = c.links.index(lid) if lid in c.links else -1
                remaining = c.links[idx + 1:]
                if not any(r in closed_links for r in remaining):
                    continue
                leg = LegSpec(c.end, c.target if c.end == "dwell" else None, c.dwell_s)
                try:
                    path, _ = route_options(g, v_node, planner.target_node(leg) or _nearest_exit(planner, g, v_node), "shortest_time")[0]
                except (RoutingError, TypeError):
                    continue
                new = make_commodity(path, c.end, c.target if c.end == "dwell" else planner.node_target_id(path[-1]),
                                     c.dwell_s, c.then, c.evac, first_link=lid)
                ls.N = _fit2(ls.N, len(commodities) if len(commodities) > ls.N.shape[1] else ls.N.shape[1])
                moved += float(ls.N[:, cid].sum())
                ls.N[:, new] += ls.N[:, cid]
                ls.N[:, cid] = 0
        return moved

    def _trigger_evac(self, model, planner, links, node_queue, reservoir_by_c, commodities, make_commodity, t, ev, P, warnings) -> dict:
        zones = ev.affected_zone_ids
        zone_polys = [model.zones[z]["polygon"] for z in zones if z in model.zones]
        affected = shapely.union_all(zone_polys) if zone_polys else None
        if affected is not None:
            shapely.prepare(affected)
        g = planner.g_evac
        # sources: link population mapped to the link's downstream node, areas to their node
        sources: dict[int, float] = {}
        moves = []  # (kind, key, cid, cell_mask)
        for lid, ls in links.items():
            mask = np.ones(ls.n, bool) if affected is None else shapely.contains_xy(affected, ls.centres[:, 0], ls.centres[:, 1])
            if not mask.any():
                continue
            amount = float(ls.N[mask].sum())
            if amount <= 1e-9:
                continue
            v = model.links[lid].v
            sources[v] = sources.get(v, 0.0) + amount
            moves.append(("link", lid, v, mask))
        for node in list(set(reservoir_by_c) | set(node_queue)):
            a = next((x for x in model.areas.values() if x.node == node), None)
            if a is None:
                continue
            if affected is not None and not affected.intersects(a.polygon):
                continue
            amount = float(reservoir_by_c.get(node, np.zeros(1)).sum() + node_queue.get(node, np.zeros(1)).sum())
            if amount > 1e-9:
                sources[node] = sources.get(node, 0.0) + amount
                moves.append(("area", node, node, None))
        node_zone = {}
        for n in sources:
            p = model.nodes[n]
            node_zone[n] = planner.zone_of(p.x, p.y, zones or list(model.zones))
        routes, plan = planner.evac_routes(sources, node_zone)
        unreachable = 0.0
        for kind, key, node, mask in moves:
            opts = routes.get(node) or []
            if kind == "link":
                ls = links[key]
                pop = ls.N[mask].copy()
                if not opts:
                    unreachable += float(pop.sum())
                    continue
                ls.N[mask] = 0
                for path, pr in opts:
                    cid = make_commodity(path, "exit", planner.node_target_id(path[-1]), evac=True, first_link=key)
                    ls.N = _fit2(ls.N, len(commodities) if len(commodities) > ls.N.shape[1] else ls.N.shape[1])
                    ls.N[mask, cid] += pop.sum(1) * pr
            else:
                total = float(reservoir_by_c.get(key, np.zeros(1)).sum() + node_queue.get(key, np.zeros(1)).sum())
                if not opts:
                    unreachable += total
                    continue
                if key in reservoir_by_c:
                    reservoir_by_c[key][:] = 0
                nq = node_queue.setdefault(key, np.zeros(P))
                nq[:] = 0
                for path, pr in opts:
                    cid = make_commodity(path, "exit", planner.node_target_id(path[-1]), evac=True)
                    nq = node_queue[key] = _fit(node_queue[key], max(len(commodities), len(nq)))
                    nq[cid] += total * pr
        if unreachable > 0:
            warnings.append(f"{unreachable:.0f} evacuees have no route to any exit")
        return {
            "trigger_s": t,
            "evacuees": sum(sources.values()),
            "unreachable": unreachable,
            "strategy": ev.strategy,
            "ccrp_estimate_s": plan.clearance_time_s if plan else None,
            "ccrp_sink_load": {planner.node_target_id(k): v for k, v in (plan.sink_load.items() if plan else [])},
        }


def _nearest_exit(planner, g, node):
    from ..geo.routing import nearest_target

    res = nearest_target(g, node, planner.normal_exits())
    return res[0] if res else None


def _fit(v: np.ndarray, n: int) -> np.ndarray:
    return v if len(v) >= n else np.pad(v, (0, n - len(v)))


def _fit2(m: np.ndarray, n: int) -> np.ndarray:
    return m if m.shape[1] >= n else np.pad(m, ((0, 0), (0, n - m.shape[1])))


def _cell_points(geom, n: int, dx: float, width: float) -> np.ndarray:
    """Points spread along and across each cell (used only for density mapping)."""
    m_across = int(min(7, max(1, round(width / 1.5))))
    m_along = 1
    offs = (np.arange(m_across) + 0.5) / m_across - 0.5
    out = np.zeros((n, m_across * m_along, 2))
    L = geom.length
    for i in range(n):
        k = 0
        for j in range(m_along):
            d = min(L, (i + (j + 0.5) / m_along) * dx)
            p0 = geom.interpolate(max(0.0, d - 0.25))
            p1 = geom.interpolate(min(L, d + 0.25))
            tx, ty = p1.x - p0.x, p1.y - p0.y
            norm = math.hypot(tx, ty) or 1.0
            nx_, ny_ = -ty / norm, tx / norm
            c = geom.interpolate(d)
            for o in offs:
                out[i, k] = (c.x + nx_ * o * width * 0.9, c.y + ny_ * o * width * 0.9)
                k += 1
    return out


def _aligned_points(poly, grid: Grid) -> np.ndarray:
    if poly.is_empty:
        return np.zeros((0, 2))
    minx, miny, maxx, maxy = poly.bounds
    h = grid.cell / 2.0
    i0, i1 = int((minx - grid.x0) // h), int((maxx - grid.x0) // h) + 1
    j0, j1 = int((miny - grid.y0) // h), int((maxy - grid.y0) // h) + 1
    xs, ys = np.meshgrid(grid.x0 + (np.arange(i0, i1) + 0.5) * h, grid.y0 + (np.arange(j0, j1) + 0.5) * h)
    xs, ys = xs.ravel(), ys.ravel()
    inside = shapely.contains_xy(poly, xs, ys)
    pts = np.stack([xs[inside], ys[inside]], 1)
    if len(pts) == 0:
        c = poly.representative_point()
        pts = np.array([[c.x, c.y]])
    return pts


def _section_links(model: SiteModel) -> dict[str, list[int]]:
    """Links (both directions) containing the midpoint of each corridor."""
    out: dict[str, list[int]] = {}
    for c in model.corridors.values():
        if not c.enabled:
            continue
        mid = c.line.interpolate(0.5, normalized=True)
        out[c.id] = [lk.id for lk in model.links.values()
                     if lk.corridor_id == c.id and lk.geom.distance(Point(mid.x, mid.y)) < 0.5]
    return out
