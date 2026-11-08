import pandas as pd
import pytest

from spadesys.generators.commerce import generate, to_csv_bytes
from spadesys.ingest.hashing import hash_frame, row_hash
from spadesys.ingest.infer import infer_schema, snake_case
from spadesys.ingest.load import cast_value
from spadesys.ingest.pipeline import ValidationError, read_csv_bytes, validate


def frame(**cols):
    return pd.DataFrame({k: [str(x) for x in v] for k, v in cols.items()})


def types(df):
    return {c["name"]: c["type"] for c in infer_schema(df)["columns"]}


def test_infers_core_types():
    df = frame(
        id=[1, 2, 3],
        price=["1.50", "2", "-3.25"],
        active=["true", "False", "yes"],
        born=["2020-01-01", "2021-12-31", "1999-07-04"],
        seen=["2024-05-01T10:00:00", "2024-05-01 11:30", "2024-05-02T00:00:00Z"],
        note=["a", "b", "c"],
    )
    assert types(df) == {
        "id": "integer",
        "price": "decimal",
        "active": "boolean",
        "born": "date",
        "seen": "timestamp",
        "note": "text",
    }


def test_leading_zeros_stay_text():
    assert types(frame(zip=["02134", "10001", "00501"]))["zip"] == "text"


def test_nulls_and_keys():
    schema = infer_schema(frame(id=[1, 2, 3], score=["10", "", "NULL"]))
    cols = {c["name"]: c for c in schema["columns"]}
    assert cols["score"]["type"] == "integer"
    assert cols["score"]["nullable"] and cols["score"]["null_count"] == 2
    assert cols["id"]["unique"] and not cols["id"]["nullable"]
    assert schema["key_candidates"] == ["id"]


def test_all_null_column_is_text():
    assert types(frame(x=["", "", ""]))["x"] == "text"


def test_column_names_snake_cased_and_deduped():
    df = pd.DataFrame({"Order ID": ["1"], "order_id": ["2"], "CustomerName": ["x"], "2nd": ["y"]})
    assert [c["name"] for c in infer_schema(df)["columns"]] == ["order_id", "order_id_1", "customer_name", "_2nd"]


@pytest.mark.parametrize("raw,expected", [("Hello World", "hello_world"), ("  ", "col"), ("a--b", "a_b")])
def test_snake_case(raw, expected):
    assert snake_case(raw) == expected


def test_row_hash_is_stable_and_normalised():
    assert row_hash(["a", " b ", ""]) == row_hash(["a", "b", "NULL"])
    assert row_hash(["a", "b"]) != row_hash(["ab", ""])
    hashes = hash_frame(frame(a=[1, 1, 2], b=["x", "x", "y"]))
    assert hashes.duplicated().sum() == 1


def test_cast_value():
    from datetime import date
    from decimal import Decimal

    assert cast_value("NULL", "integer") is None
    assert cast_value(" 42 ", "integer") == 42
    assert cast_value("1.10", "decimal") == Decimal("1.10")
    assert cast_value("Y", "boolean") is True
    assert cast_value("2024-02-29", "date") == date(2024, 2, 29)
    assert cast_value("2024-01-01T00:00:00", "timestamp").tzinfo is not None


def test_read_csv_sniffs_delimiter_and_bom():
    df = read_csv_bytes("﻿a;b\n1;x\n2;y\n".encode())
    assert list(df.columns) == ["a", "b"] and len(df) == 2


def test_validate_rejects_empty():
    with pytest.raises(ValidationError):
        validate(pd.DataFrame({"a": []}))


def test_generator_round_trip_types():
    data = generate(customers=20, items=10, orders=30, seed=7)
    assert {len(data["customers"]), len(data["items"]), len(data["orders"])} == {20, 10, 30}
    t = types(read_csv_bytes(to_csv_bytes(data["orders"])))
    assert t["order_id"] == "integer" and t["ordered_at"] == "timestamp" and t["order_total"] == "decimal"
    assert types(read_csv_bytes(to_csv_bytes(data["customers"])))["is_active"] == "boolean"
