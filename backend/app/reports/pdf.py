"""PDF reports (ReportLab): single-run SOP/drill report and scenario comparison."""
from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon as RLPolygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..geo.site_model import SiteModel

BAND_COLOURS = ["#2c7bb6", "#00a6ca", "#00ccbc", "#90eb9d", "#ffff8c", "#f9d057", "#f29e2e", "#d7191c"]
SERIES_COLOURS = [colors.HexColor(c) for c in ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b")]

LIMITATIONS = [
    "All results are simulated estimates from a model; they are not measurements and have not been validated "
    "against observed Pushkaralu crowd data for this site unless stated in the data provenance section.",
    "Demand (arrival rates, origin-destination shares, dwell times) and walking-speed distributions are scenario "
    "assumptions that must be replaced with locally observed values.",
    "Density thresholds are configurable and must be approved by the competent crowd-management authority; the "
    "approval status of the profile used is shown in this report.",
    "Agent-based runs (JuPedSim) represent individual pedestrians and collision avoidance but not pushing, falls, "
    "group cohesion, or behavioural responses to announcements.",
    "Macroscopic runs (Cell Transmission Model) estimate aggregate flows; they do not represent individuals or "
    "counterflow friction, and each direction of a two-way corridor uses the full width.",
    "Evacuation clearance times do not by themselves establish that a route is safe: accessibility, counterflows, "
    "emergency-vehicle access and secondary hazards require expert review.",
    "Corridor closures activated during a run are enforced by re-routing; agent-based runs additionally remove the "
    "closed corridor from the walkable geometry once it is empty.",
]


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("small", parent=ss["BodyText"], fontSize=8, leading=10))
    ss.add(ParagraphStyle("warn", parent=ss["BodyText"], fontSize=9, textColor=colors.HexColor("#8a1c1c"),
                          backColor=colors.HexColor("#fdecea"), borderPadding=4, leading=12))
    return ss


def _table(rows, col_widths=None, header=True, font=8):
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [("FONTSIZE", (0, 0), (-1, -1), font), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
             ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def _fmt(v, nd=1):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return str(v)


def _band_colour(v, bands):
    i = 0
    while i < len(bands) and v > bands[i]:
        i += 1
    return colors.HexColor(BAND_COLOURS[min(i, len(BAND_COLOURS) - 1)])


class _MapCanvas:
    LEGEND_W = 32 * mm

    def __init__(self, model: SiteModel, width=170 * mm, height=110 * mm):
        self.model = model
        minx, miny, maxx, maxy = model.walkable.bounds
        pad = 15
        minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
        width -= self.LEGEND_W
        self.s = min(width / (maxx - minx), height / (maxy - miny))
        self.minx, self.miny = minx, miny
        self.maxx, self.maxy = maxx, maxy
        self.map_w = (maxx - minx) * self.s
        self.d = Drawing(self.map_w + self.LEGEND_W, (maxy - miny) * self.s)

    def xy(self, x, y):
        return (x - self.minx) * self.s, (y - self.miny) * self.s

    def poly(self, geom, fill, stroke=None, sw=0.3):
        gs = getattr(geom, "geoms", [geom])
        for g in gs:
            if g.geom_type != "Polygon":
                continue
            pts = []
            for x, y in g.exterior.coords:
                pts += self.xy(x, y)
            self.d.add(RLPolygon(pts, fillColor=fill, strokeColor=stroke, strokeWidth=sw))

    def line(self, geom, colour, width=1.0, dash=None):
        pts = []
        for x, y in geom.coords:
            pts += self.xy(x, y)
        self.d.add(PolyLine(pts, strokeColor=colour, strokeWidth=width, strokeDashArray=dash))

    def base(self):
        from shapely.geometry import box as _box

        m = self.model
        frame = _box(self.minx, self.miny, self.maxx, self.maxy)
        self.d.add(Rect(0, 0, self.map_w, self.d.height, fillColor=None, strokeColor=colors.HexColor("#999999"), strokeWidth=0.3))
        if m.water is not None and not m.water.is_empty:
            self.poly(m.water.intersection(frame), colors.HexColor("#cfe3f5"))
        self.poly(m.walkable, colors.HexColor("#eeeeee"), colors.HexColor("#bbbbbb"))
        if not m.obstacles.is_empty:
            solid = m.obstacles.difference(m.water) if m.water is not None and not m.water.is_empty else m.obstacles
            self.poly(solid.intersection(frame), colors.HexColor("#8c8c8c"))
        for a in m.areas.values():
            if a.pk_type == "holding_area":
                self.poly(a.polygon, None, colors.HexColor("#7b3294"), 0.8)
        for g in m.gates.values():
            x, y = self.xy(g.point.x, g.point.y)
            col = colors.HexColor("#1a9641") if g.is_entry else colors.HexColor("#d7191c")
            self.d.add(Rect(x - 3, y - 3, 6, 6, fillColor=col if g.enabled else colors.white, strokeColor=col))
            self.d.add(String(x + 4, y + 3, g.name[:24], fontSize=5))

    def drawing(self):
        return self.d


def density_map(model: SiteModel, grid_doc: dict, analysis: dict, bands: list[float]) -> Drawing:
    mc = _MapCanvas(model)
    mc.base()
    g = grid_doc["grid"]
    # grid cells in local metres: rebuild from lon/lat bounds
    x0, y0 = model.proj.lonlat_to_xy(g["west"], g["south"])
    cell = g["cell_m"]
    idx, vals = grid_doc["max"]
    for i, v in zip(idx, vals):
        if v < 0.05:
            continue
        iy, ix = divmod(int(i), g["nx"])
        x, y = mc.xy(float(x0) + ix * cell, float(y0) + iy * cell)
        mc.d.add(Rect(x, y, cell * mc.s, cell * mc.s, fillColor=_band_colour(v, bands), strokeColor=None))
    for k, b in enumerate(analysis["bottlenecks"][:9]):
        x, y = mc.xy(b["x"], b["y"])
        mc.d.add(Circle(x, y, 6, fillColor=None, strokeColor=colors.red, strokeWidth=1.2))
        mc.d.add(String(x + 7, y + 4, str(k + 1), fontSize=7, fillColor=colors.red))
    _legend(mc.d, bands, mc.map_w + 4)
    return mc.drawing()


def _legend(d: Drawing, bands, x0=5):
    lg = Legend()
    lg.x, lg.y = x0, d.height - 5
    lg.fontSize = 5
    lg.boxAnchor = "nw"
    lg.columnMaximum = 9
    labels = [f"<= {bands[0]}"] + [f"{a}-{b}" for a, b in zip(bands[:-1], bands[1:])] + [f"> {bands[-1]} p/m2"]
    lg.colorNamePairs = [(colors.HexColor(BAND_COLOURS[min(i, len(BAND_COLOURS) - 1)]), lab) for i, lab in enumerate(labels)]
    d.add(lg)


def route_map(model: SiteModel, analysis: dict, cfg) -> Drawing:
    mc = _MapCanvas(model)
    mc.base()
    cf = analysis["corridor_flow"]
    closed = set()
    if cfg.diversion:
        closed |= set(cfg.diversion.close_corridors)
    if cfg.evacuation:
        closed |= set(cfg.evacuation.close_corridors)
    for c in model.corridors.values():
        if not c.enabled:
            mc.line(c.line, colors.red, 2.0, dash=[2, 2])
            continue
        u = (cf.get(c.id) or {}).get("peak_utilisation") or 0.0
        col = colors.HexColor("#1a9641") if u < 0.5 else colors.HexColor("#fdae61") if u < 0.85 else colors.HexColor("#d7191c")
        mc.line(c.line, col, max(1.0, c.width * mc.s * 0.6), dash=[1, 2] if c.emergency_only else None)
        if c.id in closed:
            mc.line(c.line, colors.black, 1.0, dash=[3, 2])
        if c.direction != "both":
            mid = c.line.interpolate(0.5, normalized=True)
            x, y = mc.xy(mid.x, mid.y)
            mc.d.add(String(x, y + 3, "one-way", fontSize=5))
    for k, b in enumerate(analysis["bottlenecks"][:9]):
        x, y = mc.xy(b["x"], b["y"])
        mc.d.add(Circle(x, y, 6, fillColor=None, strokeColor=colors.red, strokeWidth=1.2))
        mc.d.add(String(x + 7, y + 4, str(k + 1), fontSize=7, fillColor=colors.red))
    for eid, e in analysis["exits"].items():
        g = model.gates.get(eid)
        if g:
            x, y = mc.xy(g.point.x, g.point.y)
            mc.d.add(String(x + 4, y - 6, f"{e['share'] * 100:.0f}% of exits", fontSize=5, fillColor=colors.HexColor("#d7191c")))
    d = mc.d
    x0 = mc.map_w + 4
    d.add(String(x0, d.height - 6, "Corridor peak flow / capacity", fontSize=5))
    for i, (lab, col) in enumerate((("< 50%", "#1a9641"), ("50-85%", "#fdae61"), (">= 85%", "#d7191c"),
                                    ("disabled corridor", "#ff0000"))):
        d.add(Line(x0, d.height - 14 - 8 * i, x0 + 12, d.height - 14 - 8 * i, strokeColor=colors.HexColor(col), strokeWidth=2))
        d.add(String(x0 + 15, d.height - 16 - 8 * i, lab, fontSize=5))
    return d


def line_chart(series: list[tuple[str, list[float], list[float]]], ylabel: str, width=170 * mm, height=55 * mm) -> Drawing:
    d = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 35, 20, width - 140, height - 30
    data = []
    for _, xs, ys in series:
        step = max(1, len(xs) // 300)
        data.append(list(zip(xs[::step], ys[::step])) or [(0, 0)])
    lp.data = data
    for i in range(len(data)):
        lp.lines[i].strokeColor = SERIES_COLOURS[i % len(SERIES_COLOURS)]
        lp.lines[i].strokeWidth = 1
    lp.xValueAxis.labels.fontSize = 6
    lp.yValueAxis.labels.fontSize = 6
    lp.yValueAxis.valueMin = 0
    d.add(lp)
    d.add(String(0, height - 8, ylabel, fontSize=7))
    d.add(String(lp.x + lp.width / 2, 2, "time (s)", fontSize=7))
    lg = Legend()
    lg.x, lg.y = lp.x + lp.width + 10, height - 10
    lg.fontSize = 6
    lg.boxAnchor = "nw"
    lg.colorNamePairs = [(SERIES_COLOURS[i % len(SERIES_COLOURS)], s[0][:28]) for i, s in enumerate(series)]
    d.add(lg)
    return d


def _header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#8a1c1c"))
    canvas.drawString(15 * mm, 8 * mm, "DRAFT FOR REVIEW - simulated estimates; safety-critical decisions require approval by authorised officials.")
    canvas.setFillColor(colors.black)
    canvas.drawRightString(195 * mm, 8 * mm, f"page {doc.page}")
    canvas.restoreState()


def _provenance_rows(site: dict, datasets: list[dict]) -> list[list]:
    rows = [["Dataset", "Kind", "License / attribution", "Synthetic", "Surveyed", "Source CRS", "SHA-256 (12)"]]
    for d in datasets:
        rows.append([Paragraph(d["filename"], _styles()["small"]), d["kind"], Paragraph(f"{d['license']}<br/>{d['attribution']}", _styles()["small"]),
                     _fmt(d["is_synthetic"]), _fmt(d["is_surveyed"]), Paragraph(str(d.get("source_crs") or "-")[:60], _styles()["small"]),
                     (d.get("sha256") or "")[:12]])
    return rows


def run_report(run: dict, site: dict, datasets: list[dict], scenario_cfg, analysis: dict, series: dict, grid_doc: dict,
               model: SiteModel, profile: dict) -> bytes:
    ss = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"Simulation report - {run['name']}")
    s = analysis["summary"]
    el = [Paragraph("Pushkaralu Digital Twin - Crowd Simulation Report", ss["Title"]),
          Paragraph(f"Scenario: <b>{run['name']}</b> &nbsp; Run: {run['id']} &nbsp; Generated: "
                    f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}", ss["BodyText"])]
    if site.get("is_synthetic"):
        el.append(Paragraph("SYNTHETIC DEMONSTRATION SITE - the geometry is invented for testing and is not surveyed "
                            "data of any real ghat.", ss["warn"]))
    el.append(Paragraph(f"Method: <b>{analysis['engine']['method']}</b> ({analysis['engine']['version']}). "
                        "All figures are SIMULATED ESTIMATES.", ss["BodyText"]))
    el.append(Spacer(1, 4))
    el.append(Paragraph("1. Scenario description", ss["Heading2"]))
    el.append(Paragraph(scenario_cfg.description or "-", ss["BodyText"]))
    el.append(Paragraph("2. Map, data and model versions", ss["Heading2"]))
    el.append(_table([["Item", "Value"],
                      ["Site", f"{site['name']} (id {site['id']}, version {run['site_version']})"],
                      ["Site features hash", run["features_hash"][:16]],
                      ["Simulation engine", analysis["engine"]["version"]],
                      ["Application version", run.get("app_version", "")],
                      ["Random seed", str(run["seed"])],
                      ["Threshold profile", f"{profile.get('name')} - status: {profile.get('status', 'draft').upper()}"
                                            + (f", approved by {profile.get('approved_by')} on {profile.get('approved_on')}" if profile.get("approved_by") else "")]],
                     [50 * mm, 125 * mm]))
    el.append(Spacer(1, 4))
    el.append(_table(_provenance_rows(site, datasets), [38 * mm, 12 * mm, 45 * mm, 15 * mm, 15 * mm, 35 * mm, 20 * mm], font=7))
    el.append(Paragraph("3. Input assumptions and parameters", ss["Heading2"]))
    c = scenario_cfg
    rows = [["Parameter", "Value"],
            ["Duration / time step / output interval", f"{c.duration_s:.0f} s / {c.time_step_s} s / {c.output_interval_s} s"],
            ["Walking speed (truncated normal)", f"mean {c.walking_speed.mean} m/s, sd {c.walking_speed.sd}, range {c.walking_speed.min}-{c.walking_speed.max}"],
            ["Route choice", f"{c.route_choice.strategy}" + (f" (k={c.route_choice.k}, theta={c.route_choice.logit_theta}/s)" if c.route_choice.strategy != "shortest_time" else "")],
            ["Arrivals", "; ".join(f"{d.gate_id}: {d.rate_per_min} p/min ({d.start_s:.0f}-{d.end_s if d.end_s is not None else 'end'} s)" for d in c.demand) or "none"],
            ["Destinations", "; ".join(f"{d.target_id}: share {d.share}, dwell {d.dwell_s:.0f} s" for d in c.destinations) or "-"],
            ["Holding stops", "; ".join(f"{h.holding_id}: share {h.share}, dwell {h.dwell_s:.0f} s" for h in c.holding_stops) or "-"],
            ["Initial population", "; ".join(f"{p.zone_id}: {p.count}" for p in c.initial_population) or "-"],
            ["Corridor changes", "; ".join(f"{o.corridor_id}: " + ", ".join(f"{k}={v}" for k, v in o.model_dump(exclude_none=True).items() if k != "corridor_id") for o in c.corridor_overrides) or "-"],
            ["Gate changes", "; ".join(f"{o.gate_id}: " + ", ".join(f"{k}={v}" for k, v in o.model_dump(exclude_none=True).items() if k != "gate_id") for o in c.gate_overrides) or "-"],
            ["Entry restrictions", "; ".join(f"{r.gate_id} x{r.rate_multiplier} from {r.start_s:.0f}s" for r in c.entry_restrictions) or "-"],
            ["Diversion", (f"at {c.diversion.activation_s:.0f} s; closes {c.diversion.close_corridors}; destinations "
                           f"{[d.target_id for d in c.diversion.destinations]}") if c.diversion else "-"],
            ["Evacuation", (f"trigger {c.evacuation.trigger_s:.0f} s; strategy {c.evacuation.strategy}; exits "
                            f"{c.evacuation.exit_gate_ids or 'all'}; closures {c.evacuation.close_corridors or '-'}") if c.evacuation else "-"],
            ["Density limit (default)", f"{s['density_limit_ppm2']} persons/m2 (zone-specific limits in table 5)"]]
    el.append(_table([[Paragraph(str(a), ss["small"]), Paragraph(str(b), ss["small"])] for a, b in rows], [55 * mm, 120 * mm]))
    el.append(PageBreak())
    el.append(Paragraph("4. Results summary (simulated estimates)", ss["Heading2"]))
    keys = [("Total arrivals", "total_arrivals", "persons"), ("Initial population", "initial_population", "persons"),
            ("Exited", "total_exited", "persons"), ("Remaining in site at end", "remaining_at_end", "persons"),
            ("Waiting at entries at end", "entry_queue_at_end", "persons"), ("Peak population in site", "peak_population_in_site", "persons"),
            ("Maximum grid density", "max_density_ppm2", "p/m2"), ("Maximum zone density", "max_zone_density_ppm2", "p/m2"),
            ("Time with any cell above limit", "time_above_threshold_s", "s"), ("Average entry wait", "avg_wait_s", "s"),
            ("Maximum entry wait", "max_wait_s", "s"), ("Throughput (exits)", "throughput_ppm", "p/min"),
            ("Peak exit flow", "peak_exit_flow_ppm", "p/min"), ("Mean travel time", "mean_travel_time_s", "s"),
            ("Bottlenecks / unresolved", None, ""), ("Evacuation clearance time", "clearance_time_s", "s")]
    rows = [["Metric", "Value", "Unit"]]
    for lab, k, u in keys:
        v = f"{s['n_bottlenecks']} / {s['n_unresolved_bottlenecks']}" if k is None else _fmt(s.get(k))
        if k == "clearance_time_s" and analysis.get("evacuation") and not analysis["evacuation"]["cleared_within_simulation"]:
            v = "not cleared within simulation"
        rows.append([lab, v, u])
    el.append(_table(rows, [70 * mm, 60 * mm, 25 * mm]))
    el.append(Paragraph("Population over time", ss["Heading3"]))
    t = series["times"]
    el.append(line_chart([("in site", t, series["total_in_site"]), ("queued / congested", t, series["queued"])]
                         + [(f"entry queue {g}", t, v) for g, v in list(series["entry_queues"].items())[:3]], "persons"))
    el.append(KeepTogether([Paragraph("Crowd-density map (maximum over the run)", ss["Heading3"]),
                            density_map(model, grid_doc, analysis, profile.get("density_bands", [0.5, 1, 2, 3, 4, 5])),
                            Paragraph("Numbered red circles mark detected bottlenecks (see section 6).", ss["small"])]))
    el.append(KeepTogether([Paragraph("Route and bottleneck map", ss["Heading3"]), route_map(model, analysis, scenario_cfg)]))
    el.append(Paragraph("5. Zone-level results", ss["Heading2"]))
    rows = [["Zone", "Kind", "Usable m2", "Max count", "Max p/m2", "Limit", "Time above (s)", "Final"]]
    for z in sorted(analysis["zones"], key=lambda r: -r["max_density_ppm2"])[:40]:
        rows.append([Paragraph(z["name"][:40], ss["small"]), z["kind"], _fmt(z["usable_area_m2"], 0), _fmt(z["max_count"], 0),
                     _fmt(z["max_density_ppm2"], 2), _fmt(z["limit_ppm2"]), _fmt(z["time_above_limit_s"], 0), _fmt(z["final_count"], 0)])
    el.append(_table(rows, [45 * mm, 22 * mm, 18 * mm, 18 * mm, 16 * mm, 14 * mm, 20 * mm, 15 * mm]))
    el.append(Paragraph("6. Bottlenecks", ss["Heading2"]))
    if analysis["bottlenecks"]:
        rows = [["#", "Type", "Near", "Max p/m2", "Duration (s)", "Unresolved at end"]]
        for k, b in enumerate(analysis["bottlenecks"][:20]):
            rows.append([str(k + 1), b["type"], Paragraph(str(b.get("near")), ss["small"]), _fmt(b["max_density_ppm2"], 2),
                         _fmt(b["duration_s"], 0), _fmt(b["unresolved"])])
        el.append(_table(rows, [8 * mm, 18 * mm, 60 * mm, 20 * mm, 22 * mm, 30 * mm]))
    else:
        el.append(Paragraph("No location exceeded the configured limit for the minimum duration.", ss["BodyText"]))
    el.append(Paragraph("Exit utilisation", ss["Heading3"]))
    rows = [["Exit", "Persons", "Share", "Peak p/min", "Capacity p/min", "Peak use"]]
    for eid, e in analysis["exits"].items():
        rows.append([Paragraph(e["name"], ss["small"]), _fmt(e["count"], 0), f"{e['share'] * 100:.0f}%", _fmt(e["peak_ppm"]),
                     _fmt(e["capacity_ppm"]), f"{(e['peak_utilisation'] or 0) * 100:.0f}%"])
    el.append(_table(rows, [55 * mm, 20 * mm, 18 * mm, 22 * mm, 28 * mm, 20 * mm]))
    if analysis["holding"]:
        el.append(Paragraph("7. Holding-area capacity", ss["Heading2"]))
        rows = [["Holding area", "Usable m2", "Limit", "Peak", "Peak %", "Limit reached at", "Spare at end"]]
        for h in analysis["holding"]:
            rows.append([Paragraph(h["name"], ss["small"]), _fmt(h["usable_area_m2"], 0), _fmt(h["effective_limit"]),
                         _fmt(h["peak_population"], 0), f"{h['peak_occupancy_pct']:.0f}%", _fmt(h["time_limit_reached_s"], 0),
                         _fmt(h["available_capacity_final"], 0)])
        el.append(_table(rows, [45 * mm, 18 * mm, 18 * mm, 18 * mm, 15 * mm, 28 * mm, 25 * mm]))
        el.append(Paragraph("Limit = min(configured operational capacity, density limit x usable area). Usable area "
                            "excludes buildings, barriers and other non-walkable surfaces.", ss["small"]))
    ev = analysis.get("evacuation")
    if ev:
        el.append(Paragraph("8. Evacuation clearance estimates", ss["Heading2"]))
        el.append(_table([["Item", "Value"], ["Trigger time", f"{ev['trigger_s']:.0f} s"], ["Strategy", ev["strategy"]],
                          ["Evacuees", _fmt(ev["evacuees"], 0)], ["Unreachable evacuees", _fmt(ev["unreachable_evacuees"], 0)],
                          ["Total clearance time", _fmt(ev["clearance_time_s"], 0) + " s" if ev["cleared_within_simulation"] else "not cleared within simulation"],
                          ["Remaining in affected area at end", _fmt(ev["remaining_in_affected_area"], 0)],
                          ["Capacity-constrained (CCRP) planning estimate", _fmt(ev["ccrp_planning_estimate_s"], 0) + " s"]],
                         [80 * mm, 90 * mm]))
        rows = [["Zone", "Population at trigger", "Clearance (s)"]]
        for z, v in ev["clearance_by_zone"].items():
            rows.append([Paragraph(v["name"], ss["small"]), _fmt(v["population_at_trigger"], 0),
                         _fmt(v["clearance_s"], 0) if v["clearance_s"] is not None else "not cleared"])
        el.append(Spacer(1, 3))
        el.append(_table(rows, [80 * mm, 45 * mm, 45 * mm]))
        el.append(Paragraph(ev["note"], ss["warn"]))
    el.append(Paragraph("9. Recommended operational interventions (for expert review)", ss["Heading2"]))
    for txt in analysis["interventions"]:
        el.append(Paragraph(f"&bull; {txt}", ss["BodyText"]))
    if analysis.get("warnings"):
        el.append(Paragraph("Model warnings", ss["Heading3"]))
        for w in analysis["warnings"][:15]:
            el.append(Paragraph(f"&bull; {w}", ss["small"]))
    el.append(Paragraph("10. Limitations", ss["Heading2"]))
    for txt in LIMITATIONS:
        el.append(Paragraph(f"&bull; {txt}", ss["small"]))
    el.append(KeepTogether(_approval_block(ss, run)))
    doc.build(el, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()


def _approval_block(ss, run: dict | None = None):
    rv = (run or {}).get("review") or {}
    rows = [["Role", "Name", "Designation", "Decision / comments", "Date", "Signature"],
            ["Prepared by", rv.get("prepared_by", ""), "", "", "", ""],
            ["Reviewed by (crowd safety)", rv.get("reviewed_by", ""), "", rv.get("review_comments", ""), rv.get("reviewed_on", ""), ""],
            ["Approved by (competent authority)", rv.get("approved_by", ""), "", "", rv.get("approved_on", ""), ""]]
    return [Paragraph("11. Review and approval", ss["Heading2"]),
            Paragraph(f"Review status recorded in the application: <b>{rv.get('status', 'draft').upper()}</b>. "
                      "This report supports drafting SOPs and drills; emergency procedures and safety-critical decisions "
                      "must be approved by authorised officials.", ss["BodyText"]),
            _table([[Paragraph(str(c), ss["small"]) for c in r] for r in rows], [38 * mm, 30 * mm, 25 * mm, 40 * mm, 18 * mm, 25 * mm])]


COMPARE_KEYS = [
    ("Total clearance time", "clearance_time_s", "s", "lower"),
    ("Maximum crowd density (grid)", "max_density_ppm2", "p/m2", "lower"),
    ("Maximum zone density", "max_zone_density_ppm2", "p/m2", "lower"),
    ("Time above density threshold", "time_above_threshold_s", "s", "lower"),
    ("Average waiting time", "avg_wait_s", "s", "lower"),
    ("Maximum waiting time", "max_wait_s", "s", "lower"),
    ("Throughput (exits)", "throughput_ppm", "p/min", "higher"),
    ("Peak exit flow", "peak_exit_flow_ppm", "p/min", "higher"),
    ("Total exited", "total_exited", "persons", "higher"),
    ("Remaining at end", "remaining_at_end", "persons", ""),
    ("Bottlenecks", "n_bottlenecks", "", "lower"),
    ("Unresolved bottlenecks", "n_unresolved_bottlenecks", "", "lower"),
    ("Congestion duration", "congestion_duration_s", "s", "lower"),
    ("Peak population in site", "peak_population_in_site", "persons", ""),
]


def compare_rows(a: dict, b: dict) -> list[dict]:
    rows = []
    for label, k, unit, better in COMPARE_KEYS:
        va, vb = a.get(k), b.get(k)
        diff = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        pct = (diff / va * 100) if diff is not None and va not in (0, None) else None
        verdict = ""
        if diff is not None and better and abs(diff) > 1e-9:
            verdict = "alternative better" if (diff < 0) == (better == "lower") else "alternative worse"
        rows.append({"metric": label, "key": k, "unit": unit, "baseline": va, "alternative": vb, "difference": diff,
                     "difference_pct": pct, "direction": better, "assessment": verdict})
    # exit utilisation
    for eid in sorted(set(a.get("exit_utilisation", {})) | set(b.get("exit_utilisation", {}))):
        ua = (a.get("exit_utilisation", {}).get(eid) or {}).get("share")
        ub = (b.get("exit_utilisation", {}).get(eid) or {}).get("share")
        rows.append({"metric": f"Exit share {eid}", "key": f"exit_share:{eid}", "unit": "fraction", "baseline": ua,
                     "alternative": ub, "difference": (ub - ua) if ua is not None and ub is not None else None,
                     "difference_pct": None, "direction": "", "assessment": ""})
    return rows


def compare_report(run_a: dict, run_b: dict, site: dict, rows: list[dict], series_a: dict, series_b: dict) -> bytes:
    ss = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title="Scenario comparison")
    el = [Paragraph("Pushkaralu Digital Twin - Scenario Comparison", ss["Title"]),
          Paragraph(f"Baseline: <b>{run_a['name']}</b> ({run_a['method']}, run {run_a['id']})<br/>"
                    f"Alternative: <b>{run_b['name']}</b> ({run_b['method']}, run {run_b['id']})<br/>"
                    f"Site: {site['name']} &nbsp; Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}", ss["BodyText"])]
    if site.get("is_synthetic"):
        el.append(Paragraph("SYNTHETIC DEMONSTRATION SITE - not surveyed data.", ss["warn"]))
    if run_a["method"] != run_b["method"]:
        el.append(Paragraph("The two runs use different simulation methods; differences partly reflect the method.", ss["warn"]))
    el.append(Paragraph("All values are simulated estimates computed from the two runs.", ss["BodyText"]))
    tbl = [["Metric", "Unit", "Baseline", "Alternative", "Difference", "Assessment"]]
    for r in rows:
        tbl.append([Paragraph(r["metric"], ss["small"]), r["unit"], _fmt(r["baseline"], 2), _fmt(r["alternative"], 2),
                    (_fmt(r["difference"], 2) + (f" ({r['difference_pct']:+.0f}%)" if r["difference_pct"] is not None else "")) if r["difference"] is not None else "-",
                    r["assessment"]])
    el.append(_table(tbl, [52 * mm, 15 * mm, 25 * mm, 25 * mm, 30 * mm, 30 * mm]))
    el.append(Paragraph("Population in site", ss["Heading3"]))
    el.append(line_chart([("baseline", series_a["times"], series_a["total_in_site"]),
                          ("alternative", series_b["times"], series_b["total_in_site"])], "persons"))
    el.append(Paragraph("Queued / congested persons", ss["Heading3"]))
    el.append(line_chart([("baseline", series_a["times"], series_a["queued"]),
                          ("alternative", series_b["times"], series_b["queued"])], "persons"))
    el.append(Paragraph("Limitations", ss["Heading2"]))
    for txt in LIMITATIONS:
        el.append(Paragraph(f"&bull; {txt}", ss["small"]))
    el.append(Paragraph("An 'alternative better' assessment refers to a single metric only and is not a safety approval.", ss["warn"]))
    el.extend(_approval_block(ss))
    doc.build(el, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
