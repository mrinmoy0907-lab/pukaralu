"""GIS import through GDAL/OGR (pyogrio) and GDAL raster (rasterio).

Supported vector inputs: GeoJSON, GeoPackage, zipped Shapefile, KML and any
other OGR format readable by the bundled GDAL. Rasters: GeoTIFF and other GDAL
DEM formats. All vectors are reprojected to WGS84; DEMs are resampled to a
height grid over the site for the 3D viewer's terrain.
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pyogrio
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import mapping
from shapely.ops import transform

from ..geo.catalog import FEATURE_TYPES


class ImportErrorWithDetail(ValueError):
    pass


VECTOR_EXT = {".geojson", ".json", ".gpkg", ".zip", ".shp", ".kml", ".gml", ".fgb"}
RASTER_EXT = {".tif", ".tiff", ".asc", ".dem", ".img", ".vrt"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ogr_path(path: Path) -> str:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            shp = [n for n in zf.namelist() if n.lower().endswith(".shp")]
            gpkg = [n for n in zf.namelist() if n.lower().endswith((".gpkg", ".geojson", ".json"))]
        if shp:
            return f"/vsizip/{path}/{shp[0]}"
        if gpkg:
            return f"/vsizip/{path}/{gpkg[0]}"
        raise ImportErrorWithDetail("zip archive contains no .shp, .gpkg or .geojson file")
    return str(path)


def list_layers(path: Path) -> list[str]:
    try:
        return [str(row[0]) for row in pyogrio.list_layers(_ogr_path(path))]
    except Exception as exc:
        raise ImportErrorWithDetail(f"cannot read file: {exc}") from exc


def read_vector(path: Path, *, layer: str | None = None, pk_type: str | None = None, type_field: str = "pk_type",
                type_map: dict[str, str] | None = None, name_field: str | None = None, id_prefix: str = "imp") -> tuple[list[dict], dict]:
    """Read a vector file and return (GeoJSON features in WGS84, metadata)."""
    src = _ogr_path(path)
    try:
        meta, _fids, geoms, field_data = pyogrio.raw.read(src, layer=layer)
    except Exception as exc:
        raise ImportErrorWithDetail(f"GDAL/OGR could not read the file: {exc}") from exc
    crs_txt = meta.get("crs")
    warnings = []
    if not crs_txt:
        warnings.append("the file declares no CRS; WGS84 (EPSG:4326) was assumed")
        crs = CRS.from_epsg(4326)
    else:
        crs = CRS.from_user_input(crs_txt)
    to_wgs = None if crs.equals(CRS.from_epsg(4326)) else Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    fields = list(meta.get("fields", []))
    cols = {f: field_data[i] for i, f in enumerate(fields)}
    features, rejected = [], 0
    type_map = type_map or {}
    for i, wkb in enumerate(geoms):
        if wkb is None:
            rejected += 1
            continue
        g = shapely.from_wkb(wkb)
        if g.is_empty:
            rejected += 1
            continue
        if to_wgs is not None:
            g = transform(to_wgs.transform, g)
        if g.has_z:
            g = shapely.force_2d(g)
        props = {}
        for f, arr in cols.items():
            v = arr[i]
            if isinstance(v, (np.generic,)):
                v = v.item()
            if isinstance(v, float) and np.isnan(v):
                v = None
            if isinstance(v, bytes):
                continue
            props[f] = v if isinstance(v, (str, int, float, bool)) or v is None else str(v)
        t = pk_type or type_map.get(str(props.get(type_field))) or props.get(type_field)
        if t not in FEATURE_TYPES:
            rejected += 1
            continue
        name = props.get(name_field) if name_field else props.get("name")
        base_id = str(props.get("id") or props.get("fid") or f"{id_prefix}_{i}")
        parts = list(g.geoms) if g.geom_type in ("MultiLineString", "MultiPoint") or (
            g.geom_type == "MultiPolygon" and FEATURE_TYPES[t]["geom"] != "Polygon") else [g]
        for j, part in enumerate(parts):
            props2 = {k: v for k, v in props.items() if k not in ("pk_type", "id", "fid")}
            fid = base_id if len(parts) == 1 else f"{base_id}_{j}"
            features.append({"type": "Feature", "id": fid, "geometry": mapping(part),
                             "properties": {**props2, "pk_type": t, "name": name or fid}})
    if rejected:
        warnings.append(f"{rejected} feature(s) skipped: empty geometry or no recognised pk_type "
                        f"(set a pk_type, a type_field/type_map, or a default type for the layer)")
    if not features:
        raise ImportErrorWithDetail("no importable features found. " + " ".join(warnings))
    info = {"source_crs": crs.to_string(), "layer": layer or meta.get("layer_name"), "feature_count": len(features),
            "fields": fields, "warnings": warnings, "driver": meta.get("driver")}
    return features, info


def read_dem(path: Path, bounds_lonlat: tuple[float, float, float, float], size: int = 129) -> dict:
    """Sample a DEM onto a regular lon/lat grid (row 0 = north) for the 3D terrain."""
    import rasterio

    west, south, east, north = bounds_lonlat
    try:
        ds = rasterio.open(path)
    except Exception as exc:
        raise ImportErrorWithDetail(f"GDAL could not read the raster: {exc}") from exc
    with ds:
        if ds.crs is None:
            raise ImportErrorWithDetail("the raster has no CRS")
        band = ds.read(1, masked=True).astype("float64")
        lons = np.linspace(west, east, size)
        lats = np.linspace(north, south, size)
        LON, LAT = np.meshgrid(lons, lats)
        tr = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
        X, Y = tr.transform(LON.ravel(), LAT.ravel())
        inv = ~ds.transform
        cols, rows = inv * (np.asarray(X), np.asarray(Y))
        cols = np.asarray(cols) - 0.5
        rows = np.asarray(rows) - 0.5
        c0 = np.clip(np.floor(cols).astype(int), 0, ds.width - 1)
        r0 = np.clip(np.floor(rows).astype(int), 0, ds.height - 1)
        c1 = np.clip(c0 + 1, 0, ds.width - 1)
        r1 = np.clip(r0 + 1, 0, ds.height - 1)
        fx = np.clip(cols - c0, 0, 1)
        fy = np.clip(rows - r0, 0, 1)
        data = band.filled(np.nan)
        z = (data[r0, c0] * (1 - fx) * (1 - fy) + data[r0, c1] * fx * (1 - fy)
             + data[r1, c0] * (1 - fx) * fy + data[r1, c1] * fx * fy)
        inside = (cols >= -0.5) & (cols <= ds.width - 0.5) & (rows >= -0.5) & (rows <= ds.height - 0.5)
        z[~inside] = np.nan
        if np.isnan(z).all():
            raise ImportErrorWithDetail("the DEM does not overlap the site")
        fill = float(np.nanmin(z))
        z = np.where(np.isnan(z), fill, z)
        return {
            "west": west, "south": south, "east": east, "north": north, "width": size, "height": size,
            "heights": np.round(z, 2).tolist(), "min": float(z.min()), "max": float(z.max()),
            "source_crs": ds.crs.to_string(), "resolution": [abs(ds.transform.a), abs(ds.transform.e)],
        }
