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

from .api import meta, runs, scenarios, sites
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
    if get_settings().seed_demo_data:
        from .services.sites import seed_demo

        db = SessionLocal()
        try:
            seed_demo(db)
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
for r in (meta.router, sites.router, scenarios.router, runs.router):
    app.include_router(r)


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
