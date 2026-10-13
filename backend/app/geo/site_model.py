"""Metric site model built from GeoJSON features.

``build_site_model`` converts the stored WGS84 features of a site into a
metric representation used by the simulation engines and analytics:

* the walkable area (corridor buffers + walkable polygons - obstacles),
* the pedestrian network (nodes/links with width, length, direction, surface),
* gates, area nodes (holding areas, ghats, ...) and analysis zones.

Scenario overrides (blocked corridors, changed widths, closed gates, one-way
operation) are applied when the model is built, so the same function serves
baseline and alternative scenarios.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring, unary_union

from .catalog import (
    AREA_NODE_TYPES,
    CORRIDOR_DEFAULTS,
    CORRIDOR_TYPES,
    DEFAULT_LINE_OBSTACLE_THICKNESS,
    GATE_DEFAULTS,
    OBSTACLE_TYPES,
    SURFACE_SPEED_FACTOR,
    WALKABLE_TYPES,
)
from .crs import LocalProjection

SNAP_TOL = 1.5  # metres: endpoints closer than this are the same network node
GATE_SNAP = 20.0  # metres: max distance from a gate to the network
AREA_SNAP = 2.0  # metres: corridor nodes this close to an area polygon connect to it
# Weidmann (1993): maximum specific flow ~1.22 persons/(m s); jam density 5.4 p/m2.
SPECIFIC_FLOW_MAX = 1.22
JAM_DENSITY = 5.4


class SiteModelError(ValueError):
    pass


@dataclass
class Corridor:
    id: str
    name: str
    line: LineString
    width: float
    direction: str
    surface: str
    emergency_only: bool
    enabled: bool
    capacity_factor: float = 1.0

    @property
    def polygon(self) -> Polygon:
        return self.line.buffer(self.width / 2.0, quad_segs=4)


@dataclass
class Area:
    id: str
    name: str
    pk_type: str
    polygon: BaseGeometry
    capacity_persons: int | None
    usable_area: float = 0.0
    node: int | None = None


@dataclass
class Gate:
    id: str
    name: str
    point: Point
    role: str
    width: float
    enabled: bool
    emergency_exit: bool
    node: int | None = None

    @property
    def is_entry(self) -> bool:
        return self.enabled and self.role in ("entry", "both") and not self.emergency_exit

    @property
    def is_exit(self) -> bool:
        return self.enabled and self.role in ("exit", "both")


@dataclass
class Link:
    id: int
    u: int
    v: int
    geom: LineString  # oriented u -> v
    width: float
    surface: str
    kind: str  # corridor | area | gate
    corridor_id: str | None
    emergency_only: bool
    capacity_factor: float = 1.0

    @property
    def length(self) -> float:
        return max(self.geom.length, 0.5)

    @property
    def speed_factor(self) -> float:
        return SURFACE_SPEED_FACTOR.get(self.surface, 1.0)

    @property
    def capacity_pps(self) -> float:
        """Maximum flow (persons/s) = specific flow x effective width."""
        return SPECIFIC_FLOW_MAX * self.width * self.capacity_factor


@dataclass
class SiteModel:
    proj: LocalProjection
    corridors: dict[str, Corridor]
    areas: dict[str, Area]
    gates: dict[str, Gate]
    obstacles: BaseGeometry
    walkable: BaseGeometry
    nodes: dict[int, Point]
    node_kind: dict[int, str]
    links: dict[int, Link]
    zones: dict[str, dict]
    warnings: list[str] = field(default_factory=list)
    # (polygon, speed factor) for stairs, ghat steps and ramps
    speed_zones: list[tuple[BaseGeometry, float]] = field(default_factory=list)
    water: BaseGeometry | None = None

    # ----------------------------------------------------------------- graph
    def graph(self, *, closed_corridors: set[str] = frozenset(), allow_emergency: bool = False,
              mean_speed: float = 1.34) -> nx.DiGraph:
        """Directed routing graph. Edge weight ``time`` is free-flow travel time (s)."""
        g = nx.DiGraph()
        for n, p in self.nodes.items():
            g.add_node(n, x=p.x, y=p.y)
        for link in self.links.values():
            if link.corridor_id and link.corridor_id in closed_corridors:
                continue
            if link.emergency_only and not allow_emergency:
                continue
            g.add_edge(link.u, link.v, link=link.id, time=link.length / (mean_speed * link.speed_factor),
                       length=link.length)
        return g

    def entry_gates(self) -> list[Gate]:
        return [g for g in self.gates.values() if g.is_entry and g.node is not None]

    def exit_gates(self) -> list[Gate]:
        return [g for g in self.gates.values() if g.is_exit and g.node is not None]

    def link_between(self, u: int, v: int) -> Link:
        return self.links[self._edge_index[(u, v)]]

    def __post_init__(self):
        self._edge_index = {(lk.u, lk.v): lk.id for lk in self.links.values()}


# --------------------------------------------------------------------------
def _props(f: dict) -> dict:
    return f.get("properties") or {}


def _as_bool(v, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def _as_float(v, default: float) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


class _NodeRegistry:
    def __init__(self, tol: float):
        self.tol = tol
        self.points: list[tuple[float, float]] = []
        self.kind: dict[int, str] = {}

    def get(self, x: float, y: float, kind: str = "junction") -> int:
        for i, (px, py) in enumerate(self.points):
            if (px - x) ** 2 + (py - y) ** 2 <= self.tol ** 2:
                return i
        self.points.append((x, y))
        self.kind[len(self.points) - 1] = kind
        return len(self.points) - 1

    def new(self, x: float, y: float, kind: str) -> int:
        self.points.append((x, y))
        self.kind[len(self.points) - 1] = kind
        return len(self.points) - 1


def _equivalent_width(poly: BaseGeometry) -> float:
    if poly.length <= 0:
        return 2.0
    return float(min(max(2.0 * poly.area / poly.length, 2.0), 50.0))


def build_site_model(
    features: list[dict],
    origin: tuple[float, float],
    *,
    corridor_overrides: list | None = None,
    gate_overrides: list | None = None,
    holding_overrides: list | None = None,
) -> SiteModel:
    proj = LocalProjection(*origin)
    warnings: list[str] = []
    c_over = {o.corridor_id: o for o in (corridor_overrides or [])}
    g_over = {o.gate_id: o for o in (gate_overrides or [])}
    h_over = {o.holding_id: o for o in (holding_overrides or [])}

    corridors: dict[str, Corridor] = {}
    areas: dict[str, Area] = {}
    gates: dict[str, Gate] = {}
    obstacle_geoms: list[BaseGeometry] = []
    river_geoms: list[BaseGeometry] = []
    walkable_geoms: list[BaseGeometry] = []
    bathing_geoms: list[BaseGeometry] = []
    zones: dict[str, dict] = {}
    speed_zones: list[tuple[BaseGeometry, float]] = []

    for f in features:
        p = _props(f)
        t = p.get("pk_type")
        fid = str(f.get("id") or p.get("id") or "")
        if not fid or not t or not f.get("geometry"):
            continue
        try:
            geom = proj.to_local(f["geometry"])
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"feature {fid}: invalid geometry ({exc})")
            continue
        if not geom.is_valid:
            geom = shapely.make_valid(geom)
        name = p.get("name") or fid

        if t in CORRIDOR_TYPES:
            if geom.geom_type != "LineString":
                warnings.append(f"corridor {fid} is not a LineString and was ignored")
                continue
            o = c_over.get(fid)
            surface = p.get("surface", CORRIDOR_DEFAULTS["surface"])
            c = Corridor(
                id=fid, name=name, line=geom,
                width=_as_float(o.width_m if o and o.width_m else p.get("width_m"), CORRIDOR_DEFAULTS["width_m"]),
                direction=(o.direction if o and o.direction else p.get("direction", "both")),
                surface=surface if surface in SURFACE_SPEED_FACTOR else "path",
                emergency_only=_as_bool(p.get("emergency_only"), t == "emergency_corridor"),
                enabled=_as_bool(o.enabled if o and o.enabled is not None else p.get("enabled"), True),
                capacity_factor=(o.capacity_factor if o and o.capacity_factor else 1.0),
            )
            if c.direction not in ("both", "forward", "backward"):
                warnings.append(f"corridor {fid}: unknown direction '{c.direction}', using 'both'")
                c.direction = "both"
            corridors[fid] = c
        elif t == "gate":
            if geom.geom_type != "Point":
                geom = geom.centroid
            o = g_over.get(fid)
            gates[fid] = Gate(
                id=fid, name=name, point=geom,
                role=(o.role if o and o.role else p.get("role", GATE_DEFAULTS["role"])),
                width=_as_float(o.width_m if o and o.width_m else p.get("width_m"), GATE_DEFAULTS["width_m"]),
                enabled=_as_bool(o.enabled if o and o.enabled is not None else p.get("enabled"), True),
                emergency_exit=_as_bool(p.get("emergency_exit"), False),
            )
        elif t in OBSTACLE_TYPES:
            if geom.geom_type in ("LineString", "MultiLineString"):
                geom = geom.buffer(_as_float(p.get("thickness_m"), 2 * DEFAULT_LINE_OBSTACLE_THICKNESS) / 2.0)
            if t == "river":
                river_geoms.append(geom)
            elif _as_bool(p.get("enabled"), True):
                obstacle_geoms.append(geom)
        elif t in WALKABLE_TYPES:
            if geom.geom_type not in ("Polygon", "MultiPolygon"):
                if geom.geom_type == "Point" and t == "assembly_point":
                    geom = geom.buffer(_as_float(p.get("radius_m"), 15.0))
                else:
                    warnings.append(f"{t} {fid} must be a polygon; ignored for simulation")
                    continue
            walkable_geoms.append(geom)
            surface = p.get("surface") or (t if t in ("steps", "ramp") else "path")
            if SURFACE_SPEED_FACTOR.get(surface, 1.0) < 1.0:
                speed_zones.append((geom, SURFACE_SPEED_FACTOR[surface]))
            if t == "bathing_area":
                bathing_geoms.append(geom)
            if t in AREA_NODE_TYPES:
                cap = p.get("capacity_persons")
                if t == "holding_area" and fid in h_over and h_over[fid].capacity_persons is not None:
                    cap = h_over[fid].capacity_persons
                areas[fid] = Area(id=fid, name=name, pk_type=t, polygon=geom,
                                  capacity_persons=int(cap) if cap not in (None, "") else None)
        elif t == "zone" and geom.geom_type in ("Polygon", "MultiPolygon"):
            zones[fid] = {"id": fid, "name": name, "kind": "zone", "polygon": geom}

    # ---------------------------------------------------------------- walkable
    active_corridors = [c for c in corridors.values() if c.enabled]
    river = unary_union(river_geoms) if river_geoms else Polygon()
    bathing = unary_union(bathing_geoms) if bathing_geoms else Polygon()
    blocked = unary_union(obstacle_geoms + ([river.difference(bathing)] if not river.is_empty else []))
    walk = unary_union([c.polygon for c in active_corridors] + walkable_geoms)
    walkable = walk.difference(blocked) if not blocked.is_empty else walk
    walkable = shapely.make_valid(walkable.buffer(0)).simplify(0.05)
    if walkable.geom_type == "GeometryCollection":
        walkable = unary_union([g for g in walkable.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    if walkable.is_empty:
        raise SiteModelError("the site has no walkable area: add pedestrian corridors or walkable polygons")
    # drop slivers created by overlay operations
    if isinstance(walkable, MultiPolygon):
        walkable = MultiPolygon([g for g in walkable.geoms if g.area > 1.0])

    for a in areas.values():
        a.usable_area = float(a.polygon.intersection(walkable).area)
        if a.usable_area < 1.0:
            warnings.append(f"{a.pk_type} {a.id} has no usable walkable area")

    # ---------------------------------------------------------------- network
    nodes = _NodeRegistry(SNAP_TOL)
    links: dict[int, Link] = {}

    # Split points for every corridor: endpoints of other corridors that touch
    # it, intersections, and gate projections.
    # disabled (blocked) corridors are not part of the network at all
    clist = [c for c in corridors.values() if c.enabled]
    split_d: dict[str, list[float]] = {c.id: [0.0, c.line.length] for c in clist}
    for i, a in enumerate(clist):
        for b in clist[i + 1:]:
            inter = a.line.intersection(b.line)
            pts = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
            for pt in pts:
                if pt.geom_type == "Point":
                    split_d[a.id].append(a.line.project(pt))
                    split_d[b.id].append(b.line.project(pt))
        for b in clist:
            if b is a:
                continue
            for end in (Point(b.line.coords[0]), Point(b.line.coords[-1])):
                if a.line.distance(end) <= SNAP_TOL:
                    split_d[a.id].append(a.line.project(end))

    gate_attach: dict[str, tuple[str, str | float]] = {}
    for gt in gates.values():
        near_area = [ar for ar in areas.values() if ar.polygon.distance(gt.point) <= AREA_SNAP]
        if near_area:
            gate_attach[gt.id] = ("area", near_area[0].id)
            continue
        best = None
        for c in clist:
            d = c.line.distance(gt.point)
            if d <= GATE_SNAP and (best is None or d < best[0]):
                best = (d, c)
        if best is None:
            warnings.append(f"gate {gt.id} ({gt.name}) is more than {GATE_SNAP:.0f} m from any corridor or area; it is not connected")
            continue
        dist_along = best[1].line.project(gt.point)
        split_d[best[1].id].append(dist_along)
        gate_attach[gt.id] = ("corridor", best[1].id)

    link_id = 0
    for c in clist:
        ds = sorted(set(round(d, 2) for d in split_d[c.id]))
        merged: list[float] = []
        for d in ds:
            if not merged or d - merged[-1] > SNAP_TOL:
                merged.append(d)
        if merged[-1] < c.line.length - SNAP_TOL:
            merged.append(c.line.length)
        else:
            merged[-1] = c.line.length
        for d0, d1 in zip(merged[:-1], merged[1:]):
            seg = substring(c.line, d0, d1)
            if seg.length < 0.25:
                continue
            u = nodes.get(*seg.coords[0])
            v = nodes.get(*seg.coords[-1])
            if u == v:
                continue
            seg = LineString([nodes.points[u], *list(seg.coords)[1:-1], nodes.points[v]])
            dirs = []
            if c.direction in ("both", "forward"):
                dirs.append((u, v, seg))
            if c.direction in ("both", "backward"):
                dirs.append((v, u, LineString(seg.coords[::-1])))
            for a_, b_, g_ in dirs:
                links[link_id] = Link(link_id, a_, b_, g_, c.width, c.surface, "corridor", c.id,
                                      c.emergency_only, c.capacity_factor)
                link_id += 1

    corridor_nodes = set()
    for lk in links.values():
        corridor_nodes.update((lk.u, lk.v))

    for a in areas.values():
        if a.usable_area < 1.0:
            continue
        rp = a.polygon.intersection(walkable).representative_point()
        a.node = nodes.new(rp.x, rp.y, f"area:{a.id}")
        width = _equivalent_width(a.polygon)
        for n in list(corridor_nodes):
            pt = Point(nodes.points[n])
            if a.polygon.distance(pt) <= AREA_SNAP:
                line = LineString([nodes.points[a.node], nodes.points[n]])
                for u, v, g_ in ((a.node, n, line), (n, a.node, LineString(line.coords[::-1]))):
                    links[link_id] = Link(link_id, u, v, g_, width, "path", "area", None, False)
                    link_id += 1
    # areas that overlap each other (e.g. ghat steps touching a bathing area)
    alist = [a for a in areas.values() if a.node is not None]
    for i, a in enumerate(alist):
        for b in alist[i + 1:]:
            if a.polygon.buffer(AREA_SNAP).intersects(b.polygon):
                line = LineString([nodes.points[a.node], nodes.points[b.node]])
                w = min(_equivalent_width(a.polygon), _equivalent_width(b.polygon))
                shared = a.polygon.buffer(AREA_SNAP).intersection(b.polygon.buffer(AREA_SNAP))
                w = max(min(w, shared.length / 2.0 if shared.length else w), 2.0)
                for u, v, g_ in ((a.node, b.node, line), (b.node, a.node, LineString(line.coords[::-1]))):
                    links[link_id] = Link(link_id, u, v, g_, w, "path", "area", None, False)
                    link_id += 1

    for gt in gates.values():
        att = gate_attach.get(gt.id)
        if not att:
            continue
        if att[0] == "area":
            target = areas[att[1]].node
            if target is None:
                continue
        else:
            target = min(corridor_nodes, key=lambda n: Point(nodes.points[n]).distance(gt.point))
        gt.node = nodes.new(gt.point.x, gt.point.y, f"gate:{gt.id}")
        line = LineString([nodes.points[gt.node], nodes.points[target]])
        if line.length < 0.5:
            line = LineString([nodes.points[gt.node], (nodes.points[target][0] + 0.5, nodes.points[target][1])])
        for u, v, g_ in ((gt.node, target, line), (target, gt.node, LineString(line.coords[::-1]))):
            links[link_id] = Link(link_id, u, v, g_, gt.width, "path", "gate", None, gt.emergency_exit)
            link_id += 1
        if not walkable.buffer(0.5).contains(gt.point):
            warnings.append(f"gate {gt.id} ({gt.name}) lies outside the walkable area")

    # ---------------------------------------------------------------- zones
    for a in areas.values():
        zones[a.id] = {"id": a.id, "name": a.name, "kind": a.pk_type, "polygon": a.polygon}
    for c in corridors.values():
        zones[c.id] = {"id": c.id, "name": c.name, "kind": "corridor", "polygon": c.polygon}
    for z in zones.values():
        z["usable"] = z["polygon"].intersection(walkable)
        z["usable_area"] = float(z["usable"].area)

    model = SiteModel(
        proj=proj, corridors=corridors, areas=areas, gates=gates,
        obstacles=blocked, walkable=walkable,
        nodes={i: Point(p) for i, p in enumerate(nodes.points)}, node_kind=nodes.kind,
        links=links, zones=zones, warnings=warnings,
        water=river,
        speed_zones=speed_zones + [(c.polygon, SURFACE_SPEED_FACTOR[c.surface]) for c in active_corridors
                                   if SURFACE_SPEED_FACTOR.get(c.surface, 1.0) < 1.0],
    )
    return model


@dataclass
class Grid:
    """Regular density grid in local metres, aligned with the local axes."""

    x0: float
    y0: float
    cell: float
    nx: int
    ny: int
    walk_area: np.ndarray  # (ny, nx) walkable m2 per cell

    @classmethod
    def for_model(cls, model: SiteModel, cell: float) -> Grid:
        minx, miny, maxx, maxy = model.walkable.bounds
        nx_ = max(1, int(math.ceil((maxx - minx) / cell)))
        ny_ = max(1, int(math.ceil((maxy - miny) / cell)))
        if nx_ * ny_ > 250_000:
            raise SiteModelError(f"density grid too large ({nx_}x{ny_}); increase density_grid_cell_m")
        xs = minx + np.arange(nx_) * cell
        ys = miny + np.arange(ny_) * cell
        gx, gy = np.meshgrid(xs, ys)
        boxes = shapely.box(gx.ravel(), gy.ravel(), gx.ravel() + cell, gy.ravel() + cell)
        shapely.prepare(model.walkable)
        areas = shapely.area(shapely.intersection(boxes, model.walkable)).reshape(ny_, nx_)
        return cls(minx, miny, cell, nx_, ny_, areas)

    def counts(self, x: np.ndarray, y: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
        ix = np.floor((np.asarray(x) - self.x0) / self.cell).astype(int)
        iy = np.floor((np.asarray(y) - self.y0) / self.cell).astype(int)
        ok = (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
        out = np.zeros((self.ny, self.nx))
        np.add.at(out, (iy[ok], ix[ok]), 1.0 if weights is None else np.asarray(weights)[ok])
        return out

    def density(self, counts: np.ndarray, min_area_frac: float = 0.15) -> np.ndarray:
        """persons/m2; cells with less than ``min_area_frac`` walkable area are ignored
        (tiny slivers would otherwise produce meaningless extreme densities)."""
        valid = self.walk_area >= min_area_frac * self.cell * self.cell
        dens = np.zeros_like(counts, dtype=float)
        dens[valid] = counts[valid] / self.walk_area[valid]
        return dens

    def cell_polygon(self, iy: int, ix: int) -> Polygon:
        return box(self.x0 + ix * self.cell, self.y0 + iy * self.cell,
                   self.x0 + (ix + 1) * self.cell, self.y0 + (iy + 1) * self.cell)


def feature_from(fid: str, pk_type: str, geom: BaseGeometry | dict, **props) -> dict:
    g = geom if isinstance(geom, dict) else shapely.geometry.mapping(geom)
    return {"type": "Feature", "id": fid, "geometry": g, "properties": {"pk_type": pk_type, **props}}


def shape_of(f: dict) -> BaseGeometry:
    return shape(f["geometry"])
