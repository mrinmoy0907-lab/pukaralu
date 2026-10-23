"""End-to-end API tests (FastAPI TestClient, SQLite, worker threads)."""
import io
import json
import zipfile

import numpy as np
import pyogrio
import shapely
from shapely.geometry import LineString, Point, box

from .conftest import ORIGIN, to_features, wait_run


def _demo_site(client):
    sites = client.get("/api/sites").json()
    syn = [s for s in sites if s["is_synthetic"]]
    real = [s for s in sites if not s["is_synthetic"]]
    assert syn and real, "both the synthetic demo site and the real OSM reference site are seeded"
    return syn[0], real[0]


def test_meta_and_seeded_sites(client):
    meta = client.get("/api/meta").json()
    assert {e["key"] for e in meta["engines"]} == {"jupedsim", "macro_ctm"}
    assert meta["live_sensor_integration"] is False
    syn, real = _demo_site(client)
    detail = client.get(f"/api/sites/{real['id']}").json()
    assert detail["datasets"][0]["license"] == "ODbL-1.0"
    assert detail["datasets"][0]["is_synthetic"] is False
    fc = client.get(f"/api/sites/{real['id']}/features").json()
    assert fc["features"][0]["properties"]["pk_type"] == "river"
    syn_detail = client.get(f"/api/sites/{syn['id']}").json()
    assert syn_detail["has_terrain"]
    assert {d["kind"] for d in syn_detail["datasets"]} == {"vector", "dem"}
    terr = client.get(f"/api/sites/{syn['id']}/terrain").json()
    assert len(terr["heights"]) == terr["height"] and len(terr["heights"][0]) == terr["width"]
    assert terr["min"] < 0 < terr["max"]  # river bed below, town above water level
    presets = client.get(f"/api/sites/{syn['id']}/presets").json()
    assert len(presets) == 10 and all(p["available"] for p in presets)
    assert all(p["config"]["walking_speed"]["mean"] > 0 for p in presets)  # full configs incl. defaults
    assert len(client.get(f"/api/sites/{syn['id']}/scenarios").json()) == 10


def test_feature_crud_and_validation(client):
    syn, _ = _demo_site(client)
    sid = syn["id"]
    bad = client.post(f"/api/sites/{sid}/features", json={"type": "Feature", "geometry": {"type": "Point", "coordinates": [85, 15]},
                                                          "properties": {"pk_type": "spaceship"}})
    assert bad.status_code == 422 and "unknown pk_type" in bad.json()["detail"]
    wrong_geom = client.post(f"/api/sites/{sid}/features", json={"type": "Feature", "geometry": {"type": "Point", "coordinates": [85, 15]},
                                                                 "properties": {"pk_type": "corridor"}})
    assert wrong_geom.status_code == 422
    f = to_features([("new_c", "corridor", LineString([(0, 199), (0, 150)]), {"width_m": 3})])[0]
    r = client.post(f"/api/sites/{sid}/features", json=f)
    assert r.status_code == 201
    fid = r.json()["id"]
    f2 = r.json()
    f2["properties"]["width_m"] = 6
    assert client.put(f"/api/sites/{sid}/features/{fid}", json=f2).json()["properties"]["width_m"] == 6
    bad_w = dict(f2, properties={**f2["properties"], "width_m": -1})
    assert client.put(f"/api/sites/{sid}/features/{fid}", json=bad_w).status_code == 422
    net = client.get(f"/api/sites/{sid}/network").json()
    assert net["stats"]["nodes"] > 30 and net["stats"]["connected_components"] == 1
    assert client.delete(f"/api/sites/{sid}/features/{fid}").status_code == 204
    routes = client.post(f"/api/sites/{sid}/routes", json={"from_id": "g_bus", "to_id": "bath_main", "k": 3}).json()
    assert len(routes["routes"]) == 3
    assert routes["routes"][0]["free_flow_time_s"] <= routes["routes"][1]["free_flow_time_s"]
    blocked = client.post(f"/api/sites/{sid}/routes", json={"from_id": "g_bus", "to_id": "bath_main", "k": 1, "closed_corridors": ["c_bus"]}).json()
    assert blocked["unreachable"] is True


def test_import_formats(client, tmp_path):
    r = client.post("/api/sites", json={"name": "Import test", "origin_lon": ORIGIN[0], "origin_lat": ORIGIN[1]})
    sid = r.json()["id"]
    # GeoPackage in a projected CRS (UTM 45N) with a type attribute that needs mapping
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    feats = to_features([("a", "plaza", box(0, 0, 30, 30), {}), ("b", "corridor", LineString([(30.5, 15), (60, 15)]), {})])
    geoms = [shapely.transform(shapely.geometry.shape(f["geometry"]), lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
             for f in feats]
    gpkg = tmp_path / "survey.gpkg"
    pyogrio.raw.write(gpkg, geometry=np.array([shapely.to_wkb(g) for g in geoms], dtype=object), field_data=[np.array(["open_space", "footway"], dtype=object),
                      np.array(["Plaza A", "Path B"], dtype=object)], fields=["kind", "name"], crs="EPSG:32645",
                      driver="GPKG", geometry_type="Unknown")
    with open(gpkg, "rb") as fh:
        res = client.post(f"/api/sites/{sid}/import", files={"file": ("survey.gpkg", fh)},
                          data={"license": "test", "type_field": "kind", "type_map": json.dumps({"open_space": "plaza", "footway": "corridor"})})
    assert res.status_code == 200, res.text
    assert res.json()["imported"] == 2 and "32645" in res.json()["source_crs"]
    fc = client.get(f"/api/sites/{sid}/features").json()["features"]
    plaza = next(f for f in fc if f["properties"]["pk_type"] == "plaza")
    lon, lat = plaza["geometry"]["coordinates"][0][0]
    assert abs(lon - ORIGIN[0]) < 0.001 and abs(lat - ORIGIN[1]) < 0.001  # reprojected back to WGS84
    # zipped shapefile with a single assigned type
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gate = to_features([("g", "gate", Point(59, 15), {})])[0]
    pyogrio.raw.write(shp_dir / "gates.shp", geometry=np.array([shapely.to_wkb(shapely.geometry.shape(gate["geometry"]))], dtype=object),
                      field_data=[np.array(["exit"], dtype=object)], fields=["role"], crs="EPSG:4326", driver="ESRI Shapefile", geometry_type="Point")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in shp_dir.iterdir():
            zf.write(p, p.name)
    res = client.post(f"/api/sites/{sid}/import", files={"file": ("gates.zip", buf.getvalue())}, data={"license": "test", "pk_type": "gate"})
    assert res.status_code == 200, res.text
    gates = client.get(f"/api/sites/{sid}/features?pk_type=gate").json()["features"]
    assert gates and gates[0]["properties"]["role"] == "exit"
    # bbox filter
    assert client.get(f"/api/sites/{sid}/features?bbox=0,0,1,1").json()["features"] == []
    # licence is mandatory, rubbish is rejected with a message
    res = client.post(f"/api/sites/{sid}/import", files={"file": ("x.geojson", b"not json")}, data={"license": ""})
    assert res.status_code == 422
    res = client.post(f"/api/sites/{sid}/import", files={"file": ("x.geojson", b"not json")}, data={"license": "x"})
    assert res.status_code == 422 and "GDAL" in res.json()["detail"]


def test_scenario_validation_errors(client):
    syn, _ = _demo_site(client)
    sid = syn["id"]
    cfg = {"name": "bad", "engine": "macro_ctm", "time_step_s": 1, "demand": [{"gate_id": "g_exit_w", "rate_per_min": 10}],
           "destinations": [{"target_id": "nowhere", "share": 1}]}
    r = client.post(f"/api/sites/{sid}/scenarios/validate", json=cfg)
    assert r.status_code == 422
    errs = r.json()["detail"]["errors"]
    assert any("not an enabled entry gate" in e for e in errs) and any("unknown area 'nowhere'" in e for e in errs)
    r = client.post(f"/api/sites/{sid}/scenarios/validate", json={"name": "x", "engine": "jupedsim", "time_step_s": 0.5})
    assert r.status_code == 422


def test_run_compare_and_reports(client):
    syn, _ = _demo_site(client)
    sid = syn["id"]
    base = {"engine": "macro_ctm", "time_step_s": 1, "duration_s": 900,
            "demand": [{"gate_id": "g_bus", "rate_per_min": 150}, {"gate_id": "g_parking", "rate_per_min": 60}],
            "destinations": [{"target_id": "bath_main", "share": 1, "dwell_s": 60}],
            "holding_stops": [{"holding_id": "hold_w", "share": 0.5, "dwell_s": 60}]}
    a = client.post(f"/api/sites/{sid}/scenarios", json={"name": "Baseline", "config": base}).json()
    alt_cfg = {**base, "corridor_overrides": [{"corridor_id": "c_temple_st", "enabled": False}],
               "diversion": {"activation_s": 200, "destinations": [{"target_id": "bath_alt", "share": 1, "dwell_s": 60}]}}
    b = client.post(f"/api/sites/{sid}/scenarios", json={"name": "Alternative", "config": alt_cfg}).json()
    ra = client.post(f"/api/scenarios/{a['id']}/runs", json={}).json()
    rb = client.post(f"/api/scenarios/{b['id']}/runs", json={}).json()
    ra, rb = wait_run(client, ra["id"]), wait_run(client, rb["id"])
    assert ra["status"] == "completed", ra["error"]
    assert rb["status"] == "completed", rb["error"]
    s = ra["summary"]
    assert s["method_type"] == "macroscopic" and s["estimate_label"] == "SIMULATED ESTIMATE"
    assert s["total_arrivals"] > 1500 and s["total_exited"] > 0
    an = client.get(f"/api/runs/{ra['id']}/analysis").json()
    assert an["holding"] and an["holding"][0]["holding_id"] == "hold_w"
    series = client.get(f"/api/runs/{ra['id']}/series").json()
    assert len(series["times"]) == 901 and "hold_w" in series["zones"]
    grid = client.get(f"/api/runs/{ra['id']}/grid?every=10").json()
    assert len(grid["frames"]) == len(grid["times"]) == 91
    assert client.get(f"/api/runs/{ra['id']}/links").status_code == 200
    assert client.get(f"/api/runs/{ra['id']}/agents").status_code == 404  # macroscopic: no agents
    pdf = client.get(f"/api/runs/{ra['id']}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/runs/{ra['id']}/export.zip").content))
    assert {"summary.csv", "zones.csv", "timeseries.csv", "exits.csv"} <= set(z.namelist())
    assert "SIMULATED ESTIMATES" in z.read("summary.csv").decode()
    assert client.get(f"/api/runs/{ra['id']}/density.geojson").json()["features"]
    cmp = client.get(f"/api/compare?a={ra['id']}&b={rb['id']}").json()
    rows = {r["key"]: r for r in cmp["rows"]}
    assert rows["max_density_ppm2"]["baseline"] == ra["summary"]["max_density_ppm2"]
    assert rows["max_density_ppm2"]["difference"] == rb["summary"]["max_density_ppm2"] - ra["summary"]["max_density_ppm2"]
    assert client.get(f"/api/compare/report.pdf?a={ra['id']}&b={rb['id']}").content[:4] == b"%PDF"
    lay = client.get(f"/api/scenarios/{b['id']}/layout.geojson").json()
    temple = next(f for f in lay["features"] if f["id"] == "c_temple_st")
    assert temple["properties"]["enabled"] is False
    assert any(f["properties"].get("pk_type") == "diversion_target" for f in lay["features"])
    # review workflow
    assert client.patch(f"/api/runs/{ra['id']}/review", json={"status": "approved"}).status_code == 422
    rv = client.patch(f"/api/runs/{ra['id']}/review", json={"status": "reviewed", "reviewed_by": "Crowd safety officer"}).json()
    assert rv["review"]["status"] == "reviewed"
    # reproducibility: re-running gives identical metrics
    rr = wait_run(client, client.post(f"/api/runs/{ra['id']}/rerun").json()["id"])
    assert rr["summary"]["max_density_ppm2"] == ra["summary"]["max_density_ppm2"]
    assert rr["features_hash"] == ra["features_hash"]


def test_agent_based_run_via_api(client):
    syn, _ = _demo_site(client)
    cfg = {"engine": "jupedsim", "duration_s": 40, "demand": [{"gate_id": "g_bus", "rate_per_min": 60}],
           "destinations": [{"target_id": "bath_main", "share": 1, "dwell_s": 30}]}
    sc = client.post(f"/api/sites/{syn['id']}/scenarios", json={"name": "tiny", "config": cfg}).json()
    run = wait_run(client, client.post(f"/api/scenarios/{sc['id']}/runs", json={}).json()["id"])
    assert run["status"] == "completed", run["error"]
    assert run["method"].startswith("Agent-based")
    frames = client.get(f"/api/runs/{run['id']}/agents").json()["frames"]
    assert len(frames) == 41 and len(frames[-1]["ids"]) > 10
    assert all(84.99 < x < 85.01 for x in frames[-1]["lon"])


def test_cancel_run(client):
    syn, _ = _demo_site(client)
    cfg = {"engine": "jupedsim", "duration_s": 3000, "demand": [{"gate_id": "g_bus", "rate_per_min": 30}],
           "destinations": [{"target_id": "bath_main", "share": 1, "dwell_s": 30}]}
    sc = client.post(f"/api/sites/{syn['id']}/scenarios", json={"name": "long", "config": cfg}).json()
    run = client.post(f"/api/scenarios/{sc['id']}/runs", json={}).json()
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 200
    assert wait_run(client, run["id"])["status"] == "cancelled"
    assert client.get(f"/api/runs/{run['id']}/analysis").status_code == 409


def test_observations_and_thresholds(client):
    syn, _ = _demo_site(client)
    sid = syn["id"]
    csv = "zone_fid,count,kind,t_offset_s,source\nhold_w,120,observed,60,manual\nhold_w,300,forecast,600,manual\n"
    r = client.post(f"/api/sites/{sid}/observations/csv", files={"file": ("obs.csv", csv)})
    assert r.status_code == 201 and {o["kind"] for o in r.json()} == {"observed", "forecast"}
    bad = client.post(f"/api/sites/{sid}/observations/csv", files={"file": ("obs.csv", "zone_fid,count\nnope,1\n")})
    assert bad.status_code == 422
    prof = client.get("/api/threshold-profiles").json()[0]
    assert prof["status"] == "draft"
    body = {"name": prof["name"], "values": prof["values"], "status": "approved"}
    assert client.put(f"/api/threshold-profiles/{prof['id']}", json=body).status_code == 422  # approver required
    body.update(approved_by="District Collector", approved_on="2026-10-01")
    assert client.put(f"/api/threshold-profiles/{prof['id']}", json=body).json()["status"] == "approved"
    body["values"] = {**prof["values"], "density_bands": [3, 2, 1]}
    assert client.put(f"/api/threshold-profiles/{prof['id']}", json=body).status_code == 422
