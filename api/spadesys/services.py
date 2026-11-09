"""Operations shared by the API routes and generators."""

from __future__ import annotations

import uuid
from pathlib import PurePath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import storage
from .events import emit, human_bytes
from .ingest.infer import snake_case
from .ingest.pipeline import read_csv_bytes  # noqa: F401  (re-exported for older callers)
from .ingest.readers import apply_layout, clean_layout, describe, guess_layout, is_default, read_grid
from .models import Run, Source


def unique_table_name(session: Session, base: str) -> str:
    base = snake_case(base, fallback="dataset")[:55]
    taken = set(session.scalars(select(Source.table_name).where(Source.table_name.like(f"{base}%"))))
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def create_source(session: Session, name: str) -> Source:
    source = Source(name=name, kind="csv", table_name=unique_table_name(session, name))
    session.add(source)
    session.flush()
    return source


def queue_run_for_object(session: Session, source: Source, key: str, filename: str,
                         layout: dict[str, Any] | None = None) -> Run:
    """Queue a load of a file that is already in storage. layout: where the table is in the file."""
    run = Run(id=uuid.uuid4(), source=source, pipeline="csv_ingest", status="queued", object_key=key,
              original_filename=filename, layout=layout)
    session.add(run)
    return run


def queue_csv_run(session: Session, source: Source, filename: str, data: bytes, folder: str = "uploads") -> Run:
    """Store the bytes, then queue a load of them."""
    key = storage.new_key(folder, filename)
    storage.put(key, data, original_filename=filename)
    emit(
        "store",
        f"Saved the original file {filename} ({human_bytes(len(data))}) to storage at {key}",
        source_id=source.id, source_name=source.name,
    )
    return queue_run_for_object(session, source, key, filename)


def commit_queued(session: Session, run: Run) -> None:
    session.commit()
    emit(
        "queue", "Added to the job queue; a background worker will pick it up",
        source_id=run.source_id, run_id=run.id, source_name=run.source.name,
    )


def ingest_csv(session: Session, filename: str, data: bytes, name: str | None = None, folder: str = "uploads") -> Source:
    """Non-interactive path (API scripting, sample data): new source + immediate load."""
    source = create_source(session, name or PurePath(filename).stem)
    run = queue_csv_run(session, source, filename, data, folder=folder)
    commit_queued(session, run)
    return source


# ---------------------------------------------------------------- suggestions

def analyze_file(session: Session, key: str, filename: str, data: bytes,
                 layout: dict[str, Any] | None = None) -> dict[str, Any]:
    """Peek at a stored file and suggest what to do with it. Changes nothing.

    With no layout, Spadesys guesses where the table is (title rows, a totals row) and says so.
    """
    grid = read_grid(data, filename, (layout or {}).get("sheet"))
    guessed = layout is None
    layout = clean_layout(layout or guess_layout(grid))
    df, notes = apply_layout(grid, layout)
    columns = [str(c) for c in df.columns]
    stem = snake_case(PurePath(filename).stem, fallback="dataset")
    col_set = set(columns)

    suggestions = []
    for s in session.scalars(select(Source).order_by(Source.created_at.desc())):
        score, reasons = 0, []
        prev = {snake_case(PurePath(r.original_filename).stem) for r in s.runs if r.original_filename}
        if stem in prev:
            score += 2
            reasons.append(f"You've loaded a file called “{filename}” into this before")
        elif stem == s.table_name:
            score += 1
            reasons.append("Its table has the same name as this file")

        if s.inferred_schema:
            existing = {c["original_name"] for c in s.inferred_schema["columns"]}
            same = col_set & existing
            if same == col_set == existing:
                score += 2
                reasons.append(f"Same {len(col_set)} columns")
            elif same and len(same) / len(col_set | existing) >= 0.6:
                score += 1
                new = sorted(col_set - existing)
                missing = sorted(existing - col_set)
                txt = f"{len(same)} of {len(col_set)} columns match"
                if new:
                    txt += f"; new here: {', '.join(new)}"
                if missing:
                    txt += f"; not in this file: {', '.join(missing)}"
                reasons.append(txt)

        if score:
            suggestions.append({
                "source_id": s.id, "source_name": s.name, "table_name": s.table_name,
                "row_count": s.row_count, "score": score, "reasons": reasons,
            })

    suggestions.sort(key=lambda x: -x["score"])
    for i, sug in enumerate(suggestions):
        sug["recommended"] = i == 0 and sug["score"] >= 3

    return {
        "key": key,
        "filename": filename,
        "size": len(data),
        "row_count": int(len(df)),
        "columns": columns,
        "preview_rows": df.head(5).values.tolist(),
        "suggestions": suggestions[:5],
        "suggested_new_name": PurePath(filename).stem,
        "suggested_table_name": unique_table_name(session, PurePath(filename).stem),
        "layout": layout,
        "layout_text": describe(layout, grid),
        "layout_notes": notes,
        "layout_guessed": guessed and not is_default(layout),
    }
