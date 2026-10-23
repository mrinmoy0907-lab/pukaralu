import { useEffect, useMemo, useRef, useState } from "react";
import { basemapFor, BASEMAPS } from "../lib/basemaps";
import { LAYER_GROUPS } from "../lib/colors";
import { ROLES, useStore, type Tab } from "../store";
import Icon from "./Icon";
import { Check } from "./ui";

export const NAV: { key: Tab; label: string; icon: string; group?: string }[] = [
  { key: "overview", label: "Overview", icon: "overview" },
  { key: "usecases", label: "Use Cases", icon: "usecases" },
  { key: "workbench", label: "Planning Workbench", icon: "workbench", group: "Planning" },
  { key: "zones", label: "Zones", icon: "zones" },
  { key: "scenarios", label: "Scenarios", icon: "scenarios" },
  { key: "runs", label: "Simulation Runs", icon: "runs", group: "Simulation" },
  { key: "results", label: "Results", icon: "results" },
  { key: "compare", label: "Compare", icon: "compare" },
  { key: "feeds", label: "Feeds & Sensors", icon: "feeds", group: "Data" },
  { key: "data", label: "Data Sources", icon: "data" },
  { key: "reports", label: "Reports", icon: "reports" },
  { key: "admin", label: "Administration", icon: "admin" },
];

export function NavRail({ collapsed }: { collapsed: boolean }) {
  const { tab, set, runs } = useStore();
  const running = runs.filter((r) => r.status === "running" || r.status === "queued").length;
  return (
    <nav className={`navrail ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <span className="brand-logo">
          <Icon name="temple" size={22} />
        </span>
        {!collapsed && <span className="brand-name">Pushkaralu Twin</span>}
      </div>
      {NAV.map((n) => (
        <div key={n.key}>
          {n.group && !collapsed && <div className="nav-group">{n.group}</div>}
          <button className={`nav-item ${tab === n.key ? "active" : ""}`} onClick={() => set({ tab: n.key })} title={n.label}>
            <Icon name={n.icon} />
            {!collapsed && <span>{n.label}</span>}
            {n.key === "runs" && running > 0 && <span className="nav-badge">{running}</span>}
          </button>
        </div>
      ))}
    </nav>
  );
}

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="clock-chip">
      {now.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" })}{" "}
      {now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
    </span>
  );
}

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const { sites, site, selectSite, basemap, role, set } = useStore();
  const bm = basemapFor(basemap);
  return (
    <header className="topbar">
      <button className="icon-btn" onClick={onMenu} aria-label="menu">
        <Icon name="menu" />
      </button>
      <label className="site-select">
        <Icon name="pin" />
        <select value={site?.id ?? ""} onChange={(e) => selectSite(Number(e.target.value))} title="Site / area of interest">
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <div className="topbar-right">
        <Clock />
        {site?.is_synthetic ? (
          <span className="pill sim" title="Simulation features are synthetic (not surveyed)">
            SIM <em>Simulated data</em>
          </span>
        ) : (
          <span className="pill real">Imported data</span>
        )}
        {bm.real && <span className="pill map">Real map base</span>}
        <span className="pill neutral" title="No live sensor feeds are connected in this release">
          Feeds: manual only
        </span>
        <select className="role-select" value={role} onChange={(e) => set({ role: e.target.value })} title="Acting role (demo – no login)">
          {ROLES.map((r) => (
            <option key={r.key} value={r.key}>
              {r.label}
            </option>
          ))}
        </select>
      </div>
    </header>
  );
}

const TOOLS: { key: string; label: string; icon: string; pk?: string }[] = [
  { key: "select", label: "Select", icon: "select" },
  { key: "zone", label: "Draw Zone", icon: "polygon", pk: "zone" },
  { key: "obstacle", label: "Draw Obstruction", icon: "obstruction", pk: "obstacle" },
  { key: "gate", label: "Add Gate", icon: "gate", pk: "gate" },
  { key: "edit", label: "Edit", icon: "edit" },
  { key: "delete", label: "Delete", icon: "trash" },
];

export function MapToolbar({ onDelete }: { onDelete: () => void }) {
  const { view, set, features, drawType, editMode, selected, meta, site } = useStore();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<"" | "layers" | "more" | "search">("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen("");
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const hits = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    return features.filter((f) => `${f.properties.name ?? ""} ${f.id} ${f.properties.pk_type}`.toLowerCase().includes(s)).slice(0, 12);
  }, [q, features]);
  const activeTool = drawType ? TOOLS.find((t) => t.pk === drawType)?.key ?? "more" : editMode ? "edit" : "select";

  function tool(k: string) {
    if (k === "select") set({ drawType: null, editMode: false });
    else if (k === "edit") set({ drawType: null, editMode: !editMode, view: "2d" });
    else if (k === "delete") onDelete();
    else {
      const t = TOOLS.find((x) => x.key === k);
      set({ drawType: t?.pk ?? null, editMode: false, view: "2d", pendingGeometry: null });
    }
  }

  return (
    <div className="map-toolbar" ref={ref}>
      <div className="seg">
        <button className={view === "2d" ? "active" : ""} onClick={() => set({ view: "2d" })}>
          2D
        </button>
        <button className={view === "3d" ? "active" : ""} onClick={() => set({ view: "3d", drawType: null, editMode: false })}>
          3D
        </button>
      </div>
      <div className="search">
        <Icon name="search" />
        <input placeholder="Search locations, zones…" value={q} onChange={(e) => (setQ(e.target.value), setOpen("search"))} onFocus={() => setOpen("search")} />
        {open === "search" && hits.length > 0 && (
          <div className="dropdown search-results">
            {hits.map((f) => (
              <button
                key={String(f.id)}
                onClick={() => {
                  set({ selected: String(f.id), focus: { fid: String(f.id), ts: Date.now() } });
                  setOpen("");
                  setQ(f.properties.name ?? String(f.id));
                }}
              >
                <b>{f.properties.name ?? f.id}</b> <span className="muted small">{meta?.feature_types[f.properties.pk_type]?.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="tools">
        {TOOLS.map((t) => (
          <button
            key={t.key}
            className={`tool ${activeTool === t.key ? "active" : ""}`}
            onClick={() => tool(t.key)}
            disabled={(t.key === "delete" || t.key === "edit") && !selected}
            title={t.label}
          >
            <Icon name={t.icon} />
            <span>{t.label}</span>
          </button>
        ))}
        <div className="dd-wrap">
          <button className={`tool ${activeTool === "more" ? "active" : ""}`} onClick={() => setOpen(open === "more" ? "" : "more")} title="Other feature types">
            <Icon name="more" />
            <span>More</span>
          </button>
          {open === "more" && meta && (
            <div className="dropdown more-menu">
              {Object.entries(meta.feature_types).map(([k, ft]) => (
                <button key={k} onClick={() => (set({ drawType: k, editMode: false, view: "2d", pendingGeometry: null }), setOpen(""))}>
                  {ft.label} <span className="muted small">{ft.geom}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="dd-wrap right">
        <button className="tool" onClick={() => setOpen(open === "layers" ? "" : "layers")}>
          <Icon name="layers" />
          <span>Layers</span>
        </button>
        {open === "layers" && <LayersMenu onClose={() => setOpen("")} />}
      </div>
      <button className="tool" title="Zoom to site" onClick={() => site && features[0] && set({ focus: { fid: String(features.find((f) => f.properties.pk_type === "plaza" || f.properties.pk_type === "ghat")?.id ?? features[0].id), ts: Date.now() } })}>
        <Icon name="locate" />
      </button>
    </div>
  );
}

export function LayersMenu({ onClose }: { onClose: () => void }) {
  const { hiddenGroups, set, basemap, baseLayers, overlays, site, terrain } = useStore();
  const a = site?.assets ?? {};
  return (
    <div className="dropdown layers-menu">
      <div className="dd-head">
        <b>Map Layers</b>
        <button className="icon-btn" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
      <div className="dd-sub">Operational layers</div>
      {LAYER_GROUPS.map((g) => (
        <Check key={g.key} label={g.label} checked={!hiddenGroups[g.key]} onChange={(v) => set({ hiddenGroups: { ...hiddenGroups, [g.key]: !v } })} />
      ))}
      <div className="dd-sub">Simulation overlays</div>
      <Check label="Animated agents" checked={overlays.agents} onChange={(v) => set({ overlays: { ...overlays, agents: v } })} />
      <Check label="Density heatmap" checked={overlays.density} onChange={(v) => set({ overlays: { ...overlays, density: v } })} />
      <Check label="Corridor flows (macroscopic)" checked={overlays.flows} onChange={(v) => set({ overlays: { ...overlays, flows: v } })} />
      <Check label="Bottleneck markers" checked={overlays.bottlenecks} onChange={(v) => set({ overlays: { ...overlays, bottlenecks: v } })} />
      <div className="dd-sub">Base layers</div>
      {BASEMAPS.map((b) => (
        <label key={b.key} className="check">
          <input type="radio" name="basemap" checked={basemap === b.key} onChange={() => set({ basemap: b.key })} /> {b.label}
        </label>
      ))}
      <Check label={`Ortho imagery (${a.imagery?.length ?? 0})`} checked={baseLayers.imagery} onChange={(v) => set({ baseLayers: { ...baseLayers, imagery: v } })} />
      <Check label="3D buildings (extruded footprints)" checked={baseLayers.buildings} onChange={(v) => set({ baseLayers: { ...baseLayers, buildings: v } })} />
      <Check label={`3D Tiles (${(a.tilesets?.length ?? 0) + (site?.tileset_url ? 1 : 0)})`} checked={baseLayers.tiles3d} onChange={(v) => set({ baseLayers: { ...baseLayers, tiles3d: v } })} />
      <Check label={`3D models (${a.models?.length ?? 0})`} checked={baseLayers.models} onChange={(v) => set({ baseLayers: { ...baseLayers, models: v } })} />
      <Check
        label={`LiDAR / DTM terrain ${a.terrain_url ? "(quantized mesh)" : terrain ? "(DEM)" : "(none loaded)"}`}
        checked={baseLayers.terrain}
        onChange={(v) => set({ baseLayers: { ...baseLayers, terrain: v } })}
      />
    </div>
  );
}

export function SnappingCard() {
  const { snapping, set, drawType, editMode } = useStore();
  if (!drawType && !editMode) return null;
  const s = (k: keyof typeof snapping) => (v: boolean) => set({ snapping: { ...snapping, [k]: v } });
  return (
    <div className="float-card snapping">
      <b>Snapping & Validation</b>
      <Toggle label="Snap to corridors / roads" on={snapping.roads} onChange={s("roads")} />
      <Toggle label="Snap to river edge" on={snapping.river} onChange={s("river")} />
      <Toggle label="Prevent overlap" on={snapping.preventOverlap} onChange={s("preventOverlap")} />
      <Toggle label="Show topology errors" on={snapping.showTopology} onChange={s("showTopology")} />
    </div>
  );
}

function Toggle({ label, on, onChange }: { label: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="toggle">
      <span>{label}</span>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} />
      <i />
    </label>
  );
}
