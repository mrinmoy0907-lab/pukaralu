import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "./api";
import AboutPanel from "./components/AboutPanel";
import ComparePanel from "./components/ComparePanel";
import DataPanel from "./components/DataPanel";
import ErrorBoundary from "./components/ErrorBoundary";
import Icon from "./components/Icon";
import LayersPanel from "./components/LayersPanel";
import { FeedsPage, OverviewPage, ReportsPage, UseCasesPage } from "./components/Pages";
import ResultsPanel from "./components/ResultsPanel";
import RunsPanel from "./components/RunsPanel";
import ScenarioPanel from "./components/ScenarioPanel";
import { MapToolbar, NavRail, SnappingCard, TopBar } from "./components/Shell";
import Timeline from "./components/Timeline";
import { RightPanel, ZoneRegister, ZonesGuide } from "./components/Zones";
import { featureById, useStore } from "./store";

const CesiumView = lazy(() => import("./components/CesiumView"));
const PlanMap = lazy(() => import("./components/PlanMap"));

function Page() {
  const tab = useStore((s) => s.tab);
  switch (tab) {
    case "overview":
      return <OverviewPage />;
    case "usecases":
      return <UseCasesPage />;
    case "workbench":
      return <LayersPanel />;
    case "zones":
      return <ZonesGuide />;
    case "scenarios":
      return <ScenarioPanel />;
    case "runs":
      return <RunsPanel />;
    case "results":
      return <ResultsPanel />;
    case "compare":
      return <ComparePanel />;
    case "feeds":
      return <FeedsPage />;
    case "data":
      return <DataPanel />;
    case "reports":
      return <ReportsPage />;
    case "admin":
      return <AboutPanel />;
  }
}

export default function App() {
  const { init, tab, view, activeRun, compare, toasts, selected, features, site, set, reloadFeatures, fail } = useStore();
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(true);
  useEffect(() => {
    init();
  }, [init]);

  const split = view === "split" && compare.a && compare.b;
  const timelineRuns = split ? [compare.a!, compare.b!] : activeRun ? [activeRun] : [];

  async function onDelete() {
    const f = featureById(features, selected);
    if (!f || !site || !confirm(`Delete ${f.properties.name ?? f.id}?`)) return;
    try {
      await api.deleteFeature(site.id, String(f.id));
      set({ selected: null, areaCalc: null });
      await reloadFeatures();
    } catch (e) {
      fail(e, "Deleting feature");
    }
  }

  return (
    <div className="app">
      <NavRail collapsed={navCollapsed} />
      <div className="main-col">
        <TopBar onMenu={() => setNavCollapsed(!navCollapsed)} />
        <div className="workspace">
          {sheetOpen && (
            <section className="sheet">
              <Page />
            </section>
          )}
          <button className="sheet-toggle" onClick={() => setSheetOpen(!sheetOpen)} title={sheetOpen ? "Hide panel" : "Show panel"}>
            {sheetOpen ? "‹" : "›"}
          </button>
          <div className="map-area">
            {!split && <MapToolbar onDelete={onDelete} />}
            <SnappingCard />
            <div className="views">
              <ErrorBoundary label="The map" key={view}>
                <Suspense fallback={<div className="loading">Loading map…</div>}>
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
              {!split && <RightPanel />}
            </div>
            {tab === "zones" && !split && <ZoneRegister />}
            {split && (
              <button className="exit-split" onClick={() => set({ view: "3d" })}>
                <Icon name="close" /> Exit comparison view
              </button>
            )}
            <Timeline runIds={timelineRuns} />
          </div>
        </div>
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
