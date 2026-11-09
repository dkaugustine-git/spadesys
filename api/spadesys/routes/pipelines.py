"""Pipelines: orchestration. Run an extract (transforms and loads next) on demand or by watching."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import extracts as ex_mod
from .. import pipelines as pl
from ..db import get_session
from ..events import emit
from ..models import Event, Extract, Pipeline, Run
from ..schemas import EventOut, RunOut
from .extracts import ExtractIn, add_file_to, create_extract, extract_fields, table_info

router = APIRouter(prefix="/pipelines", tags=["pipelines"])
DB = Annotated[Session, Depends(get_session)]


class PipelineIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    extract_id: uuid.UUID | None = None  # use this extract...
    # ...or make a new one from these (same fields as POST /extracts)
    source_kind: Literal["folder", "storage"] = "folder"
    bucket: str | None = None
    prefix: str | None = None
    pattern: str = "*.csv"
    destination_source_id: uuid.UUID | None = None
    new_table_name: str | None = None
    layout: dict[str, Any] | None = None
    mode: Literal["manual", "watch"] = "manual"
    watch_seconds: int = Field(10, ge=5, le=3600)


class PipelinePatch(BaseModel):
    name: str | None = None
    extract_id: uuid.UUID | None = None
    mode: Literal["manual", "watch"] | None = None
    watch_seconds: int | None = Field(None, ge=5, le=3600)


class PipelineOut(BaseModel):
    id: uuid.UUID
    name: str
    extract: dict[str, Any] | None  # {id, name, kind}
    mode: str
    watch_seconds: int
    last_checked_at: datetime | None
    created_at: datetime
    # The extract's details, repeated here so the pipeline page can show them without a second call.
    source_kind: str | None = None
    folder: str | None = None
    location: str | None = None
    bucket: str | None = None
    prefix: str | None = None
    pattern: str | None = None
    layout: dict[str, Any] | None = None
    layout_text: str | None = None
    destination: dict[str, Any] | None = None  # the raw table the extract lands in
    waiting: int = 0
    last_run: RunOut | None = None


class PipelineDetail(PipelineOut):
    files_waiting: list[dict[str, Any]] = []
    files_done: list[dict[str, Any]] = []
    runs: list[RunOut] = []


def _get(session: Session, pid: uuid.UUID) -> Pipeline:
    p = session.get(Pipeline, pid)
    if p is None:
        raise HTTPException(404, "Pipeline not found")
    return p


def _out(session: Session, p: Pipeline, detail: bool = False) -> PipelineOut | PipelineDetail:
    ex = pl.extract_of(session, p)
    base: dict[str, Any] = dict(
        id=p.id, name=p.name, mode=p.mode, watch_seconds=p.watch_seconds,
        last_checked_at=p.last_checked_at, created_at=p.created_at,
        extract={"id": ex.id, "name": ex.name, "kind": ex.kind} if ex else None,
    )
    if ex:
        base.update(source_kind=ex.kind, destination=table_info(session, ex.source_id), **extract_fields(session, ex, detail))
        if detail:
            # This pipeline's own loads, not every load the extract has done.
            runs = session.scalars(
                select(Run).where(Run.pipeline_id == p.id).order_by(Run.created_at.desc()).limit(25)
            ).all()
            base["runs"] = [RunOut.model_validate(r) for r in runs]
    return PipelineDetail(**base) if detail else PipelineOut(**base)


def _extract_or_404(session: Session, eid: uuid.UUID) -> Extract:
    ex = session.get(Extract, eid)
    if ex is None:
        raise HTTPException(400, "That extract doesn't exist anymore")
    return ex


@router.get("", response_model=list[PipelineOut])
def list_pipelines(session: DB):
    return [_out(session, p) for p in session.scalars(select(Pipeline).order_by(Pipeline.created_at.desc()))]


@router.post("", response_model=PipelineDetail, status_code=201)
def create_pipeline(session: DB, body: PipelineIn):
    if body.extract_id:
        ex = _extract_or_404(session, body.extract_id)
    else:
        ex = create_extract(session, ExtractIn(
            name=body.name, kind=body.source_kind, bucket=body.bucket, prefix=body.prefix, pattern=body.pattern,
            source_id=body.destination_source_id, new_table_name=body.new_table_name, layout=body.layout,
        ))
    p = Pipeline(name=body.name.strip(), extract_id=ex.id, mode=body.mode, watch_seconds=body.watch_seconds)
    session.add(p)
    session.commit()
    how = f"watching every {p.watch_seconds}s" if p.mode == "watch" else "runs when you click Run now"
    emit("pipeline", f"Created pipeline “{p.name}”: runs extract “{ex.name}” ({ex_mod.location(ex)}) ({how})",
         pipeline_id=str(p.id), extract_id=str(ex.id))
    return _out(session, p, detail=True)


@router.get("/{pid}", response_model=PipelineDetail)
def get_pipeline(session: DB, pid: uuid.UUID):
    return _out(session, _get(session, pid), detail=True)


@router.patch("/{pid}", response_model=PipelineDetail)
def update_pipeline(session: DB, pid: uuid.UUID, body: PipelinePatch):
    p = _get(session, pid)
    changes = []
    if body.name is not None and body.name.strip() and body.name.strip() != p.name:
        p.name = body.name.strip()
        changes.append(f"renamed to “{p.name}”")
    if body.extract_id is not None and body.extract_id != p.extract_id:
        ex = _extract_or_404(session, body.extract_id)
        p.extract_id = ex.id
        changes.append(f"now runs extract “{ex.name}”")
    if body.watch_seconds is not None and body.watch_seconds != p.watch_seconds:
        p.watch_seconds = body.watch_seconds
        changes.append(f"checks every {p.watch_seconds}s when watching")
    if body.mode is not None and body.mode != p.mode:
        p.mode = body.mode
        p.last_checked_at = None
        ex = pl.extract_of(session, p)
        changes.append(
            f"now watching {ex_mod.location(ex) if ex else 'its extract'} every {p.watch_seconds}s" if p.mode == "watch"
            else "stopped watching; runs only when you click Run now"
        )
    session.commit()
    if changes:
        emit("pipeline", f"Pipeline “{p.name}” " + "; ".join(changes), pipeline_id=str(p.id))
    return _out(session, p, detail=True)


@router.delete("/{pid}", status_code=204)
def delete_pipeline(session: DB, pid: uuid.UUID):
    """Removes the pipeline only. Its extract, table and files stay."""
    p = _get(session, pid)
    name = p.name
    session.delete(p)
    session.commit()
    emit("pipeline", f"Deleted pipeline “{name}”. Its extract, table and files were left alone (see the Extract tab).")


@router.post("/{pid}/run", response_model=list[RunOut])
def run_now(session: DB, pid: uuid.UUID):
    p = _get(session, pid)
    return [RunOut.model_validate(r) for r in pl.run_pipeline(session, p, trigger="manual")]


@router.post("/{pid}/files")
async def add_file(session: DB, pid: uuid.UUID, file: UploadFile = File(...)):
    """Put a file where the pipeline's extract looks, exactly as if you'd dropped it there."""
    p = _get(session, pid)
    ex = pl.extract_of(session, p)
    if ex is None:
        raise HTTPException(400, "This pipeline has no extract")
    then = (". The pipeline is watching, so it'll be picked up in a few seconds." if p.mode == "watch"
            else ". Click Run now to load it.")
    return await add_file_to(session, ex, file, then, pipeline_id=str(p.id))


@router.get("/{pid}/events", response_model=list[EventOut])
def pipeline_events(session: DB, pid: uuid.UUID, after_id: int = 0, limit: int = 200):
    """This pipeline's activity: its own steps plus the loads it queued."""
    run_ids = select(Run.id).where(Run.pipeline_id == pid)
    q = select(Event).where(Event.id > after_id).where(
        (Event.detail["pipeline_id"].astext == str(pid)) | (Event.run_id.in_(run_ids))
    )
    rows = session.scalars(q.order_by(Event.id.desc()).limit(max(1, min(limit, 1000)))).all()
    return list(reversed(rows))
