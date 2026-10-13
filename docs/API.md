# REST API

Base path `/api`. Interactive OpenAPI documentation with request/response
schemas is served by FastAPI at **`/docs`** (Swagger UI) and `/openapi.json`.
Errors are JSON: `{"detail": "message"}` or, for validation, `{"detail": {"errors": ["...", ...]}}`.

## Meta
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness + database type |
| GET | `/meta` | feature-type catalogue, engines (+versions, licences), presets, model assumptions & units |
| GET/POST/PUT | `/threshold-profiles[/{id}]` | configurable density limits; approval requires `approved_by` + `approved_on` |

## Sites, features, GIS data
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/sites` | list / create (name, origin lon/lat, `is_synthetic`, basemap) |
| GET/PATCH/DELETE | `/sites/{id}` | detail incl. dataset provenance |
| GET | `/sites/{id}/features?pk_type=&bbox=` | GeoJSON FeatureCollection (PostGIS `&&` index when available) |
| POST/PUT/DELETE | `/sites/{id}/features[/{fid}]` | create/edit/delete a feature (validated: type, geometry, width, role, capacity) |
| POST | `/sites/{id}/import` | multipart: `file`, `license` (required), `attribution`, `is_synthetic`, `is_surveyed`, `pk_type` or `type_field` + `type_map` (JSON), `layer` — GeoJSON/GPKG/zipped SHP/KML/… or DEM raster |
| POST | `/sites/{id}/layers` | list layers of an uploaded GeoPackage |
| GET | `/sites/{id}/datasets` | provenance records (licence, attribution, CRS, SHA-256, synthetic/surveyed flags) |
| GET | `/sites/{id}/terrain` | resampled DEM heightmap used by the 3D viewer |
| GET | `/sites/{id}/network` | derived pedestrian network (nodes/links GeoJSON, walkable polygon, stats, warnings) |
| POST | `/sites/{id}/routes` | `{from_id,to_id,k,closed_corridors,allow_emergency}` → alternative routes with free-flow time and bottleneck capacity |
| GET | `/sites/{id}/export.geojson` | all features |
| GET/POST | `/sites/{id}/observations` | observed/forecast counts (JSON); `POST /observations/csv` upload; `DELETE /observations/{oid}` |

## Scenarios
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/sites/{id}/scenarios` | list / create (validated against the site) |
| GET/PUT/DELETE | `/scenarios/{id}` | read / update / delete |
| POST | `/sites/{id}/scenarios/validate` | validate a `ScenarioConfig` without saving: returns expected population, network size, warnings, or 422 with all errors |
| GET | `/sites/{id}/presets` | the 10 preset configurations generated from this site's features |
| POST | `/sites/{id}/presets/create` | store the presets as scenarios |
| GET | `/scenarios/{id}/layout.geojson` | proposed circulation layout (directions, closures, holding capacities, diversion targets) |

`ScenarioConfig` (see `backend/app/sim/config.py` or `/docs`): `engine`
(`jupedsim` \| `macro_ctm`), `pedestrian_model`, `duration_s`, `time_step_s`,
`output_interval_s`, `seed`, `walking_speed{mean,sd,min,max}`,
`route_choice{strategy,k,logit_theta}`, `initial_population[]`, `demand[]`,
`destinations[]`, `holding_stops[]`, `exit_gate_ids[]`, `corridor_overrides[]`,
`gate_overrides[]`, `holding_overrides[]`, `entry_restrictions[]`,
`diversion{activation_s,destinations,close_corridors,reroute_existing}`,
`evacuation{trigger_s,affected_zone_ids,exit_gate_ids,assembly_point_ids,strategy,assignments,close_corridors,capacity_reductions,stop_arrivals,use_emergency_corridors}`,
`density_grid_cell_m`, `threshold_profile_id`.

## Runs
| Method | Path | Purpose |
|---|---|---|
| POST | `/scenarios/{id}/runs` | start asynchronously (`{seed?, engine?}`) → 202 with run record |
| GET | `/runs?site_id=&scenario_id=` | list |
| GET | `/runs/{id}` | status, progress, summary metrics, provenance (config, engine version, seed, data hash, thresholds) |
| GET | `/runs/{id}/events` | server-sent events stream of status/progress |
| POST | `/runs/{id}/cancel` | cancel queued/running run |
| POST | `/runs/{id}/rerun` | reproduce from the stored data snapshot + config + seed |
| DELETE | `/runs/{id}` | delete run and result files |
| GET | `/runs/{id}/analysis` | all computed metrics (summary, zones, bottlenecks, corridor flow, exits, queues, holding, evacuation, interventions, events, warnings) |
| GET | `/runs/{id}/series` | time series (zones, queues, exits, corridor flow, holding occupancy, events) |
| GET | `/runs/{id}/grid?every=n` | density-grid definition + sparse frames, max and time-above grids |
| GET | `/runs/{id}/agents?every=n` | agent positions per frame (agent-based runs) |
| GET | `/runs/{id}/links?every=n` | link geometry + density per frame (macroscopic runs) |
| PATCH | `/runs/{id}/review` | review/approval record (`draft/reviewed/approved/rejected`, names, comments) |
| GET | `/runs/{id}/report.pdf` | SOP/drill report |
| GET | `/runs/{id}/export.zip` | CSVs (summary, zones, exits, bottlenecks, holding, corridor flow, time series, evacuation) |
| GET | `/runs/{id}/density.geojson?which=max\|above` | density grid as polygons |
| GET | `/runs/{id}/bottlenecks.geojson` | bottleneck points |

## Comparison
| Method | Path | Purpose |
|---|---|---|
| GET | `/compare?a=&b=` | metric rows (baseline, alternative, difference, %, single-metric assessment) + warnings when methods/data/thresholds differ |
| GET | `/compare/report.pdf?a=&b=` | comparison PDF |
| GET | `/compare/export.csv?a=&b=` | comparison CSV |

## Example

```bash
curl -s localhost:8000/api/sites                                   # find the site id
curl -s -X POST localhost:8000/api/scenarios/1/runs -H 'content-type: application/json' -d '{"engine":"macro_ctm"}'
curl -N localhost:8000/api/runs/<run_id>/events                    # follow progress
curl -o report.pdf localhost:8000/api/runs/<run_id>/report.pdf
curl -F file=@survey.gpkg -F license="Survey of India – authorised use" -F type_field=class \
     -F 'type_map={"footpath":"corridor","ghat":"ghat"}' localhost:8000/api/sites/3/import
```
