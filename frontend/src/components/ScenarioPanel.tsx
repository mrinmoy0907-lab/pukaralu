import { useEffect, useMemo, useState } from "react";
import { api, download } from "../api";
import { emptyConfig, expectedPopulation, precheck } from "../lib/scenario";
import { useStore } from "../store";
import type { Scenario, ScenarioConfig } from "../types";
import { Check, MultiCheck, Num, Section, Sel, Txt } from "./ui";

type Opt = { value: string; label: string };

function RowList<T>({ items, onChange, render, make, addLabel }: {
  items: T[]; onChange: (v: T[]) => void; render: (it: T, upd: (p: Partial<T>) => void) => React.ReactNode; make: () => T; addLabel: string;
}) {
  return (
    <div className="rowlist">
      {items.map((it, i) => (
        <div key={i} className="rowlist-item">
          {render(it, (p) => onChange(items.map((x, j) => (j === i ? { ...x, ...p } : x))))}
          <button className="icon danger" onClick={() => onChange(items.filter((_, j) => j !== i))} title="remove">
            ×
          </button>
        </div>
      ))}
      <button className="secondary small" onClick={() => onChange([...items, make()])}>
        + {addLabel}
      </button>
    </div>
  );
}

export default function ScenarioPanel() {
  const { site, scenarios, features, meta, reloadScenarios, reloadRuns, set, toast, fail, profiles } = useStore();
  const [current, setCurrent] = useState<Scenario | null>(null);
  const [cfg, setCfg] = useState<ScenarioConfig | null>(null);
  const [json, setJson] = useState("");
  const [validation, setValidation] = useState<{ ok: boolean; text: string[] } | null>(null);
  const [presets, setPresets] = useState<{ key: string; label: string; available: boolean; config: ScenarioConfig | null }[]>([]);
  const [runEngine, setRunEngine] = useState<string>("");

  useEffect(() => {
    if (site) api.presets(site.id).then(setPresets).catch(() => setPresets([]));
  }, [site, features.length]);

  useEffect(() => {
    if (current) {
      const sc = scenarios.find((s) => s.id === current.id);
      if (!sc) {
        setCurrent(null);
        setCfg(null);
      }
    }
  }, [scenarios, current]);

  const by = (types: string[]): Opt[] =>
    features.filter((f) => types.includes(f.properties.pk_type)).map((f) => ({ value: String(f.id), label: f.properties.name ?? String(f.id) }));
  const gates = by(["gate"]);
  const entryGates = features
    .filter((f) => f.properties.pk_type === "gate" && f.properties.role !== "exit" && !f.properties.emergency_exit)
    .map((f) => ({ value: String(f.id), label: f.properties.name ?? String(f.id) }));
  const exitGates = features.filter((f) => f.properties.pk_type === "gate" && f.properties.role !== "entry").map((f) => ({ value: String(f.id), label: f.properties.name ?? String(f.id) }));
  const dests = by(["bathing_area", "ghat", "holding_area", "assembly_point", "plaza", "transit_hub", "bus_terminal", "parking"]);
  const holdings = by(["holding_area"]);
  const areas = by(["bathing_area", "ghat", "holding_area", "assembly_point", "plaza", "transit_hub", "bus_terminal", "parking"]);
  const corridors = by(["corridor", "emergency_corridor"]);
  const zones = [...areas, ...by(["zone"]), ...corridors];
  const assembly = by(["assembly_point"]);
  const errs = useMemo(() => (cfg ? precheck(cfg, features) : []), [cfg, features]);

  function open(sc: Scenario) {
    setCurrent(sc);
    setCfg(JSON.parse(JSON.stringify(sc.config)));
    setValidation(null);
    setJson("");
  }
  function newFrom(key: string) {
    const p = presets.find((x) => x.key === key);
    const c = { ...emptyConfig(), ...(p?.config ? JSON.parse(JSON.stringify(p.config)) : {}) };
    c.name = `${c.name} (copy)`;
    setCurrent(null);
    setCfg(c);
    setValidation(null);
  }
  const upd = (p: Partial<ScenarioConfig>) => cfg && setCfg({ ...cfg, ...p });

  async function validate() {
    if (!cfg || !site) return;
    try {
      const r = await api.validateScenario(site.id, cfg);
      setValidation({ ok: true, text: [`Valid. Expected ≈ ${r.expected_population} pedestrians; network ${r.network.nodes} nodes / ${r.network.links} links; walkable ${r.walkable_area_m2} m².`, ...r.warnings] });
    } catch (e: any) {
      setValidation({ ok: false, text: e.details?.length ? e.details : [e.message] });
    }
  }
  async function save(asNew = false) {
    if (!cfg || !site) return;
    try {
      const body = { name: cfg.name, description: cfg.description, config: cfg };
      const sc = current && !asNew ? await api.updateScenario(current.id, body) : await api.createScenario(site.id, body);
      await reloadScenarios();
      open(sc);
      toast("success", "Scenario saved.");
      return sc;
    } catch (e: any) {
      setValidation({ ok: false, text: e.details?.length ? e.details : [e.message] });
      fail(e, "Saving scenario");
    }
  }
  async function run(sc?: Scenario) {
    const target = sc ?? (current ? await save() : await save(true));
    if (!target) return;
    try {
      const r = await api.startRun(target.id, runEngine ? { engine: runEngine } : {});
      toast("info", `Simulation started (${r.engine}). Progress is shown in the Runs tab.`);
      await reloadRuns();
      set({ tab: "runs" });
    } catch (e) {
      fail(e, "Starting simulation");
    }
  }
  async function remove() {
    if (!current || !confirm(`Delete scenario '${current.name}'?`)) return;
    try {
      await api.deleteScenario(current.id);
      setCurrent(null);
      setCfg(null);
      await reloadScenarios();
    } catch (e) {
      fail(e, "Deleting scenario");
    }
  }

  // corridor / gate overrides are edited in tables of all corridors/gates
  const cOver = (id: string) => cfg?.corridor_overrides.find((o) => o.corridor_id === id) ?? { corridor_id: id };
  const setCOver = (id: string, p: Record<string, any>) => {
    if (!cfg) return;
    const merged = { ...cOver(id), ...p };
    const rest = cfg.corridor_overrides.filter((o) => o.corridor_id !== id);
    const meaningful = Object.entries(merged).some(([k, v]) => k !== "corridor_id" && v !== null && v !== undefined && v !== "");
    upd({ corridor_overrides: meaningful ? [...rest, merged] : rest });
  };
  const gOver = (id: string) => cfg?.gate_overrides.find((o) => o.gate_id === id) ?? { gate_id: id };
  const setGOver = (id: string, p: Record<string, any>) => {
    if (!cfg) return;
    const merged = { ...gOver(id), ...p };
    const rest = cfg.gate_overrides.filter((o) => o.gate_id !== id);
    const meaningful = Object.entries(merged).some(([k, v]) => k !== "gate_id" && v !== null && v !== undefined && v !== "");
    upd({ gate_overrides: meaningful ? [...rest, merged] : rest });
  };

  if (!site) return null;
  return (
    <div>
      <Section title="Scenarios">
        <div className="list">
          {scenarios.map((s) => (
            <div key={s.id} className={`list-item ${current?.id === s.id ? "active" : ""}`} onClick={() => open(s)}>
              <div>
                <strong>{s.name}</strong>
                <div className="muted small">
                  {s.config.engine === "jupedsim" ? "agent-based" : "macroscopic"} · {s.config.duration_s}s{s.preset ? ` · preset ${s.preset}` : ""}
                </div>
              </div>
              <button className="small" onClick={(e) => (e.stopPropagation(), run(s))} title="Run with saved settings">
                ▶ Run
              </button>
            </div>
          ))}
          {!scenarios.length && <div className="muted">No scenarios yet.</div>}
        </div>
        <div className="row">
          <Sel
            value=""
            options={presets.filter((p) => p.available).map((p) => ({ value: p.key, label: `New from preset: ${p.label}` }))}
            onChange={(v) => v && newFrom(v)}
            allowEmpty="New scenario from preset…"
          />
          <button className="secondary" onClick={() => (setCurrent(null), setCfg(emptyConfig()))}>
            Blank
          </button>
        </div>
      </Section>

      {cfg && (
        <>
          <div className="editor-head">
            <strong>{current ? `Editing: ${current.name}` : "New scenario (unsaved)"}</strong>
            <span className="muted small">≈ {expectedPopulation(cfg).toLocaleString()} pedestrians</span>
          </div>
          {errs.length > 0 && (
            <div className="alert error">
              {errs.map((e, i) => (
                <div key={i}>{e}</div>
              ))}
            </div>
          )}
          {validation && (
            <div className={`alert ${validation.ok ? "ok" : "error"}`}>
              {validation.text.map((e, i) => (
                <div key={i}>{e}</div>
              ))}
            </div>
          )}
          <Section title="General">
            <Txt label="Name" value={cfg.name} onChange={(v) => upd({ name: v })} />
            <Txt label="Description" value={cfg.description} onChange={(v) => upd({ description: v })} area />
            <Sel
              label="Simulation method"
              value={cfg.engine}
              options={(meta?.engines ?? []).map((e) => ({ value: e.key, label: e.label }))}
              onChange={(v) => upd({ engine: v as any, time_step_s: v === "macro_ctm" ? 1 : 0.05 })}
            />
            {cfg.engine === "jupedsim" && (
              <Sel
                label="Pedestrian model"
                value={cfg.pedestrian_model}
                options={[
                  { value: "CollisionFreeSpeedModel", label: "Collision-Free Speed Model (Tordeux 2016)" },
                  { value: "SocialForceModel", label: "Social Force Model (Helbing 1995)" },
                ]}
                onChange={(v) => upd({ pedestrian_model: v })}
              />
            )}
            <div className="grid2">
              <Num label="Duration" unit="s" value={cfg.duration_s} onChange={(v) => upd({ duration_s: v ?? 0 })} />
              <Num label="Time step" unit="s" step={0.01} value={cfg.time_step_s} onChange={(v) => upd({ time_step_s: v ?? 0.05 })} />
              <Num label="Output interval" unit="s" step={0.5} value={cfg.output_interval_s} onChange={(v) => upd({ output_interval_s: v ?? 1 })} />
              <Num label="Random seed" value={cfg.seed} onChange={(v) => upd({ seed: v ?? 0 })} />
              <Num label="Density grid cell" unit="m" value={cfg.density_grid_cell_m} onChange={(v) => upd({ density_grid_cell_m: v ?? 4 })} />
              <Sel
                label="Threshold profile"
                value={cfg.threshold_profile_id ? String(cfg.threshold_profile_id) : ""}
                options={profiles.map((p) => ({ value: String(p.id), label: `${p.name} [${p.status}]` }))}
                onChange={(v) => upd({ threshold_profile_id: v ? Number(v) : null })}
                allowEmpty="default"
              />
            </div>
          </Section>
          <Section title="Pedestrians & behaviour" open={false}>
            <div className="grid2">
              <Num label="Speed mean" unit="m/s" step={0.01} value={cfg.walking_speed.mean} onChange={(v) => upd({ walking_speed: { ...cfg.walking_speed, mean: v ?? 1.34 } })} />
              <Num label="Speed sd" unit="m/s" step={0.01} value={cfg.walking_speed.sd} onChange={(v) => upd({ walking_speed: { ...cfg.walking_speed, sd: v ?? 0 } })} />
              <Num label="Speed min" unit="m/s" step={0.05} value={cfg.walking_speed.min} onChange={(v) => upd({ walking_speed: { ...cfg.walking_speed, min: v ?? 0.5 } })} />
              <Num label="Speed max" unit="m/s" step={0.05} value={cfg.walking_speed.max} onChange={(v) => upd({ walking_speed: { ...cfg.walking_speed, max: v ?? 2 } })} />
              <Num label="Body radius" unit="m" step={0.01} value={cfg.agent_radius_m} onChange={(v) => upd({ agent_radius_m: v ?? 0.2 })} />
            </div>
            <Sel
              label="Route choice"
              value={cfg.route_choice.strategy}
              options={[
                { value: "shortest_time", label: "Shortest walking time (Dijkstra)" },
                { value: "k_shortest_logit", label: "k alternative routes, logit split" },
              ]}
              onChange={(v) => upd({ route_choice: { ...cfg.route_choice, strategy: v } })}
            />
            {cfg.route_choice.strategy === "k_shortest_logit" && (
              <div className="grid2">
                <Num label="k routes" value={cfg.route_choice.k} onChange={(v) => upd({ route_choice: { ...cfg.route_choice, k: v ?? 3 } })} />
                <Num label="Logit θ" unit="1/s" step={0.01} value={cfg.route_choice.logit_theta} onChange={(v) => upd({ route_choice: { ...cfg.route_choice, logit_theta: v ?? 0.05 } })} />
              </div>
            )}
          </Section>
          <Section title="Arrivals & entry control">
            <div className="muted small">Arrival rates by entry gate (Poisson arrivals in agent-based runs).</div>
            <RowList
              items={cfg.demand}
              onChange={(v) => upd({ demand: v })}
              addLabel="arrival flow"
              make={() => ({ gate_id: entryGates[0]?.value ?? "", rate_per_min: 60, start_s: 0, end_s: null })}
              render={(d, u) => (
                <>
                  <Sel value={d.gate_id} options={entryGates} onChange={(v) => u({ gate_id: v })} />
                  <Num label="p/min" value={d.rate_per_min} onChange={(v) => u({ rate_per_min: v ?? 0 })} />
                  <Num label="from s" value={d.start_s} onChange={(v) => u({ start_s: v ?? 0 })} />
                  <Num label="to s" value={d.end_s} onChange={(v) => u({ end_s: v })} />
                </>
              )}
            />
            <div className="muted small">Scheduled reductions / closures of entry points (multiplier 0 = closed).</div>
            <RowList
              items={cfg.entry_restrictions}
              onChange={(v) => upd({ entry_restrictions: v })}
              addLabel="restriction"
              make={() => ({ gate_id: entryGates[0]?.value ?? "", start_s: 300, end_s: null, rate_multiplier: 0 })}
              render={(d, u) => (
                <>
                  <Sel value={d.gate_id} options={entryGates} onChange={(v) => u({ gate_id: v })} />
                  <Num label="×" step={0.1} value={d.rate_multiplier} onChange={(v) => u({ rate_multiplier: v ?? 0 })} />
                  <Num label="from s" value={d.start_s} onChange={(v) => u({ start_s: v ?? 0 })} />
                  <Num label="to s" value={d.end_s} onChange={(v) => u({ end_s: v })} />
                </>
              )}
            />
            <div className="muted small">Initial population (already on site at t = 0).</div>
            <RowList
              items={cfg.initial_population}
              onChange={(v) => upd({ initial_population: v })}
              addLabel="initial population"
              make={() => ({ zone_id: areas[0]?.value ?? "", count: 200, dwell_s: 120 })}
              render={(d, u) => (
                <>
                  <Sel value={d.zone_id} options={areas} onChange={(v) => u({ zone_id: v })} />
                  <Num label="persons" value={d.count} onChange={(v) => u({ count: v ?? 0 })} />
                  <Num label="dwell s" value={d.dwell_s} onChange={(v) => u({ dwell_s: v ?? 0 })} />
                </>
              )}
            />
          </Section>
          <Section title="Destinations & holding areas">
            <div className="muted small">Origin–destination split: share of arrivals per destination and dwell (bathing) time.</div>
            <RowList
              items={cfg.destinations}
              onChange={(v) => upd({ destinations: v })}
              addLabel="destination"
              make={() => ({ target_id: dests[0]?.value ?? "", share: 1, dwell_s: 120 })}
              render={(d, u) => (
                <>
                  <Sel value={d.target_id} options={dests} onChange={(v) => u({ target_id: v })} />
                  <Num label="share" step={0.1} value={d.share} onChange={(v) => u({ share: v ?? 0 })} />
                  <Num label="dwell s" value={d.dwell_s} onChange={(v) => u({ dwell_s: v ?? 0 })} />
                </>
              )}
            />
            <div className="muted small">Holding stops before the destination (shares ≤ 1 in total; the rest go directly).</div>
            <RowList
              items={cfg.holding_stops}
              onChange={(v) => upd({ holding_stops: v })}
              addLabel="holding stop"
              make={() => ({ holding_id: holdings[0]?.value ?? "", share: 0.5, dwell_s: 120 })}
              render={(d, u) => (
                <>
                  <Sel value={d.holding_id} options={holdings} onChange={(v) => u({ holding_id: v })} />
                  <Num label="share" step={0.1} value={d.share} onChange={(v) => u({ share: v ?? 0 })} />
                  <Num label="dwell s" value={d.dwell_s} onChange={(v) => u({ dwell_s: v ?? 0 })} />
                </>
              )}
            />
            {holdings.length > 0 && <div className="muted small">Holding-area capacities for this scenario:</div>}
            {holdings.map((h) => {
              const o = cfg.holding_overrides.find((x) => x.holding_id === h.value);
              const base = features.find((f) => String(f.id) === h.value)?.properties.capacity_persons;
              return (
                <Num
                  key={h.value}
                  label={h.label}
                  unit={`persons (site: ${base ?? "–"})`}
                  value={o?.capacity_persons ?? null}
                  onChange={(v) =>
                    upd({
                      holding_overrides: [
                        ...cfg.holding_overrides.filter((x) => x.holding_id !== h.value),
                        ...(v === null ? [] : [{ holding_id: h.value, capacity_persons: v }]),
                      ],
                    })
                  }
                />
              );
            })}
            <div className="muted small">Exits used after the visit (none selected = nearest open exit):</div>
            <MultiCheck options={exitGates} value={cfg.exit_gate_ids} onChange={(v) => upd({ exit_gate_ids: v })} />
          </Section>
          <Section title="Corridors & gates (circulation plan)" open={false}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Corridor</th>
                  <th>Open</th>
                  <th>Width m</th>
                  <th>Direction</th>
                </tr>
              </thead>
              <tbody>
                {corridors.map((c) => {
                  const o = cOver(c.value) as any;
                  const f = features.find((x) => String(x.id) === c.value)!;
                  return (
                    <tr key={c.value}>
                      <td>{c.label}</td>
                      <td>
                        <input type="checkbox" checked={o.enabled ?? f.properties.enabled !== false} onChange={(e) => setCOver(c.value, { enabled: e.target.checked === (f.properties.enabled !== false) ? null : e.target.checked })} />
                      </td>
                      <td>
                        <input className="narrow" type="number" placeholder={String(f.properties.width_m ?? "")} value={o.width_m ?? ""} onChange={(e) => setCOver(c.value, { width_m: e.target.value === "" ? null : Number(e.target.value) })} />
                      </td>
                      <td>
                        <select value={o.direction ?? ""} onChange={(e) => setCOver(c.value, { direction: e.target.value || null })}>
                          <option value="">site ({f.properties.direction ?? "both"})</option>
                          <option value="both">two-way</option>
                          <option value="forward">one-way →</option>
                          <option value="backward">one-way ←</option>
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Gate</th>
                  <th>Open</th>
                  <th>Role</th>
                </tr>
              </thead>
              <tbody>
                {gates.map((g) => {
                  const o = gOver(g.value) as any;
                  const f = features.find((x) => String(x.id) === g.value)!;
                  return (
                    <tr key={g.value}>
                      <td>{g.label}</td>
                      <td>
                        <input type="checkbox" checked={o.enabled ?? f.properties.enabled !== false} onChange={(e) => setGOver(g.value, { enabled: e.target.checked === (f.properties.enabled !== false) ? null : e.target.checked })} />
                      </td>
                      <td>
                        <select value={o.role ?? ""} onChange={(e) => setGOver(g.value, { role: e.target.value || null })}>
                          <option value="">site ({f.properties.role ?? "both"})</option>
                          <option value="entry">entry</option>
                          <option value="exit">exit</option>
                          <option value="both">both</option>
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Section>
          <Section title="Diversion / route failure" open={!!cfg.diversion}>
            <Check
              label="Activate a diversion during the run"
              checked={!!cfg.diversion}
              onChange={(v) => upd({ diversion: v ? { activation_s: Math.round(cfg.duration_s / 3), destinations: [], close_corridors: [], reroute_existing: true } : null })}
            />
            {cfg.diversion && (
              <>
                <Num label="Activation time" unit="s" value={cfg.diversion.activation_s} onChange={(v) => upd({ diversion: { ...cfg.diversion!, activation_s: v ?? 0 } })} />
                <div className="muted small">New destinations for arrivals after activation (empty = unchanged):</div>
                <RowList
                  items={cfg.diversion.destinations}
                  onChange={(v) => upd({ diversion: { ...cfg.diversion!, destinations: v } })}
                  addLabel="diversion destination"
                  make={() => ({ target_id: dests[0]?.value ?? "", share: 1, dwell_s: 120 })}
                  render={(d, u) => (
                    <>
                      <Sel value={d.target_id} options={dests} onChange={(v) => u({ target_id: v })} />
                      <Num label="share" step={0.1} value={d.share} onChange={(v) => u({ share: v ?? 0 })} />
                      <Num label="dwell s" value={d.dwell_s} onChange={(v) => u({ dwell_s: v ?? 0 })} />
                    </>
                  )}
                />
                <div className="muted small">Corridors closed at activation (route failure):</div>
                <MultiCheck options={corridors} value={cfg.diversion.close_corridors} onChange={(v) => upd({ diversion: { ...cfg.diversion!, close_corridors: v } })} />
                <Check label="Re-route pedestrians already on a closed route" checked={cfg.diversion.reroute_existing} onChange={(v) => upd({ diversion: { ...cfg.diversion!, reroute_existing: v } })} />
              </>
            )}
          </Section>
          <Section title="Emergency evacuation" open={!!cfg.evacuation}>
            <Check
              label="Trigger an evacuation"
              checked={!!cfg.evacuation}
              onChange={(v) =>
                upd({
                  evacuation: v
                    ? { trigger_s: 60, affected_zone_ids: [], exit_gate_ids: [], assembly_point_ids: [], strategy: "capacity_aware", assignments: [], close_corridors: [], capacity_reductions: [], stop_arrivals: true, use_emergency_corridors: true }
                    : null,
                })
              }
            />
            {cfg.evacuation && (() => {
              const ev = cfg.evacuation!;
              const ue = (p: Partial<typeof ev>) => upd({ evacuation: { ...ev, ...p } });
              return (
                <>
                  <Num label="Trigger time" unit="s" value={ev.trigger_s} onChange={(v) => ue({ trigger_s: v ?? 0 })} />
                  <Sel
                    label="Route assignment"
                    value={ev.strategy}
                    options={[
                      { value: "nearest", label: "Nearest available exit (shortest time)" },
                      { value: "capacity_aware", label: "Capacity-aware (CCRP, Lu et al. 2005)" },
                      { value: "assigned", label: "Planner-assigned exits per zone" },
                    ]}
                    onChange={(v) => ue({ strategy: v as any })}
                  />
                  <div className="muted small">Affected zones (none = whole site):</div>
                  <MultiCheck options={zones} value={ev.affected_zone_ids} onChange={(v) => ue({ affected_zone_ids: v })} />
                  <div className="muted small">Available exits (none = all open exits):</div>
                  <MultiCheck options={exitGates} value={ev.exit_gate_ids} onChange={(v) => ue({ exit_gate_ids: v })} />
                  <div className="muted small">Assembly points used as evacuation destinations:</div>
                  <MultiCheck options={assembly} value={ev.assembly_point_ids} onChange={(v) => ue({ assembly_point_ids: v })} />
                  {ev.strategy === "assigned" && (
                    <RowList
                      items={ev.assignments}
                      onChange={(v) => ue({ assignments: v })}
                      addLabel="zone → exit assignment"
                      make={() => ({ zone_id: zones[0]?.value ?? "", exit_gate_id: exitGates[0]?.value ?? "" })}
                      render={(d, u) => (
                        <>
                          <Sel value={d.zone_id} options={zones} onChange={(v) => u({ zone_id: v })} />
                          <Sel value={d.exit_gate_id} options={[...exitGates, ...assembly]} onChange={(v) => u({ exit_gate_id: v })} />
                        </>
                      )}
                    />
                  )}
                  <div className="muted small">Unsafe corridors blocked at the trigger:</div>
                  <MultiCheck options={corridors} value={ev.close_corridors} onChange={(v) => ue({ close_corridors: v })} />
                  <div className="muted small">Capacity reductions (factor 0–1):</div>
                  <RowList
                    items={ev.capacity_reductions}
                    onChange={(v) => ue({ capacity_reductions: v })}
                    addLabel="capacity reduction"
                    make={() => ({ corridor_id: corridors[0]?.value ?? "", capacity_factor: 0.5 })}
                    render={(d, u) => (
                      <>
                        <Sel value={d.corridor_id} options={corridors} onChange={(v) => u({ corridor_id: v })} />
                        <Num label="factor" step={0.1} value={d.capacity_factor ?? null} onChange={(v) => u({ capacity_factor: v })} />
                      </>
                    )}
                  />
                  <Check label="Stop arrivals at the trigger" checked={ev.stop_arrivals} onChange={(v) => ue({ stop_arrivals: v })} />
                  <Check label="Use emergency-only corridors and exits" checked={ev.use_emergency_corridors} onChange={(v) => ue({ use_emergency_corridors: v })} />
                  <div className="alert info small">A shorter simulated clearance time does not by itself make a route safe. Accessibility, counterflows, emergency access and secondary hazards require expert review.</div>
                </>
              );
            })()}
          </Section>
          <Section title="Advanced (JSON)" open={false}>
            <textarea className="code" rows={10} value={json || JSON.stringify(cfg, null, 1)} onChange={(e) => setJson(e.target.value)} />
            <button
              className="secondary small"
              onClick={() => {
                try {
                  setCfg(JSON.parse(json));
                  setJson("");
                } catch {
                  toast("error", "Invalid JSON");
                }
              }}
              disabled={!json}
            >
              Apply JSON
            </button>
          </Section>
          <div className="sticky-actions">
            <button className="secondary" onClick={validate}>
              Validate
            </button>
            <button onClick={() => save(false)} disabled={errs.length > 0}>
              {current ? "Save" : "Save new"}
            </button>
            {current && (
              <button className="secondary" onClick={() => save(true)} disabled={errs.length > 0}>
                Save as copy
              </button>
            )}
            <Sel value={runEngine} options={(meta?.engines ?? []).map((e) => ({ value: e.key, label: `run as ${e.label}` }))} onChange={setRunEngine} allowEmpty="method as configured" />
            <button className="primary" onClick={() => run()} disabled={errs.length > 0}>
              ▶ Save & run
            </button>
            {current && (
              <>
                <button className="secondary" onClick={() => download(`/api/scenarios/${current.id}/layout.geojson`)} title="Proposed circulation layout as GeoJSON">
                  Layout GeoJSON
                </button>
                <button className="danger" onClick={remove}>
                  Delete
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
