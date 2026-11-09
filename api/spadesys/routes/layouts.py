"""File layouts: preview a file as raw rows, guess where the table is, and show what a layout would load."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from .. import storage
from ..ingest.readers import (
    SUPPORTED, LayoutError, apply_layout, clean_layout, describe, guess_layout, read_grid,
)
from .sources import read_upload

router = APIRouter(prefix="/layouts", tags=["layouts"])

GRID_ROWS = 80  # raw rows shown in the picker
GRID_COLS = 40
CELL_CHARS = 80


def layout_preview(data: bytes, filename: str, layout: dict[str, Any] | None) -> dict[str, Any]:
    """Everything the layout picker shows. A bad layout comes back as an error, never an exception."""
    try:
        grid = read_grid(data, filename, (layout or {}).get("sheet"))
    except LayoutError as e:
        raise HTTPException(422, str(e)) from None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Couldn't read {filename}: {e}") from None
    guess = guess_layout(grid)
    used = {**guess, **(layout or {}), "sheet": grid.sheet}
    out: dict[str, Any] = {
        "filename": filename,
        "sheets": grid.sheets,
        "sheet": grid.sheet,
        "delimiter": grid.delimiter,
        "grid": [[c[:CELL_CHARS] for c in r[:GRID_COLS]] for r in grid.rows[:GRID_ROWS]],
        "total_rows": len(grid.rows),
        "guess": guess,
        "layout": used,
    }
    try:
        used = clean_layout(used)
        df, notes = apply_layout(grid, used)
    except LayoutError as e:
        return {**out, "ok": False, "error": str(e)}
    return jsonable_encoder({
        **out, "ok": True, "layout": used, "layout_text": describe(used, grid), "notes": notes,
        "columns": [str(c) for c in df.columns], "rows": df.head(8).values.tolist(), "row_count": int(len(df)),
    })


class StoredPreview(BaseModel):
    key: str
    bucket: str | None = None
    layout: dict[str, Any] | None = None


@router.get("/formats")
def formats():
    return {"extensions": SUPPORTED}


@router.post("/preview")
def preview_stored(body: StoredPreview):
    """Preview a file that's already in storage."""
    bucket = body.bucket or storage.bucket()
    try:
        data = storage.client().get_object(Bucket=bucket, Key=body.key)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Not found in storage: {bucket}/{body.key}") from exc
    name = storage.original_filename(body.key) if bucket == storage.bucket() else body.key.rsplit("/", 1)[-1]
    return layout_preview(data, name, body.layout)


@router.post("/preview-file")
async def preview_file(file: Annotated[UploadFile, File()], layout: Annotated[str | None, Form()] = None):
    """Preview a file from your computer without saving it anywhere."""
    data = await read_upload(file)
    try:
        lay = json.loads(layout) if layout else None
    except json.JSONDecodeError:
        raise HTTPException(400, "layout must be JSON") from None
    return layout_preview(data, file.filename or "file.csv", lay)
