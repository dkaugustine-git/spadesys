"""Pipelines: watch a place where files show up, load each new file into a table, archive the file.

Two kinds of place ("source"):

  folder   data/inbox/<name> on your computer (mounted at /data/inbox in the containers)
  storage  a bucket + folder (prefix) in Spadesys storage (MinIO / any S3)

A pipeline run does this for every new file:

  1. keep a copy in storage under archive/<name>/...   (the permanent copy the load reads from)
  2. move the file out of the way so it never loads twice
       folder:  into the folder's _done/ subfolder
       storage: the archive copy *is* the move; the original object is removed from the watched prefix
  3. queue a load into the destination table           (the worker does the rest)

Runs happen when you click "Run now", or every N seconds when the pipeline is set to watch.
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
from .models import Pipeline, Run, Source
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
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60] or "pipeline"


def unique_folder(session: Session, name: str) -> str:
    base = folder_slug(name)
    taken = {p.source_config.get("folder") for p in session.scalars(select(Pipeline))}
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


def location(p: Pipeline) -> str:
    """Where files for this pipeline show up, in words you can act on."""
    c = p.source_config
    if p.source_kind == "storage":
        return f"storage {c['bucket']}/{c['prefix']}"
    return f"data\\inbox\\{c['folder']}"


host_path = location  # older name


def archive_prefix(p: Pipeline) -> str:
    return f"{ARCHIVE}/{p.source_config['folder']}/"


# ------------------------------------------------------------------ listing

def folder_path(p: Pipeline) -> Path:
    path = inbox_root() / p.source_config["folder"]
    (path / DONE).mkdir(parents=True, exist_ok=True)
    return path


def _matches(p: Pipeline, name: str) -> bool:
    return fnmatch.fnmatch(name.lower(), (p.source_config.get("pattern") or "*").lower())


def list_items(p: Pipeline) -> list[Item]:
    """Everything sitting in the source right now, oldest first (matching the pattern or not)."""
    if p.source_kind == "storage":
        c = p.source_config
        listing = storage.list_folder(c["bucket"], c["prefix"])
        items = [Item(f["name"], f["size"], f["last_modified"], f["key"]) for f in listing["files"]]
    else:
        files = [f for f in folder_path(p).iterdir() if f.is_file() and not f.name.startswith(".")]
        items = []
        for f in files:
            st = f.stat()
            items.append(Item(f.name, st.st_size, datetime.fromtimestamp(st.st_mtime, timezone.utc), str(f)))
    return sorted(items, key=lambda i: i.modified)


def waiting_files(p: Pipeline) -> list[dict[str, Any]]:
    return [
        {"name": i.name, "size": i.size, "modified": i.modified.isoformat(), "matches": _matches(p, i.name)}
        for i in list_items(p)
    ]


def done_files(p: Pipeline, limit: int = 20) -> list[dict[str, Any]]:
    if p.source_kind == "storage":
        prefix = archive_prefix(p)
        objs = []
        for page in storage.client().get_paginator("list_objects_v2").paginate(Bucket=storage.bucket(), Prefix=prefix):
            objs += page.get("Contents", [])
        objs.sort(key=lambda o: o["LastModified"], reverse=True)
        return [{"name": PurePosixPath(o["Key"]).name, "size": o["Size"], "modified": o["LastModified"].isoformat(),
                 "path": o["Key"]} for o in objs[:limit]]
    done = folder_path(p) / DONE
    files = sorted((f for f in done.rglob("*") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"name": f.name, "size": f.stat().st_size,
             "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(),
             "path": str(f.relative_to(done)).replace("\\", "/")} for f in files[:limit]]


def add_file(p: Pipeline, filename: str, data: bytes) -> str:
    """Put a file where the pipeline looks, exactly as if it had shown up there by itself."""
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(filename).name).strip() or "file.csv"
    stem, suffix = Path(safe).stem, Path(safe).suffix
    if p.source_kind == "storage":
        c = p.source_config
        existing = {i.name for i in list_items(p)}
        name, n = safe, 2
        while name in existing:
            name, n = f"{stem}_{n}{suffix}", n + 1
        storage.client().put_object(Bucket=c["bucket"], Key=c["prefix"] + name, Body=data, ContentType="text/csv")
        return name
    target = folder_path(p) / safe
    n = 2
    while target.exists():
        target, n = target.with_name(f"{stem}_{n}{suffix}"), n + 1
    target.write_bytes(data)
    return target.name


save_into_folder = add_file  # older name


# ------------------------------------------------------------------ running

def _lock_key(p: Pipeline) -> int:
    return zlib.crc32(f"pipeline:{p.id}".encode())


def run_pipeline(session: Session, p: Pipeline, trigger: str = "manual") -> list[Run]:
    """Pick up every new matching file. Safe to call from the API and the worker at the same time."""
    with engine.connect() as lock_conn:
        if not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _lock_key(p)}).scalar():
            if trigger == "manual":
                emit("pipeline", f"“{p.name}” is already picking up files; try again in a moment", pipeline_id=str(p.id))
            return []
        try:
            return _run_locked(session, p, trigger)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_key(p)})
            lock_conn.commit()


def _take(p: Pipeline, item: Item, stamp: datetime) -> str:
    """Archive one item and move it out of the source. Returns the archive key the load reads from."""
    pid = str(p.id)
    key = f"{archive_prefix(p)}{stamp:%Y-%m-%d}/{stamp:%H%M%S}_{item.name}"
    if p.source_kind == "storage":
        c = p.source_config
        storage.client().copy_object(Bucket=storage.bucket(), Key=key, CopySource={"Bucket": c["bucket"], "Key": item.ref},
                                     Metadata={"original-filename": item.name.encode("ascii", "replace").decode()},
                                     MetadataDirective="REPLACE", ContentType="text/csv")
        storage.client().delete_object(Bucket=c["bucket"], Key=item.ref)
        emit("store", f"Moved {c['bucket']}/{item.ref} ({human_bytes(item.size)}) to {storage.bucket()}/{key} so it isn't loaded twice",
             pipeline_id=pid)
        return key

    path = Path(item.ref)
    data = path.read_bytes()
    storage.put(key, data, original_filename=item.name)
    emit("store", f"Archived {item.name} ({human_bytes(len(data))}) in storage at {key}", pipeline_id=pid)
    done_dir = path.parent / DONE / f"{stamp:%Y-%m-%d}"
    done_dir.mkdir(parents=True, exist_ok=True)
    moved = done_dir / f"{stamp:%H%M%S}_{item.name}"
    shutil.move(str(path), moved)
    emit("pipeline", f"Moved {item.name} out of the inbox into {DONE}\\{done_dir.name}\\{moved.name} so it isn't loaded twice",
         pipeline_id=pid)
    return key


def _run_locked(session: Session, p: Pipeline, trigger: str) -> list[Run]:
    pid = str(p.id)
    now = datetime.now(timezone.utc)
    candidates = [i for i in list_items(p) if _matches(p, i.name)]
    # Objects in storage appear all at once; files in a folder may still be being copied in.
    settled = candidates if p.source_kind == "storage" else [
        i for i in candidates if (now - i.modified).total_seconds() >= SETTLE_SECONDS
    ]

    who = "You clicked “Run now”" if trigger == "manual" else "Watching"
    if not settled:
        if trigger == "manual":
            extra = f" ({len(candidates)} still being copied in)" if candidates else ""
            emit("pipeline", f"{who} on “{p.name}”: no new files in {location(p)}{extra}", pipeline_id=pid)
        return []

    source = session.get(Source, p.destination_source_id) if p.destination_source_id else None
    if source is None:
        emit("error", f"“{p.name}” found files but its destination table no longer exists. Pick a table for it.", pipeline_id=pid)
        return []

    emit("pipeline", f"{who} on “{p.name}”: found {len(settled)} new file{'s' if len(settled) != 1 else ''} in {location(p)}",
         pipeline_id=pid, files=[i.name for i in settled])

    runs = []
    stamp = datetime.now(timezone.utc)
    for item in settled:
        key = _take(p, item, stamp)
        run = queue_run_for_object(session, source, key, item.name)
        run.pipeline_id = p.id
        session.commit()
        emit("queue", f"Queued a load of {item.name} into table raw.{source.table_name}",
             source_id=source.id, run_id=run.id, source_name=source.name, pipeline_id=pid)
        runs.append(run)
    return runs


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
