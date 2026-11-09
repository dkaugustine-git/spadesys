"""File layouts: reading spreadsheets and messy CSVs, guessing where the table is, cutting it out."""

import io

import pytest

from spadesys.ingest.readers import (
    LayoutError, apply_layout, describe, guess_layout, is_default, read_grid, read_table,
)

MESSY_CSV = b"Sales report\nQ3 2026\n\nfirst,last,email\nPriya,Patel,p@x.com\nJane,Smith,j@x.com\n"


def test_plain_csv_reads_the_standard_way():
    df, notes, how = read_table(b"a,b\n1,x\n2,y\n", "f.csv")
    assert list(df.columns) == ["a", "b"] and len(df) == 2 and notes == []
    assert "headers on row 1" in how


def test_semicolon_and_bom_still_work():
    df, _, _ = read_table("﻿a;b\n1;x\n".encode(), "f.csv")
    assert list(df.columns) == ["a", "b"]


def test_guess_skips_title_rows():
    g = guess_layout(read_grid(MESSY_CSV, "f.csv"))
    assert (g["header_row"], g["data_row"], g["stop"]) == (4, 5, "end")
    assert not is_default(g)


def test_layout_cuts_out_the_table_and_explains():
    grid = read_grid(MESSY_CSV, "f.csv")
    df, notes = apply_layout(grid, {"header_row": 4, "data_row": 5})
    assert list(df.columns) == ["first", "last", "email"] and len(df) == 2
    assert notes == ["Skipped 3 rows above the headers"]


def test_stop_at_a_totals_row():
    data = b"name,amount\nA,1\nB,2\nTotal,3\nprinted by x\n"
    grid = read_grid(data, "f.csv")
    g = guess_layout(grid)
    assert g["stop"] == "text" and g["stop_text"] == "Total"
    df, notes = apply_layout(grid, g)
    assert list(df["name"]) == ["A", "B"]
    assert "Stopped at row 4" in notes[0]


def test_stop_at_first_blank_row():
    grid = read_grid(b"a,b\n1,2\n\nnote\n", "f.csv")
    df, _ = apply_layout(grid, {"header_row": 1, "data_row": 2, "stop": "blank"})
    assert len(df) == 1


def test_no_header_row_names_columns():
    df, _ = apply_layout(read_grid(b"1,x\n2,y\n", "f.csv"), {"header_row": 0, "data_row": 1})
    assert list(df.columns) == ["column_1", "column_2"] and len(df) == 2


def test_duplicate_and_blank_header_names():
    df, notes = apply_layout(read_grid(b"a,a,,b\n1,2,3,4\n", "f.csv"), None)
    assert list(df.columns) == ["a", "a_2", "column_3", "b"]
    assert "no header" in notes[0]


def test_bad_layouts_are_explained():
    grid = read_grid(MESSY_CSV, "f.csv")
    with pytest.raises(LayoutError):
        apply_layout(grid, {"header_row": 4, "data_row": 4})
    with pytest.raises(LayoutError):
        apply_layout(grid, {"header_row": 1, "data_row": 2, "stop": "text", "stop_text": ""})


def test_xlsx_sheets_and_layout():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "October"
    for r in [["Acme Billing"], [], ["Customer", "Balance"], ["Smith, Jane", 120.5], ["Doe, John", 80], ["Total", 200.5]]:
        ws.append(r)
    wb.create_sheet("Notes").append(["hi"])
    buf = io.BytesIO()
    wb.save(buf)
    grid = read_grid(buf.getvalue(), "billing.xlsx")
    assert grid.sheets == ["October", "Notes"] and grid.sheet == "October"
    g = guess_layout(grid)
    assert (g["header_row"], g["data_row"], g["stop_text"]) == (3, 4, "Total")
    df, _ = apply_layout(grid, g)
    assert df.values.tolist() == [["Smith, Jane", "120.5"], ["Doe, John", "80"]]
    assert describe(g, grid).startswith("sheet “October”, column headers on row 3")
