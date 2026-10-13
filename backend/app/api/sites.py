"""Sites, features, GIS import, network inspection and routing."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import networkx as nx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from shapely.geometry import mapping
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..geo.routing import RoutingError, k_shortest, path_time
from ..geo.site_model import SiteModelError, build_site_model
from ..models import Dataset, Feature, Observation, Site
from ..services import importer
from ..services import sites as svc
from .deps import dataset_dict, get_site, site_dict

router = APIRouter(prefix="/api", tags=["sites"])


class SiteIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    origin_lon: float = Field(..., ge=-180, le=180)
    origin_lat: float = Field(..., ge=-85, le=85)
    is_synthetic: bool = False
    basemap: str = "osm"
    tileset_url: str | None = None


class SitePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    basemap: str | None = None
    tileset_url: str | None = None


@router.get("/sites")
def list_sites(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Feature.site_id, func.count()).group_by(Feature.site_id)).all())
    return [site_dict(s, counts.get(s.id, 0)) for s in db.scalars(select(Site).order_by(Site.id))]


@router.post("/sites", status_code=201)
def create_site(body: SiteIn, db: Session = Depends(get_db)):
    s = Site(**body.model_dump(), provenance={"synthetic": body.is_synthetic, "created_via": "api"})
    db.add(s)
    db.commit()
    return site_dict(s, 0)


@router.get("/sites/{site_id}")
def get_site_detail(site_id: int, db: Session = Depends(get_db)):
    s = get_site(db, site_id)
    d = site_dict(s, db.scalar(select(func.count()).where(Feature.site_id == site_id)))
    d["datasets"] = [dataset_dict(x) for x in db.scalars(select(Dataset).where(Dataset.site_id == site_id))]
    return d


@router.patch("/sites/{site_id}")
def patch_site(site_id: int, body: SitePatch, db: Session = Depends(get_db)):
    s = get_site(db, site_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    return site_dict(s)


@router.delete("/sites/{site_id}", status_code=204)
def delete_site(site_id: int, db: Session = Depends(get_db)):
    db.delete(get_site(db, site_id))
    db.commit()


@router.get("/sites/{site_id}/features")
def list_features(site_id: int, pk_type: str | None = None, bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"),
                  db: Session = Depends(get_db)):
    get_site(db, site_id)
    b = None
    if bbox:
        try:
            b = tuple(float(x) for x in bbox.split(","))
            assert len(b) == 4
        except (ValueError, AssertionError) as exc:
            raise HTTPException(422, "bbox must be minLon,minLat,maxLon,maxLat") from exc
    return {"type": "FeatureCollection", "features": svc.site_features(db, site_id, pk_type, b)}


@router.post("/sites/{site_id}/features", status_code=201)
def create_feature(site_id: int, feature: dict, db: Session = Depends(get_db)):
    s = get_site(db, site_id)
    try:
        fids = svc.add_features(db, s, [feature], source="drawn")
    except svc.FeatureValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    f = db.scalar(select(Feature).where(Feature.site_id == site_id, Feature.fid == fids[0]))
    return f.to_geojson()


@router.put("/sites/{site_id}/features/{fid}")
def update_feature(site_id: int, fid: str, feature: dict, db: Session = Depends(get_db)):
    s = get_site(db, site_id)
    f = db.scalar(select(Feature).where(Feature.site_id == site_id, Feature.fid == fid))
    if f is None:
        raise HTTPException(404, f"feature {fid} not found")
    try:
        v = svc.validate_feature({**feature, "type": "Feature"})
    except svc.FeatureValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    props = v["properties"]
    f.pk_type = props.pop("pk_type")
    f.name = str(props.pop("name", f.name) or fid)
    props.pop("source", None)
    props.pop("dataset_id", None)
    f.properties = props
    f.geometry = v["geometry"]
    if f.source != "drawn":
        f.properties = {**props, "edited": True}
    s.version += 1
    db.commit()
    return f.to_geojson()


@router.delete("/sites/{site_id}/features/{fid}", status_code=204)
def delete_feature(site_id: int, fid: str, db: Session = Depends(get_db)):
    s = get_site(db, site_id)
    f = db.scalar(select(Feature).where(Feature.site_id == site_id, Feature.fid == fid))
    if f is None:
        raise HTTPException(404, f"feature {fid} not found")
    db.delete(f)
    s.version += 1
    db.commit()


@router.get("/sites/{site_id}/datasets")
def list_datasets(site_id: int, db: Session = Depends(get_db)):
    get_site(db, site_id)
    return [dataset_dict(x) for x in db.scalars(select(Dataset).where(Dataset.site_id == site_id))]


@router.post("/sites/{site_id}/import")
async def import_data(site_id: int, file: UploadFile = File(...), license: str = Form(...), attribution: str = Form(""),
                      is_synthetic: bool = Form(False), is_surveyed: bool = Form(False), layer: str | None = Form(None),
                      pk_type: str | None = Form(None), type_field: str = Form("pk_type"), type_map: str | None = Form(None),
                      notes: str = Form(""), db: Session = Depends(get_db)):
    """Import GeoJSON / GeoPackage / zipped Shapefile / KML (vector) or a DEM raster (GeoTIFF ...).

    A licence must be declared for every import. ``pk_type`` assigns one feature type to the
    whole layer; alternatively ``type_field`` (+ optional JSON ``type_map``) maps attribute values."""
    s = get_site(db, site_id)
    if not license.strip():
        raise HTTPException(422, "a licence (or 'proprietary - authorised use') must be declared")
    tm = None
    if type_map:
        try:
            tm = json.loads(type_map)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, "type_map must be a JSON object") from exc
    name = Path(file.filename or "upload").name
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / name
        with open(dest, "wb") as fh:
            shutil.copyfileobj(file.file, fh)
        try:
            res = svc.import_file(db, s, dest, filename=name, license=license, attribution=attribution,
                                  is_synthetic=is_synthetic, is_surveyed=is_surveyed, layer=layer, pk_type=pk_type,
                                  type_field=type_field, type_map=tm, notes=notes)
        except importer.ImportErrorWithDetail as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc
    return res


@router.post("/sites/{site_id}/layers")
async def list_file_layers(site_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    get_site(db, site_id)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / Path(file.filename or "upload").name
        with open(dest, "wb") as fh:
            shutil.copyfileobj(file.file, fh)
        try:
            return {"layers": importer.list_layers(dest)}
        except importer.ImportErrorWithDetail as exc:
            raise HTTPException(422, str(exc)) from exc


@router.get("/sites/{site_id}/terrain")
def terrain(site_id: int, db: Session = Depends(get_db)):
    s = get_site(db, site_id)
    if not s.terrain:
        raise HTTPException(404, "no terrain imported for this site")
    return s.terrain


def _model(db: Session, site: Site):
    feats = svc.site_features(db, site.id)
    try:
        return feats, build_site_model(feats, (site.origin_lon, site.origin_lat))
    except SiteModelError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/sites/{site_id}/network")
def network(site_id: int, db: Session = Depends(get_db)):
    """Pedestrian network derived from the corridors, gates and areas, with validation warnings."""
    s = get_site(db, site_id)
    _feats, m = _model(db, s)
    feats = []
    for n, p in m.nodes.items():
        g = m.proj.to_wgs84(p)
        feats.append({"type": "Feature", "geometry": mapping(g), "properties": {"kind": "node", "node": n, "role": m.node_kind[n]}})
    for lk in m.links.values():
        g = m.proj.to_wgs84(lk.geom)
        feats.append({"type": "Feature", "geometry": mapping(g), "properties": {
            "kind": "link", "link": lk.id, "u": lk.u, "v": lk.v, "corridor_id": lk.corridor_id, "link_kind": lk.kind,
            "width_m": round(lk.width, 2), "length_m": round(lk.length, 1), "capacity_pps": round(lk.capacity_pps, 2),
            "emergency_only": lk.emergency_only, "surface": lk.surface}})
    walk = m.proj.to_wgs84(m.walkable)
    g = m.graph(allow_emergency=True)
    comps = nx.number_weakly_connected_components(g) if len(g) else 0
    return {"type": "FeatureCollection", "features": feats, "walkable": mapping(walk),
            "stats": {"nodes": len(m.nodes), "links": len(m.links), "walkable_area_m2": round(m.walkable.area, 1),
                      "connected_components": comps, "entries": [x.id for x in m.entry_gates()],
                      "exits": [x.id for x in m.exit_gates()],
                      "areas": {a.id: {"usable_area_m2": round(a.usable_area, 1), "connected": a.node is not None} for a in m.areas.values()}},
            "warnings": m.warnings}


class RouteQuery(BaseModel):
    from_id: str
    to_id: str
    k: int = Field(3, ge=1, le=8)
    closed_corridors: list[str] = []
    allow_emergency: bool = False


@router.post("/sites/{site_id}/routes")
def routes(site_id: int, q: RouteQuery, db: Session = Depends(get_db)):
    """Alternative routes (Yen's k-shortest paths on free-flow time) between two gates/areas,
    with capacity of the narrowest link (the route's bottleneck)."""
    s = get_site(db, site_id)
    _feats, m = _model(db, s)

    def node_of(fid):
        if fid in m.gates and m.gates[fid].node is not None:
            return m.gates[fid].node
        if fid in m.areas and m.areas[fid].node is not None:
            return m.areas[fid].node
        raise HTTPException(422, f"'{fid}' is not a connected gate or area")

    g = m.graph(closed_corridors=set(q.closed_corridors), allow_emergency=q.allow_emergency)
    try:
        paths = k_shortest(g, node_of(q.from_id), node_of(q.to_id), q.k)
    except RoutingError as exc:
        return {"routes": [], "unreachable": True, "message": str(exc)}
    out = []
    for p in paths:
        lks = [m.link_between(u, v) for u, v in zip(p[:-1], p[1:])]
        from shapely.ops import linemerge, unary_union

        geom = m.proj.to_wgs84(linemerge(unary_union([lk.geom for lk in lks])))
        bott = min(lks, key=lambda lk: lk.capacity_pps)
        out.append({"geometry": mapping(geom), "free_flow_time_s": round(path_time(g, p), 1),
                    "length_m": round(sum(lk.length for lk in lks), 1),
                    "bottleneck_capacity_ppm": round(bott.capacity_pps * 60, 1),
                    "bottleneck_corridor": bott.corridor_id,
                    "corridors": list(dict.fromkeys(lk.corridor_id for lk in lks if lk.corridor_id))})
    return {"routes": out, "unreachable": False,
            "method": "Yen k-shortest loopless paths on free-flow walking time; capacity = 1.22 p/(m s) x width"}


@router.get("/sites/{site_id}/export.geojson")
def export_site(site_id: int, db: Session = Depends(get_db)):
    s = get_site(db, site_id)
    return {"type": "FeatureCollection", "name": s.name, "features": svc.site_features(db, site_id),
            "metadata": {"synthetic": s.is_synthetic, "site_version": s.version}}


# --------------------------------------------------------------------- observations
class ObservationIn(BaseModel):
    zone_fid: str
    count: float = Field(..., ge=0)
    kind: str = Field("observed", pattern="^(observed|forecast)$")
    t_offset_s: float | None = None
    observed_at: str | None = None
    source: str = Field("manual", pattern="^(manual|cctv|counter|sensor|other)$")
    notes: str = ""


def _obs_dict(o: Observation) -> dict:
    return {"id": o.id, "zone_fid": o.zone_fid, "kind": o.kind, "count": o.count, "t_offset_s": o.t_offset_s,
            "observed_at": o.observed_at.isoformat() if o.observed_at else None, "source": o.source, "notes": o.notes}


@router.get("/sites/{site_id}/observations")
def list_observations(site_id: int, db: Session = Depends(get_db)):
    get_site(db, site_id)
    return [_obs_dict(o) for o in db.scalars(select(Observation).where(Observation.site_id == site_id).order_by(Observation.t_offset_s))]


@router.post("/sites/{site_id}/observations", status_code=201)
def add_observations(site_id: int, items: list[ObservationIn], db: Session = Depends(get_db)):
    """Manual or uploaded counts. Stored separately from simulation output and always labelled
    'observed' or 'forecast'. (No live sensor integration is implemented in this release.)"""
    from datetime import datetime

    get_site(db, site_id)
    fids = set(db.scalars(select(Feature.fid).where(Feature.site_id == site_id)))
    out = []
    for it in items:
        if it.zone_fid not in fids:
            raise HTTPException(422, f"unknown zone/feature '{it.zone_fid}'")
        ts = None
        if it.observed_at:
            try:
                ts = datetime.fromisoformat(it.observed_at)
            except ValueError as exc:
                raise HTTPException(422, "observed_at must be ISO-8601") from exc
        o = Observation(site_id=site_id, zone_fid=it.zone_fid, kind=it.kind, count=it.count, t_offset_s=it.t_offset_s,
                        observed_at=ts, source=it.source, notes=it.notes)
        db.add(o)
        out.append(o)
    db.commit()
    return [_obs_dict(o) for o in out]


@router.post("/sites/{site_id}/observations/csv", status_code=201)
async def upload_observations(site_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """CSV columns: zone_fid,count[,kind][,t_offset_s][,observed_at][,source][,notes]"""
    import csv
    import io

    text_ = (await file.read()).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text_)))
    if not rows or "zone_fid" not in rows[0] or "count" not in rows[0]:
        raise HTTPException(422, "CSV needs at least the columns zone_fid and count")
    items = []
    for i, r in enumerate(rows):
        try:
            items.append(ObservationIn(zone_fid=r["zone_fid"], count=float(r["count"]), kind=r.get("kind") or "observed",
                                       t_offset_s=float(r["t_offset_s"]) if r.get("t_offset_s") else None,
                                       observed_at=r.get("observed_at") or None, source=r.get("source") or "manual",
                                       notes=r.get("notes") or ""))
        except Exception as exc:
            raise HTTPException(422, f"row {i + 2}: {exc}") from exc
    return add_observations(site_id, items, db)


@router.delete("/sites/{site_id}/observations/{obs_id}", status_code=204)
def delete_observation(site_id: int, obs_id: int, db: Session = Depends(get_db)):
    o = db.get(Observation, obs_id)
    if o is None or o.site_id != site_id:
        raise HTTPException(404, "observation not found")
    db.delete(o)
    db.commit()
