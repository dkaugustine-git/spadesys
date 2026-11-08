from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import engine, get_session
from ..models import Source
from ..schemas import Preview, RunOut, SourceDetail, SourceOut
from ..events import emit
from ..services import commit_queued, ingest_csv, queue_csv_run

router = APIRouter(prefix="/sources", tags=["sources"])
DB = Annotated[Session, Depends(get_session)]


async def read_upload(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds {get_settings().max_upload_mb} MB")
    if not data.strip():
        raise HTTPException(400, "File is empty")
    return data


def _source_out(s: Source) -> SourceOut:
    out = SourceOut.model_validate(s)
    out.last_run = RunOut.model_validate(s.runs[0]) if s.runs else None
    return out


def _get(session: Session, source_id: uuid.UUID) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    return source


@router.get("", response_model=list[SourceOut])
def list_sources(session: DB):
    return [_source_out(s) for s in session.scalars(select(Source).order_by(Source.created_at.desc()))]


@router.post("", response_model=SourceOut, status_code=201)
async def upload_source(session: DB, file: Annotated[UploadFile, File()], name: Annotated[str | None, Form()] = None):
    """Upload a CSV: it lands in object storage and an ingest run is queued."""
    data = await read_upload(file)
    emit("upload", f"Received {file.filename} from the browser")
    source = ingest_csv(session, file.filename or "upload.csv", data, name=name)
    session.refresh(source)
    return _source_out(source)


@router.get("/{source_id}", response_model=SourceDetail)
def get_source(session: DB, source_id: uuid.UUID):
    s = _get(session, source_id)
    detail = SourceDetail.model_validate(s)
    detail.last_run = detail.runs[0] if detail.runs else None
    return detail


@router.post("/{source_id}/runs", response_model=RunOut, status_code=201)
async def reload_source(session: DB, source_id: uuid.UUID, file: Annotated[UploadFile, File()]):
    """Upload a new version of the file. Rows already loaded (same row hash) are skipped."""
    source = _get(session, source_id)
    run = queue_csv_run(session, source, file.filename or "upload.csv", await read_upload(file))
    commit_queued(session, run)
    return run


@router.get("/{source_id}/preview", response_model=Preview)
def preview_source(session: DB, source_id: uuid.UUID, limit: int = 50):
    s = _get(session, source_id)
    schema = get_settings().raw_schema
    if not inspect(engine).has_table(s.table_name, schema=schema):
        return Preview(columns=[], rows=[])
    limit = max(1, min(limit, 500))
    with engine.connect() as conn:
        result = conn.execute(
            text(f'SELECT * FROM "{schema}"."{s.table_name}" ORDER BY _loaded_at DESC LIMIT :n'), {"n": limit}
        )
        cols = list(result.keys())
        rows = jsonable_encoder([list(r) for r in result])
    return Preview(columns=cols, rows=rows)


@router.delete("/{source_id}", status_code=204)
def delete_source(session: DB, source_id: uuid.UUID, drop_table: bool = True):
    s = _get(session, source_id)
    if drop_table:
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{get_settings().raw_schema}"."{s.table_name}"'))
    name, table = s.name, s.table_name
    session.delete(s)
    session.commit()
    emit("delete", f"Deleted source{f' and dropped table raw.{table}' if drop_table else ''}", source_name=name)
