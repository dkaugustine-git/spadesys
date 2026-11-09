"""Extracts: where data comes from. Pick up each new file, archive it, land it in a raw table.

Two kinds of place:

  folder   data/inbox/<name> on your computer (mounted at /data/inbox in the containers)
  storage  a bucket + folder (prefix) in Spadesys storage (MinIO / any S3)

Running an extract does this for every new file:

  1. keep a copy in storage under archive/<name>/...   (the permanent copy the load reads from)
  2. move the file out of the way so it never loads twice
       folder:  into the folder's _done/ subfolder
       storage: the archive copy *is* the move; the original object is removed from the watched prefix
  3. queue a load into the extract's raw table          (the worker does the rest)

Raw is always kept: transforms (next) read from the raw table and write elsewhere.
An extract runs when you click "Run now", or when a pipeline that uses it runs.
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import storage
from .config import get_settings
from .db import engine
from .events import emit, human_bytes
from .models import Extract, Run, Source
from .services import queue_run_for_object

DONE = "_done"
ARCHIVE = "archive"
SETTLE_SECONDS = 2  # a file still being copied in keeps changing; wait until it's been quiet this long


@dataclass
class Item:
    name: str
    size: int
    modified: datetime
    ref: str  # file path (folder) or object key (storage)


# ------------------------------------------------------------------ naming

def inbox_root() -> Path:
    return Path(get_settings().inbox_dir)


def folder_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60] or "extract"


def unique_folder(session: Session, name: str) -> str:
    base = folder_slug(name)
    taken = {e.config.get("folder") for e in session.scalars(select(Extract))}
    taken |= {d.name for d in inbox_root().glob("*") if d.is_dir()} if inbox_root().exists() else set()
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def normalize_prefix(prefix: str) -> str:
    prefix = prefix.strip().strip("/")
    return f"{prefix}/" if prefix else ""


def check_storage_source(bucket_name: str, prefix: str) -> str | None:
    """Reason this bucket/prefix can't be watched, or None if it's fine."""
    if bucket_name not in storage.list_buckets():
        return f"There's no bucket called “{bucket_name}”"
    if bucket_name == storage.bucket() and (prefix == "" or prefix.startswith(f"{ARCHIVE}/")):
        return ("Pick a folder (not the whole bucket, and not archive/): files are moved into archive/ after loading, "
                "so watching it would load them again")
    return None


def location(ex: Extract) -> str:
    """Where files for this extract show up, in words you can act on."""
    c = ex.config
    if ex.kind == "storage":
        return f"storage {c['bucket']}/{c['prefix']}"
    return f"data\\inbox\\{c['folder']}"


def archive_prefix(ex: Extract) -> str:
    return f"{ARCHIVE}/{ex.config['folder']}/"


def make_place(ex: Extract) -> None:
    """Create the folder (or the storage prefix) now, so you can find it."""
    if ex.kind == "storage":
        storage.client().put_object(Bucket=ex.config["bucket"], Key=ex.config["prefix"], Body=b"")
    else:
        folder_path(ex)


def content_type(name: str) -> str:
    import mimetypes

    return mimetypes.guess_type(name)[0] or ("text/csv" if name.lower().endswith(".csv") else "application/octet-stream")


def layout_text(ex: Extract) -> str:
    from .ingest.readers import describe

    return describe(ex.config.get("layout"))


def sample_files(ex: Extract, limit: int = 8) -> list[dict[str, str]]:
    """Files this extract could be set up with: what's waiting, then what it loaded recently."""
    out = []
    for i in reversed(list_items(ex)):
        ref = f"inbox:{i.name}" if ex.kind == "folder" else f"s3:{ex.config['bucket']}/{i.ref}"
        out.append({"ref": ref, "label": f"{i.name} (waiting)"})
    objs = []
    for page in storage.client().get_paginator("list_objects_v2").paginate(Bucket=storage.bucket(), Prefix=archive_prefix(ex)):
        objs += page.get("Contents", [])
    objs.sort(key=lambda o: o["LastModified"], reverse=True)
    for o in objs[:limit]:
        name = re.sub(r"^\d{6}_", "", PurePosixPath(o["Key"]).name)
        out.append({"ref": f"s3:{storage.bucket()}/{o['Key']}", "label": f"{name} (loaded {o['LastModified']:%Y-%m-%d})"})
    return out[:limit * 2]


def read_sample(ex: Extract, ref: str) -> tuple[bytes, str]:
    """(bytes, filename) for a ref from sample_files(). Only this extract's own files."""
    kind, _, rest = ref.partition(":")
    if kind == "inbox" and ex.kind == "folder":
        path = folder_path(ex) / Path(rest).name  # name only: nothing outside the folder
        if not path.is_file():
            raise FileNotFoundError(rest)
        return path.read_bytes(), path.name
    if kind == "s3":
        bucket, _, key = rest.partition("/")
        archived = bucket == storage.bucket() and key.startswith(archive_prefix(ex))
        waiting = ex.kind == "storage" and bucket == ex.config["bucket"] and key.startswith(ex.config["prefix"])
        if not (archived or waiting):
            raise FileNotFoundError(ref)
        data = storage.client().get_object(Bucket=bucket, Key=key)["Body"].read()
        name = PurePosixPath(key).name
        return data, re.sub(r"^\d{6}_", "", name) if archived else name
    raise FileNotFoundError(ref)


# ------------------------------------------------------------------ listing

def folder_path(ex: Extract) -> Path:
    path = inbox_root() / ex.config["folder"]
    (path / DONE).mkdir(parents=True, exist_ok=True)
    return path


def _matches(ex: Extract, name: str) -> bool:
    return fnmatch.fnmatch(name.lower(), (ex.config.get("pattern") or "*").lower())


def list_items(ex: Extract) -> list[Item]:
    """Everything sitting in the source right now, oldest first (matching the pattern or not)."""
    if ex.kind == "storage":
        c = ex.config
        listing = storage.list_folder(c["bucket"], c["prefix"])
        items = [Item(f["name"], f["size"], f["last_modified"], f["key"]) for f in listing["files"]]
    else:
        files = [f for f in folder_path(ex).iterdir() if f.is_file() and not f.name.startswith(".")]
        items = []
        for f in files:
            st = f.stat()
            items.append(Item(f.name, st.st_size, datetime.fromtimestamp(st.st_mtime, timezone.utc), str(f)))
    return sorted(items, key=lambda i: i.modified)


def waiting_files(ex: Extract) -> list[dict[str, Any]]:
    return [
        {"name": i.name, "size": i.size, "modified": i.modified.isoformat(), "matches": _matches(ex, i.name)}
        for i in list_items(ex)
    ]


def done_files(ex: Extract, limit: int = 20) -> list[dict[str, Any]]:
    if ex.kind == "storage":
        prefix = archive_prefix(ex)
        objs = []
        for page in storage.client().get_paginator("list_objects_v2").paginate(Bucket=storage.bucket(), Prefix=prefix):
            objs += page.get("Contents", [])
        objs.sort(key=lambda o: o["LastModified"], reverse=True)
        return [{"name": PurePosixPath(o["Key"]).name, "size": o["Size"], "modified": o["LastModified"].isoformat(),
                 "path": o["Key"]} for o in objs[:limit]]
    done = folder_path(ex) / DONE
    files = sorted((f for f in done.rglob("*") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"name": f.name, "size": f.stat().st_size,
             "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(),
             "path": str(f.relative_to(done)).replace("\\", "/")} for f in files[:limit]]


def add_file(ex: Extract, filename: str, data: bytes) -> str:
    """Put a file where the extract looks, exactly as if it had shown up there by itself."""
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(filename).name).strip() or "file.csv"
    stem, suffix = Path(safe).stem, Path(safe).suffix
    if ex.kind == "storage":
        c = ex.config
        existing = {i.name for i in list_items(ex)}
        name, n = safe, 2
        while name in existing:
            name, n = f"{stem}_{n}{suffix}", n + 1
        storage.client().put_object(Bucket=c["bucket"], Key=c["prefix"] + name, Body=data, ContentType=content_type(name))
        return name
    target = folder_path(ex) / safe
    n = 2
    while target.exists():
        target, n = target.with_name(f"{stem}_{n}{suffix}"), n + 1
    target.write_bytes(data)
    return target.name


# ------------------------------------------------------------------ running

def _lock_key(ex: Extract) -> int:
    return zlib.crc32(f"extract:{ex.id}".encode())


def run_extract(session: Session, ex: Extract, *, trigger: str = "manual", who: str | None = None,
                pipeline_id: Any = None) -> list[Run]:
    """Pick up every new matching file. Safe to call from the API and the worker at the same time.

    who: how the run started, for the Activity log ("You clicked “Run now” on ...", "Pipeline “X”").
    pipeline_id: set when a pipeline is running this extract, so its runs and events show on the pipeline too.
    """
    tags = {"extract_id": str(ex.id)}
    if pipeline_id:
        tags["pipeline_id"] = str(pipeline_id)
    with engine.connect() as lock_conn:
        if not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _lock_key(ex)}).scalar():
            if trigger == "manual":
                emit("pipeline", f"“{ex.name}” is already picking up files; try again in a moment", **tags)
            return []
        try:
            return _run_locked(session, ex, trigger, who, pipeline_id, tags)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_key(ex)})
            lock_conn.commit()


def _take(ex: Extract, item: Item, stamp: datetime, tags: dict[str, str]) -> str:
    """Archive one item and move it out of the source. Returns the archive key the load reads from."""
    key = f"{archive_prefix(ex)}{stamp:%Y-%m-%d}/{stamp:%H%M%S}_{item.name}"
    if ex.kind == "storage":
        c = ex.config
        storage.client().copy_object(Bucket=storage.bucket(), Key=key, CopySource={"Bucket": c["bucket"], "Key": item.ref},
                                     Metadata={"original-filename": item.name.encode("ascii", "replace").decode()},
                                     MetadataDirective="REPLACE", ContentType=content_type(item.name))
        storage.client().delete_object(Bucket=c["bucket"], Key=item.ref)
        emit("store", f"Moved {c['bucket']}/{item.ref} ({human_bytes(item.size)}) to {storage.bucket()}/{key} so it isn't loaded twice",
             **tags)
        return key

    path = Path(item.ref)
    data = path.read_bytes()
    storage.put(key, data, original_filename=item.name, content_type=content_type(item.name))
    emit("store", f"Archived {item.name} ({human_bytes(len(data))}) in storage at {key}", **tags)
    done_dir = path.parent / DONE / f"{stamp:%Y-%m-%d}"
    done_dir.mkdir(parents=True, exist_ok=True)
    moved = done_dir / f"{stamp:%H%M%S}_{item.name}"
    shutil.move(str(path), moved)
    emit("pipeline", f"Moved {item.name} out of the inbox into {DONE}\\{done_dir.name}\\{moved.name} so it isn't loaded twice",
         **tags)
    return key


def _run_locked(session: Session, ex: Extract, trigger: str, who: str | None, pipeline_id: Any,
                tags: dict[str, str]) -> list[Run]:
    now = datetime.now(timezone.utc)
    candidates = [i for i in list_items(ex) if _matches(ex, i.name)]
    # Objects in storage appear all at once; files in a folder may still be being copied in.
    settled = candidates if ex.kind == "storage" else [
        i for i in candidates if (now - i.modified).total_seconds() >= SETTLE_SECONDS
    ]

    who = who or ("You clicked “Run now”" if trigger == "manual" else "Watching")
    if not settled:
        if trigger == "manual":
            extra = f" ({len(candidates)} still being copied in)" if candidates else ""
            emit("pipeline", f"{who} on extract “{ex.name}”: no new files in {location(ex)}{extra}", **tags)
        return []

    source = session.get(Source, ex.source_id) if ex.source_id else None
    if source is None:
        emit("error", f"Extract “{ex.name}” found files but its raw table no longer exists. Pick a table for it.", **tags)
        return []

    emit("pipeline", f"{who} on extract “{ex.name}”: found {len(settled)} new file{'s' if len(settled) != 1 else ''} "
         f"in {location(ex)}", files=[i.name for i in settled], **tags)

    runs = []
    stamp = datetime.now(timezone.utc)
    for item in settled:
        key = _take(ex, item, stamp, tags)
        run = queue_run_for_object(session, source, key, item.name, layout=ex.config.get("layout"))
        run.extract_id = ex.id
        run.pipeline_id = pipeline_id
        session.commit()
        emit("queue", f"Queued a load of {item.name} into table raw.{source.table_name}",
             source_id=source.id, run_id=run.id, source_name=source.name, **tags)
        runs.append(run)
    return runs
