"""Pipeline worker.

The `runs` table *is* the queue: workers claim the oldest queued run with
FOR UPDATE SKIP LOCKED, so you can scale with `docker compose up --scale worker=3`
and no two workers will pick up the same run. No Redis/Celery needed.
"""

from __future__ import annotations

import logging
import signal
import time
import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal, engine, init_db
from .events import emit
from .ingest.pipeline import PIPELINES
from .models import Run
from .pipelines import check_watched
from .storage import ensure_bucket

log = logging.getLogger("spadesys.worker")
_stop = False


def _handle_stop(*_):
    global _stop
    _stop = True


def claim_next() -> uuid.UUID | None:
    schema = get_settings().meta_schema
    sql = text(
        f"""
        UPDATE "{schema}".runs SET status = 'running', started_at = now()
        WHERE id = (
            SELECT id FROM "{schema}".runs
            WHERE status = 'queued'
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING id
        """
    )
    with engine.begin() as conn:
        return conn.execute(sql).scalar_one_or_none()


def execute(run_id: uuid.UUID) -> None:
    with SessionLocal() as session:
        run = session.get(Run, run_id)
        assert run is not None
        src_id, src_name = run.source.id, run.source.name
        emit("start", "Worker picked up the job and started processing", source_id=src_id, run_id=run.id, source_name=src_name)
        try:
            run.stats = PIPELINES[run.pipeline](session, run)
            run.status = "succeeded"
        except Exception as exc:  # noqa: BLE001 (record any failure on the run)
            session.rollback()
            run = session.get(Run, run_id)
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            log.error("run %s failed\n%s", run_id, traceback.format_exc())
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        secs = (run.finished_at - run.started_at).total_seconds() if run.started_at else 0
        if run.status == "succeeded":
            emit("done", f"Finished in {secs:.1f}s", source_id=src_id, run_id=run.id, source_name=src_name)
        else:
            emit("error", f"Failed after {secs:.1f}s: {run.error}", source_id=src_id, run_id=run.id, source_name=src_name)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    init_db()
    ensure_bucket()
    poll = get_settings().worker_poll_seconds
    log.info("worker started (poll every %.1fs)", poll)

    while not _stop:
        try:
            check_watched()  # pipelines that watch a folder
        except Exception:  # noqa: BLE001 (never let watching stop the worker)
            log.exception("checking watched pipelines failed")
        run_id = claim_next()
        if run_id is None:
            time.sleep(poll)
            continue
        execute(run_id)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
