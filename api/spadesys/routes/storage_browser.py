"""Object storage for the Storage page: browse, preview, download, plus folders, uploads, deletes."""

from __future__ import annotations

import mimetypes
import tempfile
import zipfile
from pathlib import PurePath

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import storage
from ..config import get_settings
from ..events import emit, human_bytes

router = APIRouter(prefix="/storage", tags=["storage"])
PREVIEW_BYTES = 64 * 1024


class FilePreview(BaseModel):
    info: dict
    lines: list[str]
    truncated: bool
    is_text: bool


@router.get("/buckets")
def buckets():
    return {"buckets": storage.list_buckets(), "default": storage.bucket()}


@router.get("/list")
def list_folder(bucket: str | None = None, prefix: str = ""):
    try:
        return storage.list_folder(bucket or storage.bucket(), prefix)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, str(exc)) from exc


@router.get("/preview", response_model=FilePreview)
def preview(key: str, bucket: str | None = None):
    try:
        info = storage.head(key, bucket)
        raw = storage.get_bytes(key, bucket, max_bytes=PREVIEW_BYTES)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Not found: {key}") from exc
    try:
        text = raw.decode("utf-8-sig")
        is_text = True
    except UnicodeDecodeError:
        text, is_text = "", False
    lines = text.splitlines()
    truncated = info["size"] > PREVIEW_BYTES
    if truncated and lines:
        lines = lines[:-1]  # last line is probably cut mid-way
    return FilePreview(info=info, lines=lines[:200], truncated=truncated or len(lines) > 200, is_text=is_text)


@router.get("/download")
def download(key: str, bucket: str | None = None):
    try:
        info = storage.head(key, bucket)
        body = storage.stream(key, bucket)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Not found: {key}") from exc
    name = info.get("original_filename") or PurePath(key).name
    return StreamingResponse(
        body.iter_chunks(),
        media_type=info.get("content_type") or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ------------------------------------------------------------------ changes
# Everything below changes storage, and each change is written to the Activity log.

def _clean_prefix(prefix: str) -> str:
    prefix = prefix.strip().lstrip("/")
    return prefix if not prefix or prefix.endswith("/") else prefix + "/"


def _safe_name(name: str) -> str:
    name = PurePath(name.replace("\\", "/")).name.strip()
    if not name or name in (".", "..") or "/" in name:
        raise HTTPException(400, "That name can't be used")
    return name


class NewFolder(BaseModel):
    bucket: str | None = None
    prefix: str = ""
    name: str


@router.post("/folders", status_code=201)
def create_folder(body: NewFolder):
    b = body.bucket or storage.bucket()
    key = _clean_prefix(body.prefix) + _safe_name(body.name) + "/"
    storage.client().put_object(Bucket=b, Key=key, Body=b"")
    emit("storage", f"Created folder {b}/{key}")
    return {"prefix": key}


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...), bucket: str | None = Form(None), prefix: str = Form("")):
    b = bucket or storage.bucket()
    prefix = _clean_prefix(prefix)
    limit = get_settings().max_upload_mb * 1024 * 1024
    existing = {f["name"] for f in storage.list_folder(b, prefix)["files"]}
    saved = []
    for f in files:
        data = await f.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"{f.filename} is bigger than {get_settings().max_upload_mb} MB")
        name = _safe_name(f.filename or "file")
        stem, suffix, n = PurePath(name).stem, PurePath(name).suffix, 2
        renamed = name
        while renamed in existing:  # never overwrite: keep both
            renamed, n = f"{stem}_{n}{suffix}", n + 1
        existing.add(renamed)
        ctype = f.content_type or mimetypes.guess_type(renamed)[0] or "application/octet-stream"
        storage.client().put_object(Bucket=b, Key=prefix + renamed, Body=data, ContentType=ctype,
                                    Metadata={"original-filename": name.encode("ascii", "replace").decode()})
        note = f" (a file called {name} was already there, so this one is {renamed})" if renamed != name else ""
        emit("storage", f"Uploaded {renamed} ({human_bytes(len(data))}) to {b}/{prefix}{note}")
        saved.append({"key": prefix + renamed, "name": renamed, "renamed": renamed != name})
    return {"saved": saved}


def _keys_under(b: str, prefix: str) -> list[dict]:
    out = []
    for page in storage.client().get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=prefix):
        out += page.get("Contents", [])
    return out


@router.delete("/object")
def delete_object(key: str, bucket: str | None = None):
    b = bucket or storage.bucket()
    try:
        storage.head(key, b)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Not found: {key}") from exc
    storage.client().delete_object(Bucket=b, Key=key)
    emit("storage", f"Deleted {b}/{key}")
    return {"deleted": 1}


@router.get("/folder-summary")
def folder_summary(prefix: str, bucket: str | None = None):
    """How much a folder holds, so the page can say what deleting or exporting it means."""
    b = bucket or storage.bucket()
    objs = [o for o in _keys_under(b, _clean_prefix(prefix)) if not o["Key"].endswith("/")]
    return {"files": len(objs), "size": sum(o["Size"] for o in objs)}


@router.delete("/folder")
def delete_folder(prefix: str, bucket: str | None = None):
    b = bucket or storage.bucket()
    prefix = _clean_prefix(prefix)
    if not prefix:
        raise HTTPException(400, "Won't delete a whole bucket from here")
    objs = _keys_under(b, prefix)
    for i in range(0, len(objs), 1000):
        storage.client().delete_objects(Bucket=b, Delete={"Objects": [{"Key": o["Key"]} for o in objs[i:i + 1000]]})
    files = sum(1 for o in objs if not o["Key"].endswith("/"))
    emit("storage", f"Deleted folder {b}/{prefix} and the {files} file{'s' if files != 1 else ''} in it")
    return {"deleted": files}


@router.get("/download-folder")
def download_folder(prefix: str, bucket: str | None = None):
    """Everything in a folder (and its sub-folders) as one .zip."""
    b = bucket or storage.bucket()
    prefix = _clean_prefix(prefix)
    objs = [o for o in _keys_under(b, prefix) if not o["Key"].endswith("/")]
    if not objs:
        raise HTTPException(404, "That folder has no files")
    buf = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for o in objs:
            with z.open(o["Key"][len(prefix):], "w") as out:
                for chunk in storage.stream(o["Key"], b).iter_chunks():
                    out.write(chunk)
    buf.seek(0)
    name = (prefix.rstrip("/").split("/")[-1] or b) + ".zip"
    emit("storage", f"Exported {b}/{prefix} as {name} ({len(objs)} files)")
    return StreamingResponse(iter(lambda: buf.read(1024 * 1024), b""), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
