export type Geometry = { type: string; coordinates: any };

export interface Feature {
  type: "Feature";
  id: string;
  geometry: Geometry;
  properties: Record<string, any> & { pk_type: string; name?: string };
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: Feature[];
}

export interface Dataset {
  id: number;
  filename: string;
  kind: string;
  format: string;
  layer: string | null;
  feature_count: number;
  source_crs: string | null;
  license: string;
  attribution: string;
  is_synthetic: boolean;
  is_surveyed: boolean;
  notes: string;
  sha256: string | null;
  imported_at: string | null;
}

export interface Site {
  id: number;
  name: string;
  description: string;
  is_synthetic: boolean;
  origin: [number, number];
  basemap: string;
  tileset_url: string | null;
  has_terrain: boolean;
  provenance: Record<string, any>;
  version: number;
  n_features: number | null;
  datasets?: Dataset[];
  assets?: {
    source_folder?: string;
    terrain_url?: string | null;
    tilesets?: { name: string; url: string; height_offset?: number }[];
    models?: { name: string; url: string; lon: number; lat: number; height: number; heading_deg: number; scale: number }[];
    imagery?: { name: string; url: string; west: number; south: number; east: number; north: number; attribution?: string }[];
  };
}

export interface Terrain {
  west: number;
  south: number;
  east: number;
  north: number;
  width: number;
  height: number;
  heights: number[][];
  min: number;
  max: number;
}

export interface FeatureTypeInfo {
  label: string;
  geom: "Point" | "LineString" | "Polygon";
  roles: string[];
}

export interface Meta {
  version: string;
  feature_types: Record<string, FeatureTypeInfo>;
  presets: { key: string; label: string }[];
  engines: { key: string; label: string; version: string; method_type: string; license: string; description: string }[];
  assumptions: Record<string, any>;
  live_sensor_integration: boolean;
}

export interface Scenario {
  id: number;
  site_id: number;
  name: string;
  description: string;
  preset: string | null;
  config: ScenarioConfig;
}

export interface ScenarioConfig {
  name: string;
  description: string;
  engine: "jupedsim" | "macro_ctm";
  pedestrian_model: string;
  duration_s: number;
  time_step_s: number;
  output_interval_s: number;
  seed: number;
  agent_radius_m: number;
  walking_speed: { mean: number; sd: number; min: number; max: number };
  route_choice: { strategy: string; k: number; logit_theta: number };
  initial_population: { zone_id: string; count: number; dwell_s: number }[];
  demand: { gate_id: string; rate_per_min: number; start_s: number; end_s: number | null }[];
  destinations: { target_id: string; share: number; dwell_s: number }[];
  holding_stops: { holding_id: string; share: number; dwell_s: number }[];
  exit_gate_ids: string[];
  corridor_overrides: { corridor_id: string; enabled?: boolean | null; width_m?: number | null; direction?: string | null; capacity_factor?: number | null }[];
  gate_overrides: { gate_id: string; enabled?: boolean | null; role?: string | null; width_m?: number | null }[];
  holding_overrides: { holding_id: string; capacity_persons?: number | null }[];
  entry_restrictions: { gate_id: string; start_s: number; end_s: number | null; rate_multiplier: number }[];
  diversion: null | {
    activation_s: number;
    destinations: { target_id: string; share: number; dwell_s: number }[];
    close_corridors: string[];
    reroute_existing: boolean;
  };
  evacuation: null | {
    trigger_s: number;
    affected_zone_ids: string[];
    exit_gate_ids: string[];
    assembly_point_ids: string[];
    strategy: "nearest" | "capacity_aware" | "assigned";
    assignments: { zone_id: string; exit_gate_id: string }[];
    close_corridors: string[];
    capacity_reductions: { corridor_id: string; capacity_factor?: number | null }[];
    stop_arrivals: boolean;
    use_emergency_corridors: boolean;
  };
  density_grid_cell_m: number;
  threshold_profile_id: number | null;
}

export interface Run {
  id: string;
  scenario_id: number | null;
  site_id: number;
  name: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  message: string;
  engine: string;
  engine_version: string;
  method: string;
  seed: number;
  summary: Summary | null;
  error: string | null;
  review: Record<string, any>;
  site_version: number;
  features_hash: string;
  created_at: string | null;
  finished_at: string | null;
  config?: ScenarioConfig;
  threshold_profile?: Record<string, any>;
}

export interface Summary {
  method: string;
  method_type: string;
  estimate_label: string;
  total_arrivals: number;
  initial_population: number;
  total_exited: number;
  remaining_at_end: number;
  entry_queue_at_end: number;
  peak_population_in_site: number;
  max_density_ppm2: number;
  max_density_location: { lon: number; lat: number };
  max_zone_density_ppm2: number;
  max_zone_density_zone: string | null;
  time_above_threshold_s: number;
  density_limit_ppm2: number;
  avg_wait_s: number;
  max_wait_s: number;
  throughput_ppm: number;
  peak_exit_flow_ppm: number;
  mean_travel_time_s: number | null;
  p95_travel_time_s: number | null;
  n_bottlenecks: number;
  n_unresolved_bottlenecks: number;
  clearance_time_s: number | null;
  exit_utilisation: Record<string, { count: number; share: number; peak_utilisation: number | null }>;
  congestion_duration_s: number;
  unroutable_arrivals?: Record<string, number>;
  wall_time_s: number;
}

export interface Bottleneck {
  type: string;
  lon: number;
  lat: number;
  near: string | null;
  max_density_ppm2: number;
  duration_s: number;
  unresolved: boolean;
  cell_index?: number[];
}

export interface Analysis {
  summary: Summary;
  zones: {
    zone_id: string;
    name: string;
    kind: string;
    usable_area_m2: number;
    max_count: number;
    final_count: number;
    max_density_ppm2: number;
    mean_density_ppm2: number;
    limit_ppm2: number;
    time_above_limit_s: number;
    exceeds_limit: boolean;
  }[];
  bottlenecks: Bottleneck[];
  corridor_flow: Record<string, { name: string; total: number; peak_ppm: number; capacity_ppm: number; peak_utilisation: number | null }>;
  exits: Record<string, { name: string; count: number; share: number; peak_ppm: number; capacity_ppm: number | null; peak_utilisation: number | null }>;
  queues: { entry_queue_peak: Record<string, number>; entry_queue_final: Record<string, number>; congested_persons_peak: number; congestion_duration_s: number };
  holding: {
    holding_id: string;
    name: string;
    usable_area_m2: number;
    configured_capacity: number | null;
    density_limit_ppm2: number;
    effective_limit: number;
    peak_population: number;
    final_population: number;
    available_capacity_final: number;
    peak_occupancy_pct: number;
    time_limit_reached_s: number | null;
    projected_time_to_limit_s: number | null;
    suggestions: string[];
    excluded_area_m2: number;
  }[];
  evacuation: null | {
    trigger_s: number;
    strategy: string;
    evacuees: number;
    unreachable_evacuees: number;
    clearance_time_s: number | null;
    cleared_within_simulation: boolean;
    remaining_in_affected_area: number;
    clearance_by_zone: Record<string, { name: string; population_at_trigger: number; clearance_s: number | null }>;
    ccrp_planning_estimate_s: number | null;
    ccrp_exit_load: Record<string, number>;
    note: string;
  };
  interventions: string[];
  events: { t: number; type: string; text: string }[];
  warnings: string[];
  engine: { name: string; version: string; method: string; method_type: string };
}

export interface Series {
  times: number[];
  total_in_site: number[];
  queued: number[];
  entry_queues: Record<string, number[]>;
  arrivals: Record<string, number[]>;
  exits: Record<string, number[]>;
  zones: Record<string, { count: number[]; density: number[] }>;
  corridor_flow_ppm: Record<string, number[]>;
  holding_occupancy_pct: Record<string, number[]>;
  events: { t: number; type: string; text: string }[];
}

export interface GridDef {
  nx: number;
  ny: number;
  cell_m: number;
  west: number;
  south: number;
  east: number;
  north: number;
}

export interface GridDoc {
  grid: GridDef;
  times: number[];
  frames: [number[], number[]][];
  max: [number[], number[]];
  above_s: [number[], number[]];
  walk_area?: number[];
}

export interface AgentFrame {
  t: number;
  ids: number[];
  lon: number[];
  lat: number[];
}

export interface LinksDoc {
  links: { id: number; corridor_id: string | null; kind: string; width: number; coords: [number, number][] }[];
  times: number[];
  frames: number[][];
}

export interface RunData {
  run: Run;
  analysis: Analysis;
  series: Series;
  grid: GridDoc;
  agents: AgentFrame[] | null;
  links: LinksDoc | null;
}

export interface Observation {
  id: number;
  zone_fid: string;
  kind: "observed" | "forecast";
  count: number;
  t_offset_s: number | null;
  observed_at: string | null;
  source: string;
  notes: string;
}

export interface ThresholdProfile {
  id: number;
  name: string;
  values: { density_bands: number[]; limits: Record<string, number>; bottleneck_min_duration_s: number; queue_wait_limit_s: number; [k: string]: any };
  status: string;
  approved_by: string | null;
  approved_on: string | null;
  notes: string;
}
