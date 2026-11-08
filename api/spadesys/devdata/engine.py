"""Turn a list of FieldSpecs into rows of fake data."""

from __future__ import annotations

import csv
import io
import random
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from faker import Faker

from .generators import GENERATORS, Ctx
from .recommend import FieldSpec

MAX_ROWS = 100_000


class GenerationError(Exception):
    pass


def _coerce(v: Any, type_: str) -> Any:
    """Make a generated value fit the column's chosen type."""
    if v is None:
        return None
    if type_ == "text":
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)
    if type_ == "integer":
        return int(v) if not isinstance(v, bool) else int(v)
    if type_ == "decimal":
        return v if isinstance(v, Decimal) else Decimal(str(v))
    if type_ == "date":
        return v.date() if isinstance(v, datetime) else v
    if type_ == "timestamp":
        return datetime.combine(v, datetime.min.time()) if isinstance(v, date) and not isinstance(v, datetime) else v
    if type_ == "uuid":
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    return v


def output_fields(fields: list[FieldSpec]) -> list[FieldSpec]:
    return [f for f in fields if f.generator != "skip"]


def generate_rows(
    fields: list[FieldSpec],
    n: int,
    *,
    seed: int | None = None,
    ref_values: dict[str, list[Any]] | None = None,
) -> list[dict[str, Any]]:
    if n < 1 or n > MAX_ROWS:
        raise GenerationError(f"Rows must be between 1 and {MAX_ROWS:,}")
    fake = Faker()
    if seed is not None:
        Faker.seed(seed)
    ctx = Ctx(fake=fake, rng=random.Random(seed), ref_values=ref_values or {})

    plan: list[tuple[FieldSpec, Callable]] = []
    for f in output_fields(fields):
        g = GENERATORS.get(f.generator)
        if g is None:
            raise GenerationError(f"{f.name}: unknown kind of value “{f.generator}”")
        if f.generator == "existing" and not ctx.ref_values.get(f.name):
            raise GenerationError(
                f"{f.name}: needs values from {f.params.get('ref') or 'another table'}, but none were found. "
                "Fill that table first, or pick a different kind of value."
            )
        plan.append((f, g.fn))

    seen: dict[str, set] = {f.name: set() for f, _ in plan if f.unique}
    rows = []
    for i in range(n):
        row = {}
        for f, fn in plan:
            if f.null_percent and ctx.rng.random() * 100 < f.null_percent and not f.unique:
                row[f.name] = None
                continue
            for _attempt in range(100):
                v = _coerce(fn(ctx, {**GENERATORS[f.generator].defaults, **f.params}, i, f.name), f.type)
                if isinstance(v, str) and f.max_length:
                    v = v[: f.max_length]
                if not f.unique or v not in seen[f.name]:
                    break
            else:
                raise GenerationError(
                    f"{f.name}: couldn't make {n:,} different values with “{GENERATORS[f.generator].label}”. "
                    "Ask for fewer rows, widen the range, or untick unique."
                )
            if f.unique:
                seen[f.name].add(v)
            row[f.name] = v
        rows.append(row)
    return rows


def to_jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def to_csv(fields: list[FieldSpec], rows: list[dict[str, Any]]) -> bytes:
    names = [f.name for f in output_fields(fields)]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(names)
    for r in rows:
        w.writerow(["" if r[n] is None else to_jsonable(r[n]) for n in names])
    return buf.getvalue().encode("utf-8")
