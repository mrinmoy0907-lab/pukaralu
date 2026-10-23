import { create } from "zustand";
import { api, ApiError } from "./api";
import { decimation } from "./lib/replay";
import type { Feature, Meta, Run, RunData, Scenario, Site, Terrain, ThresholdProfile } from "./types";

export type ViewMode = "3d" | "2d" | "split";
export type Tab =
  | "overview"
  | "usecases"
  | "workbench"
  | "zones"
  | "scenarios"
  | "runs"
  | "results"
  | "compare"
  | "feeds"
  | "data"
  | "reports"
  | "admin";

export const ROLES = [
  { key: "R1", label: "R1 · Mela administrator" },
  { key: "R3", label: "R3 · Zone in-charge" },
  { key: "R5", label: "R5 · Crowd safety officer" },
  { key: "R7", label: "R7 · Planner / GIS analyst" },
];

export interface AreaCalc {
  fid: string;
  area: {
    gross_m2: number;
    water_excluded_m2: number;
    obstructions_m2: number;
    barricades_m2: number;
    step_surface_gain_m2: number;
    net_walkable_m2: number;
    has_terrain: boolean;
    method: string;
    geometries: Record<string, any>;
  };
  topology: { valid: boolean; issues: string[] };
}

export interface Toast {
  id: number;
  kind: "info" | "error" | "success";
  text: string;
  details?: string[];
}

interface State {
  meta: Meta | null;
  sites: Site[];
  site: Site | null;
  features: Feature[];
  terrain: Terrain | null;
  scenarios: Scenario[];
  runs: Run[];
  profiles: ThresholdProfile[];
  tab: Tab;
  view: ViewMode;
  selected: string | null;
  hiddenGroups: Record<string, boolean>;
  overlays: { agents: boolean; density: boolean; flows: boolean; bottlenecks: boolean; network: boolean; routes: boolean };
  network: any | null;
  routeResult: any | null;
  runData: Record<string, RunData>;
  activeRun: string | null;
  compare: { a: string | null; b: string | null };
  time: number;
  playing: boolean;
  speed: number;
  drawType: string | null;
  editMode: boolean;
  toasts: Toast[];
  busy: Record<string, boolean>;
  basemap: string;
  baseLayers: { imagery: boolean; tiles3d: boolean; models: boolean; terrain: boolean; buildings: boolean };
  role: string;
  snapping: { roads: boolean; river: boolean; preventOverlap: boolean; showTopology: boolean };
  focus: { fid: string; ts: number } | null;
  pendingGeometry: { geometry: any; pk_type: string } | null;
  areaCalc: AreaCalc | null;
  zoneRegisterVersion: number;

  init: () => Promise<void>;
  selectSite: (id: number) => Promise<void>;
  reloadFeatures: () => Promise<void>;
  reloadScenarios: () => Promise<void>;
  reloadRuns: () => Promise<void>;
  loadRun: (id: string) => Promise<RunData | null>;
  setActiveRun: (id: string | null) => Promise<void>;
  set: (p: Partial<State>) => void;
  toast: (kind: Toast["kind"], text: string, details?: string[]) => void;
  fail: (e: unknown, context: string) => void;
}

let toastId = 1;

export const useStore = create<State>((set, get) => ({
  meta: null,
  sites: [],
  site: null,
  features: [],
  terrain: null,
  scenarios: [],
  runs: [],
  profiles: [],
  tab: "overview",
  view: "3d",
  selected: null,
  hiddenGroups: {},
  overlays: { agents: true, density: true, flows: true, bottlenecks: true, network: false, routes: true },
  network: null,
  routeResult: null,
  runData: {},
  activeRun: null,
  compare: { a: null, b: null },
  time: 0,
  playing: false,
  speed: 10,
  drawType: null,
  editMode: false,
  toasts: [],
  busy: {},
  basemap: "osm",
  baseLayers: { imagery: true, tiles3d: true, models: true, terrain: true, buildings: true },
  role: "R7",
  snapping: { roads: true, river: true, preventOverlap: true, showTopology: true },
  focus: null,
  pendingGeometry: null,
  areaCalc: null,
  zoneRegisterVersion: 0,

  set: (p) => set(p as any),

  toast: (kind, text, details) => {
    const id = toastId++;
    set({ toasts: [...get().toasts, { id, kind, text, details }] });
    setTimeout(() => set({ toasts: get().toasts.filter((t) => t.id !== id) }), kind === "error" ? 12000 : 5000);
  },

  fail: (e, context) => {
    if (e instanceof ApiError) get().toast("error", `${context}: ${e.message}`, e.details.slice(1));
    else get().toast("error", `${context}: ${String(e)}`);
  },

  init: async () => {
    try {
      const [meta, sites, profiles] = await Promise.all([api.meta(), api.sites(), api.profiles()]);
      set({ meta, sites, profiles });
      const q = new URLSearchParams(location.search);
      const want = Number(q.get("site")) || sites[0]?.id;
      if (want) await get().selectSite(want);
      const tab = q.get("tab") as Tab | null;
      if (q.get("view")) set({ view: q.get("view") as ViewMode });
      if (q.get("run")) await get().setActiveRun(q.get("run"));
      if (tab) set({ tab });
      if (q.get("t")) set({ time: Number(q.get("t")) });
    } catch (e) {
      get().fail(e, "Loading application data");
    }
  },

  selectSite: async (id) => {
    try {
      const site = await api.site(id);
      set({
        site,
        basemap: site.basemap || "osm",
        features: [],
        terrain: null,
        selected: null,
        activeRun: null,
        compare: { a: null, b: null },
        network: null,
        routeResult: null,
        areaCalc: null,
        pendingGeometry: null,
        time: 0,
      });
      const [fc, terrain] = await Promise.all([api.features(id), site.has_terrain ? api.terrain(id) : Promise.resolve(null)]);
      set({ features: fc.features, terrain });
      await Promise.all([get().reloadScenarios(), get().reloadRuns()]);
    } catch (e) {
      get().fail(e, "Loading site");
    }
  },

  reloadFeatures: async () => {
    const s = get().site;
    if (!s) return;
    const [fc, site] = await Promise.all([api.features(s.id), api.site(s.id)]);
    const terrain = site.has_terrain ? await api.terrain(s.id) : null;
    set({ features: fc.features, site, terrain, network: get().overlays.network ? await api.network(s.id).catch(() => null) : null });
  },

  reloadScenarios: async () => {
    const s = get().site;
    if (s) set({ scenarios: await api.scenarios(s.id) });
  },

  reloadRuns: async () => {
    const s = get().site;
    if (s) set({ runs: await api.runs(s.id) });
  },

  loadRun: async (id) => {
    const cached = get().runData[id];
    if (cached) return cached;
    set({ busy: { ...get().busy, [id]: true } });
    try {
      const run = await api.run(id);
      if (run.status !== "completed") throw new Error(`run is ${run.status}`);
      const [analysis, series] = await Promise.all([api.analysis(id), api.series(id)]);
      const every = decimation(series.times.length, 900);
      const [grid, agents, links] = await Promise.all([
        api.grid(id, every),
        run.engine === "jupedsim" ? api.agents(id, every).then((a) => a.frames) : Promise.resolve(null),
        run.engine === "macro_ctm" ? api.links(id, every) : Promise.resolve(null),
      ]);
      const data: RunData = { run, analysis, series, grid, agents, links };
      set({ runData: { ...get().runData, [id]: data } });
      return data;
    } catch (e) {
      get().fail(e, "Loading run results");
      return null;
    } finally {
      const b = { ...get().busy };
      delete b[id];
      set({ busy: b });
    }
  },

  setActiveRun: async (id) => {
    if (!id) {
      set({ activeRun: null, playing: false });
      return;
    }
    const d = await get().loadRun(id);
    if (d) set({ activeRun: id, time: 0, playing: false, tab: "results" });
  },
}));

export function featureById(features: Feature[], id: string | null): Feature | undefined {
  return id ? features.find((f) => String(f.id) === id) : undefined;
}
