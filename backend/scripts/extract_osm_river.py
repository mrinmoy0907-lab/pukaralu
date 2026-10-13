"""Extract the real Godavari river polygon near Rajahmundry from the
``@geo-maps/earth-rivers-10m`` dataset (derived from OpenStreetMap, ODbL 1.0).

Usage:
    npm pack @geo-maps/earth-rivers-10m && tar xzf geo-maps-earth-rivers-10m-*.tgz
    python backend/scripts/extract_osm_river.py package/map.geo.json

The output (data/real/godavari_rajahmundry_osm.geojson) is real, openly
licensed GIS data, generalised to ~10 m. It only shows the river; it contains
no ghat, crowd-management or surveyed infrastructure geometry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import box, mapping, shape

ROOT = Path(__file__).resolve().parents[2]
BBOX = (81.70, 16.93, 81.86, 17.06)  # lon/lat window around Rajahmundry


def main(src: str) -> None:
    data = json.loads(Path(src).read_text())
    geoms = data["geometries"] if data["type"] == "GeometryCollection" else [f["geometry"] for f in data["features"]]
    clip = box(*BBOX)
    parts = [shape(g).intersection(clip) for g in geoms]
    parts = [p for p in parts if not p.is_empty]
    fc = {
        "type": "FeatureCollection",
        "name": "godavari_rajahmundry_osm",
        "metadata": {
            "source": "OpenStreetMap contributors via @geo-maps/earth-rivers-10m v0.6.0 (github.com/simonepri/geo-maps)",
            "license": "ODbL-1.0 (data), https://opendatacommons.org/licenses/odbl/1-0/",
            "attribution": "(c) OpenStreetMap contributors",
            "resolution": "generalised, ~10 m absolute error",
            "clip_bbox_lonlat": BBOX,
        },
        "features": [
            {
                "type": "Feature",
                "id": f"godavari_{i}",
                "geometry": mapping(p.simplify(0.00002)),
                "properties": {"pk_type": "river", "name": "Godavari river (OSM)", "source": "OpenStreetMap",
                               "license": "ODbL-1.0", "synthetic": False},
            }
            for i, p in enumerate(parts)
        ],
    }
    out = ROOT / "data" / "real" / "godavari_rajahmundry_osm.geojson"
    out.write_text(json.dumps(fc))
    print(f"wrote {out} ({out.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main(sys.argv[1])
