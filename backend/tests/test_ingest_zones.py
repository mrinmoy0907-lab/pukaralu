"""Data drop folder ingestion and the zone workbench (P-01)."""
import json
import os

import numpy as np
import pytest
from shapely.geometry import LineString, Point, box

from .conftest import ORIGIN, to_features


def _write_site(folder, features):
    import rasterio
    from rasterio.transform import from_origin

    (folder / "vector").mkdir(parents=True)
    (folder / "dem").mkdir()
    (folder / "imagery").mkdir()
    (folder / "tiles3d" / "buildings").mkdir(parents=True)
    (folder / "models").mkdir()
    (folder / "vector" / "survey.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    lon, lat = ORIGIN
    # DTM in WGS84 covering the site, sloping 1 m per ~10 m eastwards
    z = np.tile(np.linspace(0, 12, 120, dtype="float32"), (120, 1))
    with rasterio.open(folder / "dem" / "dtm.tif", "w", driver="GTiff", width=120, height=120, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(lon - 0.0005, lat + 0.0012, 0.00001, 0.00001)) as ds:
        ds.write(z, 1)
    rgb = (np.random.default_rng(0).random((3, 50, 50)) * 255).astype("uint8")
    with rasterio.open(folder / "imagery" / "ortho.tif", "w", driver="GTiff", width=50, height=50, count=3, dtype="uint8",
                       crs="EPSG:4326", transform=from_origin(lon - 0.0002, lat + 0.0006, 0.00002, 0.00002)) as ds:
        ds.write(rgb)
    (folder / "tiles3d" / "buildings" / "tileset.json").write_text(json.dumps({"asset": {"version": "1.0"}, "geometricError": 1, "root": {}}))
    (folder / "models" / "pandal.glb").write_bytes(b"glTF\x02\x00\x00\x00")
    (folder / "site.json").write_text(json.dumps({
        "name": "Drop folder test", "is_synthetic": True, "origin": list(ORIGIN), "basemap": "satellite",
        "defaults": {"license": "test licence", "attribution": "test", "is_synthetic": True},
        "models": [{"file": "models/pandal.glb", "lon": lon, "lat": lat, "height": 2, "heading_deg": 30}],
        "create_presets": True,
    }))


@pytest.fixture
def drop_client(tmp_path, monkeypatch, toy_features):
    sites = tmp_path / "sites"
    _write_site(sites / "test_site", toy_features)
    monkeypatch.setenv("PK_SITES_DIR", str(sites))
    return sites


def test_drop_folder_ingest(drop_client, client):
    sites = client.get("/api/sites").json()
    assert [s["name"] for s in sites] == ["Drop folder test"]
    s = client.get(f"/api/sites/{sites[0]['id']}").json()
    assert s["has_terrain"] and s["basemap"] == "satellite"
    kinds = {d["filename"]: d["kind"] for d in s["datasets"]}
    assert kinds == {"vector/survey.geojson": "vector", "dem/dtm.tif": "dem"}
    a = s["assets"]
    assert a["tilesets"][0]["url"] == "/sitedata/test_site/tiles3d/buildings/tileset.json"
    assert a["models"][0]["heading_deg"] == 30 and a["models"][0]["url"].endswith("pandal.glb")
    assert a["imagery"] and a["imagery"][0]["url"].endswith(".png")
    assert client.get(a["tilesets"][0]["url"]).json()["asset"]["version"] == "1.0"
    assert client.get(a["imagery"][0]["url"]).content[:4] == b"\x89PNG"
    assert client.get("/sitedata/%2e%2e/%2e%2e/%2e%2e/etc/passwd").status_code == 404
    terr = client.get(f"/api/sites/{s['id']}/terrain").json()
    assert terr["max"] > terr["min"] + 3
    assert len(client.get(f"/api/sites/{s['id']}/scenarios").json()) >= 1  # presets created
    # unchanged rescan imports nothing; a changed file is re-imported and replaces old features
    rep = client.post("/api/ingest").json()
    site_rep = rep["sites"][0]
    assert site_rep["imported"] == [] and "vector/survey.geojson" in site_rep["skipped"]
    vec = drop_client / "test_site" / "vector" / "survey.geojson"
    fc = json.loads(vec.read_text())
    fc["features"] = [f for f in fc["features"] if f["id"] != "pillar"]
    vec.write_text(json.dumps(fc))
    rep = client.post("/api/ingest").json()["sites"][0]
    assert any(i["file"] == "vector/survey.geojson" for i in rep["imported"])
    fids = {f["id"] for f in client.get(f"/api/sites/{s['id']}/features").json()["features"]}
    assert "pillar" not in fids and "c_a" in fids
    assert len([d for d in client.get(f"/api/sites/{s['id']}/datasets").json() if d["kind"] == "vector"]) == 1


def test_zone_area_topology_and_approval(client):
    syn = next(s for s in client.get("/api/sites").json() if s["has_terrain"])
    sid = syn["id"]
    reg = client.get(f"/api/sites/{sid}/zones").json()["zones"]
    assert {"hold_w", "ghat_main", "bath_main"} <= {z["fid"] for z in reg}
    # ghat steps: the DEM slope adds surface; bathing area inside the river is not excluded as water
    ghat = client.post(f"/api/sites/{sid}/zones/ghat_main/area").json()
    assert ghat["area"]["gross_m2"] == pytest.approx(7500, rel=0.01)
    assert ghat["area"]["step_surface_gain_m2"] > 0
    bath = client.post(f"/api/sites/{sid}/zones/bath_main/area").json()["area"]
    assert bath["water_excluded_m2"] == pytest.approx(0, abs=1)
    # a zone drawn across the temple and the river: both are excluded
    z = to_features([("sector_c", "zone", box(-40, -30, 40, 110), {"zone_type": "sector", "owner_department": "Police"})])[0]
    assert client.post(f"/api/sites/{sid}/features", json=z).status_code == 201
    a = client.post(f"/api/sites/{sid}/zones/sector_c/area").json()
    ar = a["area"]
    assert ar["water_excluded_m2"] == pytest.approx(80 * 18, rel=0.02)  # 30 m of river minus the 12 m bathing strip
    assert ar["obstructions_m2"] == pytest.approx(60 * 38, rel=0.02)  # synthetic temple 60 x 38 m
    assert ar["net_walkable_m2"] < ar["gross_m2"]
    assert a["topology"]["valid"]
    # overlapping sibling zone -> topology error -> cannot be activated
    z2 = to_features([("sector_d", "zone", box(0, 0, 80, 60), {"zone_type": "sector"})])[0]
    client.post(f"/api/sites/{sid}/features", json=z2)
    t = client.post(f"/api/sites/{sid}/zones/sector_d/area").json()["topology"]
    assert not t["valid"] and "overlaps" in t["issues"][0]
    r = client.post(f"/api/sites/{sid}/zones/approve", json={"fids": ["sector_d"], "status": "active", "approved_by": "R3"})
    assert r.status_code == 422
    assert client.post(f"/api/sites/{sid}/zones/approve", json={"fids": ["hold_w"], "status": "active"}).status_code == 422
    ok = client.post(f"/api/sites/{sid}/zones/approve", json={"fids": ["hold_w", "ghat_main"], "status": "active",
                                                            "approved_by": "Zone In-charge (R3)", "approval_remarks": "verified",
                                                            "effective_from": "2026-10-10", "effective_to": "2026-10-31"})
    assert ok.status_code == 200, ok.text
    reg = {z["fid"]: z for z in client.get(f"/api/sites/{sid}/zones").json()["zones"]}
    assert reg["hold_w"]["status"] == "active" and reg["hold_w"]["approved_by"] == "Zone In-charge (R3)"
    assert reg["sector_c"]["status"] == "draft"
