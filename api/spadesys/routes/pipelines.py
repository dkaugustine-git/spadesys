"""Pipelines: a folder of files -> a Spadesys table, run on demand or by watching."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import pipelines as pl
from .. import storage
from ..db import get_session
from ..events import emit, human_bytes
from ..models import Event, Pipeline, Run, Source
from ..schemas import EventOut, RunOut
from ..services import create_source
from .sources import read_upload

router = APIRouter(prefix="/pipelines", tags=["pipelines"])
DB = Annotated[Session, Depends(get_session)]


class PipelineIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_kind: Literal["folder", "storage"] = "folder"
    bucket: str | None = None  # storage: which bucket (default: Spadesys's own)
    prefix: str | None = None  # storage: which folder in it (default: incoming/<name>/)
    pattern: str = "*.csv"
    destination_source_id: uuid.UUID | None = None  # load into this existing table...
    new_table_name: str | None = None  # ...or create a new one
    mode: Literal["manual", "watch"] = "manual"
    watch_seconds: int = Field(10, ge=5, le=3600)


class PipelinePatch(BaseModel):
    name: str | None = None
    pattern: str | None = None
    mode: Literal["manual", "watch"] | None = None
    watch_seconds: int | None = Field(None, ge=5, le=3600)
    destination_source_id: uuid.UUID | None = None


class PipelineOut(BaseModel):
    id: uuid.UUID
    name: str
    source_kind: str
    folder: str
    host_path: str
    location: str
    bucket: str | None
    prefix: str | None
    pattern: str
    destination: dict[str, Any] | None
    mode: str
    watch_seconds: int
    last_checked_at: datetime | None
    created_at: datetime
    waiting: int
    last_run: RunOut | None


class PipelineDetail(PipelineOut):
    files_waiting: list[dict[str, Any]]
    files_done: list[dict[str, Any]]
    runs: list[RunOut]


def _get(session: Session, pid: uuid.UUID) -> Pipeline:
    p = session.get(Pipeline, pid)
    if p is None:
        raise HTTPException(404, "Pipeline not found")
    return p


def _out(session: Session, p: Pipeline, detail: bool = False) -> PipelineOut | PipelineDetail:
    dest = session.get(Source, p.destination_source_id) if p.destination_source_id else None
    waiting = pl.waiting_files(p)
    runs = session.scalars(
        select(Run).where(Run.pipeline_id == p.id).order_by(Run.created_at.desc()).limit(25 if detail else 1)
    ).all()
    base = dict(
        id=p.id, name=p.name, source_kind=p.source_kind, folder=p.source_config["folder"], host_path=pl.location(p),
        location=pl.location(p), bucket=p.source_config.get("bucket"), prefix=p.source_config.get("prefix"),
        pattern=p.source_config.get("pattern") or "*",
        destination=(
            {"source_id": dest.id, "name": dest.name, "table_name": dest.table_name, "row_count": dest.row_count}
            if dest else None
        ),
        mode=p.mode, watch_seconds=p.watch_seconds, last_checked_at=p.last_checked_at, created_at=p.created_at,
        waiting=sum(1 for f in waiting if f["matches"]),
        last_run=RunOut.model_validate(runs[0]) if runs else None,
    )
    if not detail:
        return PipelineOut(**base)
    return PipelineDetail(
        **base, files_waiting=waiting, files_done=pl.done_files(p), runs=[RunOut.model_validate(r) for r in runs]
    )


@router.get("", response_model=list[PipelineOut])
def list_pipelines(session: DB):
    return [_out(session, p) for p in session.scalars(select(Pipeline).order_by(Pipeline.created_at.desc()))]


@router.post("", response_model=PipelineDetail, status_code=201)
def create_pipeline(session: DB, body: PipelineIn):
    dest = None
    if body.destination_source_id:
        dest = session.get(Source, body.destination_source_id)
        if dest is None:
            raise HTTPException(400, "That table doesn't exist anymore")
    folder = pl.unique_folder(session, body.name)
    config: dict[str, Any] = {"folder": folder, "pattern": body.pattern.strip() or "*"}
    if body.source_kind == "storage":
        config["bucket"] = (body.bucket or storage.bucket()).strip()
        config["prefix"] = pl.normalize_prefix(body.prefix if body.prefix is not None else f"incoming/{folder}")
        problem = pl.check_storage_source(config["bucket"], config["prefix"])
        if problem:
            raise HTTPException(400, problem)
    if not body.destination_source_id:
        dest = create_source(session, (body.new_table_name or body.name).strip())
    p = Pipeline(
        name=body.name.strip(), source_kind=body.source_kind, source_config=config,
        destination_kind="spadesys", destination_source_id=dest.id, mode=body.mode, watch_seconds=body.watch_seconds,
    )
    session.add(p)
    session.commit()
    # Create the place now so you can find it.
    if p.source_kind == "storage":
        storage.client().put_object(Bucket=config["bucket"], Key=config["prefix"], Body=b"")
    else:
        pl.folder_path(p)
    how = f"watching every {p.watch_seconds}s" if p.mode == "watch" else "runs when you click Run now"
    emit(
        "pipeline",
        f"Created pipeline “{p.name}”: files that show up in {pl.location(p)} load into table raw.{dest.table_name} ({how})",
        pipeline_id=str(p.id),
    )
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
    if body.pattern is not None and body.pattern != p.source_config.get("pattern"):
        p.source_config = {**p.source_config, "pattern": body.pattern.strip() or "*"}
        changes.append(f"only picks up files matching {p.source_config['pattern']}")
    if body.watch_seconds is not None and body.watch_seconds != p.watch_seconds:
        p.watch_seconds = body.watch_seconds
        changes.append(f"checks every {p.watch_seconds}s when watching")
    if body.mode is not None and body.mode != p.mode:
        p.mode = body.mode
        p.last_checked_at = None
        changes.append(
            f"now watching {pl.location(p)} every {p.watch_seconds}s" if p.mode == "watch"
            else "stopped watching; runs only when you click Run now"
        )
    if body.destination_source_id is not None and body.destination_source_id != p.destination_source_id:
        dest = session.get(Source, body.destination_source_id)
        if dest is None:
            raise HTTPException(400, "That table doesn't exist anymore")
        p.destination_source_id = dest.id
        changes.append(f"now loads into raw.{dest.table_name}")
    session.commit()
    if changes:
        emit("pipeline", f"Pipeline “{p.name}” " + "; ".join(changes), pipeline_id=str(p.id))
    return _out(session, p, detail=True)


@router.delete("/{pid}", status_code=204)
def delete_pipeline(session: DB, pid: uuid.UUID):
    """Removes the pipeline only. Its table, its folder and the archived files stay."""
    p = _get(session, pid)
    name, where = p.name, pl.location(p)
    session.delete(p)
    session.commit()
    emit("pipeline", f"Deleted pipeline “{name}”. Its table and the files in {where} were left alone.")


@router.post("/{pid}/run", response_model=list[RunOut])
def run_now(session: DB, pid: uuid.UUID):
    p = _get(session, pid)
    return [RunOut.model_validate(r) for r in pl.run_pipeline(session, p, trigger="manual")]


@router.post("/{pid}/files")
async def add_file(session: DB, pid: uuid.UUID, file: UploadFile = File(...)):
    """Put a file into the pipeline's folder, exactly as if you'd dropped it there."""
    p = _get(session, pid)
    data = await read_upload(file)
    name = pl.add_file(p, file.filename or "file.csv", data)
    then = (
        ". The pipeline is watching, so it'll be picked up in a few seconds." if p.mode == "watch"
        else ". Click Run now to load it."
    )
    emit("pipeline", f"Added {name} ({human_bytes(len(data))}) to {pl.location(p)}{then}", pipeline_id=str(p.id))
    return {"name": name}


@router.get("/{pid}/events", response_model=list[EventOut])
def pipeline_events(session: DB, pid: uuid.UUID, after_id: int = 0, limit: int = 200):
    """This pipeline's activity: its own steps plus the loads it queued."""
    run_ids = select(Run.id).where(Run.pipeline_id == pid)
    q = select(Event).where(Event.id > after_id).where(
        (Event.detail["pipeline_id"].astext == str(pid)) | (Event.run_id.in_(run_ids))
    )
    rows = session.scalars(q.order_by(Event.id.desc()).limit(max(1, min(limit, 1000)))).all()
    return list(reversed(rows))
