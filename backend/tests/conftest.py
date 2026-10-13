from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point, box, mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

ORIGIN = (85.0, 15.0)


@pytest.fixture(scope="session")
def demo_features() -> list[dict]:
    return json.loads((ROOT / "data" / "synthetic" / "demo_site.geojson").read_text())["features"]


def to_features(items, origin=ORIGIN) -> list[dict]:
    """[(id, pk_type, local shapely geometry, props)] -> WGS84 GeoJSON features."""
    from app.geo.crs import LocalProjection

    proj = LocalProjection(*origin)
    return [{"type": "Feature", "id": fid, "geometry": mapping(proj.to_wgs84(g)), "properties": {"pk_type": t, "name": fid, **p}}
            for fid, t, g, p in items]


@pytest.fixture
def toy_features() -> list[dict]:
    """Two rooms joined by a corridor and an alternative longer corridor.

    entry gate (west room) -> corridor A (short, 3 m) or B (long, 5 m) -> east room (destination)
    -> exit gate east; second exit north-east via corridor C.
    """
    return to_features([
        ("room_w", "plaza", box(0, 0, 20, 20), {}),
        ("room_e", "bathing_area", box(60, 0, 80, 20), {}),
        ("c_a", "corridor", LineString([(20.5, 10), (59.5, 10)]), {"width_m": 3}),
        ("c_b", "corridor", LineString([(10, 20.5), (10, 40), (70, 40), (70, 20.5)]), {"width_m": 5}),
        ("c_exit", "corridor", LineString([(80.5, 5), (100, 5)]), {"width_m": 4}),
        ("c_ne", "corridor", LineString([(70, 40), (70, 60)]), {"width_m": 4}),
        ("g_in", "gate", Point(2, 10), {"role": "entry", "width_m": 4}),
        ("g_out", "gate", Point(99, 5), {"role": "exit", "width_m": 4}),
        ("g_ne", "gate", Point(70, 59), {"role": "exit", "width_m": 4}),
        ("pillar", "building", box(40, 37, 42, 38), {"height_m": 3}),
    ])


def _reset_pg(url: str) -> None:
    from sqlalchemy import create_engine, text

    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    eng.dispose()


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Set PK_TEST_PG_URL=postgresql+psycopg://... to run the API tests against PostgreSQL/PostGIS.
    pg = os.environ.get("PK_TEST_PG_URL")
    if pg:
        _reset_pg(pg)
    monkeypatch.setenv("PK_DATABASE_URL", pg or f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("PK_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("PK_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("PK_JOB_MODE", "thread")
    monkeypatch.setenv("PK_MAX_WORKERS", "2")
    from app import config, db
    from app.services import jobs

    config.get_settings.cache_clear()
    db.reset_engine()
    jobs.reset_manager()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
    jobs.reset_manager()
    db.reset_engine()
    config.get_settings.cache_clear()
    for k in ("PK_DATABASE_URL", "PK_RESULTS_DIR", "PK_UPLOAD_DIR", "PK_JOB_MODE", "PK_MAX_WORKERS"):
        os.environ.pop(k, None)


def wait_run(client, run_id, timeout=240):
    import time

    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/runs/{run_id}").json()
        if r["status"] in ("completed", "failed", "cancelled"):
            return r
        time.sleep(0.3)
    raise AssertionError(f"run {run_id} did not finish")
