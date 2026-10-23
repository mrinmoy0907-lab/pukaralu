# Data drop folder – loading real DTM/DEM, 3D models and GIS data

Put each site's data in its own folder under **`data/sites/`** (change with
`PK_SITES_DIR`). The folder is scanned when the application starts, when you
press **Data Sources → ⟳ Scan data folder**, or with `scan_data_windows.bat`
(`python -m app.ingest` on Linux/macOS). New files are imported; files whose
content changed (SHA-256) are re-imported and replace the old version;
unchanged files are skipped.

```
data/sites/
  nashik_ramkund/                 <- one folder = one site (any name)
    site.json                     <- optional manifest (recommended)
    vector/                       <- GeoJSON, GeoPackage, Shapefile (.shp + .dbf/.shx/.prj, or zipped), KML, FlatGeobuf
    dem/                          <- DTM / DEM / DSM raster: GeoTIFF, .asc, .img, .vrt (latest file wins)
    terrain/                      <- quantized-mesh terrain tileset (layer.json + z/x/y.terrain)
    tiles3d/<name>/tileset.json   <- 3D Tiles: buildings, photogrammetry mesh, LiDAR point cloud
    models/                       <- glTF / GLB models (pandals, temples, stages, bridges)
    imagery/                      <- orthophoto / drone mosaic GeoTIFF
```

Any coordinate reference system is accepted (it is read from the file, e.g. UTM 44N / EPSG:32644).

## site.json

```json
{
  "name": "Ramkund Ghat - surveyed 2026",
  "description": "Drone survey Sept 2026, DGPS-controlled",
  "is_synthetic": false,
  "origin": [73.7915, 20.0077],
  "basemap": "satellite",
  "create_presets": true,
  "defaults": {
    "license": "Govt. of Maharashtra - authorised use",
    "attribution": "Nashik Municipal Corporation GIS cell",
    "is_synthetic": false,
    "is_surveyed": true
  },
  "files": {
    "vector/footpaths.gpkg": {"pk_type": "corridor"},
    "vector/landuse.shp": {"type_field": "CLASS", "type_map": {"GHAT": "ghat", "HOLDING": "holding_area", "BLDG": "building"}},
    "vector/osm_extract.geojson": {"license": "ODbL-1.0", "attribution": "(c) OpenStreetMap contributors", "is_surveyed": false}
  },
  "models": [
    {"file": "models/main_pandal.glb", "lon": 73.79161, "lat": 20.00781, "height": 0, "heading_deg": 35, "scale": 1.0}
  ],
  "tilesets": {"buildings": {"height_offset": 0}}
}
```

| Key | Meaning |
|---|---|
| `origin` | lon/lat of the site centre (defines the local metric CRS for simulation). Default: centre of the vector data. |
| `basemap` | `osm`, `satellite`, `light`, `dark`, `custom` (VITE_BASEMAP_URL) or `grid` |
| `defaults` | licence / attribution / synthetic / surveyed flags for every file (recorded as provenance; shown in reports) |
| `files.<relative path>` | per-file overrides: `pk_type` (one type for the whole layer) **or** `type_field` + `type_map`, `layer` (GeoPackage), licence fields, `notes` |
| `models` | placement of each glTF/GLB: `lon`, `lat`, `height` (m above ground; 0 = on terrain), `heading_deg`, `scale` |
| `create_presets` | generate the 10 preset scenarios once the network exists |

Vector features need a feature type (`pk_type`) – either an attribute in the
file, a per-file `pk_type`, or a `type_field` + `type_map`. The types and
their attributes are listed in [DATA_REPLACEMENT.md](DATA_REPLACEMENT.md).

## What happens to each kind of data

| Folder | Result in the Digital Twin |
|---|---|
| `vector/` | features in the database (reprojected to WGS84), used for the network, simulation, zones and analysis |
| `dem/` | terrain for the 3D view (resampled to ≤ 513 × 513 over the site; large DTMs are read windowed and decimated) and DTM step-surface area in zone calculations |
| `terrain/` | streamed as high-resolution Cesium terrain (preferred over `dem/` in 3D when present); gzip-compressed tiles are served with the right header |
| `tiles3d/` | streamed 3D Tiles (Layers → 3D Tiles) |
| `models/` | glTF models placed in 3D (Layers → 3D models) |
| `imagery/` | reprojected PNG overlay draped in 2D and 3D (Layers → Ortho imagery); suitable up to a few thousand pixels per side |

## Converting common survey outputs (open-source tools)

| You have | Convert with | Into |
|---|---|---|
| LiDAR point cloud (LAS/LAZ) | `py3dtiles convert cloud.laz --out tiles3d/lidar` (Apache-2.0) | `tiles3d/lidar/` |
| LiDAR ground points → DTM | PDAL `pdal pipeline` (writers.gdal) or `lastools` | `dem/dtm.tif` |
| Big DTM for 3D streaming | cesium-terrain-builder: `ctb-tile -f Mesh -C -N -o terrain dtm.tif` then `ctb-tile -f Mesh -C -N -l -o terrain dtm.tif` | `terrain/` |
| Photogrammetry mesh (OBJ/FBX) | Blender (export glTF) or `obj2gltf`; for city-scale meshes use `3d-tiles-tools` / Cesium ion export | `models/*.glb` or `tiles3d/` |
| CityGML / building footprints | footprints with height attribute → `vector/` as `building` (extruded automatically); CityGML → 3D Tiles with citygml-tools / FME | `vector/` or `tiles3d/` |
| Large orthophoto / satellite mosaic | `gdal2tiles.py -z 14-20 --xyz ortho.tif tiles/` and serve as XYZ → `VITE_BASEMAP_URL` | basemap |
| AutoCAD (DWG/DXF) site plan | QGIS: open DXF, assign CRS, export layers to GeoPackage with a `pk_type` attribute | `vector/` |

## Notes

* Editing an imported feature in the application and then replacing its file
  re-imports the file and **overwrites those edits** – keep the master copy in GIS.
* Removing a file from the folder does not delete already imported data; delete
  it in the application (or the site) if needed.
* The bundled folders `01_…`, `02_…`, `03_…` are demonstration data
  (01 and 02 are SIM DATA). Delete them on a production installation.
