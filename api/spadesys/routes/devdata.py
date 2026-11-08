"""Dev data: connect to a database, read a table's columns (or paste names), generate fake rows."""

from __future__ import annotations

import os
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import cloudbeaver, storage
from ..db import get_session
from ..devdata import dbbrowse
from ..devdata.engine import GenerationError, generate_rows, output_fields, to_csv, to_jsonable
from ..devdata.generators import catalog
from ..devdata.recommend import FieldSpec, apply_samples, parse_pasted_table, recommend
from ..events import emit, human_bytes
from ..models import Connection

router = APIRouter(tags=["dev data"])
DB = Annotated[Session, Depends(get_session)]


def _err(exc: Exception) -> str:
    msg = str(getattr(exc, "orig", None) or exc).strip().splitlines()
    return msg[0] if msg else type(exc).__name__


# ------------------------------------------------------------ connections
class ConnectionIn(BaseModel):
    name: str
    kind: Literal["postgresql", "mysql"]
    host: str
    port: int
    database: str = ""
    username: str
    password: str = ""


class ConnectionOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    host: str
    port: int
    database: str
    username: str


def _conn(session: Session, cid: uuid.UUID) -> Connection:
    c = session.get(Connection, cid)
    if c is None:
        raise HTTPException(404, "Connection not found")
    return c


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(session: DB):
    return [ConnectionOut.model_validate(c, from_attributes=True) for c in session.scalars(select(Connection).order_by(Connection.name))]


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
IN_DOCKER = os.path.exists("/.dockerenv")


def _localhost_hint(host: str) -> dict[str, str]:
    """Inside Docker, 'localhost' is Spadesys's own container, not the user's computer."""
    if IN_DOCKER and host.strip().lower() in LOCAL_HOSTS:
        return {
            "hint": "Spadesys runs inside Docker, so “localhost” points at Spadesys itself, not your computer. "
            "To reach a database on your computer (including one in another Docker container with a published port), "
            "use host.docker.internal.",
            "suggested_host": "host.docker.internal",
        }
    return {}


@router.post("/connections/test")
def test_connection(body: ConnectionIn):
    where = f"{body.kind}://{body.username}@{body.host}:{body.port}/{body.database}"
    try:
        version = dbbrowse.test(Connection(id=uuid.uuid4(), **body.model_dump()))
        emit("connect", f"Connection test to {where} worked")
        return {"ok": True, "version": version}
    except Exception as exc:  # noqa: BLE001
        emit("error", f"Connection test to {where} failed: {_err(exc)}")
        return {"ok": False, "error": _err(exc), **_localhost_hint(body.host)}


@router.post("/connections", response_model=ConnectionOut, status_code=201)
def create_connection(session: DB, body: ConnectionIn):
    c = Connection(**body.model_dump())
    try:
        dbbrowse.test(c)
    except Exception as exc:  # noqa: BLE001
        hint = _localhost_hint(body.host).get("hint", "")
        raise HTTPException(400, f"Couldn't connect: {_err(exc)}" + (f"\n\n{hint}" if hint else "")) from exc
    session.add(c)
    session.commit()
    emit("connect", f"Saved a connection to {dbbrowse.connection_label(c)}")
    cloudbeaver.sync(session)
    return ConnectionOut.model_validate(c, from_attributes=True)


@router.delete("/connections/{cid}", status_code=204)
def delete_connection(session: DB, cid: uuid.UUID):
    session.delete(_conn(session, cid))
    session.commit()
    cloudbeaver.sync(session)


@router.get("/connections/{cid}/tables")
def list_tables(session: DB, cid: uuid.UUID):
    try:
        return dbbrowse.list_tables(_conn(session, cid))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Couldn't list tables: {_err(exc)}") from exc


@router.get("/connections/{cid}/tables/{schema}/{table}", response_model=list[FieldSpec])
def describe_table(session: DB, cid: uuid.UUID, schema: str, table: str):
    c = _conn(session, cid)
    try:
        fields = dbbrowse.describe(c, schema, table)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Couldn't read {schema}.{table}: {_err(exc)}") from exc
    emit("schema", f"Read the columns of {schema}.{table} from {c.name}: {len(fields)} columns")
    return fields


# ------------------------------------------------------------ dev data
class RecommendIn(BaseModel):
    text: str = ""
    columns: list[str] = []


@router.get("/devdata/catalog")
def get_catalog():
    return catalog()


@router.post("/devdata/recommend", response_model=list[FieldSpec])
def recommend_fields(body: RecommendIn):
    if body.columns:
        return [recommend(n) for n in body.columns]
    names, rows = parse_pasted_table(body.text)
    if not names:
        raise HTTPException(400, "Paste at least one column name")
    return [apply_samples(recommend(n), [r[i] for r in rows]) for i, n in enumerate(names)]


class GenerateIn(BaseModel):
    fields: list[FieldSpec]
    rows: int = Field(100, ge=1, le=100_000)
    seed: int | None = None
    connection_id: uuid.UUID | None = None  # needed for "existing values" and for insert


def _ref_values(session: Session, body: GenerateIn) -> dict[str, list[Any]]:
    refs = {f.name: f.params.get("ref") for f in body.fields if f.generator == "existing"}
    if not refs:
        return {}
    if not body.connection_id:
        raise HTTPException(400, "“Values that already exist in another table” needs a database connection")
    c = _conn(session, body.connection_id)
    out = {}
    for name, ref in refs.items():
        if not ref or ref.count(".") < 2:
            raise HTTPException(400, f"{name}: say which table.column to take values from (schema.table.column)")
        try:
            out[name] = dbbrowse.fetch_values(c, ref)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"{name}: couldn't read {ref}: {_err(exc)}") from exc
    return out


def _generate(session: Session, body: GenerateIn, rows: int) -> list[dict[str, Any]]:
    try:
        return generate_rows(body.fields, rows, seed=body.seed, ref_values=_ref_values(session, body))
    except GenerationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/devdata/preview")
def preview(session: DB, body: GenerateIn):
    rows = _generate(session, body, min(body.rows, 10))
    cols = [f.name for f in output_fields(body.fields)]
    return {"columns": cols, "rows": [[to_jsonable(r[c]) for c in cols] for r in rows]}


class CsvOut(GenerateIn):
    filename: str = "dev_data.csv"


@router.post("/devdata/download")
def download(session: DB, body: CsvOut):
    data = to_csv(body.fields, _generate(session, body, body.rows))
    emit("devdata", f"Made {body.rows:,} rows of dev data and downloaded them as {body.filename}")
    return Response(data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{body.filename}"'})


@router.post("/devdata/to-storage")
def to_storage(session: DB, body: CsvOut):
    data = to_csv(body.fields, _generate(session, body, body.rows))
    key = storage.new_key("devdata", body.filename)
    storage.put(key, data, original_filename=body.filename)
    emit("devdata", f"Made {body.rows:,} rows of dev data and saved them to storage at {key} ({human_bytes(len(data))})")
    return {"key": key, "size": len(data)}


class InsertIn(GenerateIn):
    connection_id: uuid.UUID
    schema_name: str
    table: str


@router.post("/devdata/insert")
def insert(session: DB, body: InsertIn):
    c = _conn(session, body.connection_id)
    rows = _generate(session, body, body.rows)
    try:
        n = dbbrowse.insert_rows(c, body.schema_name, body.table, rows)
    except Exception as exc:  # noqa: BLE001
        emit("error", f"Inserting dev data into {body.schema_name}.{body.table} on {c.name} failed, nothing was added: {_err(exc)}")
        raise HTTPException(400, f"The database refused the rows, so nothing was added: {_err(exc)}") from exc
    emit("devdata", f"Inserted {n:,} rows of dev data into {body.schema_name}.{body.table} on {c.name}")
    return {"inserted": n}
