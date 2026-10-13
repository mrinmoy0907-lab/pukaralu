"""Simulation runs: start, monitor (SSE), cancel, results, comparison, reports."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import APP_VERSION, get_settings
from ..db import SessionLocal, get_db
from ..geo.site_model import build_site_model
from ..models import Dataset, Run
from ..reports import exports, pdf
from ..services import sites as svc
from ..services.jobs import manager
from ..sim.config import ScenarioConfig
from ..sim.runner import engine_version, load
from .deps import dataset_dict, get_run, get_scenario, get_site, profile_for, run_dict, site_dict
from .scenarios import check_against_site, parse_config

router = APIRouter(prefix="/api", tags=["runs"])


def _dir(run_id: str):
    return get_settings().results_dir / run_id


def _load(run: Run, name: str):
    if run.status != "completed":
        raise HTTPException(409, f"run is {run.status}; results are available once it has completed")
    p = _dir(run.id) / f"{name}.json.gz"
    if not p.exists():
        raise HTTPException(404, f"{name} not available for this run")
    return load(p)


class RunIn(BaseModel):
    seed: int | None = Field(None, ge=0)
    engine: str | None = Field(None, pattern="^(jupedsim|macro_ctm)$")


@router.post("/scenarios/{scenario_id}/runs", status_code=202)
def start_run(scenario_id: int, body: RunIn | None = None, db: Session = Depends(get_db)):
    sc = get_scenario(db, scenario_id)
    site = get_site(db, sc.site_id)
    cfg_d = dict(sc.config)
    if body and body.seed is not None:
        cfg_d["seed"] = body.seed
    if body and body.engine:
        cfg_d["engine"] = body.engine
        if body.engine == "macro_ctm" and cfg_d.get("time_step_s", 0.05) < 0.25:
            cfg_d["time_step_s"] = 1.0
        if body.engine == "jupedsim" and cfg_d.get("time_step_s", 1.0) > 0.1:
            cfg_d["time_step_s"] = 0.05
    cfg = parse_config(cfg_d)
    check_against_site(db, site, cfg)
    feats = svc.site_features(db, site.id)
    profile = profile_for(db, cfg.threshold_profile_id)
    run = Run(id=uuid.uuid4().hex, scenario_id=sc.id, site_id=site.id, name=sc.name, status="queued", engine=cfg.engine,
              engine_version=engine_version(cfg.engine), seed=cfg.seed, config=cfg.model_dump(mode="json"),
              site_version=site.version, features_hash=svc.features_hash(feats), features_snapshot=feats,
              threshold_profile=profile, app_version=APP_VERSION, review={"status": "draft"},
              method="Agent-based simulation (JuPedSim)" if cfg.engine == "jupedsim" else "Macroscopic flow model (CTM)")
    db.add(run)
    db.commit()
    manager().submit(run.id, feats, (site.origin_lon, site.origin_lat), run.config, profile, _dir(run.id))
    return run_dict(run)


@router.get("/runs")
def list_runs(site_id: int | None = None, scenario_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Run).order_by(Run.created_at.desc())
    if site_id:
        q = q.where(Run.site_id == site_id)
    if scenario_id:
        q = q.where(Run.scenario_id == scenario_id)
    return [run_dict(r) for r in db.scalars(q.limit(200))]


@router.get("/runs/{run_id}")
def get_run_detail(run_id: str, db: Session = Depends(get_db)):
    return run_dict(get_run(db, run_id), full=True)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    r = get_run(db, run_id)
    if r.status not in ("queued", "running"):
        raise HTTPException(409, f"run is already {r.status}")
    manager().cancel(run_id)
    return {"ok": True}


@router.post("/runs/{run_id}/rerun", status_code=202)
def rerun(run_id: str, db: Session = Depends(get_db)):
    """Reproduce a run exactly: same features snapshot, configuration, seed and thresholds."""
    r = get_run(db, run_id)
    site = get_site(db, r.site_id)
    new = Run(id=uuid.uuid4().hex, scenario_id=r.scenario_id, site_id=r.site_id, name=f"{r.name} (reproduction)",
              status="queued", engine=r.engine, engine_version=engine_version(r.engine), seed=r.seed, config=r.config,
              site_version=r.site_version, features_hash=r.features_hash, features_snapshot=r.features_snapshot,
              threshold_profile=r.threshold_profile, app_version=APP_VERSION, review={"status": "draft", "reproduces": r.id})
    db.add(new)
    db.commit()
    manager().submit(new.id, r.features_snapshot, (site.origin_lon, site.origin_lat), r.config, r.threshold_profile, _dir(new.id))
    return run_dict(new)


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: str, db: Session = Depends(get_db)):
    import shutil

    r = get_run(db, run_id)
    if r.status in ("queued", "running"):
        manager().cancel(run_id)
    db.delete(r)
    db.commit()
    shutil.rmtree(_dir(run_id), ignore_errors=True)


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str):
    """Server-sent events with run status/progress until the run finishes."""

    async def gen():
        last = None
        while True:
            db = SessionLocal()
            try:
                r = db.get(Run, run_id)
                if r is None:
                    yield "event: error\ndata: {\"error\": \"not found\"}\n\n"
                    return
                d = {"id": r.id, "status": r.status, "progress": r.progress, "message": r.message, "error": r.error}
            finally:
                db.close()
            if d != last:
                yield f"data: {json.dumps(d)}\n\n"
                last = d
            if d["status"] in ("completed", "failed", "cancelled"):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/runs/{run_id}/analysis")
def analysis(run_id: str, db: Session = Depends(get_db)):
    return _load(get_run(db, run_id), "analysis")


@router.get("/runs/{run_id}/series")
def series(run_id: str, db: Session = Depends(get_db)):
    return _load(get_run(db, run_id), "series")


@router.get("/runs/{run_id}/grid")
def grid(run_id: str, every: int = Query(1, ge=1, le=100), db: Session = Depends(get_db)):
    g = _load(get_run(db, run_id), "grid")
    if every > 1:
        g["frames"] = g["frames"][::every]
        g["times"] = g["times"][::every]
    return g


@router.get("/runs/{run_id}/agents")
def agents(run_id: str, every: int = Query(1, ge=1, le=100), db: Session = Depends(get_db)):
    r = get_run(db, run_id)
    if r.engine != "jupedsim":
        raise HTTPException(404, "macroscopic runs have no individual agents; use /links for computed flows")
    a = _load(r, "agents")
    if every > 1:
        a["frames"] = a["frames"][::every]
    return a


@router.get("/runs/{run_id}/links")
def links(run_id: str, every: int = Query(1, ge=1, le=100), db: Session = Depends(get_db)):
    r = get_run(db, run_id)
    if r.engine != "macro_ctm":
        raise HTTPException(404, "link densities are produced by macroscopic runs")
    d = _load(r, "links")
    if every > 1:
        d["frames"] = d["frames"][::every]
        d["times"] = d["times"][::every]
    return d


class ReviewIn(BaseModel):
    status: str = Field(..., pattern="^(draft|reviewed|approved|rejected)$")
    prepared_by: str | None = None
    reviewed_by: str | None = None
    review_comments: str | None = None
    approved_by: str | None = None


@router.patch("/runs/{run_id}/review")
def review(run_id: str, body: ReviewIn, db: Session = Depends(get_db)):
    """Record review/approval of a run's results (an approval record; it does not change results)."""
    r = get_run(db, run_id)
    if body.status == "approved" and not body.approved_by:
        raise HTTPException(422, "approved_by is required to mark a run approved")
    rv = dict(r.review or {})
    rv.update({k: v for k, v in body.model_dump().items() if v is not None})
    today = datetime.now(timezone.utc).date().isoformat()
    if body.status == "reviewed":
        rv["reviewed_on"] = today
    if body.status == "approved":
        rv["approved_on"] = today
    r.review = rv
    db.commit()
    return run_dict(r)


# ------------------------------------------------------------------ exports
@router.get("/runs/{run_id}/export.zip")
def export_csv(run_id: str, db: Session = Depends(get_db)):
    r = get_run(db, run_id)
    data = exports.run_csv_zip(run_dict(r), _load(r, "analysis"), _load(r, "series"))
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="run_{run_id[:8]}_csv.zip"'})


@router.get("/runs/{run_id}/density.geojson")
def density_geojson(run_id: str, which: str = Query("max", pattern="^(max|above)$"), db: Session = Depends(get_db)):
    return exports.density_geojson(_load(get_run(db, run_id), "grid"), "max" if which == "max" else "above")


@router.get("/runs/{run_id}/bottlenecks.geojson")
def bottlenecks_geojson(run_id: str, db: Session = Depends(get_db)):
    return exports.bottlenecks_geojson(_load(get_run(db, run_id), "analysis"))


@router.get("/runs/{run_id}/report.pdf")
def report_pdf(run_id: str, db: Session = Depends(get_db)):
    r = get_run(db, run_id)
    site = get_site(db, r.site_id)
    cfg = ScenarioConfig.model_validate(r.config)
    model = build_site_model(r.features_snapshot, (site.origin_lon, site.origin_lat), corridor_overrides=cfg.corridor_overrides,
                             gate_overrides=cfg.gate_overrides, holding_overrides=cfg.holding_overrides)
    datasets = [dataset_dict(d) for d in db.scalars(select(Dataset).where(Dataset.site_id == site.id))]
    data = pdf.run_report(run_dict(r), site_dict(site), datasets, cfg, _load(r, "analysis"), _load(r, "series"),
                          _load(r, "grid"), model, r.threshold_profile)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="report_{run_id[:8]}.pdf"'})


def _compare(db: Session, a: str, b: str):
    ra, rb = get_run(db, a), get_run(db, b)
    for r in (ra, rb):
        if r.status != "completed":
            raise HTTPException(409, f"run {r.id} is {r.status}")
    if ra.site_id != rb.site_id:
        raise HTTPException(422, "runs belong to different sites")
    rows = pdf.compare_rows(ra.summary or {}, rb.summary or {})
    return ra, rb, rows


@router.get("/compare")
def compare(a: str, b: str, db: Session = Depends(get_db)):
    """Side-by-side metrics of two completed runs; differences are computed from their results."""
    ra, rb, rows = _compare(db, a, b)
    warn = []
    if ra.engine != rb.engine:
        warn.append("The runs use different simulation methods; part of the difference is due to the method.")
    if ra.features_hash != rb.features_hash:
        warn.append("The runs used different versions of the site data.")
    if ra.threshold_profile.get("limits") != rb.threshold_profile.get("limits"):
        warn.append("The runs used different density thresholds.")
    return {"baseline": run_dict(ra), "alternative": run_dict(rb), "rows": rows, "warnings": warn}


@router.get("/compare/report.pdf")
def compare_pdf(a: str, b: str, db: Session = Depends(get_db)):
    ra, rb, rows = _compare(db, a, b)
    site = get_site(db, ra.site_id)
    data = pdf.compare_report(run_dict(ra), run_dict(rb), site_dict(site), rows, _load(ra, "series"), _load(rb, "series"))
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="comparison.pdf"'})


@router.get("/compare/export.csv")
def compare_csv(a: str, b: str, db: Session = Depends(get_db)):
    _ra, _rb, rows = _compare(db, a, b)
    return Response(exports._csv(rows), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="comparison.csv"'})
