# Replacing synthetic data with surveyed Pushkaralu GIS data

The bundled **SYNTHETIC demonstration ghat** is invented geometry for testing.
It is placed over open sea (85.0°E, 15.0°N) on purpose. The bundled real dataset
(Godavari river near Rajahmundry, OpenStreetMap via `@geo-maps/earth-rivers-10m`,
ODbL, generalised to ~10 m) shows only the river — it contains **no** ghat,
corridor, gate or holding-area geometry. Do not use either for operational
decisions.

## 1. Prepare data (QGIS / GDAL)

Collect, from authorised sources (survey, municipal GIS, drone photogrammetry,
police/administration plans), layers for the site and its approaches.
Any CRS is accepted (it is read from the file); UTM 44N (EPSG:32644) is typical
for Godavari/Krishna sites. Each feature needs a **type** (`pk_type`) from the
catalogue below, either as an attribute or assigned per layer at import.

| pk_type | Geometry | Key attributes |
|---|---|---|
| `corridor` | LineString (centre-line) | `width_m` (clear width), `direction` = both/forward/backward (forward = digitising direction), `surface` = path/stairs/ramp, `enabled` |
| `emergency_corridor` | LineString | as corridor; used only in evacuations |
| `gate` | Point (on a corridor end or inside an area) | `role` = entry/exit/both, `width_m`, `emergency_exit`, `enabled` |
| `holding_area` | Polygon | `capacity_persons` (approved operational capacity) |
| `bathing_area`, `ghat`, `steps`, `ramp`, `plaza`, `queue_lane`, `assembly_point`, `transit_hub`, `bus_terminal`, `parking` | Polygon | `surface` for ghats/steps |
| `building`, `temple`, `obstacle` | Polygon | `height_m` |
| `wall`, `barricade` | LineString | `height_m`, `thickness_m` |
| `river` | Polygon | water outside bathing areas is not walkable |
| `road` | LineString | display only |
| `hospital`, `first_aid`, `control_point`, `speaker` | Point | – |
| `zone` | Polygon | extra analysis zone |

Topology rules used to build the pedestrian network:
* corridors that meet must share an endpoint, cross, or have an endpoint within
  1.5 m of the other corridor;
* a corridor serving an area must end within 2 m of the area polygon;
* gates must lie within 20 m of a corridor or within 2 m of an area.
The **Layers → Pedestrian network** overlay and `GET /api/sites/{id}/network`
report unconnected elements.

Example (GDAL) – convert a surveyed Shapefile of footpaths to GeoPackage and
set the type:

```bash
ogr2ogr -f GPKG paths.gpkg footpaths.shp -t_srs EPSG:32644 -sql \
  "SELECT *, 'corridor' AS pk_type, CAST(clear_w AS REAL) AS width_m FROM footpaths"
```

## 2. Create a site and import

1. **Data → Sites → New site**: name, origin (approximate centre lon/lat), basemap; leave *Synthetic* unchecked.
2. **Data → Import GIS data**: choose the file, declare its **licence** and
   attribution, tick *Surveyed / verified* only for verified survey data, and
   either assign one type to the whole layer or map an attribute
   (`type_field` + JSON `type_map`, e.g. `{"footway":"corridor","open_space":"plaza"}`).
3. Import the **DEM** (GeoTIFF etc.) after the vectors; it is resampled over the site extent for the 3D view.
4. Optionally set a 3D Tiles URL for buildings (`PATCH /api/sites/{id}` with `tileset_url`).
5. Check the network overlay; fix geometry in the 2D map (select → drag vertices) or in QGIS and re-import.
6. **Scenarios → New from preset** generates the 10 presets from the new site's features. Replace demand,
   OD shares, dwell times and walking speeds with observed values.
7. **Method & limits**: enter the density limits approved by the competent authority and record the approval.

## 3. Calibrate and validate

* Upload observed counts (Data → Observed/forecast counts, CSV) for zones and
  compare them with simulated counts in Results (observations are shown as
  separate markers, never merged with simulation output).
* Adjust walking-speed distribution, dwell times and arrival profiles; keep the
  calibration runs (they are reproducible via **Reproduce**).
* Record review and approval for runs used in SOPs (Results → Review & approval).

## 4. Remove the demo data

Delete the synthetic site from the database (`DELETE /api/sites/{id}`), or start
with `PK_SEED_DEMO_DATA=false` on a fresh database.
