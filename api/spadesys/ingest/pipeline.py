"""csv_ingest pipeline: object storage -> validate -> infer -> hash -> load."""

from __future__ import annotations

import re
from collections import Counter
from functools import partial
from typing import Any, Callable

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import storage
from ..config import get_settings
from ..db import engine
from ..events import emit, human_bytes
from ..models import Run, Source
from .hashing import hash_frame
from .infer import infer_schema
from .load import load_frame
from .readers import is_default, read_table


class ValidationError(Exception):
    pass


def read_csv_bytes(data: bytes, filename: str = "file.csv") -> pd.DataFrame:
    """A plain file: headers on row 1, data below. (Kept for callers that don't use layouts.)"""
    return read_table(data, filename)[0]


def validate(df: pd.DataFrame) -> list[str]:
    """Raise on hard failures; return soft warnings."""
    if df.shape[1] == 0:
        raise ValidationError("File has no columns")
    if len(df) == 0:
        raise ValidationError("File has a header but no rows")
    warnings = []
    unnamed = [c for c in df.columns if re.fullmatch(r"column_\d+", str(c))]
    if unnamed:
        warnings.append(f"{len(unnamed)} column(s) had no header and were auto-named")
    return warnings


def run_csv_ingest(session: Session, run: Run) -> dict[str, Any]:
    settings = get_settings()
    source: Source = run.source
    ev = partial(emit, source_id=source.id, run_id=run.id, source_name=source.name)

    data = storage.get_bytes(run.object_key)
    ev("download", f"Fetched {run.original_filename} ({human_bytes(len(data))}) from storage")

    layout = run.layout
    df, notes, how = read_table(data, run.original_filename or run.object_key, layout)
    ev(
        "parse",
        f"Read {len(df):,} rows × {df.shape[1]} columns"
        + (f" using the saved file layout: {how}" if not is_default(layout) else f" ({how})")
        + (f". {'. '.join(notes)}" if notes else ""),
        columns=[str(c) for c in df.columns], layout=layout, layout_text=how, notes=notes,
    )

    warnings = validate(df)
    ev("validate", "Checks passed" + (f", with warnings: {'; '.join(warnings)}" if warnings else ": file has a header and rows"))

    schema = infer_schema(df)
    counts = Counter(c["type"] for c in schema["columns"])
    ev(
        "infer",
        "Guessed column types: " + ", ".join(f"{n} {t}" for t, n in counts.most_common()),
        types={c["name"]: c["type"] for c in schema["columns"]},
        key_candidates=schema["key_candidates"],
    )

    hashes = hash_frame(df)
    dup_in_file = int(hashes.duplicated().sum())
    ev(
        "hash",
        f"Fingerprinted every row: {len(df) - dup_in_file:,} unique"
        + (f", {dup_in_file:,} exact duplicates inside the file" if dup_in_file else ""),
    )

    target = f"{settings.raw_schema}.{source.table_name}"
    with engine.begin() as conn:
        result = load_frame(conn, df, hashes, schema["columns"], source.table_name, settings.raw_schema, run.id)
        total = conn.execute(text(f'SELECT count(*) FROM "{settings.raw_schema}"."{source.table_name}"')).scalar_one()

    rows_read = int(len(df))
    already = rows_read - dup_in_file - result["rows_inserted"]
    msg = f"Wrote {result['rows_inserted']:,} new rows to Postgres table {target}"
    if already:
        msg += f"; skipped {already:,} rows already there"
    if result["columns_added"]:
        msg += f"; added new column(s): {', '.join(result['columns_added'])}"
    ev("load", msg + f". Table now has {total:,} rows.")

    source.inferred_schema = schema
    source.row_count = int(total)

    return {
        "rows_read": rows_read,
        "rows_inserted": result["rows_inserted"],
        "rows_already_loaded": rows_read - dup_in_file - result["rows_inserted"],
        "duplicate_rows_in_file": dup_in_file,
        "columns": len(schema["columns"]),
        "columns_added": result["columns_added"],
        "warnings": warnings,
    }


PIPELINES: dict[str, Callable[[Session, Run], dict[str, Any]]] = {"csv_ingest": run_csv_ingest}
