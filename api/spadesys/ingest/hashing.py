"""Row hashing: a stable fingerprint of each source row.

Hashes are computed from the *raw* string values (trimmed, nulls normalised)
in original column order, so they don't change if type inference changes.
They drive idempotent loads (re-uploading a file inserts nothing new) and
make change detection between loads cheap.
"""

import hashlib

import pandas as pd

from .infer import is_null

SEP = "\x1f"  # ASCII unit separator: won't appear in normal CSV text
NULL = "\x00"


def _norm(v: object) -> str:
    return NULL if is_null(v) else str(v).strip()


def row_hash(values: list[object] | tuple[object, ...]) -> str:
    return hashlib.sha256(SEP.join(_norm(v) for v in values).encode("utf-8")).hexdigest()


def hash_frame(df: pd.DataFrame) -> pd.Series:
    return pd.Series(
        [row_hash(r) for r in df.itertuples(index=False, name=None)], index=df.index, dtype=object
    )
