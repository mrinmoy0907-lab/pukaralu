"""Run a scenario end-to-end and persist its outputs.

Output files (``<results_dir>/<run_id>/``):
  analysis.json.gz  metrics, zone table, bottlenecks, holding analysis ...
  series.json.gz    time series (zones, queues, exits, corridor flows, events)
  grid.json.gz      density-grid definition and per-frame sparse densities
  agents.json.gz    agent positions per frame (agent-based runs only)
  links.json.gz     link geometry and per-frame link densities (macroscopic runs)
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
from shapely.geometry import mapping

from ..geo.site_model import build_site_model
from .analytics import analyse
from .config import ScenarioConfig
from .ctm_engine import CTMEngine
from .jupedsim_engine import JuPedSimEngine
from .planning import TripPlanner

ENGINES = {"jupedsim": JuPedSimEngine, "macro_ctm": CTMEngine}


def engine_version(name: str) -> str:
    return ENGINES[name].version()


def build_for(features: list[dict], origin, cfg: ScenarioConfig):
    return build_site_model(features, origin, corridor_overrides=cfg.corridor_overrides,
                            gate_overrides=cfg.gate_overrides, holding_overrides=cfg.holding_overrides)


def validate(features: list[dict], origin, cfg: ScenarioConfig) -> dict:
    """Validate a scenario against its site without running it."""
    model = build_for(features, origin, cfg)
    TripPlanner(model, cfg)  # raises PlanningError with all problems found
    n_agents = sum(p.count for p in cfg.initial_population) + sum(
        d.rate_per_min / 60.0 * ((d.end_s or cfg.duration_s) - d.start_s) for d in cfg.demand)
    return {"ok": True, "warnings": model.warnings, "expected_population": round(n_agents),
            "network": {"nodes": len(model.nodes), "links": len(model.links)},
            "walkable_area_m2": round(model.walkable.area, 1)}


def _dump(path: Path, obj) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"), default=_np_default)


def _np_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def load(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def run_scenario(features: list[dict], origin, cfg_dict: dict, profile: dict, out_dir: Path,
                 progress=None, cancelled=None) -> dict:
    cfg = ScenarioConfig.model_validate(cfg_dict)
    model = build_for(features, origin, cfg)
    engine = ENGINES[cfg.engine]()
    result = engine.run(model, cfg, profile, progress=progress, cancelled=cancelled)
    if progress:
        progress(0.99, "analysing results")
    analysis = analyse(result, model, cfg, profile)
    out_dir.mkdir(parents=True, exist_ok=True)
    rec, grid = result["rec"], result["grid"]
    proj = model.proj

    # grid in lon/lat (local axes are aligned with north/east at the site origin)
    w, s = proj.xy_to_lonlat(grid.x0, grid.y0)
    e, n = proj.xy_to_lonlat(grid.x0 + grid.nx * grid.cell, grid.y0 + grid.ny * grid.cell)
    grid_def = {"nx": grid.nx, "ny": grid.ny, "cell_m": grid.cell, "west": float(w), "south": float(s),
                "east": float(e), "north": float(n)}
    max_idx = np.flatnonzero(rec.max_grid.ravel() > 0)
    _dump(out_dir / "grid.json.gz", {
        "grid": grid_def, "times": rec.times, "frames": rec.grid_frames,
        "max": [max_idx.tolist(), np.round(rec.max_grid.ravel()[max_idx], 2).tolist()],
        "above_s": [np.flatnonzero(rec.above_grid.ravel() > 0).tolist(),
                    rec.above_grid.ravel()[rec.above_grid.ravel() > 0].round(1).tolist()],
        "walk_area": np.round(grid.walk_area.ravel(), 1).tolist(),
    })
    if result["method_type"] == "agent_based":
        frames = []
        for fr in rec.agent_frames:
            lon, lat = proj.xy_to_lonlat(fr["x"], fr["y"])
            frames.append({"t": fr["t"], "ids": fr["ids"], "lon": np.round(lon, 7).tolist(), "lat": np.round(lat, 7).tolist()})
        _dump(out_dir / "agents.json.gz", {"frames": frames})
    else:
        link_geo = []
        for lk in model.links.values():
            g = proj.to_wgs84(lk.geom)
            link_geo.append({"id": lk.id, "corridor_id": lk.corridor_id, "kind": lk.kind, "width": lk.width,
                             "coords": [[round(x, 7), round(y, 7)] for x, y in g.coords]})
        _dump(out_dir / "links.json.gz", {"links": link_geo, "times": rec.times, "frames": result["link_frames"]})

    sections = {cid: mapping(proj.to_wgs84(g)) for cid, g in rec.section_geometries().items()}
    series = {
        "times": rec.times,
        "total_in_site": [round(v, 2) for v in rec.total],
        "queued": result["queued"],
        "entry_queues": result["queues"],
        "arrivals": result["arrivals"],
        "exits": {k: v["cumulative"] for k, v in analysis["exits"].items()},
        "zones": analysis.pop("zone_series"),
        "corridor_flow_ppm": {k: v.pop("series_ppm") for k, v in analysis["corridor_flow"].items()},
        "holding_occupancy_pct": {h["holding_id"]: h.pop("occupancy_pct") for h in analysis["holding"]},
        "events": result["events"],
        "sections": sections,
    }
    _dump(out_dir / "series.json.gz", series)
    analysis["events"] = result["events"]
    analysis["warnings"] = result["warnings"]
    analysis["engine"] = {"name": result["engine"], "version": result["engine_version"], "method": result["method"],
                          "method_type": result["method_type"]}
    _dump(out_dir / "analysis.json.gz", analysis)
    return analysis
