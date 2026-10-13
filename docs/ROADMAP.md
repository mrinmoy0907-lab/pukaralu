# Phases and acceptance status

| Phase | Scope | Status |
|---|---|---|
| 1 | 3D GIS viewer, synthetic demonstration site, asset layers, GIS import | **Done** – Cesium viewer with DEM terrain, layers, symbols; GeoJSON/GPKG/SHP/KML/DEM import with provenance |
| 2 | Walkable network, entry/exit definitions, basic pedestrian simulation | **Done** – automatic network, gates, JuPedSim engine |
| 3 | Animated agents, density heatmaps, queue analysis, holding-area capacity | **Done** |
| 4 | Diversions, blocked routes, evacuation, comparison | **Done** – incl. CCRP capacity-aware evacuation routing, synchronised split view |
| 5 | Validation, reporting, reproducibility, SOP workflows | **Partly** – reproducibility, PDF/CSV/GeoJSON, review records done; *calibration against real observations not possible without data* |
| 6 | Sensor integration, synchronisation with the wider Digital Twin | **Not started** – data model and endpoints for observed/forecast counts exist; no live feeds |

## Minimum acceptance criteria

| # | Criterion | Evidence |
|---|---|---|
| 1 | Starts locally with documented commands | README quick start |
| 2 | Interactive 3D site | `CesiumView.tsx` |
| 3 | Import ≥1 real and ≥1 synthetic dataset | seeded OSM river (ODbL) + synthetic site & DEM; `test_import_formats` (GPKG in UTM, zipped SHP) |
| 4 | Define entries, exits, corridors, holding areas | 2D draw tools + inspector; feature API |
| 5 | Run an actual pedestrian simulation | JuPedSim engine; `test_jupedsim_*` |
| 6 | Agents / flows over time | Cesium point primitives (agents), link-density polylines (CTM), timeline |
| 7 | Dynamically computed density & congestion | Recorder/analytics; heatmap from run output |
| 8 | Block a corridor and re-run a diversion | presets *blocked corridor*, *route failure*, *diversion*; `test_ctm_route_failure_reroutes` |
| 9 | Compare baseline and alternative with computed metrics | `/api/compare`, Compare tab; test asserts differences equal run summaries |
| 10 | Export results and maps | PDF with maps, CSV zip, GeoJSON |
| 11 | Assumptions, units, limitations, provenance | Method & limits tab, PDF sections, MODELS.md |
| 12 | Automated tests, error handling | 33 backend tests (SQLite + PostgreSQL), 9 frontend unit tests; validation errors returned with field messages |

## Known limitations / next steps

* Calibrate against observed Pushkaralu data (counts, speeds, dwell times) and document validation.
* Docker Compose and PostGIS-specific migration were not executed in the build environment (no Docker daemon / PostGIS package); verify on a target machine.
* Agent-based scale: ~1 700 agents simulate 1 200 s in ≈100 s, a 6 100-agent evacuation runs at about real time on one core; city-scale demand needs the macroscopic engine or more/HPC workers (JobManager can be replaced by Celery/RQ).
* Counterflow and bidirectional capacity in the macroscopic model; group behaviour; stairs as geometry.
* Vadere / SUMO adapters (vehicle–pedestrian interaction at approach roads).
* Authentication/authorisation and audit log for approvals (not implemented in the prototype).
* Live CCTV / counter / IoT ingestion (Phase 6).
