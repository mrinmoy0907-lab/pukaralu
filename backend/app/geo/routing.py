"""Network routing for pedestrian trips and evacuation planning.

Algorithms (all on the directed pedestrian network of ``SiteModel.graph``):

* ``shortest_time`` - Dijkstra on free-flow walking time (respects one-way links,
  closed corridors and emergency-only links).
* ``k_shortest_logit`` - Yen's k loopless shortest paths; demand split between
  them with a multinomial logit on free-flow time, P_i ~ exp(-theta * t_i).
* ``ccrp`` - Capacity Constrained Route Planner (Lu, George & Shekhar 2005,
  "Capacity Constrained Routing Algorithms for Evacuation Planning", SSTD).
  Repeatedly finds the earliest-arrival path from any remaining evacuee group to
  any exit in a time-expanded reservation table where every link has a per-period
  capacity (Weidmann specific flow x width), and reserves capacity along it.
  Unlike plain shortest paths, it spreads evacuees over alternative routes once
  the best route's capacity is used. Node storage limits are not modelled.
"""
from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from .site_model import SiteModel


class RoutingError(ValueError):
    pass


def shortest_path(g: nx.DiGraph, src: int, dst: int) -> list[int]:
    try:
        return nx.dijkstra_path(g, src, dst, weight="time")
    except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
        raise RoutingError(f"no path from node {src} to node {dst}") from exc


def path_time(g: nx.DiGraph, path: list[int]) -> float:
    return float(sum(g[u][v]["time"] for u, v in zip(path[:-1], path[1:])))


def k_shortest(g: nx.DiGraph, src: int, dst: int, k: int) -> list[list[int]]:
    out = []
    try:
        for p in nx.shortest_simple_paths(g, src, dst, weight="time"):
            out.append(p)
            if len(out) >= k:
                break
    except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
        raise RoutingError(f"no path from node {src} to node {dst}") from exc
    return out


def logit_split(g: nx.DiGraph, paths: list[list[int]], theta: float) -> list[float]:
    t = np.array([path_time(g, p) for p in paths])
    w = np.exp(-theta * (t - t.min()))
    return list(w / w.sum())


def route_options(g: nx.DiGraph, src: int, dst: int, strategy: str, k: int = 3, theta: float = 0.05):
    """Return [(path, probability)] between two nodes."""
    if src == dst:
        return [([src], 1.0)]
    if strategy == "k_shortest_logit" and k > 1:
        paths = k_shortest(g, src, dst, k)
        return list(zip(paths, logit_split(g, paths, theta)))
    return [(shortest_path(g, src, dst), 1.0)]


def nearest_target(g: nx.DiGraph, src: int, targets: list[int]) -> tuple[int, list[int]] | None:
    if src in targets:
        return src, [src]
    try:
        dist, paths = nx.single_source_dijkstra(g, src, weight="time")
    except nx.NodeNotFound:
        return None
    reach = [t for t in targets if t in dist]
    if not reach:
        return None
    best = min(reach, key=lambda t: dist[t])
    return best, paths[best]


# ---------------------------------------------------------------- CCRP
@dataclass
class CCRPResult:
    routes: dict[int, list[tuple[list[int], float]]]  # source node -> [(path, persons)]
    clearance_time_s: float
    sink_load: dict[int, float]
    unreachable: dict[int, float] = field(default_factory=dict)
    iterations: int = 0

    def split(self, src: int) -> list[tuple[list[int], float]]:
        items = self.routes.get(src, [])
        tot = sum(n for _, n in items)
        return [(p, n / tot) for p, n in items] if tot > 0 else []


def ccrp(model: SiteModel, g: nx.DiGraph, sources: dict[int, float], sinks: list[int],
         period_s: float = 2.0, mean_speed: float = 1.34, max_iter: int = 200_000,
         cap_factor: dict[str, float] | None = None) -> CCRPResult:
    sinks_set = set(sinks)
    remaining = {s: float(n) for s, n in sources.items() if n > 0}
    unreachable: dict[int, float] = {}
    routes: dict[int, dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
    sink_load: dict[int, float] = defaultdict(float)
    reserved: dict[tuple[int, int], dict[int, float]] = defaultdict(lambda: defaultdict(float))
    cap = {}
    tau = {}
    for u, v, d in g.edges(data=True):
        lk = model.links[d["link"]]
        f = (cap_factor or {}).get(lk.corridor_id, 1.0) if lk.corridor_id else 1.0
        cap[(u, v)] = max(lk.capacity_pps * f * period_s, 1e-6)
        tau[(u, v)] = max(1, math.ceil(lk.length / (mean_speed * lk.speed_factor) / period_s))
    clearance = 0
    it = 0
    for s in list(remaining):
        if s not in g or not any(nx.has_path(g, s, t) for t in sinks_set if t in g):
            unreachable[s] = remaining.pop(s)
    while remaining and it < max_iter:
        it += 1
        # earliest-arrival search from all remaining sources (multi-source, time 0)
        best: dict[int, int] = {}
        prev: dict[int, tuple[int, int] | None] = {}
        heap = []
        for s in remaining:
            best[s] = 0
            prev[s] = None
            heap.append((0, s))
        heapq.heapify(heap)
        found = None
        while heap:
            t, u = heapq.heappop(heap)
            if t > best.get(u, math.inf):
                continue
            if u in sinks_set:
                found = (u, t)
                break
            for v in g.successors(u):
                e = (u, v)
                dep = t
                res = reserved[e]
                while res.get(dep, 0.0) >= cap[e] - 1e-9:
                    dep += 1
                arr = dep + tau[e]
                if arr < best.get(v, math.inf):
                    best[v] = arr
                    prev[v] = (u, dep)
                    heapq.heappush(heap, (arr, v))
        if found is None:
            for s in list(remaining):
                unreachable[s] = remaining.pop(s)
            break
        sink, t_arr = found
        # reconstruct
        path_edges = []
        node = sink
        while prev[node] is not None:
            u, dep = prev[node]
            path_edges.append(((u, node), dep))
            node = u
        src = node
        path_edges.reverse()
        flow = remaining[src]
        for e, dep in path_edges:
            flow = min(flow, cap[e] - reserved[e].get(dep, 0.0))
        flow = max(flow, 1e-6)
        for e, dep in path_edges:
            reserved[e][dep] += flow
        path = [src] + [e[1] for e, _ in path_edges]
        routes[src][tuple(path)] += flow
        sink_load[sink] += flow
        clearance = max(clearance, t_arr)
        remaining[src] -= flow
        if remaining[src] <= 1e-6:
            del remaining[src]
    return CCRPResult(
        routes={s: [(list(p), n) for p, n in d.items()] for s, d in routes.items()},
        clearance_time_s=clearance * period_s,
        sink_load=dict(sink_load),
        unreachable=unreachable,
        iterations=it,
    )
