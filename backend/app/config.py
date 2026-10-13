"""Application settings, read from environment variables (see .env.example)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PK_", env_file=".env", extra="ignore")

    # SQLite works out of the box; set to postgresql+psycopg://... for PostGIS.
    database_url: str = f"sqlite:///{REPO_ROOT / 'var' / 'pushkaralu.db'}"
    results_dir: Path = REPO_ROOT / "var" / "results"
    upload_dir: Path = REPO_ROOT / "var" / "uploads"
    data_dir: Path = REPO_ROOT / "data"
    # Number of simulations that may run concurrently in worker processes.
    max_workers: int = 2
    # "process" (default, isolated worker processes) or "thread" (used by tests)
    job_mode: str = "process"
    # Hard upper bounds that protect the server from accidental huge runs.
    max_agents: int = 20000
    max_duration_s: float = 4 * 3600
    seed_demo_data: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.results_dir.mkdir(parents=True, exist_ok=True)
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    if s.database_url.startswith("sqlite:///"):
        Path(s.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return s
