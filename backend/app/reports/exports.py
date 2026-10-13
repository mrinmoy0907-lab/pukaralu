"""CSV and GeoJSON exports of run results and scenario layouts."""
from __future__ import annotations

import csv
import io
import zipfile

from shapely.geometry import box, mapping

from ..geo.site_model import build_site_model
from ..sim.config import ScenarioConfig


def _csv(rows: list[dict], header: list[str] | None = None) -> str:
    buf = io.StringIO()
    if not rows:
        return ""
    header = header or list(rows[0].keys())
    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in header})
    return buf.getvalue()


def summary_rows(run: dict, analysis: dict) -> list[dict]:
    rows = [{"metric": "run_id", "value": run["id"], "unit": ""},
            {"metric": "scenario", "value": run["name"], "unit": ""},
            {"metric": "method", "value": analysis["engine"]["method"], "unit": ""},
            {"metric": "engine_version", "value": analysis["engine"]["version"], "unit": ""},
            {"metric": "seed", "value": run["seed"], "unit": ""},
            {"metric": "values_are", "value": "SIMULATED ESTIMATES (not measurements)", "unit": ""}]
    units = {"_s": "s", "_ppm2": "persons/m2", "_ppm": "persons/min"}
    for k, v in analysis["summary"].items():
        if isinstance(v, (dict, list)):
            continue
        unit = next((u for suf, u in units.items() if k.endswith(suf)), "persons" if "population" in k or "exited" in k or "arrivals" in k else "")
        rows.append({"metric": k, "value": v, "unit": unit})
    return rows


def run_csv_zip(run: dict, analysis: dict, series: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("summary.csv", _csv(summary_rows(run, analysis)))
        zf.writestr("zones.csv", _csv(analysis["zones"]))
        zf.writestr("exits.csv", _csv([{"exit_id": k, **{kk: vv for kk, vv in v.items() if kk != "cumulative"}}
                                       for k, v in analysis["exits"].items()]))
        zf.writestr("bottlenecks.csv", _csv([{k: v for k, v in b.items() if k != "cell_index"} for b in analysis["bottlenecks"]],
                                            ["type", "near", "lon", "lat", "max_density_ppm2", "duration_s", "unresolved"]))
        zf.writestr("holding_areas.csv", _csv([{k: v for k, v in h.items() if k != "suggestions"} for h in analysis["holding"]]))
        zf.writestr("corridor_flow.csv", _csv([{"corridor_id": k, **v} for k, v in analysis["corridor_flow"].items()]))
        # time series: one row per output step
        times = series["times"]
        cols = {"total_in_site": series["total_in_site"], "queued_or_congested": series["queued"]}
        for g, v in series["entry_queues"].items():
            cols[f"entry_queue:{g}"] = v
        for g, v in series["exits"].items():
            cols[f"exited_cumulative:{g}"] = v
        for z, v in series["zones"].items():
            cols[f"count:{z}"] = v["count"]
            cols[f"density_ppm2:{z}"] = v["density"]
        rows = [{"t_s": t, **{k: (v[i] if i < len(v) else "") for k, v in cols.items()}} for i, t in enumerate(times)]
        zf.writestr("timeseries.csv", _csv(rows, ["t_s", *cols.keys()]))
        if analysis.get("evacuation"):
            ev = analysis["evacuation"]
            zf.writestr("evacuation_by_zone.csv", _csv([{"zone_id": k, **v} for k, v in ev["clearance_by_zone"].items()]))
        zf.writestr("README.txt", (
            "Pushkaralu Digital Twin - simulation export\n"
            "All values are SIMULATED ESTIMATES produced by the method named in summary.csv.\n"
            "They are not measurements and must be reviewed by competent crowd-safety authorities.\n"
            "Units: s = seconds, persons/m2 = density, persons/min = flow.\n"))
    return out.getvalue()


def density_geojson(grid_doc: dict, which: str = "max") -> dict:
    g = grid_doc["grid"]
    nx, ny = g["nx"], g["ny"]
    dlon = (g["east"] - g["west"]) / nx
    dlat = (g["north"] - g["south"]) / ny
    idx, vals = grid_doc[which] if which in ("max",) else grid_doc["above_s"]
    feats = []
    for i, v in zip(idx, vals):
        iy, ix = divmod(int(i), nx)
        cell = box(g["west"] + ix * dlon, g["south"] + iy * dlat, g["west"] + (ix + 1) * dlon, g["south"] + (iy + 1) * dlat)
        key = "max_density_ppm2" if which == "max" else "time_above_limit_s"
        feats.append({"type": "Feature", "geometry": mapping(cell), "properties": {key: v, "cell": int(i),
                                                                                  "simulated_estimate": True}})
    return {"type": "FeatureCollection", "features": feats}


def bottlenecks_geojson(analysis: dict) -> dict:
    feats = []
    for b in analysis["bottlenecks"]:
        props = {k: v for k, v in b.items() if k not in ("cell_index", "lon", "lat", "x", "y")}
        props["simulated_estimate"] = True
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [b["lon"], b["lat"]]}, "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def layout_geojson(features: list[dict], origin, cfg: ScenarioConfig) -> dict:
    """Proposed circulation layout: site features with the scenario's changes applied."""
    model = build_site_model(features, origin, corridor_overrides=cfg.corridor_overrides,
                             gate_overrides=cfg.gate_overrides, holding_overrides=cfg.holding_overrides)
    closed_div = set(cfg.diversion.close_corridors) if cfg.diversion else set()
    closed_ev = set(cfg.evacuation.close_corridors) if cfg.evacuation else set()
    out = []
    keep = {"corridor", "emergency_corridor", "gate", "holding_area", "assembly_point", "barricade", "bathing_area", "ghat",
            "queue_lane", "plaza", "transit_hub", "bus_terminal", "parking"}
    for f in features:
        p = dict(f["properties"])
        if p.get("pk_type") not in keep:
            continue
        fid = str(f["id"])
        if fid in model.corridors:
            c = model.corridors[fid]
            p.update({"width_m": c.width, "direction": c.direction, "enabled": c.enabled,
                      "closed_by_diversion": fid in closed_div, "closed_in_evacuation": fid in closed_ev,
                      "diversion_activation_s": cfg.diversion.activation_s if fid in closed_div else None})
        if fid in model.gates:
            g = model.gates[fid]
            p.update({"role": g.role, "enabled": g.enabled})
        if fid in model.areas and model.areas[fid].pk_type == "holding_area":
            a = model.areas[fid]
            p.update({"capacity_persons": a.capacity_persons, "usable_area_m2": round(a.usable_area, 1)})
        p["scenario"] = cfg.name
        out.append({"type": "Feature", "id": fid, "geometry": f["geometry"], "properties": p})
    if cfg.diversion:
        for d in cfg.diversion.destinations:
            if d.target_id in model.areas:
                out.append({"type": "Feature", "id": f"diversion_target_{d.target_id}",
                            "geometry": mapping(model.proj.to_wgs84(model.areas[d.target_id].polygon.centroid)),
                            "properties": {"pk_type": "diversion_target", "target_id": d.target_id, "share": d.share,
                                           "activation_s": cfg.diversion.activation_s}})
    return {"type": "FeatureCollection", "name": f"layout_{cfg.name}", "features": out,
            "metadata": {"note": "Proposed layout for review. Not an approved plan."}}
