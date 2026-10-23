import type {
  AgentFrame,
  Analysis,
  Feature,
  FeatureCollection,
  GridDoc,
  LinksDoc,
  Meta,
  Observation,
  Run,
  Scenario,
  ScenarioConfig,
  Series,
  Site,
  Terrain,
  ThresholdProfile,
} from "./types";

export interface ZoneRow {
  fid: string;
  name: string;
  pk_type: string;
  zone_type: string;
  parent_id: string | null;
  owner_department: string | null;
  status: string;
  valid_from: string | null;
  valid_to: string | null;
  approved_by: string | null;
  effective_from: string | null;
  effective_to: string | null;
  net_walkable_m2: number;
  gross_m2: number;
  capacity_persons: number | null;
  synthetic: boolean;
}

export class ApiError extends Error {
  status: number;
  details: string[];
  constructor(status: number, message: string, details: string[] = []) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

/** Turn FastAPI error payloads ({detail: string | {errors: []} | [{loc,msg}]}) into readable text. */
export function errorDetails(body: any): string[] {
  const d = body?.detail ?? body;
  if (!d) return [];
  if (typeof d === "string") return [d];
  if (Array.isArray(d)) return d.map((e) => (e.loc ? `${e.loc.slice(1).join(".")}: ${e.msg}` : String(e.msg ?? e)));
  if (Array.isArray(d.errors)) return d.errors.map(String);
  return [JSON.stringify(d)];
}

async function req<T>(method: string, url: string, body?: unknown, raw = false): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    throw new ApiError(0, "Cannot reach the API server. Is the backend running on port 8000?");
  }
  if (!res.ok) {
    let payload: any = null;
    try {
      payload = await res.json();
    } catch {
      /* not JSON */
    }
    const details = errorDetails(payload);
    throw new ApiError(res.status, details[0] ?? `${res.status} ${res.statusText}`, details);
  }
  if (res.status === 204) return undefined as T;
  return (raw ? res.blob() : res.json()) as Promise<T>;
}

export const api = {
  meta: () => req<Meta>("GET", "/api/meta"),
  sites: () => req<Site[]>("GET", "/api/sites"),
  site: (id: number) => req<Site>("GET", `/api/sites/${id}`),
  createSite: (b: { name: string; description: string; origin_lon: number; origin_lat: number; is_synthetic: boolean; basemap: string }) =>
    req<Site>("POST", "/api/sites", b),
  patchSite: (id: number, b: Partial<Site>) => req<Site>("PATCH", `/api/sites/${id}`, b),
  features: (id: number) => req<FeatureCollection>("GET", `/api/sites/${id}/features`),
  createFeature: (id: number, f: Omit<Feature, "id"> & { id?: string }) => req<Feature>("POST", `/api/sites/${id}/features`, f),
  updateFeature: (id: number, f: Feature) => req<Feature>("PUT", `/api/sites/${id}/features/${encodeURIComponent(f.id)}`, f),
  deleteFeature: (id: number, fid: string) => req<void>("DELETE", `/api/sites/${id}/features/${encodeURIComponent(fid)}`),
  terrain: (id: number) => req<Terrain>("GET", `/api/sites/${id}/terrain`),
  network: (id: number) => req<any>("GET", `/api/sites/${id}/network`),
  routes: (id: number, b: { from_id: string; to_id: string; k: number; closed_corridors: string[]; allow_emergency: boolean }) =>
    req<any>("POST", `/api/sites/${id}/routes`, b),
  importFile: (id: number, fd: FormData) => req<any>("POST", `/api/sites/${id}/import`, fd),
  scenarios: (siteId: number) => req<Scenario[]>("GET", `/api/sites/${siteId}/scenarios`),
  presets: (siteId: number) => req<{ key: string; label: string; available: boolean; config: ScenarioConfig | null }[]>("GET", `/api/sites/${siteId}/presets`),
  createScenario: (siteId: number, b: { name: string; description: string; config: ScenarioConfig; preset?: string | null }) =>
    req<Scenario>("POST", `/api/sites/${siteId}/scenarios`, b),
  updateScenario: (id: number, b: { name: string; description: string; config: ScenarioConfig }) => req<Scenario>("PUT", `/api/scenarios/${id}`, b),
  deleteScenario: (id: number) => req<void>("DELETE", `/api/scenarios/${id}`),
  validateScenario: (siteId: number, cfg: ScenarioConfig) => req<any>("POST", `/api/sites/${siteId}/scenarios/validate`, cfg),
  startRun: (scenarioId: number, b: { seed?: number; engine?: string }) => req<Run>("POST", `/api/scenarios/${scenarioId}/runs`, b),
  runs: (siteId: number) => req<Run[]>("GET", `/api/runs?site_id=${siteId}`),
  run: (id: string) => req<Run>("GET", `/api/runs/${id}`),
  cancelRun: (id: string) => req<void>("POST", `/api/runs/${id}/cancel`),
  rerun: (id: string) => req<Run>("POST", `/api/runs/${id}/rerun`),
  deleteRun: (id: string) => req<void>("DELETE", `/api/runs/${id}`),
  review: (id: string, b: Record<string, string>) => req<Run>("PATCH", `/api/runs/${id}/review`, b),
  analysis: (id: string) => req<Analysis>("GET", `/api/runs/${id}/analysis`),
  series: (id: string) => req<Series>("GET", `/api/runs/${id}/series`),
  grid: (id: string, every = 1) => req<GridDoc>("GET", `/api/runs/${id}/grid?every=${every}`),
  agents: (id: string, every = 1) => req<{ frames: AgentFrame[] }>("GET", `/api/runs/${id}/agents?every=${every}`),
  links: (id: string, every = 1) => req<LinksDoc>("GET", `/api/runs/${id}/links?every=${every}`),
  compare: (a: string, b: string) => req<any>("GET", `/api/compare?a=${a}&b=${b}`),
  observations: (siteId: number) => req<Observation[]>("GET", `/api/sites/${siteId}/observations`),
  uploadObservations: (siteId: number, fd: FormData) => req<Observation[]>("POST", `/api/sites/${siteId}/observations/csv`, fd),
  addObservations: (siteId: number, items: Partial<Observation>[]) => req<Observation[]>("POST", `/api/sites/${siteId}/observations`, items),
  ingest: () => req<any>("POST", "/api/ingest"),
  ingestStatus: () => req<any>("GET", "/api/ingest"),
  zones: (siteId: number) => req<{ zones: ZoneRow[]; zone_types: string[] }>("GET", `/api/sites/${siteId}/zones`),
  zoneArea: (siteId: number, fid: string) => req<any>("POST", `/api/sites/${siteId}/zones/${encodeURIComponent(fid)}/area`),
  approveZones: (siteId: number, b: { fids: string[]; status: string; approved_by?: string; approval_remarks?: string; effective_from?: string; effective_to?: string }) =>
    req<any>("POST", `/api/sites/${siteId}/zones/approve`, b),
  profiles: () => req<ThresholdProfile[]>("GET", "/api/threshold-profiles"),
  updateProfile: (id: number, b: Omit<ThresholdProfile, "id">) => req<ThresholdProfile>("PUT", `/api/threshold-profiles/${id}`, b),
};

export function download(url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
