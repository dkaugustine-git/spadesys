"""Connect to a developer's database server, list its tables, and describe a table."""

from __future__ import annotations

import socket
import uuid
from typing import Any

from sqlalchemy import URL, Engine, MetaData, Table, create_engine, inspect, select, text, types
from sqlalchemy.sql import column, table

from ..models import Connection
from .recommend import FieldSpec, recommend

DRIVERS = {"postgresql": "postgresql+psycopg", "mysql": "mysql+pymysql"}
SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast", "mysql", "performance_schema", "sys"}

_engines: dict[tuple, Engine] = {}


def _ipv4(host: str, port: int) -> str | None:
    """Prefer IPv4. Docker Desktop's host.docker.internal also has an IPv6 address that
    containers usually can't reach, and the drivers give up instead of trying IPv4."""
    try:
        return socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    except OSError:
        return None


def engine_for(c: Connection) -> Engine:
    key = (c.id, c.kind, c.host, c.port, c.database, c.username, c.password)
    if key not in _engines:
        ip = _ipv4(c.host, c.port)
        args: dict[str, Any] = {"connect_timeout": 5}
        host = c.host
        if ip and c.kind == "postgresql":
            args["hostaddr"] = ip  # keep host for TLS/SNI and error messages, connect via IPv4
        elif ip:
            host = ip
        url = URL.create(DRIVERS[c.kind], username=c.username, password=c.password or None,
                         host=host, port=c.port, database=c.database or None)
        _engines[key] = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2, connect_args=args)
    return _engines[key]


def test(c: Connection) -> str:
    with engine_for(c).connect() as conn:
        return str(conn.execute(text("SELECT version()")).scalar())


def list_tables(c: Connection) -> list[dict[str, Any]]:
    insp = inspect(engine_for(c))
    if c.kind == "mysql":
        schemas = [c.database] if c.database else [s for s in insp.get_schema_names() if s not in SYSTEM_SCHEMAS]
    else:
        schemas = [s for s in insp.get_schema_names() if s not in SYSTEM_SCHEMAS and not s.startswith("pg_")]
    return [{"schema": s, "tables": sorted(insp.get_table_names(schema=s))} for s in schemas]


def standard_type(t: types.TypeEngine) -> str:
    if isinstance(t, types.Boolean):
        return "boolean"
    if isinstance(t, types.Integer):
        return "integer"
    if isinstance(t, (types.Numeric, types.Float)):
        return "decimal"
    if isinstance(t, types.DateTime):
        return "timestamp"
    if isinstance(t, types.Date):
        return "date"
    if isinstance(t, types.Uuid) or type(t).__name__.upper() == "UUID":
        return "uuid"
    # MySQL TINYINT(1) is how MySQL spells boolean
    if type(t).__name__.upper() == "TINYINT" and getattr(t, "display_width", None) == 1:
        return "boolean"
    return "text"


def describe(c: Connection, schema: str, table_name: str) -> list[FieldSpec]:
    insp = inspect(engine_for(c))
    cols = insp.get_columns(table_name, schema=schema)
    pk = set(insp.get_pk_constraint(table_name, schema=schema).get("constrained_columns") or [])
    fks: dict[str, str] = {}
    for fk in insp.get_foreign_keys(table_name, schema=schema):
        ref_schema = fk.get("referred_schema") or schema
        for local, remote in zip(fk["constrained_columns"], fk["referred_columns"]):
            fks[local] = f"{ref_schema}.{fk['referred_table']}.{remote}"
    uniques = {u["column_names"][0] for u in insp.get_unique_constraints(table_name, schema=schema) if len(u["column_names"]) == 1}

    specs = []
    for col in cols:
        t = col["type"]
        std = standard_type(t)
        auto = bool(col.get("autoincrement") is True or col.get("identity") or "nextval(" in str(col.get("default") or ""))
        specs.append(recommend(
            col["name"], db_type=std, db_type_raw=str(t), is_pk=col["name"] in pk and len(pk) == 1,
            autoincrement=auto, fk_ref=fks.get(col["name"]),
            enum_values=list(getattr(t, "enums", None) or []) or None,
            max_length=getattr(t, "length", None) if std == "text" else None,
            nullable=bool(col.get("nullable", True)), unique=col["name"] in uniques,
        ))
    return specs


def fetch_values(c: Connection, ref: str, limit: int = 10_000) -> list[Any]:
    schema, tbl, col = ref.split(".", 2)
    q = select(column(col)).select_from(table(tbl, schema=schema)).distinct().limit(limit)
    with engine_for(c).connect() as conn:
        return [r[0] for r in conn.execute(q) if r[0] is not None]


def insert_rows(c: Connection, schema: str, table_name: str, rows: list[dict[str, Any]], chunk: int = 1000) -> int:
    eng = engine_for(c)
    tbl = Table(table_name, MetaData(), schema=schema, autoload_with=eng)
    with eng.begin() as conn:  # all or nothing
        for i in range(0, len(rows), chunk):
            conn.execute(tbl.insert(), rows[i : i + chunk])
    return len(rows)


def connection_label(c: Connection) -> str:
    return f"{c.name} ({c.kind}://{c.host}:{c.port}/{c.database})"


__all__ = ["engine_for", "test", "list_tables", "describe", "fetch_values", "insert_rows", "connection_label", "uuid"]
