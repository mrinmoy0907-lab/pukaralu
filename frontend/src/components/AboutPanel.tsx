import { useEffect, useState } from "react";
import { api } from "../api";
import { BAND_COLOURS, bandLabels } from "../lib/colors";
import { useStore } from "../store";
import type { ThresholdProfile } from "../types";
import { Num, Section, Sel, Txt } from "./ui";

const LIMITATIONS = [
  "All outputs are simulated estimates; they are not measurements and are not validated against observed crowd data unless you load such data and compare.",
  "Demand, origin–destination shares, dwell times and walking speeds are scenario assumptions that must be replaced with locally observed values.",
  "Density thresholds are configurable and must be approved by the competent crowd-management authority.",
  "Agent-based runs (JuPedSim) do not represent pushing, falls, group cohesion or responses to announcements.",
  "Macroscopic runs (Cell Transmission Model) estimate aggregate flows: no individuals, no counterflow friction; each direction of a two-way corridor uses the full width.",
  "Evacuation clearance time alone does not establish that a route is safe. Accessibility, counterflows, emergency access and secondary hazards need expert review.",
  "Corridor closures during a run are enforced by re-routing; in agent-based runs the corridor is also removed from the walkable area once it is empty.",
  "No live sensor, CCTV or counter integration exists in this release; observed counts can only be entered manually or uploaded.",
];

export default function AboutPanel() {
  const { meta, profiles, set, fail, toast } = useStore();
  const [p, setP] = useState<ThresholdProfile | null>(null);
  useEffect(() => setP(profiles[0] ? JSON.parse(JSON.stringify(profiles[0])) : null), [profiles]);

  async function save() {
    if (!p) return;
    try {
      await api.updateProfile(p.id, { name: p.name, values: p.values, status: p.status, approved_by: p.approved_by, approved_on: p.approved_on, notes: p.notes });
      set({ profiles: await api.profiles() });
      toast("success", "Threshold profile saved. New runs will use it.");
    } catch (e) {
      fail(e, "Saving thresholds");
    }
  }

  return (
    <div>
      <Section title="Simulation methods">
        {meta?.engines.map((e) => (
          <div key={e.key} className="card small">
            <b>{e.label}</b> – {e.version} ({e.license})
            <div className="muted">{e.description}</div>
          </div>
        ))}
        <div className="small">
          Every run is labelled with its method. Macroscopic estimates are never presented as agent-based simulation.
        </div>
      </Section>
      <Section title="Assumptions & units">
        <table className="tbl small">
          <tbody>
            <tr><td>Max specific flow</td><td>{meta?.assumptions.specific_flow_max_p_per_m_s} persons/(m·s) – Weidmann (1993)</td></tr>
            <tr><td>Jam density</td><td>{meta?.assumptions.jam_density_p_per_m2} persons/m² – Weidmann (1993)</td></tr>
            <tr><td>Default walking speed</td><td>N({meta?.assumptions.default_walking_speed_m_s?.mean}, {meta?.assumptions.default_walking_speed_m_s?.sd}) m/s, truncated</td></tr>
            <tr><td>Surface speed factors</td><td>{Object.entries(meta?.assumptions.surface_speed_factor ?? {}).map(([k, v]) => `${k} ${v}`).join(", ")}</td></tr>
            <tr><td>Units</td><td>density persons/m² · flow persons/min · time s · length m</td></tr>
            <tr><td>Density estimate</td><td>persons per walkable m² in each grid cell / zone (buildings, barriers, water excluded)</td></tr>
          </tbody>
        </table>
      </Section>
      {p && (
        <Section title="Density thresholds (configurable)">
          <div className={`alert ${p.status === "approved" ? "ok" : "warn"} small`}>
            Status: <b>{p.status.toUpperCase()}</b>
            {p.approved_by ? ` – approved by ${p.approved_by} on ${p.approved_on}` : " – not approved by a competent authority"}
          </div>
          <Txt label="Profile name" value={p.name} onChange={(v) => setP({ ...p, name: v })} />
          <div className="legend">
            {bandLabels(p.values.density_bands).map((l, i) => (
              <span key={i}>
                <i style={{ background: BAND_COLOURS[i] }} />
                {l}
              </span>
            ))}
          </div>
          <Txt
            label="Colour breaks (p/m², comma separated)"
            value={p.values.density_bands.join(", ")}
            onChange={(v) => setP({ ...p, values: { ...p.values, density_bands: v.split(",").map((x) => Number(x.trim())).filter((x) => !Number.isNaN(x)) } })}
          />
          <div className="grid2">
            {Object.entries(p.values.limits).map(([k, v]) => (
              <Num key={k} label={`Limit: ${k}`} unit="p/m²" step={0.1} value={v} onChange={(x) => setP({ ...p, values: { ...p.values, limits: { ...p.values.limits, [k]: x ?? 0 } } })} />
            ))}
            <Num label="Bottleneck min. duration" unit="s" value={p.values.bottleneck_min_duration_s} onChange={(x) => setP({ ...p, values: { ...p.values, bottleneck_min_duration_s: x ?? 60 } })} />
            <Num label="Entry wait limit" unit="s" value={p.values.queue_wait_limit_s} onChange={(x) => setP({ ...p, values: { ...p.values, queue_wait_limit_s: x ?? 900 } })} />
          </div>
          <Sel label="Status" value={p.status} options={["draft", "approved", "retired"].map((x) => ({ value: x, label: x }))} onChange={(v) => setP({ ...p, status: v })} />
          <Txt label="Approved by" value={p.approved_by ?? ""} onChange={(v) => setP({ ...p, approved_by: v || null })} />
          <Txt label="Approved on (YYYY-MM-DD)" value={p.approved_on ?? ""} onChange={(v) => setP({ ...p, approved_on: v || null })} />
          <Txt label="Notes / sources" value={p.notes} onChange={(v) => setP({ ...p, notes: v })} area />
          <button onClick={save}>Save profile</button>
        </Section>
      )}
      <Section title="Limitations">
        {LIMITATIONS.map((l, i) => (
          <div key={i} className="small suggestion">
            • {l}
          </div>
        ))}
      </Section>
      <Section title="Open-source components" open={false}>
        <div className="small">
          CesiumJS (Apache-2.0) · OpenLayers (BSD-2) · React (MIT) · Recharts (MIT) · zustand (MIT) · JuPedSim (LGPL-3.0+) · FastAPI (MIT) · Shapely (BSD) · GDAL via pyogrio/rasterio (MIT/BSD) · pyproj (MIT) · NetworkX (BSD) · ReportLab (BSD) · SQLAlchemy/Alembic (MIT) · PostGIS (GPL-2.0, server side). Basemap: © OpenStreetMap contributors (ODbL). See docs/LICENSES.md.
        </div>
      </Section>
    </div>
  );
}
