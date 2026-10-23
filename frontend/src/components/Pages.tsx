import { useEffect, useState } from "react";
import { api, download, type ZoneRow } from "../api";
import { fmtNum, fmtTime } from "../lib/replay";
import { USE_CASES } from "../lib/usecases";
import { ROLES, useStore } from "../store";
import type { Observation } from "../types";
import Icon from "./Icon";
import { Section } from "./ui";

export function OverviewPage() {
  const { site, features, scenarios, runs, set, setActiveRun } = useStore();
  const [zones, setZones] = useState<ZoneRow[]>([]);
  useEffect(() => {
    if (site) api.zones(site.id).then((r) => setZones(r.zones)).catch(() => setZones([]));
  }, [site, features]);
  if (!site) return null;
  const count = (t: string) => features.filter((f) => f.properties.pk_type === t).length;
  const gates = features.filter((f) => f.properties.pk_type === "gate");
  const net = zones.reduce((a, z) => a + z.net_walkable_m2, 0);
  const holdCap = features.filter((f) => f.properties.pk_type === "holding_area").reduce((a, f) => a + Number(f.properties.capacity_persons ?? 0), 0);
  const done = runs.filter((r) => r.status === "completed");
  const last = done[0];
  return (
    <div>
      <h2 className="page-title">{site.name}</h2>
      <p className="muted small">{site.description}</p>
      <div className="kpi-cards">
        <div className="kcard"><span>Zones</span><b>{zones.length}</b><em>{zones.filter((z) => z.status === "active").length} active</em></div>
        <div className="kcard"><span>Net walkable area</span><b>{fmtNum(net / 10000, 2)} ha</b><em>all zones</em></div>
        <div className="kcard"><span>Gates</span><b>{gates.length}</b><em>{gates.filter((g) => g.properties.role !== "exit").length} entry · {gates.filter((g) => g.properties.role !== "entry").length} exit</em></div>
        <div className="kcard"><span>Holding capacity</span><b>{fmtNum(holdCap, 0)}</b><em>{count("holding_area")} areas (configured)</em></div>
        <div className="kcard"><span>Corridors</span><b>{count("corridor") + count("emergency_corridor")}</b><em>{count("emergency_corridor")} emergency</em></div>
        <div className="kcard"><span>Scenarios / runs</span><b>{scenarios.length} / {done.length}</b><em>completed runs</em></div>
      </div>
      {last?.summary && (
        <Section title={`Latest result: ${last.name}`}>
          <div className="kpi-cards small3">
            <div className="kcard"><span>Peak in site</span><b>{fmtNum(last.summary.peak_population_in_site, 0)}</b></div>
            <div className="kcard"><span>Max density</span><b className={last.summary.max_density_ppm2 > last.summary.density_limit_ppm2 ? "bad" : "good"}>{fmtNum(last.summary.max_density_ppm2, 2)} p/m²</b></div>
            <div className="kcard"><span>Bottlenecks</span><b className={last.summary.n_unresolved_bottlenecks ? "bad" : "good"}>{last.summary.n_bottlenecks}</b></div>
          </div>
          <div className="muted small">{last.method} · simulated estimate{last.summary.clearance_time_s !== null && ` · clearance ${fmtTime(last.summary.clearance_time_s)}`}</div>
          <button className="secondary small" onClick={() => setActiveRun(last.id)}>Open results</button>
        </Section>
      )}
      <Section title="Start a task">
        {USE_CASES.slice(0, 6).map((u) => (
          <div key={u.id} className="step" onClick={() => set({ tab: u.tab })}>
            <span className="step-n small">{u.id.slice(2)}</span>
            <div>
              <b>{u.title}</b>
              <div className="muted small">{u.goal}</div>
            </div>
          </div>
        ))}
        <button className="secondary small" onClick={() => set({ tab: "usecases" })}>All use cases →</button>
      </Section>
    </div>
  );
}

export function UseCasesPage() {
  const { set } = useStore();
  const roleLabel = (k: string) => ROLES.find((r) => r.key === k)?.label ?? k;
  return (
    <div>
      <h2 className="page-title">Use cases</h2>
      <p className="muted small">
        Each use case opens the screen where it is carried out. Step-by-step journeys with screenshots:{" "}
        <a href="/api/docs/user-journeys.pdf" target="_blank" rel="noreferrer">User journeys (PDF)</a>.
      </p>
      {USE_CASES.map((u) => (
        <div key={u.id} className="uc">
          <div className="uc-head">
            <span className="uc-id">{u.id}</span>
            <b>{u.title}</b>
            <button className="primary small" onClick={() => set({ tab: u.tab })}>Open</button>
          </div>
          <div className="small">{u.goal}</div>
          <div className="muted small">Roles: {u.roles.map(roleLabel).join(", ")}</div>
          <ol className="uc-steps">
            {u.steps.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}

export function ReportsPage() {
  const { runs, scenarios, compare, setActiveRun } = useStore();
  const done = runs.filter((r) => r.status === "completed");
  return (
    <div>
      <h2 className="page-title">Reports & exports</h2>
      <p className="muted small">All outputs are simulated estimates. Emergency procedures need approval by authorised officials.</p>
      <Section title={`Simulation reports (${done.length})`}>
        {done.map((r) => (
          <div key={r.id} className="list-item col">
            <div className="row spread">
              <b>{r.name}</b>
              <span className={`pill ${r.review?.status === "approved" ? "ok" : r.review?.status === "reviewed" ? "warn" : "neutral"}`}>{r.review?.status ?? "draft"}</span>
            </div>
            <div className="muted small">{r.method} · {r.created_at?.slice(0, 16).replace("T", " ")}</div>
            <div className="row wrap">
              <button className="small" onClick={() => download(`/api/runs/${r.id}/report.pdf`)}>PDF report</button>
              <button className="small secondary" onClick={() => download(`/api/runs/${r.id}/export.zip`)}>CSV</button>
              <button className="small secondary" onClick={() => download(`/api/runs/${r.id}/density.geojson`)}>Density GeoJSON</button>
              <button className="small secondary" onClick={() => download(`/api/runs/${r.id}/bottlenecks.geojson`)}>Bottlenecks</button>
              <button className="small secondary" onClick={() => setActiveRun(r.id)}>Review…</button>
            </div>
          </div>
        ))}
        {!done.length && <div className="muted small">No completed runs yet.</div>}
      </Section>
      {compare.a && compare.b && (
        <Section title="Comparison report">
          <div className="row">
            <button onClick={() => download(`/api/compare/report.pdf?a=${compare.a}&b=${compare.b}`)}>Comparison PDF</button>
            <button className="secondary" onClick={() => download(`/api/compare/export.csv?a=${compare.a}&b=${compare.b}`)}>CSV</button>
          </div>
        </Section>
      )}
      <Section title="Circulation layouts (GeoJSON)">
        {scenarios.map((s) => (
          <div key={s.id} className="row spread small">
            <span>{s.name}</span>
            <button className="small secondary" onClick={() => download(`/api/scenarios/${s.id}/layout.geojson`)}>Layout</button>
          </div>
        ))}
      </Section>
      <Section title="Documentation">
        <button className="secondary" onClick={() => window.open("/api/docs/user-journeys.pdf", "_blank")}>
          <Icon name="reports" /> User journeys for all use cases (PDF)
        </button>
      </Section>
    </div>
  );
}

export function FeedsPage() {
  const { site, meta, toast, fail } = useStore();
  const [obs, setObs] = useState<Observation[]>([]);
  const [file, setFile] = useState<File | null>(null);
  useEffect(() => {
    if (site) api.observations(site.id).then(setObs).catch(() => setObs([]));
  }, [site]);
  if (!site) return null;
  async function upload() {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      await api.uploadObservations(site!.id, fd);
      setObs(await api.observations(site!.id));
      toast("success", "Counts uploaded.");
    } catch (e) {
      fail(e, "Upload");
    }
  }
  return (
    <div>
      <h2 className="page-title">Feeds & sensors</h2>
      <div className="alert warn small">
        {meta?.live_sensor_integration ? "Live feeds connected." : "No live CCTV, counter or IoT feed is connected in this release."} Counts can be entered manually or uploaded; they
        are always shown as <b>observed</b> or <b>forecast</b>, separately from simulated values.
      </div>
      <Section title="Upload counts (CSV)">
        <div className="muted small">Columns: zone_fid, count, kind (observed|forecast), t_offset_s, observed_at, source (manual|cctv|counter|sensor), notes</div>
        <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button onClick={upload} disabled={!file}>Upload</button>
      </Section>
      <Section title={`Records (${obs.length})`}>
        <table className="tbl">
          <thead>
            <tr><th>Zone</th><th>Count</th><th>Kind</th><th>Time</th><th>Source</th></tr>
          </thead>
          <tbody>
            {obs.slice(0, 100).map((o) => (
              <tr key={o.id}>
                <td>{o.zone_fid}</td>
                <td>{o.count}</td>
                <td><span className={`pill ${o.kind === "observed" ? "ok" : "warn"}`}>{o.kind}</span></td>
                <td>{o.t_offset_s !== null ? `${o.t_offset_s}s` : o.observed_at}</td>
                <td>{o.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

export function DataFolderSection() {
  const { site, selectSite, toast, fail, set } = useStore();
  const [rep, setRep] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.ingestStatus().then(setRep).catch(() => null);
  }, []);
  async function scan() {
    setBusy(true);
    try {
      const r = await api.ingest();
      setRep(r);
      const n = r.sites.reduce((a: number, s: any) => a + s.imported.length, 0);
      toast("success", `Data folder scanned: ${n} new or changed item(s).`);
      set({ sites: await api.sites() });
      if (site) await selectSite(site.id);
    } catch (e) {
      fail(e, "Scanning data folder");
    } finally {
      setBusy(false);
    }
  }
  const mine = rep?.sites?.find((s: any) => s.site_id === site?.id);
  const a = site?.assets ?? {};
  return (
    <Section title="Data folder (drop surveyed data here)">
      <div className="small">
        Folder: <code>{rep?.root ?? "data/sites"}</code>
        {a.source_folder && (
          <>
            {" "}· this site: <code>{a.source_folder}</code>
          </>
        )}
      </div>
      <pre className="tree small">{`<site folder>/
  site.json      name, origin, basemap, licences, model placement
  vector/        GeoJSON, GeoPackage, Shapefile, KML
  dem/           DTM / DEM / DSM GeoTIFF
  terrain/       quantized-mesh tiles (layer.json)
  tiles3d/<n>/   3D Tiles (tileset.json)
  models/        glTF / GLB models
  imagery/       orthophoto GeoTIFF`}</pre>
      <button className="primary" onClick={scan} disabled={busy}>
        {busy ? "Scanning…" : "⟳ Scan data folder"}
      </button>
      <div className="small">
        Loaded: terrain {site?.has_terrain ? "DEM" : "–"}
        {a.terrain_url ? " + quantized mesh" : ""} · 3D Tiles {a.tilesets?.length ?? 0} · models {a.models?.length ?? 0} · ortho {a.imagery?.length ?? 0}
      </div>
      {mine && (
        <div className="small">
          Last scan {rep.ran_at?.slice(0, 19).replace("T", " ")}: {mine.imported.length} imported, {mine.skipped.length} unchanged
          {mine.errors.map((e: string, i: number) => (
            <div key={i} className="warn-text">⚠ {e}</div>
          ))}
        </div>
      )}
    </Section>
  );
}
