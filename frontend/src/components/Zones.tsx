import { useEffect, useState } from "react";
import { api, type ZoneRow } from "../api";
import { DRAW_DEFAULTS, OWNER_DEPARTMENTS, ZONE_LIKE, ZONE_TYPES } from "../lib/features";
import { fmtNum } from "../lib/replay";
import { featureById, ROLES, useStore } from "../store";
import type { Feature } from "../types";
import Icon from "./Icon";
import Inspector from "./Inspector";
import { Num, Sel, Txt } from "./ui";

const KINDS = [
  { value: "zone", label: "Operational zone" },
  { value: "holding_area", label: "Holding area (simulation)" },
  { value: "ghat", label: "Ghat (simulation)" },
  { value: "bathing_area", label: "Bathing area (simulation)" },
  { value: "plaza", label: "Open walkable area (simulation)" },
  { value: "assembly_point", label: "Assembly point (simulation)" },
  { value: "parking", label: "Parking (simulation)" },
  { value: "queue_lane", label: "Queue lane (simulation)" },
];
const DEFAULT_TYPE: Record<string, string> = { zone: "sector", holding_area: "holding", ghat: "ghat", bathing_area: "bathing", plaza: "approach", assembly_point: "assembly", parking: "parking", queue_lane: "queue" };

export const statusClass = (s: string) => ({ active: "ok", review: "warn", draft: "neutral", retired: "neutral" })[s] ?? "neutral";

/** Calculate area + topology for a zone and show it on the map. */
export async function recalc(fid: string): Promise<boolean> {
  const st = useStore.getState();
  if (!st.site) return false;
  try {
    const r = await api.zoneArea(st.site.id, fid);
    st.set({ areaCalc: { fid, ...r }, zoneRegisterVersion: st.zoneRegisterVersion + 1 });
    await st.reloadFeatures();
    return r.topology.valid;
  } catch (e) {
    st.fail(e, "Area calculation");
    return false;
  }
}

function ZoneFields({ p, setP, isNew }: { p: Record<string, any>; setP: (k: string, v: any) => void; isNew?: boolean }) {
  const features = useStore((s) => s.features);
  const parents = features
    .filter((f) => f.properties.pk_type === "zone" && f.properties.name !== p.name)
    .map((f) => ({ value: String(f.id), label: f.properties.name ?? String(f.id) }));
  return (
    <>
      <Txt label="Zone name *" value={p.name ?? ""} onChange={(v) => setP("name", v)} />
      {isNew && <Sel label="Kind" value={p.pk_type} options={KINDS} onChange={(v) => (setP("pk_type", v), setP("zone_type", DEFAULT_TYPE[v]))} />}
      <Sel label="Parent zone" value={p.parent_id ?? ""} options={parents} onChange={(v) => setP("parent_id", v || null)} allowEmpty="— none —" />
      <Sel label="Type" value={p.zone_type ?? DEFAULT_TYPE[p.pk_type] ?? "other"} options={ZONE_TYPES.map((t) => ({ value: t, label: t }))} onChange={(v) => setP("zone_type", v)} />
      <Sel label="Owner department *" value={p.owner_department ?? ""} options={OWNER_DEPARTMENTS.map((d) => ({ value: d, label: d }))} onChange={(v) => setP("owner_department", v)} allowEmpty="— select —" />
      <div className="grid2">
        <label className="field">
          <span>Valid from</span>
          <input type="datetime-local" value={p.valid_from ?? ""} onChange={(e) => setP("valid_from", e.target.value)} />
        </label>
        <label className="field">
          <span>Valid to</span>
          <input type="datetime-local" value={p.valid_to ?? ""} onChange={(e) => setP("valid_to", e.target.value)} />
        </label>
      </div>
      {p.pk_type === "holding_area" && <Num label="Operational capacity" unit="persons" value={p.capacity_persons ?? null} onChange={(v) => setP("capacity_persons", v)} />}
      <Txt label="Description" value={p.description ?? ""} onChange={(v) => setP("description", v)} area />
    </>
  );
}

export function AreaCalcCard() {
  const { areaCalc, set, selected } = useStore();
  if (!areaCalc || areaCalc.fid !== selected) return null;
  const a = areaCalc.area;
  return (
    <div className="card area-card">
      <div className="card-head">
        <b>Area Calculation</b>
        <button className="icon-btn" onClick={() => set({ areaCalc: null })}>
          <Icon name="close" />
        </button>
      </div>
      <table className="area-tbl">
        <tbody>
          <tr><td>Gross polygon area</td><td>{fmtNum(a.gross_m2, 0)} m²</td></tr>
          <tr className="neg"><td>Water excluded</td><td>− {fmtNum(a.water_excluded_m2, 0)} m²</td></tr>
          <tr className="neg"><td>Obstructions (stalls, buildings)</td><td>− {fmtNum(a.obstructions_m2, 0)} m²</td></tr>
          <tr className="neg"><td>Barricades / walls</td><td>− {fmtNum(a.barricades_m2, 0)} m²</td></tr>
          <tr className="pos"><td title="Extra surface of ghat steps and ramps from the DEM slope">Usable step area (3D)</td><td>{a.has_terrain ? `+ ${fmtNum(a.step_surface_gain_m2, 0)} m²` : "no DTM"}</td></tr>
          <tr className="total"><td>Net walkable area</td><td>{fmtNum(a.net_walkable_m2, 0)} m²</td></tr>
        </tbody>
      </table>
      <button className="primary wide" onClick={() => recalc(areaCalc.fid)}>
        ⟳ Recalculate area
      </button>
      {areaCalc.topology.valid ? (
        <div className="alert ok small">
          <Icon name="check" /> <b>Topology valid</b> – no overlaps or gaps detected
        </div>
      ) : (
        <div className="alert error small">
          <b>Topology issues</b>
          {areaCalc.topology.issues.map((i, k) => (
            <div key={k}>• {i}</div>
          ))}
        </div>
      )}
      <div className="legend-list small">
        <span><i className="lg zone" />Zone boundary</span>
        <span><i className="lg walk" />Walkable area (usable)</span>
        <span><i className="lg obs" />Obstructions (stalls)</span>
        <span><i className="lg bar" />Barricades (excluded)</span>
        <span><i className="lg water" />Water (excluded)</span>
      </div>
    </div>
  );
}

/** Right-hand panel for a selected zone-like polygon: properties + area calculation. */
export function ZonePanel({ f }: { f: Feature }) {
  const { site, set, reloadFeatures, toast, fail } = useStore();
  const [d, setD] = useState<Record<string, any>>({});
  useEffect(() => setD({ ...f.properties }), [f]);
  const setP = (k: string, v: any) => setD((x) => ({ ...x, [k]: v }));
  async function save() {
    if (!site) return;
    try {
      await api.updateFeature(site.id, { ...f, properties: { ...d, pk_type: f.properties.pk_type } });
      await reloadFeatures();
      toast("success", "Zone properties saved.");
    } catch (e) {
      fail(e, "Saving zone");
    }
  }
  return (
    <aside className="side-panel">
      <AreaCalcCard />
      <div className="card">
        <div className="card-head">
          <b>Zone Properties</b>
          <button className="icon-btn" onClick={() => set({ selected: null, areaCalc: null })}>
            <Icon name="close" />
          </button>
        </div>
        <div className="muted small">
          {f.properties.pk_type} · <code>{String(f.id)}</code> · status <span className={`pill ${statusClass(d.status ?? "draft")}`}>{d.status ?? "draft"}</span>
          {f.properties.synthetic && <span className="pill sim inline">SIM</span>}
        </div>
        <ZoneFields p={d} setP={setP} />
        <div className="row">
          <button className="primary" onClick={save}>
            Save
          </button>
          <button className="secondary" onClick={() => recalc(String(f.id))}>
            <Icon name="calc" /> Recalculate area
          </button>
        </div>
      </div>
    </aside>
  );
}

/** Form shown after a new geometry has been drawn. */
export function NewFeatureForm() {
  const { pendingGeometry: pg, site, meta, set, reloadFeatures, toast, fail, snapping } = useStore();
  const [d, setD] = useState<Record<string, any>>({});
  useEffect(() => {
    if (!pg) return;
    const label = meta?.feature_types[pg.pk_type]?.label ?? pg.pk_type;
    setD({ pk_type: pg.pk_type, name: "", zone_type: DEFAULT_TYPE[pg.pk_type], status: "draft", ...(DRAW_DEFAULTS[pg.pk_type] ?? {}), _label: label });
  }, [pg, meta]);
  if (!pg || !site) return null;
  const zoneLike = ZONE_LIKE.has(d.pk_type ?? pg.pk_type);
  const setP = (k: string, v: any) => setD((x) => ({ ...x, [k]: v }));
  async function create() {
    const { _label, ...props } = d;
    if (!props.name?.trim()) return toast("error", "A name is required.");
    if (zoneLike && !props.owner_department) return toast("error", "Select the owner department.");
    try {
      const created = await api.createFeature(site!.id, { type: "Feature", geometry: pg!.geometry, properties: props as any });
      set({ pendingGeometry: null, selected: String(created.id) });
      await reloadFeatures();
      set({ focus: { fid: String(created.id), ts: Date.now() } });
      if (zoneLike) {
        const ok = await recalc(String(created.id));
        if (!ok && snapping.preventOverlap) {
          await api.deleteFeature(site!.id, String(created.id));
          await reloadFeatures();
          set({ selected: null, areaCalc: null });
          toast("error", "Zone not saved: it overlaps another zone (Prevent overlap is on). Redraw or turn the option off.");
          return;
        }
      }
      toast("success", `${props.name} saved as draft.`);
    } catch (e) {
      fail(e, "Saving feature");
    }
  }
  return (
    <aside className="side-panel">
      <div className="card">
        <div className="card-head">
          <b>{zoneLike ? "Zone Properties" : `New ${d._label ?? "feature"}`}</b>
          <button className="icon-btn" onClick={() => set({ pendingGeometry: null })}>
            <Icon name="close" />
          </button>
        </div>
        {zoneLike ? (
          <ZoneFields p={d} setP={setP} isNew />
        ) : (
          <>
            <Txt label="Name *" value={d.name ?? ""} onChange={(v) => setP("name", v)} />
            {pg.pk_type === "obstacle" && (
              <Sel label="Obstruction type" value={d.obstruction_type ?? "stall"} options={["stall", "pandal", "kiosk", "barrier block", "other"].map((x) => ({ value: x, label: x }))} onChange={(v) => setP("obstruction_type", v)} />
            )}
            {pg.pk_type === "gate" && (
              <>
                <Sel label="Role" value={d.role ?? "both"} options={["entry", "exit", "both"].map((x) => ({ value: x, label: x }))} onChange={(v) => setP("role", v)} />
                <Num label="Width" unit="m" value={d.width_m} onChange={(v) => setP("width_m", v)} />
              </>
            )}
            {(pg.pk_type === "corridor" || pg.pk_type === "emergency_corridor") && <Num label="Width" unit="m" value={d.width_m} onChange={(v) => setP("width_m", v)} />}
            {["obstacle", "building", "temple", "wall", "barricade"].includes(pg.pk_type) && <Num label="Height" unit="m" value={d.height_m ?? 2} onChange={(v) => setP("height_m", v)} />}
          </>
        )}
        <div className="row">
          <button className="primary" onClick={create}>
            Save
          </button>
          <button className="secondary" onClick={() => set({ pendingGeometry: null })}>
            Discard
          </button>
        </div>
      </div>
    </aside>
  );
}

/** Right panel switcher: new feature form, zone panel or generic inspector. */
export function RightPanel() {
  const { pendingGeometry, selected, features } = useStore();
  if (pendingGeometry) return <NewFeatureForm />;
  const f = featureById(features, selected);
  if (!f) return null;
  if (ZONE_LIKE.has(f.properties.pk_type) && f.geometry.type.endsWith("Polygon")) return <ZonePanel f={f} />;
  return <Inspector />;
}

export function ZoneRegister() {
  const { site, role, set, zoneRegisterVersion, reloadFeatures, toast, fail, features } = useStore();
  const [rows, setRows] = useState<ZoneRow[]>([]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [appr, setAppr] = useState({ approved_by: "", remarks: "", from: "", to: "" });
  useEffect(() => {
    if (site) api.zones(site.id).then((r) => setRows(r.zones)).catch(() => setRows([]));
  }, [site, zoneRegisterVersion, features]);
  useEffect(() => {
    const r = ROLES.find((x) => x.key === role);
    setAppr((a) => ({ ...a, approved_by: a.approved_by || (r ? r.label.replace(" · ", " – ") : "") }));
  }, [role]);
  const shown = rows.filter((r) => !filter || r.status === filter);
  async function apply(status: string) {
    if (!site || !sel.size) return;
    if (status === "active" && !(role === "R3" || role === "R1"))
      return toast("error", "Activation must be confirmed by the Zone in-charge (R3) or the Mela administrator (R1). Switch role in the top bar.");
    try {
      await api.approveZones(site.id, {
        fids: [...sel],
        status,
        approved_by: status === "active" ? appr.approved_by : undefined,
        approval_remarks: appr.remarks,
        effective_from: appr.from || undefined,
        effective_to: appr.to || undefined,
      });
      toast("success", status === "active" ? `${sel.size} zone(s) confirmed and activated.` : `${sel.size} zone(s) submitted for review.`);
      setSel(new Set());
      set({ zoneRegisterVersion: zoneRegisterVersion + 1 });
      await reloadFeatures();
    } catch (e) {
      fail(e, "Approval");
    }
  }
  return (
    <div className="register">
      <div className="register-head">
        <b>Zone Register</b> <span className="muted">({rows.length} zones)</span>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">all statuses</option>
          {["draft", "review", "active", "retired"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <button className="primary small" onClick={() => set({ drawType: "zone", view: "2d", editMode: false })}>
          + Add Zone
        </button>
      </div>
      <div className="register-body">
        <div className="register-table">
          <table className="tbl">
            <thead>
              <tr>
                <th />
                <th>#</th>
                <th>Zone name</th>
                <th>Type</th>
                <th>Net walkable area</th>
                <th>Owner department</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={r.fid} className={sel.has(r.fid) ? "sel" : ""} onClick={() => set({ selected: r.fid, focus: { fid: r.fid, ts: Date.now() } })}>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={sel.has(r.fid)}
                      onChange={(e) => {
                        const s = new Set(sel);
                        if (e.target.checked) s.add(r.fid);
                        else s.delete(r.fid);
                        setSel(s);
                      }}
                    />
                  </td>
                  <td>{i + 1}</td>
                  <td>
                    {r.name} {r.synthetic && <span className="pill sim inline">SIM</span>}
                  </td>
                  <td>
                    <span className="pill type">{r.zone_type}</span>
                  </td>
                  <td>{fmtNum(r.net_walkable_m2, 0)} m²</td>
                  <td>{r.owner_department ?? <span className="muted">—</span>}</td>
                  <td>
                    <span className={`pill ${statusClass(r.status)}`}>{r.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="approval">
          <b>Approval & Activation</b>
          <label className="field">
            <span>Approved by *</span>
            <input value={appr.approved_by} onChange={(e) => setAppr({ ...appr, approved_by: e.target.value })} placeholder="Zone in-charge (R3)" />
          </label>
          <Txt label="Approval remarks" value={appr.remarks} onChange={(v) => setAppr({ ...appr, remarks: v })} area />
          <div className="grid2">
            <label className="field">
              <span>Effective from</span>
              <input type="date" value={appr.from} onChange={(e) => setAppr({ ...appr, from: e.target.value })} />
            </label>
            <label className="field">
              <span>Effective to</span>
              <input type="date" value={appr.to} onChange={(e) => setAppr({ ...appr, to: e.target.value })} />
            </label>
          </div>
          <div className="row">
            <button className="secondary" disabled={!sel.size} onClick={() => apply("review")}>
              Submit for review
            </button>
            <button className="primary" disabled={!sel.size || !appr.approved_by.trim()} onClick={() => apply("active")}>
              <Icon name="check" /> Confirm & Activate
            </button>
          </div>
          <div className="muted small">{sel.size} selected. Activation checks topology; the record is not a substitute for authenticated sign-off (no login in this prototype).</div>
        </div>
      </div>
    </div>
  );
}

export function ZonesGuide() {
  const { set, hiddenGroups } = useStore();
  const steps = [
    { n: 1, t: "Turn on layers", d: "Zones, walkable areas, obstructions, barricades, gates.", a: () => set({ hiddenGroups: Object.fromEntries(Object.keys(hiddenGroups).map((k) => [k, false])) }) },
    { n: 2, t: "Draw zone boundary", d: "Draw Zone, click the corners, double-click to finish. Snapping helps align to corridors and the river edge.", a: () => set({ drawType: "zone", view: "2d", editMode: false }) },
    { n: 3, t: "Fill zone properties", d: "Name, parent, type, owner department, validity dates." },
    { n: 4, t: "Recalculate walkable area", d: "Gross area minus water, obstructions and barricades, plus DTM step surface." },
    { n: 5, t: "Review and confirm", d: "Zone in-charge selects zones in the register and clicks Confirm & Activate." },
  ];
  return (
    <div>
      <h2 className="page-title">P-01 · Zone and walkable-area setup</h2>
      <p className="muted">Define operational zones and calculate usable crowd area (excluding water, stalls and barricades).</p>
      {steps.map((s) => (
        <div key={s.n} className="step" onClick={s.a}>
          <span className="step-n">{s.n}</span>
          <div>
            <b>{s.t}</b>
            <div className="muted small">{s.d}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
