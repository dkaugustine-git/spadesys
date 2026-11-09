"""Extracts: where data comes from (a folder or a storage prefix) and the raw table it lands in."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import extracts as ex_mod
from .. import storage
from ..db import get_session
from ..events import emit, human_bytes
from ..models import Event, Extract, Pipeline, Run, Source
from ..schemas import EventOut, RunOut
from ..ingest.readers import LayoutError, clean_layout
from ..services import create_source
from .layouts import layout_preview
from .sources import read_upload

router = APIRouter(prefix="/extracts", tags=["extracts"])
DB = Annotated[Session, Depends(get_session)]


class ExtractIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["folder", "storage"] = "folder"
    bucket: str | None = None  # storage: which bucket (default: Spadesys's own)
    prefix: str | None = None  # storage: which folder in it (default: incoming/<name>/)
    pattern: str = "*.csv"
    source_id: uuid.UUID | None = None  # land in this existing raw table...
    new_table_name: str | None = None  # ...or create a new one
    layout: dict[str, Any] | None = None  # where the table is in each file (see ingest/readers.py)


class ExtractPatch(BaseModel):
    name: str | None = None
    pattern: str | None = None
    source_id: uuid.UUID | None = None
    layout: dict[str, Any] | None = None
    reset_layout: bool = False  # back to: headers on row 1, data from row 2


class LayoutPreviewIn(BaseModel):
    ref: str  # from GET /extracts/{id}/samples
    layout: dict[str, Any] | None = None


class ExtractOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    folder: str
    location: str
    bucket: str | None
    prefix: str | None
    pattern: str
    layout: dict[str, Any] | None
    layout_text: str
    table: dict[str, Any] | None
    created_at: datetime
    waiting: int
    last_run: RunOut | None
    used_by: list[dict[str, Any]]


class ExtractDetail(ExtractOut):
    files_waiting: list[dict[str, Any]]
    files_done: list[dict[str, Any]]
    runs: list[RunOut]


def _checked_layout(layout: dict[str, Any]) -> dict[str, Any]:
    try:
        return clean_layout(layout)
    except LayoutError as e:
        raise HTTPException(400, str(e)) from None


def get_extract(session: Session, eid: uuid.UUID) -> Extract:
    ex = session.get(Extract, eid)
    if ex is None:
        raise HTTPException(404, "Extract not found")
    return ex


def table_info(session: Session, source_id: uuid.UUID | None) -> dict[str, Any] | None:
    s = session.get(Source, source_id) if source_id else None
    return {"source_id": s.id, "name": s.name, "table_name": s.table_name, "row_count": s.row_count} if s else None


def extract_fields(session: Session, ex: Extract, detail: bool = False) -> dict[str, Any]:
    """Everything about an extract that the extract and pipeline pages both show."""
    waiting = ex_mod.waiting_files(ex)
    runs = session.scalars(
        select(Run).where(Run.extract_id == ex.id).order_by(Run.created_at.desc()).limit(25 if detail else 1)
    ).all()
    out: dict[str, Any] = dict(
        folder=ex.config["folder"], location=ex_mod.location(ex),
        bucket=ex.config.get("bucket"), prefix=ex.config.get("prefix"), pattern=ex.config.get("pattern") or "*",
        layout=ex.config.get("layout"), layout_text=ex_mod.layout_text(ex),
        waiting=sum(1 for f in waiting if f["matches"]),
        last_run=RunOut.model_validate(runs[0]) if runs else None,
    )
    if detail:
        out.update(files_waiting=waiting, files_done=ex_mod.done_files(ex), runs=[RunOut.model_validate(r) for r in runs])
    return out


def _out(session: Session, ex: Extract, detail: bool = False) -> ExtractOut | ExtractDetail:
    used_by = [{"id": p.id, "name": p.name, "mode": p.mode}
               for p in session.scalars(select(Pipeline).where(Pipeline.extract_id == ex.id))]
    base = dict(id=ex.id, name=ex.name, kind=ex.kind, table=table_info(session, ex.source_id),
                created_at=ex.created_at, used_by=used_by, **extract_fields(session, ex, detail))
    return ExtractDetail(**base) if detail else ExtractOut(**base)


def create_extract(session: Session, body: ExtractIn) -> Extract:
    """Make an extract, its folder (or storage prefix) and, if asked, a new raw table."""
    dest = None
    if body.source_id:
        dest = session.get(Source, body.source_id)
        if dest is None:
            raise HTTPException(400, "That table doesn't exist anymore")
    folder = ex_mod.unique_folder(session, body.name)
    config: dict[str, Any] = {"folder": folder, "pattern": body.pattern.strip() or "*"}
    if body.layout:
        config["layout"] = _checked_layout(body.layout)
    if body.kind == "storage":
        config["bucket"] = (body.bucket or storage.bucket()).strip()
        config["prefix"] = ex_mod.normalize_prefix(body.prefix if body.prefix is not None else f"incoming/{folder}")
        problem = ex_mod.check_storage_source(config["bucket"], config["prefix"])
        if problem:
            raise HTTPException(400, problem)
    if dest is None:
        dest = create_source(session, (body.new_table_name or body.name).strip())
    ex = Extract(name=body.name.strip(), kind=body.kind, config=config, source_id=dest.id)
    session.add(ex)
    session.commit()
    ex_mod.make_place(ex)
    emit("pipeline", f"Created extract “{ex.name}”: files that show up in {ex_mod.location(ex)} land in raw.{dest.table_name}"
         f". File layout: {ex_mod.layout_text(ex)}", extract_id=str(ex.id))
    return ex


@router.get("", response_model=list[ExtractOut])
def list_extracts(session: DB):
    return [_out(session, ex) for ex in session.scalars(select(Extract).order_by(Extract.created_at.desc()))]


@router.post("", response_model=ExtractDetail, status_code=201)
def new_extract(session: DB, body: ExtractIn):
    return _out(session, create_extract(session, body), detail=True)


@router.get("/{eid}", response_model=ExtractDetail)
def get_one(session: DB, eid: uuid.UUID):
    return _out(session, get_extract(session, eid), detail=True)


@router.patch("/{eid}", response_model=ExtractDetail)
def update_extract(session: DB, eid: uuid.UUID, body: ExtractPatch):
    ex = get_extract(session, eid)
    changes = []
    if body.name is not None and body.name.strip() and body.name.strip() != ex.name:
        ex.name = body.name.strip()
        changes.append(f"renamed to “{ex.name}”")
    if body.pattern is not None and body.pattern != ex.config.get("pattern"):
        ex.config = {**ex.config, "pattern": body.pattern.strip() or "*"}
        changes.append(f"only picks up files matching {ex.config['pattern']}")
    if body.reset_layout and ex.config.get("layout"):
        ex.config = {k: v for k, v in ex.config.items() if k != "layout"}
        changes.append(f"reads files the standard way again: {ex_mod.layout_text(ex)}")
    elif body.layout is not None:
        lay = _checked_layout(body.layout)
        if lay != ex.config.get("layout"):
            ex.config = {**ex.config, "layout": lay}
            changes.append(f"reads every file with this layout: {ex_mod.layout_text(ex)}")
    if body.source_id is not None and body.source_id != ex.source_id:
        dest = session.get(Source, body.source_id)
        if dest is None:
            raise HTTPException(400, "That table doesn't exist anymore")
        ex.source_id = dest.id
        changes.append(f"now lands in raw.{dest.table_name}")
    session.commit()
    if changes:
        emit("pipeline", f"Extract “{ex.name}” " + "; ".join(changes), extract_id=str(ex.id))
    return _out(session, ex, detail=True)


@router.delete("/{eid}", status_code=204)
def delete_extract(session: DB, eid: uuid.UUID):
    """Removes the extract only. Its raw table, its folder and the archived files stay."""
    ex = get_extract(session, eid)
    users = session.scalars(select(Pipeline.name).where(Pipeline.extract_id == ex.id)).all()
    if users:
        raise HTTPException(409, "Pipelines still use this extract: " + ", ".join(f"“{u}”" for u in users)
                            + ". Delete those pipelines first.")
    name, where = ex.name, ex_mod.location(ex)
    session.delete(ex)
    session.commit()
    emit("pipeline", f"Deleted extract “{name}”. Its raw table and the files in {where} were left alone.")


@router.post("/{eid}/run", response_model=list[RunOut])
def run_now(session: DB, eid: uuid.UUID):
    ex = get_extract(session, eid)
    return [RunOut.model_validate(r) for r in ex_mod.run_extract(session, ex, trigger="manual")]


async def add_file_to(session: Session, ex: Extract, file: UploadFile, then: str, **tags: str) -> dict[str, str]:
    data = await read_upload(file)
    name = ex_mod.add_file(ex, file.filename or "file.csv", data)
    emit("pipeline", f"Added {name} ({human_bytes(len(data))}) to {ex_mod.location(ex)}{then}", extract_id=str(ex.id), **tags)
    return {"name": name}


@router.post("/{eid}/files")
async def add_file(session: DB, eid: uuid.UUID, file: UploadFile = File(...)):
    """Put a file where the extract looks, exactly as if you'd dropped it there."""
    ex = get_extract(session, eid)
    watching = session.scalar(select(Pipeline.id).where(Pipeline.extract_id == ex.id, Pipeline.mode == "watch"))
    then = (". A pipeline is watching it, so it'll be picked up in a few seconds." if watching
            else ". Click Run now to load it.")
    return await add_file_to(session, ex, file, then)


@router.get("/{eid}/events", response_model=list[EventOut])
def extract_events(session: DB, eid: uuid.UUID, after_id: int = 0, limit: int = 200):
    """This extract's activity: its own steps plus the loads it queued."""
    run_ids = select(Run.id).where(Run.extract_id == eid)
    q = select(Event).where(Event.id > after_id).where(
        (Event.detail["extract_id"].astext == str(eid)) | (Event.run_id.in_(run_ids))
    )
    rows = session.scalars(q.order_by(Event.id.desc()).limit(max(1, min(limit, 1000)))).all()
    return list(reversed(rows))


@router.get("/{eid}/samples")
def samples(session: DB, eid: uuid.UUID):
    """Files to set up the layout with: what's waiting, then what was loaded recently."""
    return ex_mod.sample_files(get_extract(session, eid))


@router.post("/{eid}/layout-preview")
def preview_layout(session: DB, eid: uuid.UUID, body: LayoutPreviewIn):
    ex = get_extract(session, eid)
    try:
        data, name = ex_mod.read_sample(ex, body.ref)
    except FileNotFoundError:
        raise HTTPException(404, "That file isn't there anymore") from None
    return layout_preview(data, name, body.layout if body.layout is not None else ex.config.get("layout"))
