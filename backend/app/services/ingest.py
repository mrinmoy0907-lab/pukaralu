"""Data drop folder ingestion.

Every sub-folder of ``PK_SITES_DIR`` (default ``data/sites``) is one site::

    data/sites/<site_folder>/
        site.json        optional manifest (name, origin, basemap, licence defaults, per-file options, model placement)
        vector/          GeoJSON, GeoPackage, Shapefile (.shp + sidecars or .zip), KML, FlatGeobuf ...
        dem/             DTM / DEM / DSM rasters (GeoTIFF, .asc, .img, VRT ...) -> 3D terrain
        terrain/         quantized-mesh terrain tileset (layer.json + tiles), e.g. from cesium-terrain-builder
        tiles3d/<name>/  3D Tiles tilesets (tileset.json): buildings, photogrammetry meshes, point clouds
        models/          glTF / GLB models placed with the "models" entries of site.json
        imagery/         orthophoto / drone mosaic GeoTIFF -> draped image overlay

A scan creates missing sites and (re)imports every file whose content changed
(SHA-256), so replacing a file in the folder and pressing *Scan data folder*
(or restarting) updates the Digital Twin. Unchanged files are skipped.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Dataset, Feature, Scenario, Site
from . import importer
from . import sites as svc

log = logging.getLogger(__name__)

MODEL_EXT = {".glb", ".gltf"}
_last_report: dict = {"ran_at": None, "sites": []}


def last_report() -> dict:
    return _last_report


def _manifest(folder: Path) -> dict:
    f = folder / "site.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise importer.ImportErrorWithDetail(f"{f}: invalid JSON ({exc})") from exc


def _files(folder: Path, sub: str, exts: set[str]) -> list[Path]:
    d = folder / sub
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts:
            # a .shp inside a zip is handled by the zip; sidecar files are read with their .shp
            out.append(p)
    return out


def _opts(manifest: dict, rel: str) -> dict:
    d = {"license": "unspecified - declare it in site.json", "attribution": "", "is_synthetic": False,
         "is_surveyed": False, "notes": ""}
    d.update(manifest.get("defaults") or {})
    d.update((manifest.get("files") or {}).get(rel) or {})
    return d


def _dataset(db: Session, site: Site, rel: str) -> Dataset | None:
    return db.scalars(select(Dataset).where(Dataset.site_id == site.id, Dataset.filename == rel)).first()


def _drop_dataset(db: Session, ds: Dataset) -> None:
    for f in db.scalars(select(Feature).where(Feature.dataset_id == ds.id)):
        db.delete(f)
    db.delete(ds)
    db.flush()


def _url(folder: Path, p: Path) -> str:
    rel = p.relative_to(get_settings().sites_dir).as_posix()
    return f"/sitedata/{rel}"


def ingest_folder(db: Session, folder: Path) -> dict:
    manifest = _manifest(folder)
    rep = {"folder": folder.name, "site_id": None, "imported": [], "skipped": [], "errors": [], "assets": {}}
    site = next((s for s in db.scalars(select(Site)) if (s.assets or {}).get("source_folder") == folder.name), None)
    created = False
    if site is None:
        origin = manifest.get("origin") or [0.0, 0.0]
        site = Site(name=manifest.get("name") or folder.name.replace("_", " "), description=manifest.get("description", ""),
                    is_synthetic=bool(manifest.get("is_synthetic", False)), origin_lon=float(origin[0]),
                    origin_lat=float(origin[1]), basemap=manifest.get("basemap", "osm"),
                    provenance={"synthetic": bool(manifest.get("is_synthetic", False)), "source_folder": folder.name},
                    assets={"source_folder": folder.name})
        db.add(site)
        db.flush()
        created = True
    rep["site_id"] = site.id

    # ------------------------------------------------------------ vectors
    for p in _files(folder, "vector", importer.VECTOR_EXT):
        rel = p.relative_to(folder).as_posix()
        if p.suffix.lower() == ".json" and p.name == "site.json":
            continue
        digest = importer.sha256(p)
        old = _dataset(db, site, rel)
        if old is not None and old.sha256 == digest:
            rep["skipped"].append(rel)
            continue
        o = _opts(manifest, rel)
        try:
            if old is not None:
                _drop_dataset(db, old)
            res = svc.import_file(db, site, p, filename=rel, license=o["license"], attribution=o["attribution"],
                                  is_synthetic=bool(o["is_synthetic"]), is_surveyed=bool(o["is_surveyed"]),
                                  layer=o.get("layer"), pk_type=o.get("pk_type"), type_field=o.get("type_field", "pk_type"),
                                  type_map=o.get("type_map"), notes=o.get("notes", ""))
            rep["imported"].append({"file": rel, "kind": "vector", "features": res.get("imported"),
                                    "warnings": res.get("warnings", []) + res.get("rejected", [])})
        except importer.ImportErrorWithDetail as exc:
            db.rollback()
            rep["errors"].append(f"{rel}: {exc}")

    feats = svc.site_features(db, site.id)
    if created and not manifest.get("origin") and feats:
        b = svc.bounds_of(feats, 0)
        site.origin_lon, site.origin_lat = round((b[0] + b[2]) / 2, 6), round((b[1] + b[3]) / 2, 6)

    # ------------------------------------------------------------ DEM / DTM (latest file wins)
    dems = _files(folder, "dem", importer.RASTER_EXT)
    if dems:
        p = dems[-1]
        rel = p.relative_to(folder).as_posix()
        digest = importer.sha256(p)
        cur = (site.terrain or {}).get("dataset_id")
        cur_ds = db.get(Dataset, cur) if cur else None
        if cur_ds is not None and cur_ds.sha256 == digest:
            rep["skipped"].append(rel)
        elif not feats:
            rep["errors"].append(f"{rel}: add vector data first so the terrain extent is known")
        else:
            o = _opts(manifest, rel)
            try:
                if cur_ds is not None:
                    db.delete(cur_ds)
                res = svc.import_file(db, site, p, filename=rel, license=o["license"], attribution=o["attribution"],
                                      is_synthetic=bool(o["is_synthetic"]), is_surveyed=bool(o["is_surveyed"]), notes=o.get("notes", ""))
                rep["imported"].append({"file": rel, "kind": "dem", "min": res["min"], "max": res["max"]})
            except importer.ImportErrorWithDetail as exc:
                db.rollback()
                rep["errors"].append(f"{rel}: {exc}")

    # ------------------------------------------------------------ 3D assets and imagery
    assets = dict(site.assets or {})
    assets["source_folder"] = folder.name
    terrain_dir = folder / "terrain"
    assets["terrain_url"] = _url(folder, terrain_dir) + "/" if (terrain_dir / "layer.json").exists() else None
    tilesets = []
    for ts in sorted((folder / "tiles3d").rglob("tileset.json")) if (folder / "tiles3d").is_dir() else []:
        name = ts.parent.name if ts.parent != folder / "tiles3d" else "tileset"
        conf = (manifest.get("tilesets") or {}).get(name, {})
        tilesets.append({"name": name, "url": _url(folder, ts), "height_offset": conf.get("height_offset", 0)})
    assets["tilesets"] = tilesets
    placements = {m.get("file"): m for m in manifest.get("models") or []}
    models = []
    for p in _files(folder, "models", MODEL_EXT):
        rel = p.relative_to(folder).as_posix()
        m = placements.get(rel)
        if m is None:
            rep["errors"].append(f"{rel}: no placement in site.json 'models' - placed at the site origin")
            m = {}
        models.append({"name": m.get("name", p.stem), "url": _url(folder, p), "lon": m.get("lon", site.origin_lon),
                       "lat": m.get("lat", site.origin_lat), "height": m.get("height", 0.0),
                       "heading_deg": m.get("heading_deg", 0.0), "scale": m.get("scale", 1.0)})
    assets["models"] = models
    imagery = []
    for p in _files(folder, "imagery", {".tif", ".tiff", ".jp2", ".img", ".vrt"}):
        rel = p.relative_to(folder).as_posix()
        digest = importer.sha256(p)
        prev = next((i for i in (site.assets or {}).get("imagery", []) if i.get("file") == rel), None)
        out = get_settings().derived_dir / f"site{site.id}" / f"{p.stem}_{digest[:8]}.png"
        if prev and prev.get("sha256") == digest and out.exists():
            imagery.append(prev)
            rep["skipped"].append(rel)
            continue
        try:
            info = importer.read_ortho(p, out)
            o = _opts(manifest, rel)
            imagery.append({"file": rel, "name": p.stem, "url": f"/derived/site{site.id}/{out.name}", "sha256": digest,
                            "license": o["license"], "attribution": o["attribution"], **info})
            rep["imported"].append({"file": rel, "kind": "imagery"})
        except importer.ImportErrorWithDetail as exc:
            rep["errors"].append(f"{rel}: {exc}")
    assets["imagery"] = imagery
    if manifest.get("basemap"):
        site.basemap = manifest["basemap"]
    site.assets = assets
    rep["assets"] = {"terrain_url": assets["terrain_url"], "tilesets": len(tilesets), "models": len(models),
                     "imagery": len(imagery)}
    db.commit()

    if manifest.get("create_presets") and not db.scalars(select(Scenario).where(Scenario.site_id == site.id)).first():
        try:
            n = len(svc.create_preset_scenarios(db, site))
            rep["imported"].append({"kind": "presets", "scenarios": n})
        except Exception as exc:  # presets need a connected network; report and continue
            db.rollback()
            rep["errors"].append(f"presets not created: {exc}")
    return rep


def ingest_all(db: Session) -> dict:
    global _last_report
    root = get_settings().sites_dir
    root.mkdir(parents=True, exist_ok=True)
    reports = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        try:
            reports.append(ingest_folder(db, folder))
        except Exception as exc:  # one bad folder must not stop the others
            db.rollback()
            log.exception("ingest of %s failed", folder)
            reports.append({"folder": folder.name, "errors": [str(exc)], "imported": [], "skipped": []})
    _last_report = {"ran_at": datetime.now(timezone.utc).isoformat(), "root": str(root), "sites": reports}
    return _last_report
