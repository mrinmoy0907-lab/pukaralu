"""Density thresholds.

The default profile is a *placeholder for configuration*, not an approved
standard. Values are indicative figures drawn from the crowd-science
literature (Fruin 1971 levels of service; Weidmann 1993 fundamental diagram;
Still 2014 "Introduction to Crowd Science") and MUST be reviewed and approved
by the competent crowd-management authority before operational use. The
application shows the approval status of the profile on every report.
"""
from __future__ import annotations

DEFAULT_PROFILE = {
    "name": "Default (literature-indicative, NOT APPROVED)",
    "status": "draft",
    "approved_by": None,
    "approved_on": None,
    "notes": (
        "Indicative values only. Fruin (1971) walkway LoS E/F boundary ~2.2 p/m2; "
        "Weidmann (1993) jam density 5.4 p/m2; Still (2014) notes rapidly rising risk above "
        "~4-5 p/m2 in static crowds. Must be approved by the competent authority."
    ),
    # colour breaks for heatmaps (persons per m2)
    "density_bands": [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0],
    # operational limits by zone kind (persons per m2)
    "limits": {
        "default": 2.0,
        "corridor": 2.0,
        "plaza": 2.0,
        "holding_area": 3.0,
        "bathing_area": 2.5,
        "ghat": 2.5,
        "assembly_point": 3.0,
        "transit_hub": 2.0,
        "bus_terminal": 2.0,
        "parking": 2.0,
        "zone": 2.0,
    },
    # a location counts as a bottleneck when its limit is exceeded for at least this long
    "bottleneck_min_duration_s": 60,
    # entry-queue waiting time considered unacceptable
    "queue_wait_limit_s": 900,
    # holding-area occupancy at which alternatives are suggested (fraction of capacity)
    "holding_warning_fraction": 0.85,
}


def limit_for(profile: dict, kind: str) -> float:
    lim = profile.get("limits", {})
    return float(lim.get(kind, lim.get("default", 2.0)))


def merged(profile: dict | None) -> dict:
    out = {**DEFAULT_PROFILE, **(profile or {})}
    out["limits"] = {**DEFAULT_PROFILE["limits"], **((profile or {}).get("limits") or {})}
    return out


def validate_profile(p: dict) -> list[str]:
    errs = []
    bands = p.get("density_bands", [])
    if not bands or any(b <= 0 for b in bands) or sorted(bands) != list(bands):
        errs.append("density_bands must be positive and increasing")
    for k, v in (p.get("limits") or {}).items():
        try:
            if not 0 < float(v) <= 10:
                errs.append(f"limit '{k}' must be in (0, 10] persons/m2")
        except (TypeError, ValueError):
            errs.append(f"limit '{k}' is not a number")
    if float(p.get("bottleneck_min_duration_s", 60)) < 0:
        errs.append("bottleneck_min_duration_s must be >= 0")
    return errs
