import { useEffect, useState } from "react";
import { api } from "../api";
import { featureById, useStore } from "../store";
import type { Feature } from "../types";
import { Check, Num, Sel, Txt } from "./ui";

export default function Inspector() {
  const { features, selected, site, meta, set, reloadFeatures, toast, fail, runData, activeRun } = useStore();
  const f = featureById(features, selected);
  const [draft, setDraft] = useState<Feature | null>(null);
  useEffect(() => setDraft(f ? JSON.parse(JSON.stringify(f)) : null), [f]);
  if (!f || !draft || !site) return null;
  const p = draft.properties;
  const t = p.pk_type;
  const setP = (k: string, v: any) => setDraft({ ...draft, properties: { ...draft.properties, [k]: v } });
  const dirty = JSON.stringify(draft) !== JSON.stringify(f);
  const zone = activeRun ? runData[activeRun]?.analysis.zones.find((z) => z.zone_id === String(f.id)) : undefined;
  const flow = activeRun ? runData[activeRun]?.analysis.corridor_flow[String(f.id)] : undefined;

  async function save() {
    try {
      await api.updateFeature(site!.id, draft!);
      await reloadFeatures();
      toast("success", "Feature saved (site version incremented).");
    } catch (e) {
      fail(e, "Saving feature");
    }
  }
  async function remove() {
    if (!confirm(`Delete ${p.name ?? f!.id}?`)) return;
    try {
      await api.deleteFeature(site!.id, String(f!.id));
      set({ selected: null });
      await reloadFeatures();
    } catch (e) {
      fail(e, "Deleting feature");
    }
  }

  return (
    <aside className="inspector">
      <header>
        <strong>{p.name ?? f.id}</strong>
        <button className="icon" onClick={() => set({ selected: null })} aria-label="close">
          ×
        </button>
      </header>
      <div className="muted small">
        {meta?.feature_types[t]?.label ?? t} · id <code>{String(f.id)}</code> · source: {p.source}
        {p.synthetic && <span className="badge warn inline">synthetic</span>}
      </div>
      <Txt label="Name" value={p.name ?? ""} onChange={(v) => setP("name", v)} />
      {(t === "corridor" || t === "emergency_corridor") && (
        <>
          <Num label="Width" unit="m" value={p.width_m} step={0.5} onChange={(v) => setP("width_m", v)} />
          <Sel
            label="Direction"
            value={p.direction ?? "both"}
            options={[
              { value: "both", label: "two-way" },
              { value: "forward", label: "one-way (as digitised)" },
              { value: "backward", label: "one-way (reverse)" },
            ]}
            onChange={(v) => setP("direction", v)}
          />
          <Sel
            label="Surface"
            value={p.surface ?? "path"}
            options={["path", "stairs", "ramp"].map((x) => ({ value: x, label: x }))}
            onChange={(v) => setP("surface", v)}
          />
          <Check label="Enabled (unchecked = blocked)" checked={p.enabled !== false} onChange={(v) => setP("enabled", v)} />
          <Check label="Emergency-only path" checked={!!p.emergency_only} onChange={(v) => setP("emergency_only", v)} />
          <div className="muted small">Capacity ≈ {(1.22 * Number(p.width_m ?? 4) * 60).toFixed(0)} persons/min (1.22 p/(m·s) × width, Weidmann 1993)</div>
        </>
      )}
      {t === "gate" && (
        <>
          <Sel label="Role" value={p.role ?? "both"} options={["entry", "exit", "both"].map((x) => ({ value: x, label: x }))} onChange={(v) => setP("role", v)} />
          <Num label="Width" unit="m" value={p.width_m} step={0.5} onChange={(v) => setP("width_m", v)} />
          <Check label="Open" checked={p.enabled !== false} onChange={(v) => setP("enabled", v)} />
          <Check label="Emergency exit only" checked={!!p.emergency_exit} onChange={(v) => setP("emergency_exit", v)} />
        </>
      )}
      {t === "holding_area" && (
        <Num label="Operational capacity" unit="persons" value={p.capacity_persons} onChange={(v) => setP("capacity_persons", v)} title="Approved operational capacity; the analysis also applies the density limit × usable area" />
      )}
      {["building", "temple", "wall", "barricade", "obstacle"].includes(t) && <Num label="Height" unit="m" value={p.height_m} step={0.5} onChange={(v) => setP("height_m", v)} />}
      {["ghat", "steps", "ramp"].includes(t) && (
        <Sel label="Surface" value={p.surface ?? (t === "ramp" ? "ramp" : "steps")} options={["path", "steps", "ramp"].map((x) => ({ value: x, label: x }))} onChange={(v) => setP("surface", v)} />
      )}
      <div className="row">
        <button onClick={save} disabled={!dirty}>
          Save
        </button>
        <button className="secondary" onClick={() => setDraft(JSON.parse(JSON.stringify(f)))} disabled={!dirty}>
          Revert
        </button>
        <button className="danger" onClick={remove}>
          Delete
        </button>
      </div>
      {zone && (
        <div className="inspect-results">
          <div className="label-sim">Simulated in active run</div>
          <div>Usable area {zone.usable_area_m2.toLocaleString()} m²</div>
          <div>
            Max {zone.max_count.toFixed(0)} persons · max {zone.max_density_ppm2.toFixed(2)} p/m² (limit {zone.limit_ppm2})
          </div>
          <div className={zone.time_above_limit_s > 0 ? "warn-text" : ""}>Time above limit: {zone.time_above_limit_s.toFixed(0)} s</div>
          {flow && (
            <div>
              Peak flow {flow.peak_ppm.toFixed(0)} p/min of {flow.capacity_ppm.toFixed(0)} p/min capacity ({((flow.peak_utilisation ?? 0) * 100).toFixed(0)}%)
            </div>
          )}
        </div>
      )}
      <details>
        <summary className="muted small">All attributes</summary>
        <pre className="small">{JSON.stringify(f.properties, null, 1)}</pre>
      </details>
    </aside>
  );
}
