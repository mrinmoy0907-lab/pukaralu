"""Operational zones: walkable-area calculation, topology checks and register.

Any polygon feature that represents an operational area (``zone``, holding
area, ghat, bathing area, plaza, assembly point, parking, transit hub, bus
terminal, queue lane) is a *zone* in the register. Zone metadata lives in the
feature properties: ``zone_type``, ``parent_id``, ``owner_department``,
``valid_from``, ``valid_to``, ``description``, ``status`` (draft / review /
active / retired), ``approved_by``, ``approval_remarks``, ``effective_from``,
``effective_to``.

Net walkable area (m², computed in the site's local metric CRS)::

    net = gross - water - obstructions - barricades + step_surface_gain

* water: river/water polygons, except designated bathing areas;
* obstructions: buildings, temples, stalls and other obstacle polygons;
* barricades/walls: line features buffered by their thickness;
* step_surface_gain: extra surface of ghat steps/ramps from the DEM slope,
  sum(cell_area * (sqrt(1 + |grad z|^2) - 1)) - zero when no DEM is loaded.
"""
from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from ..geo.catalog import DEFAULT_LINE_OBSTACLE_THICKNESS
from ..geo.crs import LocalProjection

ZONE_TYPES = {"zone", "holding_area", "ghat", "bathing_area", "plaza", "assembly_point", "parking", "transit_hub",
              "bus_terminal", "queue_lane", "steps", "ramp"}
DEFAULT_ZONE_TYPE = {"zone": "sector", "holding_area": "holding", "ghat": "ghat", "bathing_area": "bathing",
                     "plaza": "approach", "assembly_point": "assembly", "parking": "parking", "transit_hub": "transit",
                     "bus_terminal": "transit", "queue_lane": "queue", "steps": "ghat", "ramp": "approach"}
OBSTRUCTION = {"building", "temple", "obstacle"}
BARRIER = {"wall", "barricade"}
STEP_TYPES = {"ghat", "steps", "ramp"}


def _local(features: list[dict], proj: LocalProjection):
    out = []
    for f in features:
        try:
            g = proj.to_local(f["geometry"])
            if not g.is_valid:
                g = shapely.make_valid(g)
            out.append((f, g))
        except Exception:  # pragma: no cover - invalid geometry is reported elsewhere
            continue
    return out


def _slope_gain(poly, terrain: dict | None, proj: LocalProjection) -> float:
    if not terrain or poly.is_empty:
        return 0.0
    h = np.asarray(terrain["heights"], dtype=float)
    ny, nx = h.shape
    lat0 = (terrain["north"] + terrain["south"]) / 2
    dx = (terrain["east"] - terrain["west"]) / (nx - 1) * 111_320 * math.cos(math.radians(lat0))
    dy = (terrain["north"] - terrain["south"]) / (ny - 1) * 110_540
    gy, gx = np.gradient(h, dy, dx)
    factor = np.sqrt(1 + gx ** 2 + gy ** 2) - 1
    lons = np.linspace(terrain["west"], terrain["east"], nx)
    lats = np.linspace(terrain["north"], terrain["south"], ny)
    LON, LAT = np.meshgrid(lons, lats)
    X, Y = proj.lonlat_to_xy(LON.ravel(), LAT.ravel())
    inside = shapely.contains_xy(poly, np.asarray(X), np.asarray(Y))
    return float(factor.ravel()[inside].sum() * dx * dy)


def area_breakdown(fid: str, features: list[dict], origin, terrain: dict | None = None) -> dict:
    proj = LocalProjection(*origin)
    loc = _local(features, proj)
    zone = next((g for f, g in loc if str(f["id"]) == str(fid)), None)
    if zone is None or zone.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"'{fid}' is not a polygon feature of this site")
    water = unary_union([g for f, g in loc if f["properties"].get("pk_type") == "river"] or [Point()])
    bathing = unary_union([g for f, g in loc if f["properties"].get("pk_type") == "bathing_area"] or [Point()])
    water = water.difference(bathing)
    obstr = unary_union([g for f, g in loc if f["properties"].get("pk_type") in OBSTRUCTION
                         and f["properties"].get("enabled", True) is not False and str(f["id"]) != str(fid)] or [Point()])
    barr = unary_union([g.buffer(float(f["properties"].get("thickness_m") or 2 * DEFAULT_LINE_OBSTACLE_THICKNESS) / 2)
                        for f, g in loc if f["properties"].get("pk_type") in BARRIER] or [Point()])
    gross = zone.area
    z1 = zone.difference(water)
    w = gross - z1.area
    z2 = z1.difference(obstr)
    o = z1.area - z2.area
    z3 = z2.difference(barr)
    b = z2.area - z3.area
    steps = unary_union([g for f, g in loc if f["properties"].get("pk_type") in STEP_TYPES] or [Point()])
    step_poly = z3.intersection(steps)
    gain = _slope_gain(step_poly, terrain, proj)
    return {"zone_id": fid, "gross_m2": round(gross, 1), "water_excluded_m2": round(w, 1),
            "obstructions_m2": round(o, 1), "barricades_m2": round(b, 1), "step_surface_gain_m2": round(gain, 1),
            "net_walkable_m2": round(z3.area + gain, 1), "has_terrain": bool(terrain),
            "method": "net = gross - water - obstructions - barricades + DEM step-surface gain (local metric CRS)"}


def topology(fid: str, features: list[dict], origin) -> dict:
    proj = LocalProjection(*origin)
    loc = [(f, g) for f, g in _local(features, proj) if f["properties"].get("pk_type") in ZONE_TYPES]
    zone_f, zone = next(((f, g) for f, g in loc if str(f["id"]) == str(fid)), (None, None))
    if zone is None:
        raise ValueError(f"'{fid}' is not a zone")
    issues = []
    raw = shape(zone_f["geometry"])
    if not raw.is_valid:
        issues.append(f"invalid geometry: {shapely.is_valid_reason(raw)}")
    parent = zone_f["properties"].get("parent_id")
    for f, g in loc:
        if str(f["id"]) == str(fid):
            continue
        # zones nested in each other (parent/child) or a bathing area inside the river edge are expected
        if parent and str(f["id"]) == str(parent):
            continue
        if f["properties"].get("parent_id") == fid:
            continue
        same_level = (f["properties"].get("parent_id") or None) == (parent or None)
        ov = zone.intersection(g).area
        if same_level and ov > 1.0 and f["properties"].get("pk_type") == zone_f["properties"].get("pk_type") == "zone":
            issues.append(f"overlaps zone '{f['properties'].get('name', f['id'])}' by {ov:.0f} m2")
    if parent:
        pg = next((g for f, g in loc if str(f["id"]) == str(parent)), None)
        if pg is None:
            issues.append(f"parent zone '{parent}' not found")
        else:
            outside = zone.difference(pg).area
            if outside > 1.0:
                issues.append(f"{outside:.0f} m2 lies outside the parent zone")
    return {"valid": not issues, "issues": issues}


def register(features: list[dict], origin, terrain: dict | None = None) -> list[dict]:
    rows = []
    for f in features:
        p = f["properties"]
        if p.get("pk_type") not in ZONE_TYPES or f["geometry"]["type"] not in ("Polygon", "MultiPolygon"):
            continue
        try:
            a = area_breakdown(str(f["id"]), features, origin, terrain)
        except ValueError:
            continue
        rows.append({
            "fid": str(f["id"]), "name": p.get("name", f["id"]), "pk_type": p["pk_type"],
            "zone_type": p.get("zone_type") or DEFAULT_ZONE_TYPE.get(p["pk_type"], "other"),
            "parent_id": p.get("parent_id"), "owner_department": p.get("owner_department"),
            "status": p.get("status", "draft"), "valid_from": p.get("valid_from"), "valid_to": p.get("valid_to"),
            "approved_by": p.get("approved_by"), "effective_from": p.get("effective_from"),
            "effective_to": p.get("effective_to"), "net_walkable_m2": a["net_walkable_m2"], "gross_m2": a["gross_m2"],
            "capacity_persons": p.get("capacity_persons"), "synthetic": bool(p.get("synthetic")),
        })
    return rows
