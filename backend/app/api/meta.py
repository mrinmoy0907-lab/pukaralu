"""Metadata: feature catalogue, engines, thresholds, licences, assumptions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import APP_VERSION
from ..db import get_db, is_postgis
from ..geo.catalog import FEATURE_TYPES, SURFACE_SPEED_FACTOR
from ..geo.site_model import JAM_DENSITY, SPECIFIC_FLOW_MAX
from ..models import ThresholdProfile
from ..sim.ctm_engine import CTMEngine
from ..sim.jupedsim_engine import JuPedSimEngine
from ..sim.presets import PRESETS
from ..sim.thresholds import DEFAULT_PROFILE, merged, validate_profile

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health():
    from ..db import engine

    dialect = engine().dialect.name
    return {"ok": True, "version": APP_VERSION, "database": "postgis" if is_postgis() else dialect}


@router.get("/meta")
def meta():
    return {
        "version": APP_VERSION,
        "feature_types": FEATURE_TYPES,
        "presets": [{"key": k, "label": lab} for k, lab in PRESETS],
        "engines": [
            {"key": "jupedsim", "label": "Agent-based (JuPedSim)", "version": JuPedSimEngine.version(),
             "method_type": "agent_based", "license": "LGPL-3.0-or-later",
             "description": "Individual pedestrians with collision avoidance (Collision-Free Speed Model or Social Force Model)."},
            {"key": "macro_ctm", "label": "Macroscopic flow (Cell Transmission Model)", "version": CTMEngine.version(),
             "method_type": "macroscopic", "license": "project (MIT)",
             "description": "Aggregate flows on the corridor network; triangular fundamental diagram calibrated to Weidmann (1993)."},
        ],
        "assumptions": {
            "specific_flow_max_p_per_m_s": SPECIFIC_FLOW_MAX,
            "jam_density_p_per_m2": JAM_DENSITY,
            "default_walking_speed_m_s": {"mean": 1.34, "sd": 0.26, "source": "Weidmann (1993)"},
            "surface_speed_factor": SURFACE_SPEED_FACTOR,
            "units": {"density": "persons/m2", "flow": "persons/min", "time": "s", "length": "m"},
        },
        "live_sensor_integration": False,
    }


class ProfileIn(BaseModel):
    name: str
    values: dict
    status: str = "draft"
    approved_by: str | None = None
    approved_on: str | None = None
    notes: str = ""


def _pd(p: ThresholdProfile) -> dict:
    return {"id": p.id, "name": p.name, "values": merged(p.values), "status": p.status, "approved_by": p.approved_by,
            "approved_on": p.approved_on, "notes": p.notes}


@router.get("/threshold-profiles")
def list_profiles(db: Session = Depends(get_db)):
    return [_pd(p) for p in db.scalars(select(ThresholdProfile).order_by(ThresholdProfile.id))]


@router.get("/threshold-profiles/default")
def default_profile():
    return DEFAULT_PROFILE


def _check(body: ProfileIn) -> dict:
    vals = merged(body.values)
    errs = validate_profile(vals)
    if body.status == "approved" and not (body.approved_by and body.approved_on):
        errs.append("an approved profile needs approved_by and approved_on")
    if errs:
        raise HTTPException(422, {"errors": errs})
    return vals


@router.post("/threshold-profiles", status_code=201)
def create_profile(body: ProfileIn, db: Session = Depends(get_db)):
    p = ThresholdProfile(name=body.name, values=_check(body), status=body.status, approved_by=body.approved_by,
                         approved_on=body.approved_on, notes=body.notes)
    db.add(p)
    db.commit()
    return _pd(p)


@router.put("/threshold-profiles/{pid}")
def update_profile(pid: int, body: ProfileIn, db: Session = Depends(get_db)):
    p = db.get(ThresholdProfile, pid)
    if p is None:
        raise HTTPException(404, "profile not found")
    p.values, p.name, p.status, p.approved_by, p.approved_on, p.notes = (
        _check(body), body.name, body.status, body.approved_by, body.approved_on, body.notes)
    db.commit()
    return _pd(p)
