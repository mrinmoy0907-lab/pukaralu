from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Dataset, Run, Scenario, Site, ThresholdProfile


def get_site(db: Session, site_id: int) -> Site:
    s = db.get(Site, site_id)
    if s is None:
        raise HTTPException(404, f"site {site_id} not found")
    return s


def get_scenario(db: Session, scenario_id: int) -> Scenario:
    s = db.get(Scenario, scenario_id)
    if s is None:
        raise HTTPException(404, f"scenario {scenario_id} not found")
    return s


def get_run(db: Session, run_id: str) -> Run:
    r = db.get(Run, run_id)
    if r is None:
        raise HTTPException(404, f"run {run_id} not found")
    return r


def site_dict(s: Site, n_features: int | None = None) -> dict:
    return {"id": s.id, "name": s.name, "description": s.description, "is_synthetic": s.is_synthetic,
            "origin": [s.origin_lon, s.origin_lat], "basemap": s.basemap, "tileset_url": s.tileset_url,
            "has_terrain": s.terrain is not None, "provenance": s.provenance, "version": s.version,
            "n_features": n_features, "updated_at": s.updated_at.isoformat() if s.updated_at else None}


def dataset_dict(d: Dataset) -> dict:
    return {"id": d.id, "filename": d.filename, "kind": d.kind, "format": d.format, "layer": d.layer,
            "feature_count": d.feature_count, "source_crs": d.source_crs, "license": d.license,
            "attribution": d.attribution, "is_synthetic": d.is_synthetic, "is_surveyed": d.is_surveyed,
            "notes": d.notes, "sha256": d.sha256, "imported_at": d.imported_at.isoformat() if d.imported_at else None}


def scenario_dict(s: Scenario) -> dict:
    return {"id": s.id, "site_id": s.site_id, "name": s.name, "description": s.description, "preset": s.preset,
            "config": s.config, "updated_at": s.updated_at.isoformat() if s.updated_at else None}


def run_dict(r: Run, full: bool = False) -> dict:
    d = {"id": r.id, "scenario_id": r.scenario_id, "site_id": r.site_id, "name": r.name, "status": r.status,
         "progress": r.progress, "message": r.message, "engine": r.engine, "engine_version": r.engine_version,
         "method": r.method, "seed": r.seed, "summary": r.summary, "error": r.error, "review": r.review or {},
         "site_version": r.site_version, "features_hash": r.features_hash, "app_version": r.app_version,
         "created_at": r.created_at.isoformat() if r.created_at else None,
         "started_at": r.started_at.isoformat() if r.started_at else None,
         "finished_at": r.finished_at.isoformat() if r.finished_at else None}
    if full:
        d["config"] = r.config
        d["threshold_profile"] = r.threshold_profile
    return d


def profile_for(db: Session, profile_id: int | None) -> dict:
    from ..sim.thresholds import merged

    p = db.get(ThresholdProfile, profile_id) if profile_id else db.scalars(select(ThresholdProfile).order_by(ThresholdProfile.id)).first()
    if p is None:
        return merged(None)
    vals = merged(p.values)
    vals.update({"id": p.id, "name": p.name, "status": p.status, "approved_by": p.approved_by, "approved_on": p.approved_on})
    return vals
