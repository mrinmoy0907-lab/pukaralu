"""Preset scenarios generated from the features of any site.

Presets are starting points: every value is editable in the scenario editor
and must be replaced with locally validated demand figures. The generator only
uses the site's own features (entry gates, destinations, holding areas,
corridors) so the presets work for imported surveyed sites as well as for the
synthetic demonstration site.
"""
from __future__ import annotations

import networkx as nx

from ..geo.routing import RoutingError, nearest_target, shortest_path
from ..geo.site_model import SiteModel, build_site_model

PRESETS = [
    ("normal", "Normal crowd movement"),
    ("peak_bathing", "Peak bathing-period arrivals"),
    ("holding_overcrowded", "Overcrowded holding area"),
    ("blocked_corridor", "Blocked pedestrian corridor"),
    ("primary_exit_closed", "Closure of a primary exit"),
    ("one_way", "One-way circulation plan"),
    ("diversion_alt_ghat", "Diversion to an alternative ghat"),
    ("evacuation", "Emergency evacuation"),
    ("transit_surge", "Transit-hub arrival surge"),
    ("route_failure", "Failure of a planned route requiring an alternative"),
]

DESCRIPTIONS = {
    "normal": "Moderate arrivals at all entry gates; pilgrims pass a holding area, bathe and leave by the nearest exit.",
    "peak_bathing": "Arrival rates three times the normal preset and longer bathing dwell (auspicious bathing period).",
    "holding_overcrowded": "All arrivals are held in a single holding area with a reduced operational capacity.",
    "blocked_corridor": "A corridor on the main inbound route is unavailable for the whole simulation.",
    "primary_exit_closed": "The exit nearest to the main bathing area is closed.",
    "one_way": "Corridors used only inbound or only outbound are operated one-way to separate flows.",
    "diversion_alt_ghat": "Part-way through the run new arrivals are diverted to an alternative ghat.",
    "evacuation": "Ghat, bathing and plaza areas are occupied; an evacuation is triggered and routed with the capacity-aware planner.",
    "transit_surge": "A surge of arrivals from the transit hub / bus terminal for five minutes.",
    "route_failure": "A corridor on the main route fails mid-run; pedestrians are re-routed to alternatives.",
}


def _pick(model: SiteModel):
    entries = model.entry_gates()
    bathing = [a for a in model.areas.values() if a.pk_type == "bathing_area" and a.node is not None]
    ghats = [a for a in model.areas.values() if a.pk_type == "ghat" and a.node is not None]
    dests = bathing or ghats or [a for a in model.areas.values() if a.pk_type in ("plaza",) and a.node is not None]
    holding = [a for a in model.areas.values() if a.pk_type == "holding_area" and a.node is not None]
    exits = [g for g in model.exit_gates() if not g.emergency_exit]
    return entries, dests, holding, exits


def _corridors_on(model: SiteModel, path: list[int]) -> list[str]:
    out = []
    for u, v in zip(path[:-1], path[1:]):
        c = model.link_between(u, v).corridor_id
        if c and c not in out:
            out.append(c)
    return out


def build_presets(features: list[dict], origin) -> dict[str, dict]:
    model = build_site_model(features, origin)
    entries, dests, holding, exits = _pick(model)
    if not entries or not dests or not exits:
        return {}
    g = model.graph()
    main = max(dests, key=lambda a: a.usable_area)
    # main inbound path from the busiest (first) entry to the main destination
    try:
        inbound = shortest_path(g, entries[0].node, main.node)
    except RoutingError:
        return {}
    out_res = nearest_target(g, main.node, [e.node for e in exits])
    outbound = out_res[1] if out_res else []
    in_corr = _corridors_on(model, inbound)
    out_corr = _corridors_on(model, outbound)
    hold_stops = [{"holding_id": h.id, "share": round(0.8 / len(holding), 3), "dwell_s": 60} for h in holding]

    def base(name, rate=45.0, dwell=120.0, **kw):
        cfg = {
            "name": name, "description": DESCRIPTIONS.get(kw.pop("key", ""), ""), "engine": "jupedsim",
            "duration_s": 1200, "time_step_s": 0.05, "output_interval_s": 1.0, "seed": 42,
            "demand": [{"gate_id": e.id, "rate_per_min": rate} for e in entries],
            "destinations": [{"target_id": main.id, "share": 1.0, "dwell_s": dwell}],
            "holding_stops": hold_stops,
        }
        cfg.update(kw)
        return cfg

    presets: dict[str, dict] = {}
    presets["normal"] = base("Normal crowd movement", key="normal")
    presets["peak_bathing"] = base("Peak bathing-period arrivals", rate=135, dwell=180, key="peak_bathing")
    if holding:
        h = holding[0]
        cap = int(max(50, 0.15 * h.usable_area))
        presets["holding_overcrowded"] = base(
            "Overcrowded holding area", rate=100, key="holding_overcrowded",
            holding_stops=[{"holding_id": h.id, "share": 1.0, "dwell_s": 300}],
            holding_overrides=[{"holding_id": h.id, "capacity_persons": cap}])
    blockable = [c for c in in_corr if c in model.corridors]
    if len(blockable) >= 2:
        # block a corridor that has an alternative
        for cid in blockable[1:] + blockable[:1]:
            g2 = model.graph(closed_corridors={cid})
            if nx.has_path(g2, entries[0].node, main.node):
                presets["blocked_corridor"] = base("Blocked pedestrian corridor", key="blocked_corridor",
                                                   corridor_overrides=[{"corridor_id": cid, "enabled": False}])
                break
    if out_res and len(exits) > 1:
        primary = model.node_kind[out_res[0]].split(":", 1)[1]
        presets["primary_exit_closed"] = base("Closure of a primary exit", key="primary_exit_closed",
                                              gate_overrides=[{"gate_id": primary, "enabled": False}])
    # one-way plan: corridors used only inbound/only outbound get the travel direction
    ow = []
    for path, used, other in ((inbound, in_corr, out_corr), (outbound, out_corr, in_corr)):
        for u, v in zip(path[:-1], path[1:]):
            lk = model.link_between(u, v)
            c = lk.corridor_id
            if not c or c in other or any(o["corridor_id"] == c for o in ow):
                continue
            line = model.corridors[c].line
            forward = line.project(model.nodes[u]) <= line.project(model.nodes[v])
            ow.append({"corridor_id": c, "direction": "forward" if forward else "backward"})
    if ow:
        presets["one_way"] = base("One-way circulation plan", rate=90, key="one_way", corridor_overrides=ow)
    alts = [a for a in model.areas.values() if a.pk_type in ("bathing_area", "ghat") and a.node is not None and a.id != main.id
            and a.pk_type == main.pk_type]
    if alts:
        presets["diversion_alt_ghat"] = base("Diversion to an alternative ghat", rate=100, key="diversion_alt_ghat",
                                             diversion={"activation_s": 200, "destinations": [
                                                 {"target_id": alts[0].id, "share": 1.0, "dwell_s": 120}],
                                                 "close_corridors": [], "reroute_existing": False})
    occupied = [a for a in model.areas.values() if a.pk_type in ("bathing_area", "ghat", "plaza") and a.node is not None]
    init = [{"zone_id": a.id, "count": int(min(0.5 * a.usable_area, 1500)), "dwell_s": 600} for a in occupied]
    presets["evacuation"] = base("Emergency evacuation", rate=45, key="evacuation", duration_s=900,
                                 initial_population=init,
                                 evacuation={"trigger_s": 60, "strategy": "capacity_aware", "affected_zone_ids": [],
                                             "exit_gate_ids": [], "use_emergency_corridors": True})
    hubs = [e for e in entries if any(a.pk_type in ("transit_hub", "bus_terminal") and a.polygon.distance(e.point) < 2
                                      for a in model.areas.values())]
    hub = hubs[0] if hubs else entries[0]
    demand = [{"gate_id": e.id, "rate_per_min": 60} for e in entries if e.id != hub.id]
    demand += [{"gate_id": hub.id, "rate_per_min": 400, "start_s": 60, "end_s": 360},
               {"gate_id": hub.id, "rate_per_min": 60, "start_s": 0, "end_s": 60},
               {"gate_id": hub.id, "rate_per_min": 60, "start_s": 360}]
    presets["transit_surge"] = base("Transit-hub arrival surge", key="transit_surge", demand=demand)
    if "blocked_corridor" in presets:
        cid = presets["blocked_corridor"]["corridor_overrides"][0]["corridor_id"]
        presets["route_failure"] = base("Failure of a planned route requiring an alternative", rate=90, key="route_failure",
                                        diversion={"activation_s": 180, "destinations": [], "close_corridors": [cid],
                                                   "reroute_existing": True})
    for key, cfg in presets.items():
        cfg["description"] = cfg.get("description") or DESCRIPTIONS[key]
    return presets
