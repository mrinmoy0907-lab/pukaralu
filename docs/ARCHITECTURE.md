# Architecture

```
 Browser (React + TypeScript, Vite)
 ├─ CesiumJS 3D operational view ─┐  terrain: CustomHeightmapTerrainProvider fed by the site DEM
 ├─ OpenLayers 2D planning map ───┤  draw/modify/select features, overlays
 ├─ Recharts time series          │
 └─ zustand state, SSE progress ──┘
            │  REST/JSON + server-sent events (/api/...)
 FastAPI backend (Python)
 ├─ api/        sites · features · import · network · routes · scenarios · runs · compare · reports · thresholds · observations
 ├─ services/   GIS import (GDAL/OGR via pyogrio, GDAL rasters via rasterio) · seeding · JobManager
 ├─ geo/        feature catalogue · SiteModel (walkable polygon + pedestrian network) · routing (Dijkstra/Yen/CCRP)
 ├─ sim/        ScenarioConfig · presets · TripPlanner · engines (adapter) · Recorder · analytics · thresholds
 │    ├─ JuPedSimEngine  (agent-based, JuPedSim 1.4)
 │    └─ CTMEngine       (macroscopic Cell Transmission Model)
 └─ reports/    PDF (ReportLab) · CSV zip · GeoJSON
            │                                   │
 PostgreSQL/PostGIS (or SQLite)          result files var/results/<run>/*.json.gz
 (sites, features, datasets, scenarios,  (series, grid frames, agent frames, link frames, analysis)
  runs + provenance, observations,
  threshold profiles)                    GeoServer (optional) publishes v_site_features as WMS/WFS
```

## Key design decisions

### Simulation engine: JuPedSim (agent-based) + own CTM (macroscopic)

| | JuPedSim | Vadere | SUMO |
|---|---|---|---|
| Licence | LGPL-3.0+ | LGPL-3.0 | EPL-2.0 |
| Integration | Python package (`pip install jupedsim`, C++ core), step-wise API: add agents, journeys, stages, switch journeys, switch geometry | Java application; scenario files + CLI/remote control | Road traffic first; pedestrian model on sidewalks/crossings |
| Fit here | continuous 2D walkable geometry from GIS polygons; we control arrivals, dwell, diversions and evacuation every time step | strong models (OSM, gradient navigation, SIR), heavier integration via files | relevant only if vehicle–pedestrian interaction is needed |

JuPedSim was chosen for the agent-based engine because it can be driven step by
step from Python inside a worker process, which is what the operational layer
(entry queues, holding dwell, mid-run closures, evacuation triggers) needs. The
API was verified against the installed version (1.4.2): e.g. a direct-steering
stage must be the only stage of its journey, and `removed_agents()` reports
agents one iteration before they disappear from `agents()`.

The engine sits behind a small adapter (`Engine.run(model, cfg, thresholds,
progress, cancelled) -> result dict`) consumed by `Recorder`/`analytics`, so a
Vadere or SUMO adapter can be added without changing the API or the frontend.

The macroscopic engine is implemented in the project (no suitable maintained
open-source pedestrian CTM library was available) and documented in
[MODELS.md](MODELS.md). It is used for large populations where agent-based
simulation is too slow, and is always labelled "Macroscopic flow estimate".

### Coordinates

Features are stored as GeoJSON in WGS84. Each site has an origin; simulations
run in a site-local Transverse Mercator projection (metres, axes aligned with
east/north), so density grids map to geographic rectangles for display.

### Pedestrian network

Built automatically from features (`geo/site_model.py`):
corridor centre-lines (width, direction, surface, emergency-only, enabled) are
split at intersections, shared endpoints and gate projections; walkable
polygons of type holding area, ghat, bathing area, plaza, transit hub … become
area nodes connected to corridor ends within 2 m; gates connect to an area they
lie in or to the nearest corridor (≤ 20 m). Unconnected elements produce
validation warnings shown in the UI.

### Asynchronous runs and reproducibility

`POST /api/scenarios/{id}/runs` validates the scenario, stores a **snapshot of
all site features**, the full configuration, the seed, the engine version, the
threshold profile and the application version in the `runs` row, and hands the
job to `JobManager`, which executes it in a separate process (spawn context),
limits concurrency, streams progress to the DB and supports cancellation. The
browser follows progress via SSE (`/api/runs/{id}/events`). `POST
/api/runs/{id}/rerun` reproduces a run from the stored snapshot. JobManager's
interface (submit/cancel) is small enough to replace with Celery/RQ later.

### Real-time integration (future)

Observed and forecast counts are stored in `observations` with `kind` and
`source` and are drawn as separate markers. The table and the
`/observations` endpoints are the intended landing point for CCTV-derived
counts, entry counters and approved IoT sensors; **no live feed is implemented**.
