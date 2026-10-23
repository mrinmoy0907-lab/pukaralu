"""Zone register, walkable-area calculation, topology validation and approval (use case P-01)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Feature
from ..services import sites as svc
from ..services import zones as zsvc
from .deps import get_site

router = APIRouter(prefix="/api", tags=["zones"])


@router.get("/sites/{site_id}/zones")
def zone_register(site_id: int, db: Session = Depends(get_db)):
    s = get_site(db, site_id)
    feats = svc.site_features(db, site_id)
    return {"zones": zsvc.register(feats, (s.origin_lon, s.origin_lat), s.terrain),
            "zone_types": sorted(set(zsvc.DEFAULT_ZONE_TYPE.values()) | {"medical", "corridor", "other"})}


@router.post("/sites/{site_id}/zones/{fid}/area")
def recalculate(site_id: int, fid: str, db: Session = Depends(get_db)):
    """Recalculate the net walkable area and check topology; the result is stored on the feature."""
    s = get_site(db, site_id)
    feats = svc.site_features(db, site_id)
    try:
        area = zsvc.area_breakdown(fid, feats, (s.origin_lon, s.origin_lat), s.terrain)
        topo = zsvc.topology(fid, feats, (s.origin_lon, s.origin_lat))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    f = db.scalar(select(Feature).where(Feature.site_id == site_id, Feature.fid == fid))
    f.properties = {**(f.properties or {}), "net_walkable_m2": area["net_walkable_m2"],
                    "area_breakdown": {k: v for k, v in area.items() if k != "geometries"},
                    "area_calculated_at": datetime.now(timezone.utc).isoformat(), "topology_valid": topo["valid"]}
    db.commit()
    return {"area": area, "topology": topo}


class ApprovalIn(BaseModel):
    fids: list[str] = Field(..., min_length=1)
    status: str = Field("active", pattern="^(draft|review|active|retired)$")
    approved_by: str | None = None
    approval_remarks: str = ""
    effective_from: str | None = None
    effective_to: str | None = None


@router.post("/sites/{site_id}/zones/approve")
def approve(site_id: int, body: ApprovalIn, db: Session = Depends(get_db)):
    """Submit zones for review, or confirm and activate them (requires the approving role/officer)."""
    s = get_site(db, site_id)
    if body.status == "active" and not (body.approved_by and body.approved_by.strip()):
        raise HTTPException(422, "'approved_by' is required to activate zones")
    feats = svc.site_features(db, site_id)
    origin = (s.origin_lon, s.origin_lat)
    errors = []
    rows = []
    for fid in body.fids:
        f = db.scalar(select(Feature).where(Feature.site_id == site_id, Feature.fid == fid))
        if f is None or f.pk_type not in zsvc.ZONE_TYPES:
            errors.append(f"'{fid}' is not a zone of this site")
            continue
        if body.status == "active":
            topo = zsvc.topology(fid, feats, origin)
            if not topo["valid"]:
                errors.append(f"{f.name}: topology issues - " + "; ".join(topo["issues"]))
                continue
        rows.append(f)
    if errors:
        raise HTTPException(422, {"errors": errors})
    now = datetime.now(timezone.utc).isoformat()
    for f in rows:
        f.properties = {**(f.properties or {}), "status": body.status, "approved_by": body.approved_by,
                        "approval_remarks": body.approval_remarks, "effective_from": body.effective_from,
                        "effective_to": body.effective_to, "status_changed_at": now}
    s.version += 1
    db.commit()
    return {"updated": [f.fid for f in rows], "status": body.status}
