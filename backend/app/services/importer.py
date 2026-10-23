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
        if g.has_z:
            g = shapely.force_2d(g)
        if to_wgs is not None:
            g = shapely.transform(g, lambda xy: np.column_stack(to_wgs.transform(xy[:, 0], xy[:, 1])))
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


def read_dem(path: Path, bounds_lonlat: tuple[float, float, float, float], size: int | None = None) -> dict:
    """Sample a DTM/DEM/DSM onto a regular lon/lat grid (row 0 = north) for the 3D terrain.

    Only the window covering the site is read, decimated to at most ~2048 px, so
    large survey DTMs (e.g. 0.5 m, tens of thousands of pixels) load quickly. The
    output grid is 65..513 samples per side depending on the DEM resolution."""
    import rasterio
    from rasterio.windows import from_bounds

    west, south, east, north = bounds_lonlat
    try:
        ds = rasterio.open(path)
    except Exception as exc:
        raise ImportErrorWithDetail(f"GDAL could not read the raster: {exc}") from exc
    with ds:
        if ds.crs is None:
            raise ImportErrorWithDetail("the raster has no CRS")
        tr = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
        bx, by = tr.transform([west, east, west, east], [south, south, north, north])
        win = from_bounds(min(bx), min(by), max(bx), max(by), transform=ds.transform)
        win = win.round_offsets().round_lengths()
        col_off, row_off = max(0, int(win.col_off)), max(0, int(win.row_off))
        w = min(ds.width, int(win.col_off + win.width)) - col_off
        h = min(ds.height, int(win.row_off + win.height)) - row_off
        if w <= 0 or h <= 0:
            raise ImportErrorWithDetail("the DEM does not overlap the site")
        from rasterio.windows import Window

        win = Window(col_off, row_off, w, h)
        f = max(1.0, max(w, h) / 2048.0)
        out_w, out_h = max(2, int(w / f)), max(2, int(h / f))
        band = ds.read(1, window=win, out_shape=(out_h, out_w), masked=True, resampling=rasterio.enums.Resampling.average)
        band = band.astype("float64")
        wt = ds.window_transform(win) @ rasterio.Affine.scale(w / out_w, h / out_h)
        res_m = abs(ds.transform.a) * (111_320 if ds.crs.is_geographic else 1.0)
        if size is None:
            extent_m = max((east - west) * 111_320 * np.cos(np.radians((north + south) / 2)), (north - south) * 110_540)
            size = int(np.clip(2 ** np.ceil(np.log2(max(extent_m / max(res_m, 1.0), 64))) + 1, 65, 513))
        lons = np.linspace(west, east, size)
        lats = np.linspace(north, south, size)
        LON, LAT = np.meshgrid(lons, lats)
        X, Y = tr.transform(LON.ravel(), LAT.ravel())
        inv = ~wt
        X, Y = np.asarray(X), np.asarray(Y)
        cols = inv.a * X + inv.b * Y + inv.c - 0.5
        rows = inv.d * X + inv.e * Y + inv.f - 0.5
        c0 = np.clip(np.floor(cols).astype(int), 0, out_w - 1)
        r0 = np.clip(np.floor(rows).astype(int), 0, out_h - 1)
        c1 = np.clip(c0 + 1, 0, out_w - 1)
        r1 = np.clip(r0 + 1, 0, out_h - 1)
        fx = np.clip(cols - c0, 0, 1)
        fy = np.clip(rows - r0, 0, 1)
        data = band.filled(np.nan)
        z = (data[r0, c0] * (1 - fx) * (1 - fy) + data[r0, c1] * fx * (1 - fy)
             + data[r1, c0] * (1 - fx) * fy + data[r1, c1] * fx * fy)
        inside = (cols >= -0.5) & (cols <= out_w - 0.5) & (rows >= -0.5) & (rows <= out_h - 0.5)
        z[~inside] = np.nan
        if np.isnan(z).all():
            raise ImportErrorWithDetail("the DEM does not overlap the site")
        fill = float(np.nanmin(z))
        z = np.where(np.isnan(z), fill, z).reshape(size, size)
        return {
            "west": west, "south": south, "east": east, "north": north, "width": size, "height": size,
            "heights": np.round(z, 2).tolist(), "min": float(z.min()), "max": float(z.max()),
            "source_crs": ds.crs.to_string(), "resolution": [abs(ds.transform.a), abs(ds.transform.e)],
        }


def read_ortho(path: Path, out_png: Path, max_px: int = 4096) -> dict:
    """Reproject an orthophoto/satellite GeoTIFF to WGS84 and write a PNG overlay.

    Suitable for site-sized imagery; very large mosaics should be tiled with
    gdal2tiles and served as XYZ tiles (VITE_BASEMAP_URL / site basemap)."""
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    try:
        src = rasterio.open(path)
    except Exception as exc:
        raise ImportErrorWithDetail(f"GDAL could not read the image: {exc}") from exc
    with src:
        if src.crs is None:
            raise ImportErrorWithDetail("the image has no CRS")
        tf, w, h = calculate_default_transform(src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        f = max(1.0, max(w, h) / max_px)
        w2, h2 = max(1, int(w / f)), max(1, int(h / f))
        tf2 = tf @ rasterio.Affine.scale(w / w2, h / h2)
        nb = min(src.count, 4) if src.count >= 3 else 1
        dst = np.zeros((nb if nb != 3 else 4, h2, w2), dtype="uint8")
        for b in range(nb):
            arr = np.zeros((h2, w2), dtype="float32")
            reproject(rasterio.band(src, b + 1), arr, dst_transform=tf2, dst_crs="EPSG:4326",
                      resampling=Resampling.bilinear)
            if src.dtypes[b] != "uint8":
                lo, hi = np.nanpercentile(arr[arr > 0], [2, 98]) if (arr > 0).any() else (0, 1)
                arr = np.clip((arr - lo) / max(hi - lo, 1e-6) * 255, 0, 255)
            dst[b] = arr.astype("uint8")
        if nb == 3:
            dst[3] = np.where(dst[:3].sum(0) > 0, 255, 0)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
            with rasterio.open(out_png, "w", driver="PNG", width=w2, height=h2, count=dst.shape[0], dtype="uint8") as o:
                o.write(dst)
        west, north = tf2.c, tf2.f
        east, south = tf2.c + tf2.a * w2, tf2.f + tf2.e * h2
        return {"west": west, "south": south, "east": east, "north": north, "width": w2, "height": h2,
                "source_crs": src.crs.to_string()}
