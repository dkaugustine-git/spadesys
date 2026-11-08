"""Deterministic schema inference for CSV data.

Every value is read as a string first, then each column is tested against
progressively looser types. The result is a plain dict so it can be stored as
JSON, shown in the UI, and later reviewed or amended by the AI assistant.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

NULL_TOKENS = {"", "null", "none", "na", "n/a", "nan", "#n/a"}
TRUE_TOKENS = {"true", "t", "yes", "y"}
FALSE_TOKENS = {"false", "f", "no", "n"}

_INT_RE = r"^[+-]?\d+$"
_LEADING_ZERO_RE = r"^[+-]?0\d"
_DECIMAL_RE = r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$"
_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
_TS_RE = r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$"

INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1

# Order matters: first match wins.
TYPE_ORDER = ["boolean", "integer", "decimal", "date", "timestamp", "text"]


def snake_case(name: str, fallback: str = "col") -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.strip())
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    if not s:
        s = fallback
    if s[0].isdigit():
        s = f"_{s}"
    return s[:63]


def is_null(v: object) -> bool:
    return v is None or str(v).strip().lower() in NULL_TOKENS


def _parses_dt(values: pd.Series) -> bool:
    try:
        pd.to_datetime(values, format="ISO8601", utc=True)
        return True
    except (ValueError, TypeError):
        return False


def _matches(type_: str, values: pd.Series) -> bool:
    stripped = values.str.strip()
    if type_ == "boolean":
        return bool(stripped.str.lower().isin(TRUE_TOKENS | FALSE_TOKENS).all())
    if type_ in ("integer", "decimal") and stripped.str.match(_LEADING_ZERO_RE).any():
        # Leading zeros (zip codes, ids like "007") are identifiers, not numbers.
        return False
    if type_ == "integer":
        if not stripped.str.match(_INT_RE).all():
            return False
        return bool(stripped.map(int).between(INT64_MIN, INT64_MAX).all())
    if type_ == "decimal":
        return bool(stripped.str.match(_DECIMAL_RE).all())
    if type_ == "date":
        return bool(stripped.str.match(_DATE_RE).all()) and _parses_dt(stripped)
    if type_ == "timestamp":
        return bool(stripped.str.match(_TS_RE).all()) and _parses_dt(stripped)
    return True  # text


def infer_column(original_name: str, raw: pd.Series, position: int) -> dict[str, Any]:
    raw = raw.fillna("").astype(str)
    null_mask = raw.map(is_null)
    values = raw[~null_mask]

    type_ = "text"
    if len(values):
        type_ = next(t for t in TYPE_ORDER if _matches(t, values))

    distinct = int(values.nunique())
    return {
        "name": snake_case(original_name, fallback=f"col_{position}"),
        "original_name": original_name,
        "position": position,
        "type": type_,
        "nullable": bool(null_mask.any()),
        "null_count": int(null_mask.sum()),
        "distinct_count": distinct,
        "unique": bool(len(values) > 0 and distinct == len(values) and not null_mask.any()),
        "samples": values.drop_duplicates().head(5).tolist(),
    }


def infer_schema(df: pd.DataFrame) -> dict[str, Any]:
    """`df` must have been read with dtype=str, keep_default_na=False."""
    columns = [infer_column(str(c), df[c], i) for i, c in enumerate(df.columns)]

    # De-duplicate names that collide after snake_casing ("Order ID" vs "order_id").
    seen: dict[str, int] = {}
    for col in columns:
        n = col["name"]
        if n in seen:
            seen[n] += 1
            col["name"] = f"{n}_{seen[n]}"[:63]
        else:
            seen[n] = 0

    key_candidates = [c["name"] for c in columns if c["unique"] and c["type"] in ("integer", "text")]
    return {
        "version": 1,
        "row_count": int(len(df)),
        "columns": columns,
        "key_candidates": key_candidates,
    }
