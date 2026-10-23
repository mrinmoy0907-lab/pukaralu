import type { Tab } from "../store";

export interface UseCase {
  id: string;
  title: string;
  roles: string[];
  goal: string;
  tab: Tab;
  steps: string[];
}

/** Operational use cases of the Digital Twin (also used for docs/user-journeys.pdf). */
export const USE_CASES: UseCase[] = [
  {
    id: "P-01",
    title: "Zone and walkable-area setup",
    roles: ["R7", "R3"],
    goal: "Define operational zones and calculate usable crowd area (excluding water, stalls and barricades).",
    tab: "zones",
    steps: ["Turn on layers", "Draw zone boundary", "Fill zone properties", "Recalculate walkable area", "Review and confirm"],
  },
  {
    id: "P-02",
    title: "Load surveyed GIS, DTM and 3D models",
    roles: ["R7", "R1"],
    goal: "Bring surveyed vectors, DTM/DEM, 3D Tiles, glTF models and orthophotos into the Digital Twin from the data folder.",
    tab: "data",
    steps: ["Copy files into data/sites/<site>", "Scan data folder", "Check provenance and licences", "Verify in 3D"],
  },
  {
    id: "P-03",
    title: "Corridors, gates and network check",
    roles: ["R7"],
    goal: "Draw pedestrian corridors and gates and verify the walkable network is connected.",
    tab: "workbench",
    steps: ["Draw corridor / add gate", "Set width, direction, surface", "Show the pedestrian network", "Fix warnings"],
  },
  {
    id: "P-04",
    title: "Alternative routes and diversions",
    roles: ["R7"],
    goal: "Compare alternative routes between gates and areas, with closures and route capacities.",
    tab: "workbench",
    steps: ["Pick origin and destination", "Close corridors", "Compare routes and bottleneck capacities"],
  },
  {
    id: "P-05",
    title: "Holding-area capacity",
    roles: ["R7", "R5"],
    goal: "Estimate occupancy over time, time to reach the limit and alternative holding areas.",
    tab: "results",
    steps: ["Run the overcrowded-holding preset", "Open holding-area capacity", "Read suggestions"],
  },
  {
    id: "P-06",
    title: "Scenario setup",
    roles: ["R7"],
    goal: "Create a scenario from a preset and edit arrivals, destinations, behaviour and circulation plan.",
    tab: "scenarios",
    steps: ["New from preset", "Edit parameters", "Validate", "Save"],
  },
  {
    id: "P-07",
    title: "Run and monitor a simulation",
    roles: ["R7"],
    goal: "Run agent-based or macroscopic simulations in the background and follow progress.",
    tab: "runs",
    steps: ["Save & run", "Follow progress", "Cancel or reproduce", "Open results"],
  },
  {
    id: "P-08",
    title: "Density, queues and bottlenecks",
    roles: ["R5"],
    goal: "Replay agents and density heatmaps; inspect zone densities, queues and bottlenecks.",
    tab: "results",
    steps: ["Open results", "Replay timeline", "Inspect zones and bottlenecks"],
  },
  {
    id: "P-09",
    title: "Blocked corridor and route failure",
    roles: ["R7", "R5"],
    goal: "Block a corridor or let a route fail mid-run and re-run with diversions.",
    tab: "scenarios",
    steps: ["Disable corridor / closure", "Run", "Check re-routing and new bottlenecks"],
  },
  {
    id: "P-10",
    title: "Emergency evacuation",
    roles: ["R5", "R1"],
    goal: "Simulate an evacuation with chosen exits, closures and routing strategy; read clearance times.",
    tab: "scenarios",
    steps: ["Configure evacuation", "Run", "Read clearance by zone and exit use"],
  },
  {
    id: "P-11",
    title: "Compare baseline and alternative",
    roles: ["R5"],
    goal: "Compare two runs with computed metrics and synchronised 3D views.",
    tab: "compare",
    steps: ["Choose baseline and alternative", "Read metric differences", "Synchronised 3D"],
  },
  {
    id: "P-12",
    title: "Reports, SOP and drill package",
    roles: ["R5", "R1"],
    goal: "Download PDF/CSV/GeoJSON outputs and record review and approval.",
    tab: "reports",
    steps: ["Download report", "Export layout GeoJSON", "Record review / approval"],
  },
  {
    id: "P-13",
    title: "Observed and forecast counts",
    roles: ["R7"],
    goal: "Upload manual or counter counts and compare them with simulated values.",
    tab: "feeds",
    steps: ["Upload CSV", "Compare with simulated counts"],
  },
  {
    id: "P-14",
    title: "Density thresholds approval",
    roles: ["R1", "R5"],
    goal: "Configure density limits and record approval by the competent authority.",
    tab: "admin",
    steps: ["Edit limits", "Record approver and date", "Save profile"],
  },
];
