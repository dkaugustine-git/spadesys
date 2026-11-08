from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Run
from ..schemas import RunOut

router = APIRouter(prefix="/runs", tags=["runs"])
DB = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[RunOut])
def list_runs(session: DB, source_id: uuid.UUID | None = None, status: str | None = None, limit: int = 100):
    q = select(Run).order_by(Run.created_at.desc()).limit(max(1, min(limit, 500)))
    if source_id:
        q = q.where(Run.source_id == source_id)
    if status:
        q = q.where(Run.status == status)
    return session.scalars(q).all()


@router.get("/{run_id}", response_model=RunOut)
def get_run(session: DB, run_id: uuid.UUID):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/{run_id}/retry", response_model=RunOut, status_code=201)
def retry_run(session: DB, run_id: uuid.UUID):
    """Re-queue a run's original file as a new run."""
    old = session.get(Run, run_id)
    if old is None:
        raise HTTPException(404, "Run not found")
    run = Run(
        source_id=old.source_id,
        pipeline=old.pipeline,
        status="queued",
        object_key=old.object_key,
        original_filename=old.original_filename,
    )
    session.add(run)
    session.commit()
    return run
