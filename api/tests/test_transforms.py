"""Transform compiler: steps -> SQL, column tracking and step-level errors. No database needed."""

import pytest

from spadesys import transforms as tf
from spadesys.transforms import Col, TransformError

TABLES = {
    "raw.billing": [Col("customer_name", "text"), Col("account", "text"), Col("amount", "numeric")],
    "raw.sales": [Col("first", "text"), Col("last", "text"), Col("email", "text")],
}


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    def cols(_conn, full):
        if full not in TABLES:
            raise TransformError(f"There's no table {full}")
        return list(TABLES[full])

    monkeypatch.setattr(tf, "table_columns", cols)


def names(compiled):
    return [c.name for c in compiled.columns]


def test_no_steps_selects_the_input_without_lineage_columns():
    c = tf.compile_steps(None, "raw.billing", [])
    assert names(c) == ["customer_name", "account", "amount"]
    assert '"raw"."billing"' in c.sql


def test_split_puts_new_columns_where_the_old_one_was():
    c = tf.compile_steps(None, "raw.billing", [
        {"op": "split", "column": "account", "separator": "-", "into": ["prefix", "number", "region"]},
    ])
    assert names(c) == ["customer_name", "prefix", "number", "region", "amount"]
    assert "split_part(\"account\"::text, '-', 3)" in c.sql


def test_split_separator_is_quoted_safely():
    c = tf.compile_steps(None, "raw.billing", [
        {"op": "split", "column": "account", "separator": "'", "into": ["a", "b"]},
    ])
    assert "''''" in c.sql  # a single quote, escaped


def test_parse_name_handles_comma_and_space_forms():
    c = tf.compile_steps(None, "raw.billing", [{"op": "parse_name", "column": "customer_name"}])
    assert names(c) == ["first_name", "last_name", "account", "amount"]
    assert "LIKE '%,%'" in c.sql and "LIKE '% %'" in c.sql


def test_stack_maps_columns_and_fills_missing_with_null():
    c = tf.compile_steps(None, "raw.billing", [
        {"op": "parse_name", "column": "customer_name"},
        {"op": "stack", "table": "raw.sales", "mapping": {"first_name": "first", "last_name": "last"},
         "label_column": "came_from", "this_label": "billing", "other_label": "sales"},
    ])
    assert names(c) == ["first_name", "last_name", "account", "amount", "came_from"]
    assert '"first" AS "first_name"' in c.sql
    assert 'NULL::numeric AS "amount"' in c.sql
    assert "UNION ALL" in c.sql
    assert c.reads == ["raw.billing", "raw.sales"]


def test_dedupe_ignores_case_by_default():
    c = tf.compile_steps(None, "raw.sales", [{"op": "dedupe", "columns": ["first", "last"]}])
    assert 'DISTINCT ON (lower(btrim("first"::text))' in c.sql


def test_step_columns_track_each_step():
    c = tf.compile_steps(None, "raw.billing", [
        {"op": "drop", "columns": ["amount"]},
        {"op": "rename", "renames": {"account": "account_code"}},
    ])
    assert [x.name for x in c.step_columns[1]] == ["customer_name", "account"]
    assert names(c) == ["customer_name", "account_code"]


def test_unknown_column_names_the_step():
    with pytest.raises(TransformError) as e:
        tf.compile_steps(None, "raw.billing", [
            {"op": "drop", "columns": ["amount"]},
            {"op": "clean", "columns": ["amount"]},
        ])
    assert e.value.step == 1


def test_new_names_cant_clash():
    with pytest.raises(TransformError):
        tf.compile_steps(None, "raw.billing", [
            {"op": "split", "column": "account", "separator": "-", "into": ["amount", "x"]},
        ])


def test_clean_refuses_non_text_columns():
    with pytest.raises(TransformError):
        tf.compile_steps(None, "raw.billing", [{"op": "clean", "columns": ["amount"]}])


def test_cant_read_the_table_being_written():
    with pytest.raises(TransformError):
        tf.compile_steps(None, "clean.out", [], output="out")


def test_disabled_steps_are_skipped():
    c = tf.compile_steps(None, "raw.billing", [{"op": "drop", "columns": ["amount"], "disabled": True}])
    assert "amount" in names(c)


def test_only_raw_and_clean_tables():
    with pytest.raises(TransformError):
        tf.compile_steps(None, "spadesys.connections", [])
