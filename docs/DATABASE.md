# Database schema and migrations

SQLAlchemy 2 models (`backend/app/models.py`), Alembic migrations
(`backend/migrations/versions`). Migrations run automatically at API start-up
(`app.db.migrate()`); manually: `cd backend && alembic upgrade head` with
`PK_DATABASE_URL` set.

Supported databases: SQLite (default, zero setup) and PostgreSQL ≥ 13 with
PostGIS ≥ 3 (recommended for production, used by `docker-compose.yml`). JSON
columns map to `JSONB` on PostgreSQL.

| Table | Content |
|---|---|
| `sites` | name, description, `is_synthetic`, origin lon/lat (defines the local metric CRS), basemap, optional 3D Tiles URL, resampled terrain (JSON), provenance, `version` (incremented on every feature change) |
| `datasets` | one row per imported file: filename, kind (vector/dem), format/driver, layer, feature count, source CRS, **licence**, attribution, `is_synthetic`, `is_surveyed`, notes, SHA-256 |
| `features` | `fid` (unique per site), `pk_type`, name, properties (JSON), geometry (GeoJSON, WGS84), source (synthetic/imported/drawn), dataset link |
| `threshold_profiles` | density bands and limits (JSON), status (draft/approved/retired), approver and date, notes |
| `scenarios` | site, name, description, preset key, `config` (validated ScenarioConfig JSON) |
| `runs` | status/progress/message, engine + engine version, method label, seed, **config snapshot**, **features snapshot** + hash, site version, thresholds snapshot, summary metrics, error, app version, review record, timestamps |
| `observations` | zone/feature id, kind (`observed`/`forecast`), timestamp or offset, count, source (manual/cctv/counter/sensor/other), notes |

Large per-run outputs (time series, density frames, trajectories) are stored as
gzip JSON under `PK_RESULTS_DIR/<run_id>/` and referenced by run id.

## Migrations

* `0001_initial` – all tables above.
* `0002_postgis` – PostgreSQL only and only if the PostGIS extension is
  available: `features.geom geometry(Geometry,4326)` maintained by trigger
  `trg_features_geom` (`ST_GeomFromGeoJSON` + `ST_MakeValid`), GiST index
  `ix_features_geom`, view `v_site_features` (for GeoServer WMS/WFS layers,
  filter by `site_id` / `pk_type`). Without PostGIS the migration is skipped
  with a warning and spatial filters fall back to Shapely.

## GeoServer

With `docker compose --profile gis up`, create a PostGIS store in GeoServer
pointing at host `db`, database `pushkaralu`, and publish the view
`v_site_features` (one layer per `pk_type` via a CQL filter, e.g.
`pk_type = 'holding_area' AND site_id = 3`).
