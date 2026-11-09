"""Transforms: reusable changes to a table, compiled to plain SQL you can read.

A transform reads one input table (raw.* or clean.*), applies its steps in order, and writes the
result to clean.<output>. Raw tables are never changed. Every step becomes one (or two) CTEs:

    WITH s0 AS (SELECT <columns> FROM raw.billing_customers),
         s1 AS (... split ...),
         s2 AS (... parse names ...)
    SELECT * FROM s2

Steps (each a dict with "op"):

  split        {column, separator, into: [names], keep_original}
  parse_name   {column, first, last, keep_original}        "Smith, Jane" / "Jane Smith" -> Jane | Smith
  join         {columns: [...], separator, into, keep_originals}
  clean        {columns: [...] (empty = all text), trim, case: none|upper|lower|title}
  rename       {renames: {old: new}}
  drop         {columns: [...]}
  stack        {table, mapping: {our_col: their_col}, label_column, this_label, other_label}
  dedupe       {columns: [...], ignore_case}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .config import get_settings

LINEAGE = {"_row_hash", "_run_id", "_loaded_at"}
TEXTY = {"text", "character varying", "character"}

OPS: dict[str, str] = {
    "split": "Split a column",
    "parse_name": "Parse names",
    "join": "Join columns",
    "clean": "Clean up text",
    "rename": "Rename columns",
    "drop": "Remove columns",
    "stack": "Stack another table",
    "dedupe": "Remove duplicates",
}


def schemas() -> tuple[str, str]:
    s = get_settings()
    return s.raw_schema, s.clean_schema


class TransformError(ValueError):
    def __init__(self, message: str, step: int | None = None):
        super().__init__(message)
        self.step = step  # 0-based index of the step at fault, None for the input/output
        self.step_columns: list[list["Col"]] = []  # columns going into each step up to the fault


@dataclass
class Col:
    name: str
    type: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "type": self.type}


@dataclass
class Compiled:
    sql: str
    columns: list[Col]
    step_columns: list[list[Col]] = field(default_factory=list)  # columns going *into* each step
    reads: list[str] = field(default_factory=list)  # every table the SQL reads


# ------------------------------------------------------------------ quoting

def q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def lit(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def valid_name(name: str) -> str:
    name = (name or "").strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name):
        raise ValueError(f"“{name}” isn't a usable column or table name: use lowercase letters, numbers and _")
    return name


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:63]
    return ("t_" + s if s[:1].isdigit() else s) or "result"


def split_table(full: str) -> tuple[str, str]:
    schema, _, table = (full or "").partition(".")
    if not table or schema not in schemas():
        raise TransformError(f"Pick a table in raw or clean (got “{full}”)")
    return schema, table


# ------------------------------------------------------------------ catalog

def table_columns(conn: Connection, full: str) -> list[Col]:
    schema, table = split_table(full)
    rows = conn.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"
    ), {"s": schema, "t": table}).all()
    if not rows:
        raise TransformError(f"There's no table {full}")
    return [Col(n, t) for n, t in rows if n not in LINEAGE]


def list_tables(conn: Connection) -> list[dict[str, Any]]:
    rows = conn.execute(text(
        "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = ANY(:s) ORDER BY table_schema, table_name, ordinal_position"
    ), {"s": list(schemas())}).all()
    out: dict[str, dict[str, Any]] = {}
    for schema, table, col, typ in rows:
        t = out.setdefault(f"{schema}.{table}", {"full": f"{schema}.{table}", "schema": schema, "name": table, "columns": []})
        if col not in LINEAGE:
            t["columns"].append({"name": col, "type": typ})
    return list(out.values())


# ------------------------------------------------------------------ compiling

def _find(cols: list[Col], name: str, i: int, what: str = "column") -> Col:
    for c in cols:
        if c.name == name:
            return c
    raise TransformError(f"There's no {what} “{name}” at this step", i)


def _fresh(cols: list[Col], names: list[str], i: int, replacing: set[str] = frozenset()) -> None:
    have = {c.name for c in cols} - set(replacing)
    for n in names:
        try:
            valid_name(n)
        except ValueError as e:
            raise TransformError(str(e), i) from None
        if n in have:
            raise TransformError(f"There's already a column “{n}”; pick another name", i)
    if len(set(names)) != len(names):
        raise TransformError("The new column names must all be different", i)


def _select(cols: list[tuple[str, Col]]) -> str:
    """[(expression, resulting column)] -> 'expr AS "name", ...' (bare column when unchanged)."""
    parts = []
    for expr, c in cols:
        parts.append(expr if expr == q(c.name) else f"{expr} AS {q(c.name)}")
    return ",\n    ".join(parts)


def _same(cols: list[Col]) -> list[tuple[str, Col]]:
    return [(q(c.name), c) for c in cols]


def _replace_at(cols: list[Col], target: str, new: list[tuple[str, Col]], keep: bool) -> list[tuple[str, Col]]:
    """Put new columns where `target` was, keeping or dropping the original."""
    out: list[tuple[str, Col]] = []
    for c in cols:
        if c.name == target:
            if keep:
                out.append((q(c.name), c))
            out.extend(new)
        else:
            out.append((q(c.name), c))
    return out


def _tidy(expr: str) -> str:
    """Trim and collapse runs of spaces."""
    return f"btrim(regexp_replace({expr}, '\\s+', ' ', 'g'))"


def _step(step: dict[str, Any], i: int, prev: str, cols: list[Col], conn: Connection, me: str,
          reads: list[str]) -> tuple[list[tuple[str, str]], list[Col]]:
    """One step -> ([(cte_name, select_sql)], resulting columns)."""
    op = step.get("op")
    name = f"s{i + 1}"

    if op == "split":
        col = _find(cols, step.get("column", ""), i)
        sep = step.get("separator") or ""
        if not sep:
            raise TransformError("Say which character to split at", i)
        into = [n.strip() for n in step.get("into") or [] if n.strip()]
        if len(into) < 2:
            raise TransformError("Name at least two new columns", i)
        keep = bool(step.get("keep_original"))
        _fresh(cols, into, i, set() if keep else {col.name})
        new = [(f"NULLIF(btrim(split_part({q(col.name)}::text, {lit(sep)}, {k + 1})), '')", Col(n, "text"))
               for k, n in enumerate(into)]
        out = _replace_at(cols, col.name, new, keep)
        return [(name, f"SELECT\n    {_select(out)}\n  FROM {prev}")], [c for _, c in out]

    if op == "parse_name":
        col = _find(cols, step.get("column", ""), i)
        first, last = (step.get("first") or "first_name").strip(), (step.get("last") or "last_name").strip()
        keep = bool(step.get("keep_original"))
        _fresh(cols, [first, last], i, set() if keep else {col.name})
        v = q("_name")
        prep = f"SELECT *, NULLIF({_tidy(q(col.name) + '::text')}, '') AS {v}\n  FROM {prev}"
        first_expr = (f"CASE WHEN {v} LIKE '%,%' THEN NULLIF(btrim(split_part({v}, ',', 2)), '')\n"
                      f"         WHEN {v} LIKE '% %' THEN regexp_replace({v}, ' \\S+$', '')\n"
                      f"    END")
        last_expr = (f"CASE WHEN {v} LIKE '%,%' THEN NULLIF(btrim(split_part({v}, ',', 1)), '')\n"
                     f"         ELSE substring({v} from '(\\S+)$')\n"
                     f"    END")
        out = _replace_at(cols, col.name, [(first_expr, Col(first, "text")), (last_expr, Col(last, "text"))], keep)
        return ([(f"{name}_prep", prep), (name, f"SELECT\n    {_select(out)}\n  FROM {name}_prep")],
                [c for _, c in out])

    if op == "join":
        names = [n for n in step.get("columns") or [] if n]
        if len(names) < 2:
            raise TransformError("Pick at least two columns to join", i)
        picked = [_find(cols, n, i) for n in names]
        into = (step.get("into") or "").strip()
        keep = step.get("keep_originals", True)
        _fresh(cols, [into], i, set() if keep else set(names))
        sep = step.get("separator")
        sep = " " if sep is None else sep
        parts = ", ".join(f"NULLIF(btrim({q(c.name)}::text), '')" for c in picked)
        new = (f"NULLIF(concat_ws({lit(sep)}, {parts}), '')", Col(into, "text"))
        out: list[tuple[str, Col]] = []
        for c in cols:
            if c.name == names[0]:
                if keep:
                    out.append((q(c.name), c))
                out.append(new)
            elif c.name in names and not keep:
                continue
            else:
                out.append((q(c.name), c))
        return [(name, f"SELECT\n    {_select(out)}\n  FROM {prev}")], [c for _, c in out]

    if op == "clean":
        names = [n for n in step.get("columns") or [] if n] or [c.name for c in cols if c.type in TEXTY]
        for n in names:
            c = _find(cols, n, i)
            if c.type not in TEXTY:
                raise TransformError(f"Clean up works on text columns; “{n}” is {c.type}", i)
        case = step.get("case") or "none"
        trim = step.get("trim", True)
        out = []
        for c in cols:
            if c.name not in names:
                out.append((q(c.name), c))
                continue
            e = q(c.name)
            if trim:
                e = _tidy(e)
            e = {"upper": f"upper({e})", "lower": f"lower({e})", "title": f"initcap({e})"}.get(case, e)
            out.append((f"NULLIF({e}, '')" if e != q(c.name) else e, c))
        return [(name, f"SELECT\n    {_select(out)}\n  FROM {prev}")], [c for _, c in out]

    if op == "rename":
        renames = {k: (v or "").strip() for k, v in (step.get("renames") or {}).items() if (v or "").strip() and v != k}
        for old in renames:
            _find(cols, old, i)
        _fresh(cols, list(renames.values()), i, set(renames))
        out = [(q(c.name), Col(renames.get(c.name, c.name), c.type)) for c in cols]
        return [(name, f"SELECT\n    {_select(out)}\n  FROM {prev}")], [c for _, c in out]

    if op == "drop":
        names = set(step.get("columns") or [])
        for n in names:
            _find(cols, n, i)
        out = [(q(c.name), c) for c in cols if c.name not in names]
        if not out:
            raise TransformError("That would remove every column", i)
        return [(name, f"SELECT\n    {_select(out)}\n  FROM {prev}")], [c for _, c in out]

    if op == "stack":
        other = step.get("table") or ""
        if other == me:
            raise TransformError("A transform can't stack the table it's writing to", i)
        try:
            theirs = {c.name: c for c in table_columns(conn, other)}
        except TransformError as e:
            raise TransformError(str(e), i) from None
        reads.append(other)
        mapping = step.get("mapping") or {}
        label = (step.get("label_column") or "").strip()
        if label:
            _fresh(cols, [label], i)
        mine_sel, their_sel, out_cols = [], [], []
        for c in cols:
            src = mapping.get(c.name, c.name if c.name in theirs else "")
            t = theirs.get(src) if src else None
            if src and t is None:
                raise TransformError(f"{other} has no column “{src}”", i)
            same = t is not None and t.type == c.type
            typ = c.type if (t is None or same) else "text"
            mine_sel.append(q(c.name) if typ == c.type else f"{q(c.name)}::text AS {q(c.name)}")
            if t is None:
                their_sel.append(f"NULL::{typ} AS {q(c.name)}" if typ != "USER-DEFINED" else f"NULL AS {q(c.name)}")
            else:
                their_sel.append(q(src) if (same and src == c.name) else f"{q(src)}{'' if same else '::text'} AS {q(c.name)}")
            out_cols.append(Col(c.name, typ))
        if label:
            mine_sel.append(f"{lit(step.get('this_label') or prev_label(me))} AS {q(label)}")
            their_sel.append(f"{lit(step.get('other_label') or other)} AS {q(label)}")
            out_cols.append(Col(label, "text"))
        s_schema, s_table = split_table(other)
        sql = (f"SELECT\n    {', '.join(mine_sel)}\n  FROM {prev}\n  UNION ALL\n"
               f"  SELECT\n    {', '.join(their_sel)}\n  FROM {q(s_schema)}.{q(s_table)}")
        return [(name, sql)], out_cols

    if op == "dedupe":
        names = [n for n in step.get("columns") or [] if n]
        if not names:
            raise TransformError("Pick the columns that make two rows “the same”", i)
        ignore = step.get("ignore_case", True)
        keys = []
        for n in names:
            c = _find(cols, n, i)
            keys.append(f"lower(btrim({q(c.name)}::text))" if ignore else q(c.name))
        k = ", ".join(keys)
        return [(name, f"SELECT DISTINCT ON ({k}) *\n  FROM {prev}\n  ORDER BY {k}")], cols

    raise TransformError(f"Unknown step “{op}”", i)


def prev_label(me: str) -> str:
    return me.split(".")[-1] if me else "this table"


def compile_steps(conn: Connection, input_table: str, steps: list[dict[str, Any]], output: str = "") -> Compiled:
    """Turn a transform into one SQL query. Raises TransformError naming the step at fault."""
    me = f"{schemas()[1]}.{output}" if output else ""
    if input_table == me:
        raise TransformError("A transform can't read the table it's writing to; pick another output name")
    cols = table_columns(conn, input_table)
    schema, table = split_table(input_table)
    ctes = [("s0", f"SELECT\n    {_select(_same(cols))}\n  FROM {q(schema)}.{q(table)}")]
    step_columns = [cols]
    reads = [input_table]
    for i, step in enumerate(steps):
        if step.get("disabled"):
            step_columns.append(cols)
            continue
        try:
            new_ctes, cols = _step(step, i, ctes[-1][0], cols, conn, me, reads)
        except TransformError as e:
            e.step_columns = step_columns
            raise
        ctes += new_ctes
        step_columns.append(cols)
    body = ",\n".join(f"{n} AS (\n  {s}\n)" for n, s in ctes)
    return Compiled(sql=f"WITH {body}\nSELECT * FROM {ctes[-1][0]}", columns=cols, step_columns=step_columns, reads=reads)


# ------------------------------------------------------------------ running

def preview(conn: Connection, c: Compiled, limit: int = 50) -> dict[str, Any]:
    conn.execute(text("SET LOCAL statement_timeout = '10s'"))
    result = conn.execute(text(f"SELECT * FROM (\n{c.sql}\n) AS t LIMIT {int(limit)}"))
    rows = [list(r) for r in result]
    total = conn.execute(text(f"SELECT count(*) FROM (\n{c.sql}\n) AS t")).scalar()
    return {"rows": rows, "row_count": total}


def write(conn: Connection, c: Compiled, output: str) -> int:
    """Replace clean.<output> with the transform's result. Returns the row count."""
    clean = schemas()[1]
    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {q(clean)}"))
    conn.execute(text(f"DROP TABLE IF EXISTS {q(clean)}.{q(output)}"))
    conn.execute(text(f"CREATE TABLE {q(clean)}.{q(output)} AS\n{c.sql}"))
    return conn.execute(text(f"SELECT count(*) FROM {q(clean)}.{q(output)}")).scalar() or 0
