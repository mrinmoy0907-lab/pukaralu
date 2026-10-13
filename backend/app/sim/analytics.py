"""Derive crowd-safety metrics from a simulation result.

All numbers here are computed from the engine output of the run; nothing is
hard-coded. They are *simulated estimates* and are labelled as such.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from ..geo.site_model import SPECIFIC_FLOW_MAX, SiteModel
from .config import ScenarioConfig
from .thresholds import limit_for


def _first_time(times, values, pred, start=0.0):
    for t, v in zip(times, values):
        if t >= start and pred(v):
            return t
    return None


def _duration_above(times, values, limit, dt):
    return float(sum(dt for v in values if v > limit))


def _rate_per_min(cum: list[float], times: list[float], window_s: float = 60.0) -> list[float]:
    out = []
    j = 0
    for i, t in enumerate(times):
        while times[j] < t - window_s:
            j += 1
        span = t - times[j]
        out.append((cum[i] - cum[j]) / span * 60.0 if span > 0 else 0.0)
    return out


def _wait_from_curves(times, arrivals_cum, entered_cum):
    """FIFO waiting time from cumulative arrival/departure curves (point queue)."""
    A = np.asarray(arrivals_cum, float)
    D = np.asarray(entered_cum, float)
    T = np.asarray(times, float)
    if len(A) == 0 or A[-1] <= 0:
        return 0.0, 0.0
    waits = []
    for n in np.linspace(0, D[-1], 50)[1:]:
        ta = np.interp(n, A, T) if A[-1] >= n else None
        td = np.interp(n, D, T)
        if ta is not None:
            waits.append(max(0.0, td - ta))
    return (float(np.mean(waits)) if waits else 0.0, float(np.max(waits)) if waits else 0.0)


def _clusters(mask: np.ndarray, reach: int = 2) -> list[list[tuple[int, int]]]:
    """Group cells above the limit; cells within ``reach`` cells of each other form one
    bottleneck (corridors are often interrupted by partly walkable grid cells)."""
    seen = np.zeros_like(mask, bool)
    out = []
    ny, nx = mask.shape
    for iy, ix in zip(*np.nonzero(mask)):
        if seen[iy, ix]:
            continue
        comp = []
        dq = deque([(iy, ix)])
        seen[iy, ix] = True
        while dq:
            y, x = dq.popleft()
            comp.append((y, x))
            for dy, dx in [(a, b) for a in range(-reach, reach + 1) for b in range(-reach, reach + 1) if a or b]:
                yy, xx = y + dy, x + dx
                if 0 <= yy < ny and 0 <= xx < nx and mask[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True
                    dq.append((yy, xx))
        out.append(comp)
    return out


def analyse(result: dict, model: SiteModel, cfg: ScenarioConfig, profile: dict) -> dict:
    rec = result["rec"]
    grid = result["grid"]
    times = rec.times
    dt_out = cfg.output_interval_s
    proj = model.proj
    min_dur = float(profile.get("bottleneck_min_duration_s", 60))
    default_limit = limit_for(profile, "default")

    # ------------------------------------------------------------ zones
    zone_rows = []
    zone_series = {}
    for zid, counts in rec.zone_counts.items():
        z = model.zones[zid]
        area = z["usable_area"]
        dens = [c / area for c in counts]
        lim = limit_for(profile, z["kind"])
        above = _duration_above(times, dens, lim, dt_out)
        row = {
            "zone_id": zid, "name": z["name"], "kind": z["kind"], "usable_area_m2": round(area, 1),
            "max_count": round(max(counts), 1) if counts else 0, "final_count": round(counts[-1], 1) if counts else 0,
            "max_density_ppm2": round(max(dens), 3) if dens else 0,
            "mean_density_ppm2": round(float(np.mean(dens)), 3) if dens else 0,
            "limit_ppm2": lim, "time_above_limit_s": above,
            "exceeds_limit": bool(above > 0),
        }
        zone_rows.append(row)
        if max(counts, default=0) > 0:
            zone_series[zid] = {"count": [round(c, 2) for c in counts], "density": [round(d, 3) for d in dens]}

    # ------------------------------------------------------------ grid
    max_grid = rec.max_grid
    max_density = float(max_grid.max()) if max_grid.size else 0.0
    iy, ix = np.unravel_index(int(np.argmax(max_grid)), max_grid.shape) if max_grid.size else (0, 0)
    cx = grid.x0 + (ix + 0.5) * grid.cell
    cy = grid.y0 + (iy + 0.5) * grid.cell
    lon, lat = proj.xy_to_lonlat(cx, cy)
    any_cell_above = [0.0] * len(times)
    for i, fr in enumerate(rec.grid_frames):
        if fr[1] and max(fr[1]) > default_limit:
            any_cell_above[i] = 1.0
    time_above_grid = float(sum(any_cell_above) * dt_out)

    # bottlenecks: clusters of cells above the limit for >= min_dur, plus zones
    last_frame = np.zeros(grid.nx * grid.ny)
    if rec.grid_frames:
        idx, vals = rec.grid_frames[-1]
        last_frame[idx] = vals
    last_frame = last_frame.reshape(grid.ny, grid.nx)
    bottlenecks = []
    for comp in _clusters(rec.above_grid >= max(min_dur, dt_out)):
        ys = np.array([c[0] for c in comp])
        xs = np.array([c[1] for c in comp])
        bx = grid.x0 + (xs.mean() + 0.5) * grid.cell
        by = grid.y0 + (ys.mean() + 0.5) * grid.cell
        blon, blat = proj.xy_to_lonlat(bx, by)
        near = _nearest_zone(model, bx, by)
        bottlenecks.append({
            "type": "density", "lon": float(blon), "lat": float(blat), "x": float(bx), "y": float(by),
            "cells": len(comp), "max_density_ppm2": round(float(max_grid[ys, xs].max()), 2),
            "duration_s": float(rec.above_grid[ys, xs].max()), "near": near,
            "unresolved": bool((last_frame[ys, xs] > default_limit).any()),
            "cell_index": [int(y * grid.nx + x) for y, x in comp],
        })
    # zone-level bottlenecks: corridors running at capacity or above limit
    for row in zone_rows:
        if row["time_above_limit_s"] >= min_dur and row["kind"] == "corridor":
            c = model.corridors[row["zone_id"]]
            mid = c.line.interpolate(0.5, normalized=True)
            blon, blat = proj.xy_to_lonlat(mid.x, mid.y)
            bottlenecks.append({
                "type": "corridor", "lon": float(blon), "lat": float(blat), "x": mid.x, "y": mid.y,
                "near": row["name"], "zone_id": row["zone_id"], "max_density_ppm2": row["max_density_ppm2"],
                "duration_s": row["time_above_limit_s"],
                "unresolved": bool(rec.zone_counts[row["zone_id"]][-1] / max(row["usable_area_m2"], 1) > row["limit_ppm2"]),
            })
    bottlenecks.sort(key=lambda b: -b["duration_s"])

    # ------------------------------------------------------------ throughput & corridors
    corridor_flow = {}
    for cid, flows in rec.section_flow.items():
        if not flows:
            continue
        c = model.corridors[cid]
        rate = [f / dt_out * 60.0 for f in flows]  # persons/min across the section
        cap = SPECIFIC_FLOW_MAX * c.width * 60.0
        corridor_flow[cid] = {
            "name": c.name, "total": round(float(sum(flows)), 1), "peak_ppm": round(max(_smooth(rate)), 1),
            "capacity_ppm": round(cap, 1), "peak_utilisation": round(max(_smooth(rate)) / cap, 3) if cap else None,
            "series_ppm": [round(r, 2) for r in _smooth(rate)],
        }

    exits = {}
    total_exited = 0.0
    for eid, cum in result["exits"].items():
        cum = list(cum) + [cum[-1] if cum else 0] * (len(times) - len(cum))
        cum = cum[: len(times)]
        if not cum:
            continue
        total_exited += cum[-1]
        rate = _rate_per_min(cum, times)
        gate = model.gates.get(eid)
        cap = SPECIFIC_FLOW_MAX * gate.width * 60.0 if gate else None
        exits[eid] = {
            "name": gate.name if gate else model.areas[eid].name if eid in model.areas else eid,
            "count": round(cum[-1], 1), "peak_ppm": round(max(rate), 1),
            "capacity_ppm": round(cap, 1) if cap else None,
            "peak_utilisation": round(max(rate) / cap, 3) if cap else None,
            "cumulative": [round(c, 2) for c in cum],
        }
    for e in exits.values():
        e["share"] = round(e["count"] / total_exited, 3) if total_exited > 0 else 0.0

    # ------------------------------------------------------------ waiting & travel
    arrivals_total = sum(v[-1] for v in result["arrivals"].values() if v)
    initial = sum(p.count for p in cfg.initial_population)
    entry_queue_final = sum(v[-1] for v in result["queues"].values() if v)
    if result["method_type"] == "agent_based":
        waits = [tr["spawn_t"] - tr["arrival_t"] for tr in result["trips"] if tr["entry"]]
        waits += [r["spawn_t"] - r["arrival_t"] for r in result["remaining"] if r.get("entry")]
        travel = [tr["exit_t"] - tr["spawn_t"] for tr in result["trips"] if tr["entry"] and not tr["evacuee"]]
        avg_wait = float(np.mean(waits)) if waits else 0.0
        max_wait = float(np.max(waits)) if waits else 0.0
        travel_mean = float(np.mean(travel)) if travel else None
        travel_p95 = float(np.percentile(travel, 95)) if travel else None
    else:
        w = [_wait_from_curves(times, result["arrivals"][g], result["entered"][g]) for g in result["arrivals"]]
        avg_wait = float(np.mean([a for a, _ in w])) if w else 0.0
        max_wait = float(max([m for _, m in w], default=0.0))
        travel_mean = travel_p95 = None
    # the oldest person still waiting at an entry at the end also counts
    for gid, q in result["queues"].items():
        if q and q[-1] > 0.5:
            arr = result["arrivals"][gid]
            n_served = arr[-1] - q[-1]
            t_first_waiting = np.interp(n_served, arr, times) if arr[-1] > 0 else times[-1]
            max_wait = max(max_wait, times[-1] - float(t_first_waiting))

    queued = result["queued"]
    queue_info = {
        "entry_queue_peak": {g: round(max(v), 1) for g, v in result["queues"].items() if v},
        "entry_queue_final": {g: round(v[-1], 1) for g, v in result["queues"].items() if v},
        "congested_persons_peak": round(max(queued), 1) if queued else 0,
        "congestion_duration_s": float(sum(dt_out for q in queued if q >= 10)),
    }

    # ------------------------------------------------------------ holding areas
    holding = []
    for a in model.areas.values():
        if a.pk_type != "holding_area" or a.id not in rec.zone_counts:
            continue
        counts = rec.zone_counts[a.id]
        lim_d = limit_for(profile, "holding_area")
        density_cap = lim_d * a.usable_area
        cap = min(a.capacity_persons, density_cap) if a.capacity_persons else density_cap
        occ = [c / cap * 100 if cap > 0 else 0 for c in counts]
        t_limit = _first_time(times, counts, lambda c: c >= cap)
        # trend over last 60 s
        k = max(1, int(60 / dt_out))
        trend = (counts[-1] - counts[-1 - k]) / (times[-1] - times[-1 - k]) if len(counts) > k else 0.0
        proj_t = (cap - counts[-1]) / trend if trend > 1 / 60 and counts[-1] < cap else None
        peak = max(counts) if counts else 0
        sugg = []
        warn_frac = float(profile.get("holding_warning_fraction", 0.85))
        if peak >= cap * warn_frac:
            spare = [b for b in model.areas.values() if b.pk_type == "holding_area" and b.id != a.id and b.id in rec.zone_counts]
            spare = [(b, _cap(b, lim_d) - max(rec.zone_counts[b.id])) for b in spare]
            spare = [(b, s) for b, s in spare if s > 0]
            infl = _inflow_rate(counts, times)
            if peak >= cap:
                sugg.append(f"Peak occupancy {peak:.0f} exceeds the configured limit of {cap:.0f}. "
                            f"Reduce inflow (peak net inflow {infl:.0f} p/min) or release earlier.")
            else:
                sugg.append(f"Occupancy reached {peak / cap * 100:.0f}% of the configured limit.")
            for b, s in sorted(spare, key=lambda x: -x[1])[:2]:
                sugg.append(f"Alternative holding area '{b.name}' had at least {s:.0f} spare places in this scenario.")
        holding.append({
            "holding_id": a.id, "name": a.name, "usable_area_m2": round(a.usable_area, 1),
            "configured_capacity": a.capacity_persons, "density_limit_ppm2": lim_d,
            "density_based_capacity": round(density_cap), "effective_limit": round(cap),
            "peak_population": round(peak, 1), "final_population": round(counts[-1], 1) if counts else 0,
            "available_capacity_final": round(cap - (counts[-1] if counts else 0), 1),
            "peak_occupancy_pct": round(max(occ), 1) if occ else 0,
            "time_limit_reached_s": t_limit, "projected_time_to_limit_s": round(proj_t, 0) if proj_t else None,
            "occupancy_pct": [round(o, 2) for o in occ], "suggestions": sugg,
            "excluded_area_m2": round(max(0.0, a.polygon.area - a.usable_area), 1),
        })

    # ------------------------------------------------------------ evacuation
    evac = None
    ev_info = result.get("evacuation")
    if ev_info and cfg.evacuation:
        t0 = ev_info["trigger_s"]
        zones_ev = cfg.evacuation.affected_zone_ids or [r["zone_id"] for r in zone_rows]
        clear_by_zone = {}
        for z in zones_ev:
            counts = rec.zone_counts.get(z)
            if not counts:
                continue
            i0 = next((i for i, t in enumerate(times) if t >= t0), None)
            if i0 is None or counts[i0] < 0.5:
                continue
            tc = _first_time(times, counts, lambda c: c < 0.5, start=t0)
            clear_by_zone[z] = {"name": model.zones[z]["name"], "population_at_trigger": round(counts[i0], 1),
                                "clearance_s": (tc - t0) if tc is not None else None}
        if cfg.evacuation.affected_zone_ids:
            series = [sum(rec.zone_counts[z][i] for z in zones_ev if z in rec.zone_counts) for i in range(len(times))]
        else:
            series = rec.total
        tc_total = _first_time(times, series, lambda c: c < 0.5, start=t0)
        remaining_ev = series[-1]
        evac = {
            "trigger_s": t0, "strategy": ev_info["strategy"], "evacuees": round(ev_info["evacuees"], 1),
            "unreachable_evacuees": round(ev_info.get("unreachable", 0), 1),
            "clearance_time_s": (tc_total - t0) if tc_total is not None else None,
            "cleared_within_simulation": tc_total is not None,
            "remaining_in_affected_area": round(remaining_ev, 1),
            "clearance_by_zone": clear_by_zone,
            "ccrp_planning_estimate_s": ev_info.get("ccrp_estimate_s"),
            "ccrp_exit_load": {k: round(v, 1) for k, v in (ev_info.get("ccrp_sink_load") or {}).items()},
            "note": ("Clearance time is a simulated estimate. A shorter clearance time alone does not make a "
                     "route safe: accessibility, counterflows, emergency access and secondary hazards require expert review."),
        }

    duration_min = cfg.duration_s / 60.0
    summary = {
        "method": result["method"],
        "method_type": result["method_type"],
        "estimate_label": "SIMULATED ESTIMATE",
        "total_arrivals": round(arrivals_total, 1),
        "initial_population": initial,
        "total_exited": round(total_exited, 1),
        "remaining_at_end": round(float(result.get("remaining_count", 0.0)), 1),
        "entry_queue_at_end": round(entry_queue_final, 1),
        "turned_away_at_evacuation": round(float(result.get("turned_away", 0.0)), 1),
        "peak_population_in_site": round(max(rec.total), 1) if rec.total else 0,
        "max_density_ppm2": round(max_density, 3),
        "max_density_location": {"lon": float(lon), "lat": float(lat)},
        "max_zone_density_ppm2": max((r["max_density_ppm2"] for r in zone_rows), default=0),
        "max_zone_density_zone": max(zone_rows, key=lambda r: r["max_density_ppm2"])["name"] if zone_rows else None,
        "time_above_threshold_s": time_above_grid,
        "density_limit_ppm2": default_limit,
        "avg_wait_s": round(avg_wait, 1),
        "max_wait_s": round(max_wait, 1),
        "throughput_ppm": round(total_exited / duration_min, 2) if duration_min > 0 else 0,
        "peak_exit_flow_ppm": round(max((e["peak_ppm"] for e in exits.values()), default=0), 1),
        "mean_travel_time_s": round(travel_mean, 1) if travel_mean is not None else None,
        "p95_travel_time_s": round(travel_p95, 1) if travel_p95 is not None else None,
        "unroutable_arrivals": {k: round(float(v), 1) for k, v in (result.get("unroutable") or {}).items()},
        "n_bottlenecks": len(bottlenecks),
        "n_unresolved_bottlenecks": sum(1 for b in bottlenecks if b["unresolved"]),
        "clearance_time_s": evac["clearance_time_s"] if evac else None,
        "exit_utilisation": {k: {"count": v["count"], "share": v["share"], "peak_utilisation": v["peak_utilisation"]}
                             for k, v in exits.items()},
        "congestion_duration_s": queue_info["congestion_duration_s"],
        "wall_time_s": round(result.get("wall_time_s", 0), 1),
    }
    interventions = _interventions(summary, zone_rows, bottlenecks, holding, exits, evac, corridor_flow, profile)
    return {
        "summary": summary,
        "zones": zone_rows,
        "zone_series": zone_series,
        "bottlenecks": bottlenecks,
        "corridor_flow": corridor_flow,
        "exits": exits,
        "queues": queue_info,
        "holding": holding,
        "evacuation": evac,
        "interventions": interventions,
    }


def _smooth(rate: list[float], k: int = 30) -> list[float]:
    if not rate:
        return [0.0]
    a = np.asarray(rate)
    k = max(1, min(k, len(a)))
    return list(np.convolve(a, np.ones(k) / k, mode="same"))


def _cap(b, lim_d):
    dc = lim_d * b.usable_area
    return min(b.capacity_persons, dc) if b.capacity_persons else dc


def _inflow_rate(counts, times):
    if len(counts) < 2:
        return 0.0
    d = np.diff(counts) / np.diff(times) * 60
    return float(max(d.max(), 0))


def _nearest_zone(model: SiteModel, x: float, y: float) -> str | None:
    from shapely.geometry import Point

    p = Point(x, y)
    best, bd = None, math.inf
    for z in model.zones.values():
        d = z["polygon"].distance(p)
        if d < bd:
            best, bd = z["name"], d
    return best


def _interventions(summary, zones, bottlenecks, holding, exits, evac, corridor_flow, profile) -> list[str]:
    """Rule-based prompts for planners. They are suggestions for expert review,
    not decisions."""
    out = []
    for b in bottlenecks[:5]:
        status = "still above the limit at the end of the run" if b["unresolved"] else "resolved before the end of the run"
        out.append(f"Bottleneck near {b['near']}: up to {b['max_density_ppm2']} p/m2 for {b['duration_s']:.0f} s ({status}). "
                   "Consider metering upstream inflow, widening the passage, one-way operation or an alternative route.")
    for h in holding:
        out.extend(f"Holding area {h['name']}: {s}" for s in h["suggestions"])
    if summary["max_wait_s"] > float(profile.get("queue_wait_limit_s", 900)):
        out.append(f"Maximum entry waiting time {summary['max_wait_s']:.0f} s exceeds the configured limit; "
                   "consider additional entry capacity or staggered arrivals.")
    utils = {k: v["peak_utilisation"] for k, v in exits.items() if v["peak_utilisation"] is not None}
    if utils and max(utils.values()) > 0.8 and min(utils.values()) < 0.3 and len(utils) > 1:
        hi = max(utils, key=utils.get)
        lo = min(utils, key=utils.get)
        out.append(f"Exit use is unbalanced: {exits[hi]['name']} peaked at {utils[hi] * 100:.0f}% of capacity while "
                   f"{exits[lo]['name']} peaked at {utils[lo] * 100:.0f}%. Review exit assignment / signage.")
    if evac:
        if not evac["cleared_within_simulation"]:
            out.append(f"The affected area was not cleared within the simulated time ({evac['remaining_in_affected_area']:.0f} "
                       "pedestrians remaining). Extend the simulation or revise the evacuation strategy.")
        if evac["unreachable_evacuees"] > 0:
            out.append(f"{evac['unreachable_evacuees']:.0f} evacuees had no route to an available exit.")
    for g, n in (summary.get("unroutable_arrivals") or {}).items():
        out.append(f"{n:.0f} arrivals at {g} could not reach any destination with the active closures (unreachable destination).")
    if not out:
        out.append("No configured limit was exceeded in this scenario. This does not by itself demonstrate safety.")
    return out
