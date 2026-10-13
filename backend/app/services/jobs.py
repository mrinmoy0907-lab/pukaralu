"""Background execution of simulations.

Each run executes in its own worker *process* (multiprocessing, spawn context)
so long simulations never block the API, can use a separate CPU core and can be
cancelled. A dispatcher thread limits concurrency to ``max_workers``; progress
messages flow back over a queue and are written to the ``runs`` table, from
which the API streams them to the browser (server-sent events).

The interface (submit / cancel / status) is deliberately small so the job
backend can be swapped for Celery/RQ/Kubernetes jobs without touching the API.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

from ..db import SessionLocal
from ..models import Run

log = logging.getLogger(__name__)


def _worker(run_id: str, features: list, origin: tuple, cfg: dict, profile: dict, out_dir: str, q, cancel_evt) -> None:
    from ..sim.runner import run_scenario

    def progress(frac, msg):
        q.put(("progress", run_id, float(frac), str(msg)))

    try:
        analysis = run_scenario(features, origin, cfg, profile, Path(out_dir), progress=progress,
                                cancelled=cancel_evt.is_set)
        q.put(("done", run_id, analysis["summary"], analysis["engine"]))
    except Exception as exc:  # noqa: BLE001 - report every failure to the user
        if type(exc).__name__ == "Cancelled":
            q.put(("cancelled", run_id, None, None))
        else:
            q.put(("error", run_id, f"{type(exc).__name__}: {exc}", traceback.format_exc()))


class JobManager:
    def __init__(self, max_workers: int = 2, mode: str = "process"):
        self.max_workers = max_workers
        self.mode = mode
        self._ctx = mp.get_context("spawn")
        self._q = self._ctx.Queue() if mode == "process" else queue.Queue()
        self._pending: list[tuple] = []
        self._active: dict[str, tuple] = {}  # run_id -> (process/thread, cancel event)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="job-manager")
        self._thread.start()

    # ------------------------------------------------------------------ API
    def submit(self, run_id: str, features: list, origin: tuple, cfg: dict, profile: dict, out_dir: Path) -> None:
        with self._lock:
            self._pending.append((run_id, features, origin, cfg, profile, str(out_dir)))
        self._dispatch()

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            for i, job in enumerate(self._pending):
                if job[0] == run_id:
                    self._pending.pop(i)
                    self._set(run_id, status="cancelled", message="cancelled before start",
                              finished_at=datetime.now(timezone.utc))
                    return True
            if run_id in self._active:
                self._active[run_id][1].set()
                return True
        return False

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            for proc, evt in self._active.values():
                evt.set()

    # ------------------------------------------------------------------ internals
    def _dispatch(self) -> None:
        with self._lock:
            while self._pending and len(self._active) < self.max_workers:
                job = self._pending.pop(0)
                run_id = job[0]
                if self.mode == "process":
                    evt = self._ctx.Event()
                    proc = self._ctx.Process(target=_worker, args=(*job, self._q, evt), daemon=True)
                else:
                    evt = threading.Event()
                    proc = threading.Thread(target=_worker, args=(*job, self._q, evt), daemon=True)
                self._active[run_id] = (proc, evt)
                self._set(run_id, status="running", started_at=datetime.now(timezone.utc), message="starting")
                proc.start()

    def _set(self, run_id: str, **fields) -> None:
        db = SessionLocal()
        try:
            run = db.get(Run, run_id)
            if run is None:
                return
            for k, v in fields.items():
                setattr(run, k, v)
            db.commit()
        except Exception:  # pragma: no cover - logged
            log.exception("could not update run %s", run_id)
        finally:
            db.close()

    def _finish(self, run_id: str) -> None:
        with self._lock:
            self._active.pop(run_id, None)
        self._dispatch()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._q.get(timeout=0.5)
            except queue.Empty:
                self._reap()
                continue
            except (EOFError, OSError):  # pragma: no cover
                break
            kind, run_id = msg[0], msg[1]
            now = datetime.now(timezone.utc)
            if kind == "progress":
                self._set(run_id, progress=round(min(msg[2], 0.999), 4), message=msg[3])
            elif kind == "done":
                eng = msg[3]
                self._set(run_id, status="completed", progress=1.0, message="completed", summary=msg[2],
                          engine_version=eng["version"], method=eng["method"], finished_at=now)
                self._finish(run_id)
            elif kind == "cancelled":
                self._set(run_id, status="cancelled", message="cancelled by user", finished_at=now)
                self._finish(run_id)
            elif kind == "error":
                log.error("run %s failed: %s", run_id, msg[3])
                self._set(run_id, status="failed", error=msg[2], message="failed", finished_at=now)
                self._finish(run_id)

    def _reap(self) -> None:
        """Detect worker processes that died without reporting (e.g. killed)."""
        dead = []
        with self._lock:
            for run_id, (proc, _evt) in self._active.items():
                if not proc.is_alive() and getattr(proc, "exitcode", 0) not in (0, None):
                    dead.append(run_id)
        for run_id in dead:
            self._set(run_id, status="failed", error="worker process terminated unexpectedly",
                      finished_at=datetime.now(timezone.utc))
            self._finish(run_id)


_manager: JobManager | None = None


def manager() -> JobManager:
    global _manager
    if _manager is None:
        from ..config import get_settings

        s = get_settings()
        _manager = JobManager(s.max_workers, s.job_mode)
    return _manager


def reset_manager() -> None:
    global _manager
    if _manager is not None:
        _manager.shutdown()
    _manager = None
