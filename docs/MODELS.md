# Models, assumptions, units and limitations

All outputs are **simulated estimates** and are labelled with the method that
produced them. Units: length m, time s, density persons/m² (p/m²), flow
persons/min (p/min) unless stated.

## 1. Agent-based simulation (JuPedSim)

* **Locomotion**: JuPedSim Collision-Free Speed Model (Tordeux, Chraibi &
  Seyfried 2016) by default, or Social Force Model (Helbing & Molnár 1995).
  Agent radius 0.2 m (editable). Time step ≤ 0.1 s (default 0.05 s).
* **Walkable geometry**: union of corridor buffers (centre-line ± width/2) and
  walkable polygons (ghat, steps, bathing area, plaza, holding areas, …) minus
  buildings, temples, walls/barricades (buffered lines), other obstacles and
  water outside bathing areas.
* **Desired speed**: truncated normal, default mean 1.34 m/s, sd 0.26 m/s,
  range 0.5–2.0 m/s (Weidmann 1993). On stairs/ghat steps the desired speed is
  multiplied by 0.6 (ramps 0.9) while the agent is inside that surface.
* **Arrivals**: Poisson process per entry gate with the configured rate and
  time window, multiplied by scheduled restriction factors. An arrival is placed
  only if the space near the gate is free; otherwise it waits in an entry queue
  (queue length and waiting time are recorded).
* **Trips**: entry → optional holding area (shares ≤ 1, dwell) → destination
  (OD shares, dwell) → exit (nearest open exit, or a configured set). The route
  of each leg is computed on the pedestrian network when the leg starts and
  passed to JuPedSim as waypoints; dwelling uses a direct-steering stage to a
  random point in the area.
* **Diversion / route failure**: at the activation time new arrivals use the
  diversion destinations; pedestrians whose remaining route uses a closed
  corridor are re-routed from their nearest node; the closed corridor is removed
  from the walkable geometry once nobody is inside it.
* **Evacuation**: at the trigger, arrivals stop (optional), every pedestrian in
  the affected zones (or everyone) is assigned a route to an exit/assembly point
  by the chosen strategy (nearest, capacity-aware CCRP, planner-assigned).
* **Reproducibility**: the random seed drives arrivals, plan choice, speeds and
  placement; identical inputs + seed give identical results.

## 2. Macroscopic flow model (Cell Transmission Model)

Daganzo's Cell Transmission Model (1994, 1995) on the directed pedestrian network:

* Link → cells of length Δx ≥ v_f·Δt. Each cell stores pedestrians per
  *commodity* (one routed trip leg), so destinations are preserved.
* Triangular fundamental diagram per link: free speed v_f = mean speed × surface
  factor; capacity Q = J_max·W with J_max = 1.22 p/(m·s) (Weidmann 1993);
  jam density k_j = 5.4 p/m²; critical density k_c = Q/(W·v_f); congested wave
  speed w = Q / (W (k_j − k_c)).
* Sending S = min(N·min(1, v_fΔt/Δx), QΔt); receiving R = min(QΔt, (wΔt/Δx)(N_jam − N)).
* Nodes: demand-proportional merge, FIFO diverge (a link's outflow is limited by
  its most constrained downstream target).
* Areas are reservoirs for dwelling pedestrians: storage 0.8·k_j·usable area,
  first-order release N/dwell (exponentially distributed dwell).
* Entry gates are point queues (FIFO waiting time from cumulative curves); exits are sinks.
* Closures: closed links accept no new inflow; affected commodities are re-routed.
* Deterministic (expected values), no randomness.

**Limitations**: no individuals, no lateral/counterflow interaction (each
direction of a two-way corridor uses the full width — this *overestimates*
bidirectional capacity), point-mass reservoirs inside areas.

## 3. Routing

* Free-flow travel time = length / (mean speed × surface factor).
* `shortest_time`: Dijkstra. `k_shortest_logit`: Yen's k loopless paths, split
  P_i ∝ exp(−θ t_i).
* **CCRP** (Lu, George & Shekhar 2005): repeated earliest-arrival search in a
  time-expanded reservation table with per-period link capacities; flow is
  reserved along each found path until all evacuees are assigned. It accounts
  for capacity and congestion, unlike plain shortest paths. Waiting at nodes is
  allowed; node storage limits are not modelled. Its clearance time is reported
  as a *planning estimate* next to the simulated clearance time.

## 4. Analytics

* **Zone count / density**: persons inside the zone's *usable* area (zone ∩
  walkable) / usable area, per output frame.
* **Density grid**: persons per cell / walkable area of the cell (cells with
  < 15 % walkable area are ignored). Macroscopic cell contents are spread over
  sample points across the corridor width for mapping.
* **Throughput**: agent crossings of a measurement section at each corridor's
  midpoint (agent-based) or link flow at the corresponding cell boundary (CTM).
* **Time above threshold**: seconds during which any grid cell (or a zone)
  exceeds its configured limit.
* **Bottleneck**: a connected cluster of grid cells above the default limit for
  at least `bottleneck_min_duration_s`, or a corridor zone above its limit for
  that long; "unresolved" if still above the limit in the final frame.
* **Waiting time**: spawn time − arrival time (agent-based) or FIFO
  cumulative-curve difference (CTM); people still waiting at the end are included.
* **Holding areas**: effective limit = min(configured operational capacity,
  density limit × usable area). Occupancy %, time the limit is reached, projected
  time to limit from the last 60 s trend, and alternative holding areas with
  spare capacity.
* **Evacuation**: clearance time = first time after the trigger when the
  affected zones (or the whole site) hold < 0.5 persons; per-zone clearance;
  unreachable evacuees; exit loads.
* **Interventions**: rule-based prompts for planners (metering, alternative
  routes, exit rebalancing, holding alternatives). They are suggestions for expert
  review, not decisions.

## 5. Thresholds

The default profile (`app/sim/thresholds.py`) is **indicative and not
approved**: corridor/plaza 2.0 p/m², holding & assembly 3.0, bathing & ghat
2.5, colour breaks 0.5–5 p/m², bottleneck minimum duration 60 s, entry-wait
limit 900 s. Sources for orders of magnitude: Fruin (1971) levels of service,
Weidmann (1993), Still (2014). The profile's status and approver are printed on
every report; set and approve values in **Method & limits**.

## 6. Known limitations

* Not calibrated or validated against Pushkaralu observations.
* No pushing/falls/group cohesion/announcement response; no vehicles (SUMO not integrated).
* Stairs are represented by speed factors, not 3D step geometry; terrain is used for display only.
* Capacity reductions during evacuation affect the CTM and CCRP; in agent-based
  runs physical narrowing must be modelled with a corridor width override.
* Agent-based runs of large crowds are slow: on the demo site ~1 700 agents
  simulate 1 200 s in ~100 s, ~5 200 agents in ~375 s, and a 6 100-agent
  evacuation takes about real time (one core per run). Use the macroscopic
  model for site-wide demand and the agent-based model for local hotspots.
* On the demo evacuation the macroscopic model cleared in 655 s while the
  agent-based model had not cleared after 840 s — treat CTM clearance times as
  optimistic.
