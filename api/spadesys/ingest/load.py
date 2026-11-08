"""Cast raw string frames to inferred types and land them in Postgres."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, MetaData, Numeric, Table, Text, inspect, text
from sqlalchemy.dialects.postgresql import UUID, insert
from sqlalchemy.engine import Connection

from .infer import FALSE_TOKENS, TRUE_TOKENS, is_null

SA_TYPES = {
    "boolean": Boolean,
    "integer": BigInteger,
    "decimal": Numeric,
    "date": Date,
    "timestamp": lambda: DateTime(timezone=True),
    "text": Text,
}

PG_TYPES = {
    "boolean": "BOOLEAN",
    "integer": "BIGINT",
    "decimal": "NUMERIC",
    "date": "DATE",
    "timestamp": "TIMESTAMPTZ",
    "text": "TEXT",
}

SYSTEM_COLUMNS = ["_row_hash", "_run_id", "_loaded_at"]
CHUNK = 2_000


def cast_value(v: object, type_: str) -> Any:
    if is_null(v):
        return None
    s = str(v).strip()
    if type_ == "boolean":
        lo = s.lower()
        return True if lo in TRUE_TOKENS else False if lo in FALSE_TOKENS else None
    if type_ == "integer":
        return int(s)
    if type_ == "decimal":
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    if type_ in ("date", "timestamp"):
        ts = pd.Timestamp(s)
        if type_ == "date":
            return ts.date()
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")  # naive CSV timestamps are treated as UTC
        return ts.to_pydatetime()
    return s


def build_table(table_name: str, schema_name: str, columns: list[dict]) -> Table:
    cols = [Column(c["name"], SA_TYPES[c["type"]]()) for c in columns]
    cols += [
        Column("_row_hash", Text, primary_key=True),
        Column("_run_id", UUID(as_uuid=True), nullable=False),
        Column("_loaded_at", DateTime(timezone=True), nullable=False),
    ]
    return Table(table_name, MetaData(schema=schema_name), *cols)


def ensure_table(conn: Connection, table: Table, columns: list[dict]) -> list[str]:
    """Create the table, or add any new columns (schema drift). Returns added column names."""
    insp = inspect(conn)
    if not insp.has_table(table.name, schema=table.schema):
        table.create(conn)
        return []
    existing = {c["name"] for c in insp.get_columns(table.name, schema=table.schema)}
    added = []
    for c in columns:
        if c["name"] not in existing:
            ddl = f'ALTER TABLE "{table.schema}"."{table.name}" ADD COLUMN "{c["name"]}" {PG_TYPES[c["type"]]}'
            conn.execute(text(ddl))
            added.append(c["name"])
    return added


def load_frame(
    conn: Connection,
    df: pd.DataFrame,
    hashes: pd.Series,
    columns: list[dict],
    table_name: str,
    schema_name: str,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    table = build_table(table_name, schema_name, columns)
    added = ensure_table(conn, table, columns)

    loaded_at = datetime.now(timezone.utc)
    src_cols = [c["original_name"] for c in columns]
    records = []
    for row, h in zip(df[src_cols].itertuples(index=False, name=None), hashes):
        rec = {c["name"]: cast_value(v, c["type"]) for c, v in zip(columns, row)}
        rec.update(_row_hash=h, _run_id=run_id, _loaded_at=loaded_at)
        records.append(rec)

    inserted = 0
    for i in range(0, len(records), CHUNK):
        stmt = insert(table).on_conflict_do_nothing(index_elements=["_row_hash"]).returning(table.c._row_hash)
        inserted += len(conn.execute(stmt, records[i : i + CHUNK]).all())

    return {"rows_inserted": inserted, "columns_added": added}
