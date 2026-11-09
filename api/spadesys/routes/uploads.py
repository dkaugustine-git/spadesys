"""Two-step upload: (1) stage the file in storage and get suggestions, (2) the user decides."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from .. import storage
from ..db import get_session
from ..events import emit, human_bytes
from ..models import Source
from ..schemas import FileAnalysis, SourceOut
from ..ingest.readers import LayoutError, clean_layout, describe, is_default
from ..services import analyze_file, commit_queued, create_source, queue_run_for_object
from .sources import read_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])
DB = Annotated[Session, Depends(get_session)]


@router.post("", response_model=FileAnalysis, status_code=201)
async def stage_upload(session: DB, file: Annotated[UploadFile, File()]):
    """Save the file to storage (nothing else) and suggest what to do with it."""
    data = await read_upload(file)
    filename = file.filename or "upload.csv"
    key = storage.new_key("uploads", filename)
    storage.put(key, data, original_filename=filename)
    emit("upload", f"Received {filename} ({human_bytes(len(data))}) and saved it to storage at {key}. Waiting for you to decide what to do with it.")
    try:
        return analyze_file(session, key, filename, data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Saved to storage, but couldn't read it as a table: {exc}") from exc


@router.get("/analyze", response_model=FileAnalysis)
def analyze_stored(session: DB, key: str):
    """Suggestions for a file that's already in storage (e.g. picked on the Storage page)."""
    try:
        data = storage.get_bytes(key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Not found in storage: {key}") from exc
    try:
        return analyze_file(session, key, storage.original_filename(key), data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Couldn't read it as a table: {exc}") from exc


class LoadRequest(BaseModel):
    key: str
    layout: dict[str, Any] | None = None  # where the table is in the file; None = headers on row 1
    source_id: uuid.UUID | None = None  # load into this existing source...
    new_name: str | None = None  # ...or create a new one with this name

    @model_validator(mode="after")
    def one_target(self):
        if bool(self.source_id) == bool(self.new_name and self.new_name.strip()):
            raise ValueError("Give either source_id or new_name")
        return self


@router.post("/load", response_model=SourceOut, status_code=201)
def load_staged(session: DB, req: LoadRequest):
    try:
        storage.head(req.key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Not found in storage: {req.key}") from exc
    filename = storage.original_filename(req.key)

    if req.source_id:
        source = session.get(Source, req.source_id)
        if source is None:
            raise HTTPException(404, "Source not found")
        emit("decide", f"You chose to add {filename} to the existing table raw.{source.table_name}", source_id=source.id, source_name=source.name)
    else:
        source = create_source(session, req.new_name.strip())
        emit("decide", f"You chose to create a new table raw.{source.table_name} from {filename}", source_id=source.id, source_name=source.name)

    layout = None
    if req.layout:
        try:
            layout = clean_layout(req.layout)
        except LayoutError as e:
            raise HTTPException(400, str(e)) from None
        if is_default(layout) and not layout.get("sheet"):
            layout = None
        else:
            emit("decide", f"Reading {filename} with this layout: {describe(layout)}", source_id=source.id, source_name=source.name)
    run = queue_run_for_object(session, source, req.key, filename, layout=layout)
    commit_queued(session, run)
    session.refresh(source)
    return SourceOut.model_validate(source)
