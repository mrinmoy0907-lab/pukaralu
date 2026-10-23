"""Scenarios: create, edit, validate, presets, layout export."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..geo.routing import RoutingError
from ..geo.site_model import SiteModelError
from ..models import Scenario
from ..reports.exports import layout_geojson
from ..services import sites as svc
from ..sim.config import ScenarioConfig
from ..sim.planning import PlanningError
from ..sim.presets import PRESETS, build_presets
from ..sim.runner import validate
from .deps import get_scenario, get_site, scenario_dict

router = APIRouter(prefix="/api", tags=["scenarios"])


def _errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]


def parse_config(cfg: dict) -> ScenarioConfig:
    try:
        return ScenarioConfig.model_validate(cfg)
    except ValidationError as exc:
        raise HTTPException(422, {"errors": _errors(exc)}) from exc


def check_against_site(db: Session, site, cfg: ScenarioConfig) -> dict:
    from ..config import get_settings

    feats = svc.site_features(db, site.id)
    try:
        res = validate(feats, (site.origin_lon, site.origin_lat), cfg)
    except (PlanningError, SiteModelError, RoutingError) as exc:
        raise HTTPException(422, {"errors": [s.strip() for s in str(exc).split(";")]}) from exc
    st = get_settings()
    errs = []
    if cfg.duration_s > st.max_duration_s:
        errs.append(f"duration_s exceeds the server limit of {st.max_duration_s:.0f} s")
    if cfg.engine == "jupedsim" and res["expected_population"] > st.max_agents:
        errs.append(f"expected population {res['expected_population']} exceeds the agent limit of {st.max_agents}; "
                    "use the macroscopic engine or reduce demand")
    if errs:
        raise HTTPException(422, {"errors": errs})
    return res


class ScenarioIn(BaseModel):
    name: str
    description: str = ""
    config: dict
    preset: str | None = None


@router.get("/sites/{site_id}/scenarios")
def list_scenarios(site_id: int, db: Session = Depends(get_db)):
    get_site(db, site_id)
    return [scenario_dict(s) for s in db.scalars(select(Scenario).where(Scenario.site_id == site_id).order_by(Scenario.id))]


@router.post("/sites/{site_id}/scenarios", status_code=201)
def create_scenario(site_id: int, body: ScenarioIn, db: Session = Depends(get_db)):
    site = get_site(db, site_id)
    cfg = parse_config({**body.config, "name": body.name, "description": body.description})
    check_against_site(db, site, cfg)
    sc = Scenario(site_id=site_id, name=body.name, description=body.description, preset=body.preset,
                  config=cfg.model_dump(mode="json"))
    db.add(sc)
    db.commit()
    return scenario_dict(sc)


@router.get("/scenarios/{scenario_id}")
def get_scenario_detail(scenario_id: int, db: Session = Depends(get_db)):
    return scenario_dict(get_scenario(db, scenario_id))


@router.put("/scenarios/{scenario_id}")
def update_scenario(scenario_id: int, body: ScenarioIn, db: Session = Depends(get_db)):
    sc = get_scenario(db, scenario_id)
    site = get_site(db, sc.site_id)
    cfg = parse_config({**body.config, "name": body.name, "description": body.description})
    check_against_site(db, site, cfg)
    sc.name, sc.description, sc.config = body.name, body.description, cfg.model_dump(mode="json")
    db.commit()
    return scenario_dict(sc)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: int, db: Session = Depends(get_db)):
    db.delete(get_scenario(db, scenario_id))
    db.commit()


@router.post("/sites/{site_id}/scenarios/validate")
def validate_config(site_id: int, config: dict, db: Session = Depends(get_db)):
    """Validate a scenario configuration against the site without saving or running it."""
    site = get_site(db, site_id)
    cfg = parse_config(config)
    return check_against_site(db, site, cfg)


@router.get("/sites/{site_id}/presets")
def presets(site_id: int, db: Session = Depends(get_db)):
    site = get_site(db, site_id)
    feats = svc.site_features(db, site_id)
    try:
        built = build_presets(feats, (site.origin_lon, site.origin_lat))
    except SiteModelError as exc:
        raise HTTPException(422, str(exc)) from exc
    full = {k: ScenarioConfig.model_validate(c).model_dump(mode="json") for k, c in built.items()}
    return [{"key": k, "label": lab, "available": k in full, "config": full.get(k)} for k, lab in PRESETS]


@router.post("/sites/{site_id}/presets/create", status_code=201)
def create_presets(site_id: int, db: Session = Depends(get_db)):
    site = get_site(db, site_id)
    return [scenario_dict(s) for s in svc.create_preset_scenarios(db, site)]


@router.get("/scenarios/{scenario_id}/layout.geojson")
def layout(scenario_id: int, db: Session = Depends(get_db)):
    """Proposed circulation layout (corridor directions, closures, holding capacities, diversion targets)."""
    sc = get_scenario(db, scenario_id)
    site = get_site(db, sc.site_id)
    cfg = parse_config(sc.config)
    return layout_geojson(svc.site_features(db, site.id), (site.origin_lon, site.origin_lat), cfg)
