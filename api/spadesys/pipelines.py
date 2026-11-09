"""Pipelines: orchestration. Run the pieces (an extract today; transforms and loads next) on demand or by watching.

The pieces live on their own (see extracts.py) so one can be reused by several pipelines.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .events import emit
from .models import Extract, Pipeline, Run


def extract_of(session: Session, p: Pipeline) -> Extract | None:
    return session.get(Extract, p.extract_id) if p.extract_id else None


def run_pipeline(session: Session, p: Pipeline, trigger: str = "manual") -> list[Run]:
    from .extracts import run_extract

    ex = extract_of(session, p)
    if ex is None:
        emit("error", f"Pipeline “{p.name}” has no extract to run. Pick one for it.", pipeline_id=str(p.id))
        return []
    who = f"You clicked “Run now” on pipeline “{p.name}”" if trigger == "manual" else f"Pipeline “{p.name}” (watching)"
    return run_extract(session, ex, trigger=trigger, who=who, pipeline_id=p.id)


def check_watched() -> None:
    """Called by the worker between jobs: run any watching pipeline that's due."""
    from .db import SessionLocal

    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        due = [p for p in session.scalars(select(Pipeline).where(Pipeline.mode == "watch"))
               if p.last_checked_at is None or (now - p.last_checked_at).total_seconds() >= p.watch_seconds]
        for p in due:
            p.last_checked_at = now
            session.commit()
            try:
                run_pipeline(session, p, trigger="watch")
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                emit("error", f"Watching “{p.name}” failed: {exc}", pipeline_id=str(p.id))
