from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path

from shapely.geometry import shape
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import is_postgis
from ..geo.catalog import CORRIDOR_DEFAULTS, FEATURE_TYPES, GATE_DEFAULTS
from ..models import Dataset, Feature, Scenario, Site, ThresholdProfile
from ..sim.thresholds import DEFAULT_PROFILE
from . import importer

log = logging.getLogger(__name__)

GEOM_COMPAT = {
    "Point": {"Point", "MultiPoint"},
    "LineString": {"LineString", "MultiLineString"},
    "Polygon": {"Polygon", "MultiPolygon"},
}


class FeatureValidationError(ValueError):
    pass


def validate_feature(f: dict) -> dict:
    """Validate and normalise one GeoJSON feature (raises FeatureValidationError)."""
    if not isinstance(f, dict) or f.get("type") != "Feature":
        raise FeatureValidationError("not a GeoJSON Feature")
    props = dict(f.get("properties") or {})
    t = props.get("pk_type")
    if t not in FEATURE_TYPES:
        raise FeatureValidationError(f"unknown pk_type '{t}'. Allowed: {', '.join(sorted(FEATURE_TYPES))}")
    try:
        g = shape(f["geometry"])
    except Exception as exc:
        raise FeatureValidationError(f"invalid geometry: {exc}") from exc
    if g.is_empty:
        raise FeatureValidationError("empty geometry")
    expected = FEATURE_TYPES[t]["geom"]
    allowed = GEOM_COMPAT[expected] | ({"Point"} if t == "assembly_point" else set())
    if g.geom_type not in allowed:
        raise FeatureValidationError(f"{t} requires a {expected} geometry, got {g.geom_type}")
    minx, miny, maxx, maxy = g.bounds
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
        raise FeatureValidationError("coordinates must be WGS84 longitude/latitude")
    if t in ("corridor", "emergency_corridor"):
        for k, v in CORRIDOR_DEFAULTS.items():
            props.setdefault(k, v)
        if t == "emergency_corridor":
            props["emergency_only"] = True
        try:
            if not 0.3 < float(props["width_m"]) <= 200:
                raise FeatureValidationError("width_m must be between 0.3 and 200 m")
        except (TypeError, ValueError) as exc:
            raise FeatureValidationError("width_m must be a number") from exc
        if props["direction"] not in ("both", "forward", "backward"):
            raise FeatureValidationError("direction must be both, forward or backward")
    if t == "gate":
        for k, v in GATE_DEFAULTS.items():
            props.setdefault(k, v)
        if props["role"] not in ("entry", "exit", "both"):
            raise FeatureValidationError("gate role must be entry, exit or both")
    if t == "holding_area" and props.get("capacity_persons") not in (None, ""):
        try:
            if int(props["capacity_persons"]) < 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise FeatureValidationError("capacity_persons must be a non-negative integer") from exc
    return {"type": "Feature", "id": f.get("id"), "geometry": f["geometry"], "properties": props}


def site_features(db: Session, site_id: int, pk_type: str | None = None, bbox=None) -> list[dict]:
    if bbox is not None and is_postgis():
        sql = ("SELECT fid FROM features WHERE site_id=:s AND geom && ST_MakeEnvelope(:a,:b,:c,:d,4326)"
               + (" AND pk_type=:t" if pk_type else ""))
        fids = {r[0] for r in db.execute(text(sql), {"s": site_id, "a": bbox[0], "b": bbox[1], "c": bbox[2], "d": bbox[3], "t": pk_type})}
        q = select(Feature).where(Feature.site_id == site_id, Feature.fid.in_(fids))
        return [f.to_geojson() for f in db.scalars(q)]
    q = select(Feature).where(Feature.site_id == site_id)
    if pk_type:
        q = q.where(Feature.pk_type == pk_type)
    feats = [f.to_geojson() for f in db.scalars(q.order_by(Feature.id))]
    if bbox is not None:
        from shapely.geometry import box

        b = box(*bbox)
        feats = [f for f in feats if shape(f["geometry"]).intersects(b)]
    return feats


def features_hash(features: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted(features, key=lambda f: str(f["id"])), sort_keys=True).encode()).hexdigest()


def unique_fid(db: Session, site_id: int, fid: str | None) -> str:
    fid = (str(fid) if fid else uuid.uuid4().hex[:10]).replace(" ", "_")[:90]
    existing = set(db.scalars(select(Feature.fid).where(Feature.site_id == site_id)))
    if fid not in existing:
        return fid
    i = 2
    while f"{fid}_{i}" in existing:
        i += 1
    return f"{fid}_{i}"


def add_features(db: Session, site: Site, features: list[dict], *, source: str, dataset_id: int | None = None) -> list[str]:
    fids = []
    for raw in features:
        f = validate_feature(raw)
        props = f["properties"]
        fid = unique_fid(db, site.id, f.get("id"))
        db.add(Feature(site_id=site.id, fid=fid, pk_type=props.pop("pk_type"), name=str(props.pop("name", "") or fid),
                       properties={k: v for k, v in props.items() if k not in ("source", "dataset_id")},
                       geometry=f["geometry"], dataset_id=dataset_id, source=source))
        db.flush()
        fids.append(fid)
    site.version += 1
    return fids


def bounds_of(features: list[dict], margin_deg: float = 0.002):
    gs = [shape(f["geometry"]) for f in features]
    if not gs:
        return None
    minx = min(g.bounds[0] for g in gs) - margin_deg
    miny = min(g.bounds[1] for g in gs) - margin_deg
    maxx = max(g.bounds[2] for g in gs) + margin_deg
    maxy = max(g.bounds[3] for g in gs) + margin_deg
    return (minx, miny, maxx, maxy)


def import_file(db: Session, site: Site, path: Path, *, filename: str, license: str, attribution: str,
                is_synthetic: bool, is_surveyed: bool, layer: str | None = None, pk_type: str | None = None,
                type_field: str = "pk_type", type_map: dict | None = None, notes: str = "") -> dict:
    ext = path.suffix.lower()
    digest = importer.sha256(path)
    if ext in importer.RASTER_EXT:
        feats = site_features(db, site.id)
        bnds = bounds_of(feats)
        if bnds is None:
            raise importer.ImportErrorWithDetail("import vector features before the DEM so the terrain extent is known")
        terrain = importer.read_dem(path, bnds)
        ds = Dataset(site_id=site.id, filename=filename, kind="dem", format=ext.lstrip("."), license=license,
                     attribution=attribution, is_synthetic=is_synthetic, is_surveyed=is_surveyed, notes=notes,
                     source_crs=terrain["source_crs"], sha256=digest)
        db.add(ds)
        db.flush()
        terrain["dataset_id"] = ds.id
        site.terrain = terrain
        site.version += 1
        db.commit()
        return {"dataset_id": ds.id, "kind": "dem", "min": terrain["min"], "max": terrain["max"], "warnings": []}
    if ext not in importer.VECTOR_EXT:
        raise importer.ImportErrorWithDetail(f"unsupported file type '{ext}'")
    feats, info = importer.read_vector(path, layer=layer, pk_type=pk_type, type_field=type_field, type_map=type_map,
                                       id_prefix=Path(filename).stem[:20])
    ds = Dataset(site_id=site.id, filename=filename, kind="vector", format=info.get("driver") or ext.lstrip("."),
                 layer=info.get("layer"), feature_count=len(feats), source_crs=info["source_crs"], license=license,
                 attribution=attribution, is_synthetic=is_synthetic, is_surveyed=is_surveyed, notes=notes, sha256=digest)
    db.add(ds)
    db.flush()
    errors = []
    ok = []
    for f in feats:
        try:
            ok += add_features(db, site, [f], source="synthetic" if is_synthetic else "imported", dataset_id=ds.id)
        except FeatureValidationError as exc:
            errors.append(f"{f.get('id')}: {exc}")
    ds.feature_count = len(ok)
    db.commit()
    return {"dataset_id": ds.id, "kind": "vector", "imported": len(ok), "rejected": errors[:50],
            "warnings": info["warnings"], "source_crs": info["source_crs"]}


def ensure_default_profile(db: Session) -> ThresholdProfile:
    p = db.scalars(select(ThresholdProfile).order_by(ThresholdProfile.id)).first()
    if p is None:
        p = ThresholdProfile(name=DEFAULT_PROFILE["name"], values=DEFAULT_PROFILE, status="draft",
                             notes=DEFAULT_PROFILE["notes"])
        db.add(p)
        db.commit()
    return p


def seed_demo(db: Session) -> None:
    """Create the synthetic demonstration site and the real-data reference site."""
    ensure_default_profile(db)
    if db.scalars(select(Site)).first() is not None:
        return
    data = get_settings().data_dir
    syn = data / "synthetic" / "demo_site.geojson"
    if syn.exists():
        meta = json.loads(syn.read_text()).get("metadata", {})
        lon, lat = meta.get("origin_lonlat", (85.0, 15.0))
        site = Site(name="SYNTHETIC demonstration ghat",
                    description=("Invented layout for testing and training. NOT surveyed data and NOT a real Pushkaralu ghat. "
                                 "Placed offshore on purpose. Replace with surveyed GIS data (docs/DATA_REPLACEMENT.md)."),
                    is_synthetic=True, origin_lon=lon, origin_lat=lat, basemap="grid",
                    provenance={"synthetic": True, "generator": "backend/scripts/generate_synthetic_site.py"})
        db.add(site)
        db.flush()
        import_file(db, site, syn, filename=syn.name, license="CC0-1.0 (synthetic)", attribution="Synthetic demo data",
                    is_synthetic=True, is_surveyed=False, notes="Synthetic demonstration geometry")
        dem = data / "synthetic" / "demo_dem.tif"
        if dem.exists():
            import_file(db, site, dem, filename=dem.name, license="CC0-1.0 (synthetic)", attribution="Synthetic terrain",
                        is_synthetic=True, is_surveyed=False, notes="Synthetic DEM")
        create_preset_scenarios(db, site)
    real = data / "real" / "godavari_rajahmundry_osm.geojson"
    if real.exists():
        g = [shape(f["geometry"]) for f in json.loads(real.read_text())["features"]]
        c = g[0].centroid
        site = Site(name="Godavari river at Rajahmundry - OSM reference layer",
                    description=("Real OpenStreetMap-derived river polygon (ODbL, generalised ~10 m). Contains no ghat or "
                                 "crowd-management infrastructure: import or draw surveyed features before simulating."),
                    is_synthetic=False, origin_lon=round(c.x, 5), origin_lat=round(c.y, 5), basemap="osm",
                    provenance={"synthetic": False, "source": "OpenStreetMap contributors via @geo-maps/earth-rivers-10m"})
        db.add(site)
        db.flush()
        import_file(db, site, real, filename=real.name, license="ODbL-1.0", attribution="(c) OpenStreetMap contributors",
                    is_synthetic=False, is_surveyed=False, notes="Generalised OSM water polygon, clipped to Rajahmundry")
    db.commit()


def create_preset_scenarios(db: Session, site: Site) -> list[Scenario]:
    from ..sim.config import ScenarioConfig
    from ..sim.presets import build_presets

    feats = site_features(db, site.id)
    out = []
    for key, cfg in build_presets(feats, (site.origin_lon, site.origin_lat)).items():
        cfg = ScenarioConfig.model_validate(cfg).model_dump(mode="json")
        sc = Scenario(site_id=site.id, name=cfg["name"], description=cfg["description"], preset=key, config=cfg)
        db.add(sc)
        out.append(sc)
    db.commit()
    return out
