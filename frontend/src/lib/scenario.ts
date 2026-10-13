import type { Feature, ScenarioConfig } from "../types";

/** Client-side pre-checks; the server performs the authoritative validation
 * (including network reachability) before a scenario is saved or run. */
export function precheck(cfg: ScenarioConfig, features: Feature[]): string[] {
  const errs: string[] = [];
  const byId = new Map(features.map((f) => [String(f.id), f]));
  const typeOf = (id: string) => byId.get(id)?.properties.pk_type;
  if (!cfg.name.trim()) errs.push("Scenario name is required.");
  if (cfg.duration_s <= 0) errs.push("Duration must be positive.");
  if (cfg.engine === "jupedsim" && cfg.time_step_s > 0.1) errs.push("Agent-based time step must be ≤ 0.1 s.");
  if (cfg.engine === "macro_ctm" && cfg.time_step_s < 0.25) errs.push("Macroscopic time step must be ≥ 0.25 s.");
  for (const d of cfg.demand) {
    if (typeOf(d.gate_id) !== "gate") errs.push(`Arrival gate '${d.gate_id}' is not a gate.`);
    if (d.rate_per_min < 0) errs.push(`Arrival rate at '${d.gate_id}' must be ≥ 0.`);
  }
  if (cfg.demand.length && !cfg.destinations.length && !cfg.evacuation) errs.push("Arrivals need at least one destination.");
  for (const d of cfg.destinations) if (!byId.has(d.target_id)) errs.push(`Unknown destination '${d.target_id}'.`);
  const hs = cfg.holding_stops.reduce((a, h) => a + h.share, 0);
  if (hs > 1.0001) errs.push("Holding-area shares must sum to ≤ 1 (the rest walk directly).");
  for (const h of cfg.holding_stops) if (typeOf(h.holding_id) !== "holding_area") errs.push(`'${h.holding_id}' is not a holding area.`);
  const ws = cfg.walking_speed;
  if (!(ws.min <= ws.mean && ws.mean <= ws.max)) errs.push("Walking speed must satisfy min ≤ mean ≤ max.");
  if (cfg.evacuation && cfg.evacuation.trigger_s > cfg.duration_s) errs.push("Evacuation trigger is after the end of the run.");
  if (cfg.diversion && cfg.diversion.activation_s > cfg.duration_s) errs.push("Diversion activation is after the end of the run.");
  return errs;
}

export function emptyConfig(name = "New scenario"): ScenarioConfig {
  return {
    name,
    description: "",
    engine: "jupedsim",
    pedestrian_model: "CollisionFreeSpeedModel",
    duration_s: 900,
    time_step_s: 0.05,
    output_interval_s: 1,
    seed: 42,
    agent_radius_m: 0.2,
    walking_speed: { mean: 1.34, sd: 0.26, min: 0.5, max: 2.0 },
    route_choice: { strategy: "shortest_time", k: 3, logit_theta: 0.05 },
    initial_population: [],
    demand: [],
    destinations: [],
    holding_stops: [],
    exit_gate_ids: [],
    corridor_overrides: [],
    gate_overrides: [],
    holding_overrides: [],
    entry_restrictions: [],
    diversion: null,
    evacuation: null,
    density_grid_cell_m: 4,
    threshold_profile_id: null,
  };
}

/** Approximate number of pedestrians a scenario generates (for the editor). */
export function expectedPopulation(cfg: ScenarioConfig): number {
  const init = cfg.initial_population.reduce((a, p) => a + p.count, 0);
  const arr = cfg.demand.reduce((a, d) => a + (d.rate_per_min / 60) * Math.max(0, (d.end_s ?? cfg.duration_s) - d.start_s), 0);
  return Math.round(init + arr);
}
