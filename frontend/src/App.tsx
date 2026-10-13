import { lazy, Suspense, useEffect } from "react";
import AboutPanel from "./components/AboutPanel";
import ComparePanel from "./components/ComparePanel";
import ErrorBoundary from "./components/ErrorBoundary";
import DataPanel from "./components/DataPanel";
import Inspector from "./components/Inspector";
import LayersPanel from "./components/LayersPanel";
import ResultsPanel from "./components/ResultsPanel";
import RunsPanel from "./components/RunsPanel";
import ScenarioPanel from "./components/ScenarioPanel";
import Timeline from "./components/Timeline";
import { useStore, type Tab } from "./store";

const CesiumView = lazy(() => import("./components/CesiumView"));
const PlanMap = lazy(() => import("./components/PlanMap"));

const TABS: { key: Tab; label: string }[] = [
  { key: "layers", label: "Layers & tools" },
  { key: "scenarios", label: "Scenarios" },
  { key: "runs", label: "Runs" },
  { key: "results", label: "Results" },
  { key: "compare", label: "Compare" },
  { key: "data", label: "Data" },
  { key: "about", label: "Method & limits" },
];

export default function App() {
  const { init, sites, site, selectSite, tab, view, set, activeRun, compare, toasts, selected, runs } = useStore();
  useEffect(() => {
    init();
  }, [init]);

  const running = runs.filter((r) => r.status === "running" || r.status === "queued").length;
  const split = view === "split" && compare.a && compare.b;
  const timelineRuns = split ? [compare.a!, compare.b!] : activeRun ? [activeRun] : [];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Pushkaralu Crowd Digital Twin <small>open-source 3D GIS · crowd simulation · evacuation planning</small>
        </div>
        <select value={site?.id ?? ""} onChange={(e) => selectSite(Number(e.target.value))} title="site">
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.is_synthetic ? "[SYNTHETIC] " : ""}
              {s.name}
            </option>
          ))}
        </select>
        <div className="seg">
          <button className={view === "3d" ? "active" : ""} onClick={() => set({ view: "3d" })}>
            3D operational
          </button>
          <button className={view === "2d" ? "active" : ""} onClick={() => set({ view: "2d" })}>
            2D planning
          </button>
          <button className={view === "split" ? "active" : ""} disabled={!compare.a || !compare.b} onClick={() => set({ view: "split" })} title="Choose a baseline and an alternative run first">
            Compare 3D
          </button>
        </div>
        {running > 0 && <span className="badge sim">{running} simulation(s) running</span>}
      </header>
      <div className="body">
        <nav className="sidebar">
          <div className="tabs">
            {TABS.map((t) => (
              <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => set({ tab: t.key })}>
                {t.label}
              </button>
            ))}
          </div>
          <div className="panel">
            {tab === "layers" && <LayersPanel />}
            {tab === "scenarios" && <ScenarioPanel />}
            {tab === "runs" && <RunsPanel />}
            {tab === "results" && <ResultsPanel />}
            {tab === "compare" && <ComparePanel />}
            {tab === "data" && <DataPanel />}
            {tab === "about" && <AboutPanel />}
          </div>
        </nav>
        <main className="main">
          <div className="views">
            <ErrorBoundary label="The viewer" key={view}>
            <Suspense fallback={<div className="loading">Loading viewer…</div>}>
              {split ? (
                <div className="split">
                  <CesiumView key="a" runId={compare.a} syncId="a" title="Baseline" />
                  <CesiumView key="b" runId={compare.b} syncId="b" title="Alternative" />
                </div>
              ) : view === "2d" ? (
                <PlanMap runId={activeRun} />
              ) : (
                <CesiumView key="main" runId={activeRun} />
              )}
            </Suspense>
            </ErrorBoundary>
            {selected && !split && <Inspector />}
          </div>
          <Timeline runIds={timelineRuns} />
        </main>
      </div>
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.text}
            {t.details?.map((d, i) => (
              <div key={i} className="small">
                {d}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
