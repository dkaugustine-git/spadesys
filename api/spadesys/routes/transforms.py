"""Transforms: reusable changes from a raw (or clean) table to clean.<output>, with a live preview and the SQL."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from .. import transforms as tf
from ..db import engine, get_session
from ..events import emit
from ..models import Event, Transform
from ..schemas import EventOut

router = APIRouter(prefix="/transforms", tags=["transforms"])
DB = Annotated[Session, Depends(get_session)]


class TransformBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    input_table: str
    steps: list[dict[str, Any]] = []
    output_table: str = ""  # default: a slug of the name


class PreviewBody(BaseModel):
    input_table: str
    steps: list[dict[str, Any]] = []
    output_table: str = ""
    limit: int = Field(50, ge=1, le=500)


class TransformOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    input_table: str
    steps: list[dict[str, Any]]
    output_table: str
    output_full: str
    last_run_at: datetime | None
    last_rows: int | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


def _out(t: Transform) -> TransformOut:
    return TransformOut(
        id=t.id, name=t.name, description=t.description, input_table=t.input_table, steps=t.steps,
        output_table=t.output_table, output_full=f"{tf.schemas()[1]}.{t.output_table}", last_run_at=t.last_run_at,
        last_rows=t.last_rows, last_error=t.last_error, created_at=t.created_at, updated_at=t.updated_at,
    )


def _get(session: Session, tid: uuid.UUID) -> Transform:
    t = session.get(Transform, tid)
    if t is None:
        raise HTTPException(404, "Transform not found")
    return t


def _db_message(exc: DBAPIError) -> str:
    orig = getattr(exc, "orig", None)
    msg = str(orig or exc).strip().splitlines()[0]
    if "statement timeout" in msg:
        return "The preview took longer than 10 seconds and was stopped"
    return f"The database said: {msg}"


def _output_name(body_output: str, name: str) -> str:
    out = body_output.strip() or tf.slug(name)
    try:
        return tf.valid_name(out)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/ops")
def ops():
    """The kinds of step a transform can have."""
    return [{"op": k, "label": v} for k, v in tf.OPS.items()]


@router.get("/tables")
def tables(session: DB):
    """Tables a transform can read: everything in raw and clean, with which transform made each clean one."""
    made_by = {t.output_table: {"id": t.id, "name": t.name} for t in session.scalars(select(Transform))}
    with engine.connect() as conn:
        out = tf.list_tables(conn)
    for t in out:
        t["made_by"] = made_by.get(t["name"]) if t["schema"] == tf.schemas()[1] else None
    return jsonable_encoder(out)


@router.post("/preview")
def preview(body: PreviewBody):
    """Compile and run a transform without saving it: the SQL, the columns after each step, and sample rows.

    Never fails on a bad step; it reports which step is wrong and what's right up to there.
    """
    with engine.connect() as conn:
        try:
            c = tf.compile_steps(conn, body.input_table, body.steps, body.output_table.strip())
        except tf.TransformError as e:
            return {"ok": False, "error": {"step": e.step, "message": str(e)},
                    "step_columns": [[x.as_dict() for x in cols] for cols in e.step_columns]}
        conn.rollback()  # end the catalog reads so the preview gets its own transaction (and timeout)
        try:
            with conn.begin():
                res = tf.preview(conn, c, body.limit)
        except DBAPIError as e:
            return {"ok": False, "sql": c.sql, "error": {"step": None, "message": _db_message(e)}}
    return jsonable_encoder({
        "ok": True, "sql": c.sql, "columns": [x.as_dict() for x in c.columns],
        "step_columns": [[x.as_dict() for x in cols] for cols in c.step_columns],
        "rows": res["rows"], "row_count": res["row_count"],
    })


@router.get("", response_model=list[TransformOut])
def list_transforms(session: DB):
    return [_out(t) for t in session.scalars(select(Transform).order_by(Transform.created_at.desc()))]


@router.post("", response_model=TransformOut, status_code=201)
def create_transform(session: DB, body: TransformBody):
    output = _output_name(body.output_table, body.name)
    taken = session.scalar(select(Transform.name).where(Transform.output_table == output))
    if taken:
        raise HTTPException(409, f"Transform “{taken}” already writes {tf.schemas()[1]}.{output}; pick another output name")
    t = Transform(name=body.name.strip(), description=body.description, input_table=body.input_table,
                  steps=body.steps, output_table=output)
    session.add(t)
    session.commit()
    emit("transform", f"Saved transform “{t.name}”: {t.input_table} → {len(t.steps)} step{'s' if len(t.steps) != 1 else ''} "
         f"→ {tf.schemas()[1]}.{output}", transform_id=str(t.id))
    return _out(t)


@router.get("/{tid}", response_model=TransformOut)
def get_transform(session: DB, tid: uuid.UUID):
    return _out(_get(session, tid))


@router.put("/{tid}", response_model=TransformOut)
def save_transform(session: DB, tid: uuid.UUID, body: TransformBody):
    t = _get(session, tid)
    output = _output_name(body.output_table, body.name)
    taken = session.scalar(select(Transform.name).where(Transform.output_table == output, Transform.id != t.id))
    if taken:
        raise HTTPException(409, f"Transform “{taken}” already writes {tf.schemas()[1]}.{output}; pick another output name")
    t.name, t.description, t.input_table, t.steps, t.output_table = (
        body.name.strip(), body.description, body.input_table, body.steps, output)
    session.commit()
    emit("transform", f"Saved changes to transform “{t.name}” ({len(t.steps)} step{'s' if len(t.steps) != 1 else ''})",
         transform_id=str(t.id))
    return _out(t)


@router.delete("/{tid}", status_code=204)
def delete_transform(session: DB, tid: uuid.UUID, drop_table: bool = False):
    t = _get(session, tid)
    name, out = t.name, t.output_table
    if drop_table:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {tf.q(tf.schemas()[1])}.{tf.q(out)}"))
    session.delete(t)
    session.commit()
    emit("transform", f"Deleted transform “{name}”"
         + (f" and dropped {tf.schemas()[1]}.{out}" if drop_table else f". Its table {tf.schemas()[1]}.{out} was left alone."))


def run_transform(session: Session, t: Transform) -> dict[str, Any]:
    """Rebuild clean.<output> from scratch. Raw tables are only read."""
    tid = str(t.id)
    full = f"{tf.schemas()[1]}.{t.output_table}"
    emit("transform", f"Running transform “{t.name}”: reading {t.input_table}, {len(t.steps)} step(s)", transform_id=tid)
    start = time.monotonic()
    try:
        with engine.begin() as conn:
            c = tf.compile_steps(conn, t.input_table, t.steps, t.output_table)
            rows = tf.write(conn, c, t.output_table)
    except (tf.TransformError, DBAPIError) as e:
        msg = str(e) if isinstance(e, tf.TransformError) else _db_message(e)
        if isinstance(e, tf.TransformError) and e.step is not None:
            msg = f"Step {e.step + 1}: {msg}"
        t.last_error = msg
        session.commit()
        emit("error", f"Transform “{t.name}” failed: {msg}. {full} was left as it was.", transform_id=tid)
        raise HTTPException(400, msg) from None
    t.last_run_at, t.last_rows, t.last_error = datetime.now(timezone.utc), rows, None
    session.commit()
    others = [r for r in c.reads if r != t.input_table]
    emit("transform", f"Wrote {rows:,} rows to {full} from {t.input_table}"
         + (f" (stacked with {', '.join(others)})" if others else "")
         + f" in {time.monotonic() - start:.1f}s. The raw data wasn't changed.", transform_id=tid)
    return {"rows": rows, "table": full}


@router.post("/{tid}/run")
def run(session: DB, tid: uuid.UUID):
    return run_transform(session, _get(session, tid))


@router.get("/{tid}/sql")
def sql(session: DB, tid: uuid.UUID):
    t = _get(session, tid)
    with engine.connect() as conn:
        try:
            c = tf.compile_steps(conn, t.input_table, t.steps, t.output_table)
        except tf.TransformError as e:
            raise HTTPException(400, str(e)) from None
    clean = tf.schemas()[1]
    return {"sql": f"DROP TABLE IF EXISTS {clean}.{t.output_table};\nCREATE TABLE {clean}.{t.output_table} AS\n{c.sql};"}


@router.get("/{tid}/events", response_model=list[EventOut])
def transform_events(session: DB, tid: uuid.UUID, after_id: int = 0, limit: int = 200):
    q = select(Event).where(Event.id > after_id, Event.detail["transform_id"].astext == str(tid))
    rows = session.scalars(q.order_by(Event.id.desc()).limit(max(1, min(limit, 1000)))).all()
    return list(reversed(rows))
