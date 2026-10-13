"""Generate the SYNTHETIC demonstration ghat used by the prototype.

The geometry is invented for software testing and training only. It is NOT a
survey of any real Pushkaralu ghat. It is deliberately placed over open water in
the Bay of Bengal (85.0E, 15.0N) so it cannot be mistaken for a real location
when shown over a basemap. Replace it with surveyed data (see
docs/DATA_REPLACEMENT.md).

Outputs (in data/synthetic/):
  demo_site.geojson   - site features (WGS84) with pk_type attributes
  demo_dem.tif        - synthetic terrain raster (local metres, GeoTIFF)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, Polygon, box, mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.geo.crs import LocalProjection, local_crs  # noqa: E402

ORIGIN = (85.0, 15.0)  # lon, lat - synthetic, offshore on purpose
OUT = ROOT / "data" / "synthetic"

PROV = {"source": "synthetic", "synthetic": True}


def F(fid, pk_type, geom, **props):
    return {"id": fid, "pk_type": pk_type, "geom": geom, "props": props}


def features() -> list[dict]:
    fs = [
        # --- river and bathing --------------------------------------------
        F("river", "river", box(-500, -200, 500, 0), name="Synthetic river channel"),
        F("bath_main", "bathing_area", box(-150, -12, 150, 0), name="Main Ghat bathing area", height_m=0),
        F("bath_alt", "bathing_area", box(250, -10, 350, 0), name="Alternative Ghat B bathing area"),
        F("ghat_main", "ghat", box(-150, 0, 150, 25), name="Main Ghat steps", surface="steps"),
        F("ghat_alt", "ghat", box(250, 0, 350, 20), name="Alternative Ghat B steps", surface="steps"),
        F("plaza", "plaza", box(-150, 25, 150, 55), name="Ghat front plaza"),
        # --- built environment ---------------------------------------------
        F("temple", "temple", box(-30, 62, 30, 100), name="Synthetic temple", height_m=18),
        F("bld_1", "building", box(-140, 70, -60, 110), name="Synthetic building 1", height_m=9),
        F("bld_2", "building", box(80, 70, 160, 120), name="Synthetic building 2", height_m=12),
        F("bld_3", "building", box(-160, 230, -40, 300), name="Synthetic market block", height_m=7),
        F("bld_4", "building", box(40, 230, 160, 320), name="Synthetic lodge", height_m=15),
        F("wall_w", "wall", LineString([(-150, 57), (-110, 57)]), name="Compound wall W", height_m=2.5),
        F("wall_c", "wall", LineString([(-90, 57), (-10, 57)]), name="Compound wall C", height_m=2.5),
        F("wall_e", "wall", LineString([(110, 57), (150, 57)]), name="Compound wall E", height_m=2.5),
        F("barricade_1", "barricade", LineString([(-40, 30), (-40, 48)]), name="Queue barricade", height_m=1.1),
        # --- holding, transport, assembly ----------------------------------
        F("hold_w", "holding_area", box(-260, 80, -180, 160), name="Holding Area West", capacity_persons=9000),
        F("hold_e", "holding_area", box(180, 80, 260, 160), name="Holding Area East", capacity_persons=9000),
        F("bus", "bus_terminal", box(-40, 400, 40, 460), name="Synthetic bus terminal"),
        F("parking", "parking", box(-420, 150, -340, 230), name="Synthetic parking area"),
        F("assembly_w", "assembly_point", box(-400, 0, -332, 60), name="Assembly Point West"),
        # --- corridors -----------------------------------------------------
        F("c_bus", "corridor", LineString([(0, 399), (0, 200)]), name="Bus terminal walkway", width_m=8),
        F("c_hw_north", "corridor", LineString([(0, 200), (-220, 200), (-220, 161)]), name="West holding approach", width_m=6),
        F("c_he_north", "corridor", LineString([(0, 200), (220, 200), (220, 161)]), name="East holding approach", width_m=6),
        F("c_parking", "corridor", LineString([(-339, 190), (-220, 200)]), name="Parking walkway", width_m=5),
        F("c_hw_south", "corridor", LineString([(-220, 79), (-220, 40), (-151, 40)]), name="West holding release lane", width_m=5),
        F("c_he_south", "corridor", LineString([(220, 79), (220, 40), (151, 40)]), name="East holding release lane", width_m=5),
        F("c_temple_st", "corridor", LineString([(0, 200), (50, 170), (50, 125), (50, 56)]), name="Temple street", width_m=5),
        F("c_exit_w", "corridor", LineString([(-151, 30), (-331, 30)]), name="West exit road", width_m=6),
        F("c_exit_e1", "corridor", LineString([(151, 30), (300, 30)]), name="Riverside promenade east", width_m=6),
        F("c_alt_link", "corridor", LineString([(300, 30), (300, 21)]), name="Alt Ghat B access", width_m=6),
        F("c_exit_e2", "corridor", LineString([(300, 30), (430, 30)]), name="East exit road", width_m=6),
        F("c_emerg", "emergency_corridor", LineString([(-100, 56), (-100, 62), (-165, 62), (-165, 330)]), name="Emergency access corridor", width_m=5),
        # --- gates ---------------------------------------------------------
        F("g_bus", "gate", Point(0, 440), name="Bus terminal entry", role="entry", width_m=8),
        F("g_parking", "gate", Point(-380, 190), name="Parking entry", role="entry", width_m=6),
        F("g_exit_w", "gate", Point(-320, 30), name="West exit gate", role="exit", width_m=6),
        F("g_exit_e", "gate", Point(425, 30), name="East exit gate", role="exit", width_m=6),
        F("g_emerg", "gate", Point(-165, 325), name="Emergency exit N", role="exit", width_m=5, emergency_exit=True),
        # --- services --------------------------------------------------------
        F("fa_1", "first_aid", Point(-120, 45), name="First-aid post 1"),
        F("fa_2", "first_aid", Point(230, 190), name="First-aid post 2"),
        F("ctrl_1", "control_point", Point(10, 190), name="Control point (junction)"),
        F("ctrl_2", "control_point", Point(140, 50), name="Ghat control room"),
        F("hosp", "hospital", Point(-450, 320), name="Synthetic hospital"),
        F("spk_1", "speaker", Point(-60, 50), name="PA speaker 1"),
        F("spk_2", "speaker", Point(60, 50), name="PA speaker 2"),
        F("spk_3", "speaker", Point(-220, 120), name="PA speaker holding W"),
        F("spk_4", "speaker", Point(220, 120), name="PA speaker holding E"),
        F("road_n", "road", LineString([(-500, 470), (500, 470)]), name="Synthetic approach road"),
    ]
    return fs


def to_geojson(proj: LocalProjection) -> dict:
    out = []
    for f in features():
        g = proj.to_wgs84(f["geom"])
        props = {"pk_type": f["pk_type"], **f["props"], **PROV}
        out.append({"type": "Feature", "id": f["id"], "geometry": mapping(g), "properties": props})
    return {
        "type": "FeatureCollection",
        "name": "synthetic_demo_ghat",
        "metadata": {
            "title": "SYNTHETIC demonstration ghat - not surveyed data",
            "origin_lonlat": ORIGIN,
            "license": "CC0-1.0 (synthetic, generated by scripts/generate_synthetic_site.py)",
            "warning": "Invented geometry for testing. Not a real Pushkaralu site.",
        },
        "features": out,
    }


def dem(path: Path, proj: LocalProjection) -> None:
    import rasterio
    from rasterio.transform import from_origin

    res = 5.0
    minx, maxx, miny, maxy = -520.0, 520.0, -220.0, 500.0
    xs = np.arange(minx, maxx, res) + res / 2
    ys = np.arange(maxy, miny, -res) - res / 2
    X, Y = np.meshgrid(xs, ys)
    z = np.where(Y < 0, -2.5 + 2.5 * np.clip((Y + 30) / 30, 0, 1), 0.0)  # river bed slopes to water edge
    steps = (Y >= 0) & (Y < 25)
    z = np.where(steps, np.floor(Y / 2.5) * 0.5, z)  # 0.5 m risers every 2.5 m
    town = Y >= 25
    z = np.where(town, 5.0 + 0.008 * (Y - 25), z)
    z = z.astype("float32")
    with rasterio.open(
        path, "w", driver="GTiff", width=z.shape[1], height=z.shape[0], count=1, dtype="float32",
        crs=local_crs(*ORIGIN).to_wkt(), transform=from_origin(minx, maxy, res, res),
    ) as ds:
        ds.write(z, 1)
        ds.update_tags(SOURCE="synthetic", WARNING="Synthetic terrain - not surveyed")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    proj = LocalProjection(*ORIGIN)
    fc = to_geojson(proj)
    (OUT / "demo_site.geojson").write_text(json.dumps(fc, indent=1))
    dem(OUT / "demo_dem.tif", proj)
    print(f"wrote {len(fc['features'])} features and DEM to {OUT}")


if __name__ == "__main__":
    main()
