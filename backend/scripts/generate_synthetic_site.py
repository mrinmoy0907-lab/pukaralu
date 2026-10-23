"""Generate the SYNTHETIC demonstration layouts used by the prototype.

The layout geometry is invented for software testing and training only. It is
NOT a survey of any real Pushkaralu ghat. Two data-drop folders are written
(they are loaded like any user-supplied site, see docs/DATA_FOLDER.md):

data/sites/01_synthetic_offshore_demo/
    The layout placed over open sea (85.0E, 15.0N) with a synthetic river and a
    synthetic DEM, so it can never be mistaken for a real place.

data/sites/02_sim_layout_on_real_map_rajahmundry/
    The same SIM DATA layout (without the synthetic river and DEM) placed along a
    straight stretch of the real OpenStreetMap Godavari east bank at
    Rajahmundry, so planners can see simulation features over the real map. The
    river polygon is real (ODbL); every other feature is illustrative SIM DATA,
    labelled as such in the application, and does not represent the real ghats.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import shapely.affinity
from shapely.geometry import LineString, Point, Polygon, box, mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.geo.crs import LocalProjection, local_crs  # noqa: E402

ORIGIN = (85.0, 15.0)  # lon, lat - synthetic, offshore on purpose
SITES = ROOT / "data" / "sites"
OUT = SITES / "01_synthetic_offshore_demo"
REAL_OUT = SITES / "02_sim_layout_on_real_map_rajahmundry"
OSM_RIVER = ROOT / "data" / "reference" / "godavari_rajahmundry_osm.geojson"
# straight stretch of the generalised OSM east bank (lon, lat), south -> north
BANK_A = (81.76848, 16.99376)
BANK_B = (81.76827, 17.01477)
BANK_ORIGIN_LAT = 17.0040

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


def to_geojson(proj: LocalProjection, frame=None, skip=(), origin=ORIGIN, title=None) -> dict:
    """``frame`` = (ex, ey): unit vectors of the layout x/y axes in local metres."""
    out = []
    for f in features():
        if f["pk_type"] in skip:
            continue
        geom = f["geom"]
        if frame is not None:
            (ax, ay), (bx, by) = frame
            geom = shapely.affinity.affine_transform(geom, [ax, bx, ay, by, 0.0, 0.0])
        g = proj.to_wgs84(geom)
        props = {"pk_type": f["pk_type"], **f["props"], **PROV}
        out.append({"type": "Feature", "id": f["id"], "geometry": mapping(g), "properties": props})
    return {
        "type": "FeatureCollection",
        "name": "synthetic_demo_ghat",
        "metadata": {
            "title": title or "SYNTHETIC demonstration ghat - not surveyed data",
            "origin_lonlat": origin,
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


def bank_frame():
    """Origin on the OSM bank and layout axes: x along the bank (northwards), y inland (east)."""
    t = (BANK_ORIGIN_LAT - BANK_A[1]) / (BANK_B[1] - BANK_A[1])
    origin = (round(BANK_A[0] + t * (BANK_B[0] - BANK_A[0]), 6), BANK_ORIGIN_LAT)
    proj = LocalProjection(*origin)
    ax, ay = proj.lonlat_to_xy(*BANK_A)
    bx, by = proj.lonlat_to_xy(*BANK_B)
    d = np.array([bx - ax, by - ay], dtype=float)
    d /= np.linalg.norm(d)
    n = np.array([d[1], -d[0]])  # right-hand normal: east of a northward bank
    return origin, proj, (tuple(d), tuple(n))


def write_manifest(folder: Path, manifest: dict) -> None:
    (folder / "site.json").write_text(json.dumps(manifest, indent=2))


def main() -> None:
    # 1) offshore synthetic demo (synthetic river + DEM)
    (OUT / "vector").mkdir(parents=True, exist_ok=True)
    (OUT / "dem").mkdir(parents=True, exist_ok=True)
    proj = LocalProjection(*ORIGIN)
    fc = to_geojson(proj)
    (OUT / "vector" / "demo_site.geojson").write_text(json.dumps(fc, indent=1))
    dem(OUT / "dem" / "demo_dem.tif", proj)
    write_manifest(OUT, {
        "name": "SYNTHETIC demonstration ghat (offshore)",
        "description": ("Invented layout for testing and training. NOT surveyed data and NOT a real Pushkaralu ghat. "
                        "Placed offshore on purpose. Replace with surveyed GIS data (docs/DATA_FOLDER.md)."),
        "is_synthetic": True, "origin": list(ORIGIN), "basemap": "grid", "create_presets": True,
        "defaults": {"license": "CC0-1.0 (synthetic)", "attribution": "Synthetic demo data", "is_synthetic": True,
                     "is_surveyed": False},
    })
    # 2) same SIM DATA layout along the real OSM bank at Rajahmundry (real river, no synthetic DEM)
    origin, rproj, frame = bank_frame()
    (REAL_OUT / "vector").mkdir(parents=True, exist_ok=True)
    fc2 = to_geojson(rproj, frame=frame, skip=("river",), origin=origin,
                     title="SIM DATA layout on the real map - illustrative, not the real ghats")
    (REAL_OUT / "vector" / "sim_layout.geojson").write_text(json.dumps(fc2, indent=1))
    (REAL_OUT / "vector" / "godavari_river_osm.geojson").write_text(OSM_RIVER.read_text())
    write_manifest(REAL_OUT, {
        "name": "SIM DATA layout on real map - Rajahmundry riverfront",
        "description": ("Real basemap and real OpenStreetMap river polygon (ODbL). All ghats, corridors, gates, holding "
                        "areas and buildings are ILLUSTRATIVE SIM DATA placed on a straight stretch of the river bank; they "
                        "do not represent the real Pushkar Ghat or any surveyed infrastructure."),
        "is_synthetic": True, "origin": list(origin), "basemap": "osm", "create_presets": True,
        "defaults": {"license": "CC0-1.0 (synthetic)", "attribution": "Synthetic SIM DATA layout", "is_synthetic": True,
                     "is_surveyed": False},
        "files": {"vector/godavari_river_osm.geojson": {
            "license": "ODbL-1.0", "attribution": "(c) OpenStreetMap contributors", "is_synthetic": False,
            "is_surveyed": False, "notes": "Generalised OSM water polygon (@geo-maps/earth-rivers-10m)"}},
    })
    print(f"wrote {OUT} and {REAL_OUT}")


if __name__ == "__main__":
    main()
