import pytest

from spadesys.devdata.engine import GenerationError, generate_rows, to_csv
from spadesys.devdata.recommend import parse_pasted, recommend


@pytest.mark.parametrize(
    "name,type_,generator",
    [
        ("id", "integer", "sequence"),
        ("customer_id", "text", "id_code"),
        ("CustomerNumber", "text", "id_code"),
        ("zip", "text", "postal_code"),
        ("phone_number", "text", "phone"),
        ("email", "text", "email"),
        ("account_type", "text", "choice"),
        ("is_deleted", "boolean", "boolean"),
        ("deleted_at", "timestamp", "timestamp_recent"),
        ("created_by", "text", "id_code"),
        ("order_total", "decimal", "money"),
        ("quantity", "integer", "integer_range"),
        ("birth_date", "date", "birth_date"),
        ("paid", "text", "word"),  # no false "id" match on the trailing letters
    ],
)
def test_recommend_from_name(name, type_, generator):
    f = recommend(name)
    assert (f.type, f.generator) == (type_, generator)
    assert f.reason


def test_database_type_wins_but_warns_for_numeric_ids():
    f = recommend("customer_id", db_type="integer", db_type_raw="INTEGER")
    assert f.type == "integer" and f.warning and "leading zeros" in f.warning.lower()


def test_database_facts():
    assert recommend("id", db_type="integer", is_pk=True, autoincrement=True).generator == "skip"
    fk = recommend("customer_id", db_type="integer", fk_ref="public.customers.id")
    assert fk.generator == "existing" and fk.params["ref"] == "public.customers.id"
    assert recommend("status", db_type="text", enum_values=["a", "b"]).params["choices"] == "a,b"


def test_parse_pasted_accepts_csv_header_or_lines():
    assert parse_pasted('"id","Name"\n') == ["id", "Name"]
    assert parse_pasted("a\tb\nc, a") == ["a", "b", "c"]


def test_generate_unique_ids_keep_leading_zeros():
    fields = [recommend("id"), recommend("zip"), recommend("customer_id")]
    fields[2].unique = True
    rows = generate_rows(fields, 500, seed=3)
    assert [r["id"] for r in rows[:3]] == [1, 2, 3]
    assert len({r["customer_id"] for r in rows}) == 500
    assert all(isinstance(r["customer_id"], str) and len(r["customer_id"]) == 8 for r in rows)
    assert to_csv(fields, rows).decode().splitlines()[0] == "id,zip,customer_id"


def test_unique_impossible_is_explained():
    f = recommend("rating")  # 1..5
    f.unique = True
    with pytest.raises(GenerationError, match="couldn't make"):
        generate_rows([f], 10, seed=1)


def test_skip_columns_are_left_out():
    f = recommend("id", db_type="integer", is_pk=True, autoincrement=True)
    rows = generate_rows([f, recommend("email")], 2, seed=1)
    assert list(rows[0]) == ["email"]


def test_pasted_spreadsheet_range_uses_example_rows():
    from spadesys.devdata.recommend import apply_samples, parse_pasted_table

    text = "Customer ID\tSignup\tPlan\tScore\n00123\t1/5/2024\tgold\t10\n00456\t2/9/2024\tgold\t70\n00789\t3/1/2024\tsilver\t40\n01011\t4/4/2024\tgold\t55\n"
    names, rows = parse_pasted_table(text)
    assert names == ["Customer ID", "Signup", "Plan", "Score"]
    assert len(rows) == 4
    f = [apply_samples(recommend(n), [r[i] for r in rows]) for i, n in enumerate(names)]
    assert f[0].type == "text" and f[0].params["length"] == 5
    assert f[1].type == "date"
    assert f[2].generator == "choice" and set(f[2].params["choices"].split(",")) == {"gold", "silver"}
    assert f[3].type == "integer" and (f[3].params["min"], f[3].params["max"]) == (10, 70)


def test_pasted_names_only_still_work():
    from spadesys.devdata.recommend import parse_pasted_table

    assert parse_pasted_table("id\nname\nemail") == (["id", "name", "email"], [])
    assert parse_pasted_table('"id","Name"\n') == (["id", "Name"], [])
