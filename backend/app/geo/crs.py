"""Coordinate handling.

All features are stored as GeoJSON in WGS84 (EPSG:4326). Simulations run in a
site-local Transverse Mercator projection centred on the site origin, so x/y
are metres east/north with negligible distortion over a few kilometres and
grid axes that stay aligned with longitude/latitude (important for drawing
density grids as geographic rectangles).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform


def local_crs(lon0: float, lat0: float) -> CRS:
    return CRS.from_proj4(
        f"+proj=tmerc +lat_0={lat0} +lon_0={lon0} +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"
    )


@dataclass
class LocalProjection:
    lon0: float
    lat0: float

    def __post_init__(self) -> None:
        crs = local_crs(self.lon0, self.lat0)
        self._fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        self._inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    @property
    def proj4(self) -> str:
        return local_crs(self.lon0, self.lat0).to_proj4()

    def to_local(self, geom: BaseGeometry | dict) -> BaseGeometry:
        if isinstance(geom, dict):
            geom = shape(geom)
        return transform(self._fwd.transform, geom)

    def to_wgs84(self, geom: BaseGeometry) -> BaseGeometry:
        return transform(self._inv.transform, geom)

    def xy_to_lonlat(self, x, y):
        lon, lat = self._inv.transform(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        return lon, lat

    def lonlat_to_xy(self, lon, lat):
        return self._fwd.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
