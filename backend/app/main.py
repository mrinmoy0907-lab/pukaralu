"""FastAPI application. Interactive API docs: /docs (OpenAPI at /openapi.json)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import meta, runs, scenarios, sites, zones
from .config import APP_VERSION, REPO_ROOT, get_settings
from .db import SessionLocal, migrate
from .services.jobs import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pushkaralu")


def _mark_interrupted_runs() -> None:
    from .models import Run

    db = SessionLocal()
    try:
        for r in db.query(Run).filter(Run.status.in_(("queued", "running"))):
            r.status, r.error = "failed", "server restarted while the run was in progress"
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate()
    _mark_interrupted_runs()
    from .services.ingest import ingest_all
    from .services.sites import ensure_default_profile

    db = SessionLocal()
    try:
        ensure_default_profile(db)
        if get_settings().auto_ingest:
            rep = ingest_all(db)
            for s_ in rep["sites"]:
                log.info("data folder %s: %d imported, %d unchanged, %d error(s)", s_["folder"], len(s_["imported"]),
                         len(s_["skipped"]), len(s_["errors"]))
    finally:
        db.close()
    manager()
    yield
    manager().shutdown()


app = FastAPI(
    title="Pushkaralu Crowd Digital Twin API",
    version=APP_VERSION,
    description=("GIS-enabled crowd simulation and evacuation planning. All simulation outputs are estimates and "
                 "must be reviewed by competent authorities before operational use."),
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])
for r in (meta.router, sites.router, scenarios.router, runs.router, zones.router):
    app.include_router(r)


@app.get("/sitedata/{path:path}", include_in_schema=False)
def sitedata(path: str):
    """Files of the data drop folder (3D Tiles, terrain, models). Pre-gzipped tiles
    (e.g. quantized-mesh .terrain from cesium-terrain-builder) get Content-Encoding: gzip."""
    root = get_settings().sites_dir.resolve()
    f = (root / path).resolve()
    if root not in f.parents or not f.is_file():
        return JSONResponse(status_code=404, content={"detail": "not found"})
    headers = {"Access-Control-Allow-Origin": "*"}
    with open(f, "rb") as fh:
        magic = fh.read(2)
    if magic == b"\x1f\x8b" and f.suffix.lower() != ".gz":
        headers["Content-Encoding"] = "gzip"
    media = {".terrain": "application/vnd.quantized-mesh", ".b3dm": "application/octet-stream",
             ".pnts": "application/octet-stream", ".glb": "model/gltf-binary", ".gltf": "model/gltf+json",
             ".json": "application/json"}.get(f.suffix.lower())
    return FileResponse(f, headers=headers, media_type=media)


@app.get("/api/docs/user-journeys.pdf", include_in_schema=False)
def user_journeys():
    f = REPO_ROOT / "docs" / "user-journeys.pdf"
    if not f.exists():
        return JSONResponse(status_code=404, content={"detail": "docs/user-journeys.pdf has not been generated"})
    return FileResponse(f, media_type="application/pdf", filename="user-journeys.pdf")


@app.get("/derived/{path:path}", include_in_schema=False)
def derived(path: str):
    root = get_settings().derived_dir.resolve()
    f = (root / path).resolve()
    if root not in f.parents or not f.is_file():
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return FileResponse(f)


@app.exception_handler(ValueError)
async def value_error(_req: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# Serve the built frontend (frontend/dist) when present, e.g. in the Docker image.
_dist = Path(REPO_ROOT / "frontend" / "dist")
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")
    if (_dist / "cesium").exists():
        app.mount("/cesium", StaticFiles(directory=_dist / "cesium"), name="cesium")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
