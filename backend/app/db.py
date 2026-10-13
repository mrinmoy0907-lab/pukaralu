from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine: Engine | None = None
_Session: sessionmaker | None = None


def engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        url = get_settings().database_url
        kw = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engine = create_engine(url, **kw)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _fk(dbapi_conn, _):  # pragma: no cover - trivial
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def SessionLocal() -> Session:
    engine()
    return _Session()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_postgis: bool | None = None


def is_postgis() -> bool:
    """True when the database is PostgreSQL with the PostGIS geom column installed."""
    global _postgis
    if _postgis is None:
        eng = engine()
        if eng.dialect.name != "postgresql":
            _postgis = False
        else:
            from sqlalchemy import text

            with eng.connect() as c:
                _postgis = c.execute(text("SELECT 1 FROM information_schema.columns "
                                          "WHERE table_name='features' AND column_name='geom'")).first() is not None
    return _postgis


def migrate() -> None:
    """Apply Alembic migrations (creates the schema on first start)."""
    from alembic import command
    from alembic.config import Config

    here = Path(__file__).resolve().parents[1]
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def reset_engine() -> None:
    """Used by tests to point the app at a fresh database."""
    global _engine, _Session, _postgis
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None
    _postgis = None
