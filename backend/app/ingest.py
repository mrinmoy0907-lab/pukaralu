"""Command line: scan the data drop folder and load new/changed data.

    python -m app.ingest            (run from the backend folder)
"""
from __future__ import annotations

import json

from .db import SessionLocal, migrate
from .services.ingest import ingest_all
from .services.sites import ensure_default_profile


def main() -> None:
    migrate()
    db = SessionLocal()
    try:
        ensure_default_profile(db)
        print(json.dumps(ingest_all(db), indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
