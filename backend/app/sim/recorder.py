"""Engine-independent recording of simulation output.

Both engines hand positions (agent-based: one point per agent; macroscopic: one
weighted point per cell) to ``Recorder.record_frame`` at every output interval.
From these the recorder derives, for every frame:

* pedestrian count and density (persons / usable m2) for every zone,
* a density grid (persons / walkable m2 per grid cell),
* corridor throughput (agent-based: crossings of a measurement section at the
  corridor midpoint; macroscopic: link outflow supplied by the engine).

Measured observations are never mixed into these arrays; they live in a
separate table and are labelled "observed" in every output.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString

from ..geo.site_model import Grid, SiteModel


@dataclass
class Section:
    corridor_id: str
    a: np.ndarray
    b: np.ndarray


def _sections(model: SiteModel) -> list[Section]:
    out = []
    for c in model.corridors.values():
        if not c.enabled or c.line.length < 2:
            continue
        mid = c.line.interpolate(0.5, normalized=True)
        p0 = c.line.interpolate(max(0.0, 0.5 * c.line.length - 0.5))
        p1 = c.line.interpolate(min(c.line.length, 0.5 * c.line.length + 0.5))
        dx, dy = p1.x - p0.x, p1.y - p0.y
        n = np.hypot(dx, dy) or 1.0
        nx_, ny_ = -dy / n, dx / n
        h = c.width / 2.0 + 0.5
        out.append(Section(c.id, np.array([mid.x - nx_ * h, mid.y - ny_ * h]), np.array([mid.x + nx_ * h, mid.y + ny_ * h])))
    return out


def _crosses(p: np.ndarray, q: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Vectorised segment intersection test between moves p->q and section a-b."""

    def orient(o, s, t):
        return (s[..., 0] - o[..., 0]) * (t[..., 1] - o[..., 1]) - (s[..., 1] - o[..., 1]) * (t[..., 0] - o[..., 0])

    a_ = np.broadcast_to(a, p.shape)
    b_ = np.broadcast_to(b, p.shape)
    o1 = orient(p, q, a_)
    o2 = orient(p, q, b_)
    o3 = orient(a_, b_, p)
    o4 = orient(a_, b_, q)
    return (o1 * o2 < 0) & (o3 * o4 < 0)


@dataclass
class Recorder:
    model: SiteModel
    grid: Grid
    interval: float
    grid_limit: float
    keep_agents: bool = True
    times: list[float] = field(default_factory=list)
    zone_counts: dict[str, list[float]] = field(default_factory=dict)
    total: list[float] = field(default_factory=list)
    grid_frames: list[list] = field(default_factory=list)
    agent_frames: list[dict] = field(default_factory=list)
    section_flow: dict[str, list[float]] = field(default_factory=dict)
    max_grid: np.ndarray | None = None
    above_grid: np.ndarray | None = None
    _prev: dict | None = None
    _static: tuple | None = None

    def __post_init__(self):
        self._zones = []
        for zid, z in self.model.zones.items():
            if z["usable_area"] <= 0.5:
                continue
            geom = z["usable"]
            shapely.prepare(geom)
            self._zones.append((zid, geom))
            self.zone_counts[zid] = []
        self._sections = _sections(self.model)
        for s in self._sections:
            self.section_flow[s.corridor_id] = []
        self.max_grid = np.zeros((self.grid.ny, self.grid.nx))
        self.above_grid = np.zeros((self.grid.ny, self.grid.nx))

    def record_frame(self, t: float, x, y, weights=None, ids=None, section_flow: dict | None = None,
                     static_points: bool = False):
        """Record one output frame. ``static_points`` means x/y are the same sample
        points every frame (macroscopic model), so zone membership is computed once."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        w = np.ones_like(x) if weights is None else np.asarray(weights, dtype=float)
        self.times.append(round(float(t), 3))
        self.total.append(float(w.sum()))
        if static_points:
            if self._static is None or self._static[0] != len(x):
                masks = {zid: shapely.contains_xy(geom, x, y) for zid, geom in self._zones}
                self._static = (len(x), masks)
            masks = self._static[1]
            for zid, _geom in self._zones:
                self.zone_counts[zid].append(float(w[masks[zid]].sum()))
        else:
            for zid, geom in self._zones:
                inside = shapely.contains_xy(geom, x, y) if len(x) else np.zeros(0, bool)
                self.zone_counts[zid].append(float(w[inside].sum()))
        counts = self.grid.counts(x, y, w)
        dens = self.grid.density(counts)
        np.maximum(self.max_grid, dens, out=self.max_grid)
        self.above_grid += (dens > self.grid_limit) * self.interval
        nz = np.flatnonzero(dens.ravel() >= 0.01)
        self.grid_frames.append([nz.tolist(), np.round(dens.ravel()[nz], 2).tolist()])

        if section_flow is not None:
            for s in self._sections:
                self.section_flow[s.corridor_id].append(float(section_flow.get(s.corridor_id, 0.0)))
        elif ids is not None:
            ids = np.asarray(ids)
            if self._prev is not None and len(ids):
                pids, pxy = self._prev
                common, i_now, i_prev = np.intersect1d(ids, pids, return_indices=True)
                q = np.stack([x[i_now], y[i_now]], axis=1)
                p = pxy[i_prev]
                for s in self._sections:
                    self.section_flow[s.corridor_id].append(float(_crosses(p, q, s.a, s.b).sum()) if len(common) else 0.0)
            else:
                for s in self._sections:
                    self.section_flow[s.corridor_id].append(0.0)
            self._prev = (ids.copy(), np.stack([x, y], axis=1))
            if self.keep_agents:
                self.agent_frames.append({"t": round(float(t), 3), "ids": ids.astype(int).tolist(),
                                          "x": np.round(x, 2).tolist(), "y": np.round(y, 2).tolist()})

    def section_geometries(self) -> dict[str, LineString]:
        return {s.corridor_id: LineString([tuple(s.a), tuple(s.b)]) for s in self._sections}
