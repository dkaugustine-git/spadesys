"""Read any supported file as a grid of cells, then cut the real table out of it with a layout.

Real exports often aren't a clean table: a report title, a date line and a blank row sit above the
headers, and a "Total" row sits below the data. A *layout* says where the table is:

    {"sheet": "Q3" | None,        # spreadsheets: which sheet (None = the first)
     "header_row": 4,             # 1-based row with the column names; 0 = the file has no header row
     "data_row": 5,               # 1-based first row of data
     "stop": "end" | "blank" | "text",
     "stop_text": "Total"}        # with stop="text": stop at the first row that starts with this

No layout means the plain CSV convention: headers on row 1, data from row 2 to the end.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

import pandas as pd

TEXT_EXT = {".csv", ".tsv", ".txt", ".tab", ".dat"}
SHEET_ENGINES = {".xlsx": "openpyxl", ".xlsm": "openpyxl", ".xls": "xlrd", ".ods": "odf"}
SUPPORTED = sorted(TEXT_EXT | set(SHEET_ENGINES))
DEFAULT_LAYOUT: dict[str, Any] = {"sheet": None, "header_row": 1, "data_row": 2, "stop": "end", "stop_text": ""}
NUMBERISH = re.compile(r"^[-+$€£(]?\s*[\d.,]+\s*%?\)?$")
TOTALISH = re.compile(r"^(grand\s+)?(total|totals|sum|subtotal)\b", re.I)


class LayoutError(ValueError):
    pass


@dataclass
class Grid:
    rows: list[list[str]]
    sheets: list[str] = field(default_factory=list)  # empty for text files
    sheet: str | None = None
    delimiter: str | None = None  # text files


# ------------------------------------------------------------------ reading cells

def engine_for(filename: str, data: bytes) -> str | None:
    """'openpyxl' / 'xlrd' / 'odf' for spreadsheets, None for text."""
    ext = PurePath(filename or "").suffix.lower()
    if ext in SHEET_ENGINES:
        return SHEET_ENGINES[ext]
    if ext in TEXT_EXT:
        return None
    if data[:4] == b"\xd0\xcf\x11\xe0":
        return "xlrd"
    if data[:2] == b"PK":
        return "odf" if b"opendocument.spreadsheet" in data[:200] else "openpyxl"
    return None


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def sniff_delimiter(text_: str, filename: str = "") -> str:
    if PurePath(filename).suffix.lower() in {".tsv", ".tab"}:
        return "\t"
    lines = [ln for ln in text_.splitlines()[:200] if ln.strip()]
    best, best_score = ",", 0
    for d in (",", "\t", ";", "|"):
        counts = Counter(ln.count(d) for ln in lines if ln.count(d))
        if not counts:
            continue
        n, freq = counts.most_common(1)[0]
        score = freq * math.log2(n + 1)  # many lines agreeing on the same number of separators
        if score > best_score:
            best, best_score = d, score
    return best


def _cell(v: Any) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    s = str(v).strip()
    if s.endswith(" 00:00:00"):  # a spreadsheet date with no time
        s = s[:-9]
    return "" if s.lower() == "nan" else s


def read_grid(data: bytes, filename: str, sheet: str | None = None) -> Grid:
    eng = engine_for(filename, data)
    if eng is None:
        text_ = decode(data)
        delim = sniff_delimiter(text_, filename)
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text_), delimiter=delim)]
        return Grid(rows=rows, delimiter=delim)
    try:
        book = pd.ExcelFile(io.BytesIO(data), engine=eng)
    except Exception as exc:  # noqa: BLE001
        raise LayoutError(f"Couldn't open {filename} as a spreadsheet: {exc}") from exc
    sheets = [str(s) for s in book.sheet_names]
    if not sheets:
        raise LayoutError(f"{filename} has no sheets")
    use = sheet if sheet in sheets else sheets[0]
    df = pd.read_excel(book, sheet_name=use, header=None, dtype=str)
    rows = [[_cell(v) for v in r] for r in df.itertuples(index=False, name=None)]
    return Grid(rows=rows, sheets=sheets, sheet=use)


# ------------------------------------------------------------------ guessing

def _width(row: list[str]) -> int:
    return sum(1 for c in row if c)


def _first(row: list[str]) -> str:
    return next((c for c in row if c), "")


def guess_layout(grid: Grid) -> dict[str, Any]:
    """Where the table probably is. Plain files come back as the default layout."""
    rows = grid.rows
    layout = {**DEFAULT_LAYOUT, "sheet": grid.sheet}
    widths = [_width(r) for r in rows[:300]]
    wide = [w for w in widths if w >= 2]
    if not wide:
        return layout
    typical = Counter(wide).most_common(1)[0][0]

    header = 0
    for i, r in enumerate(rows[:60]):
        w = widths[i] if i < len(widths) else _width(r)
        if w < max(2, math.ceil(0.7 * typical)):
            continue
        cells = [c for c in r if c]
        texty = sum(1 for c in cells if not NUMBERISH.match(c)) / len(cells)
        nxt = next((x for x in rows[i + 1:i + 6] if _width(x)), None)
        if texty >= 0.7 and nxt is not None and _width(nxt) >= 0.5 * typical:
            header = i + 1
            break
    if header == 0:
        return layout
    data = next((j + 1 for j in range(header, len(rows)) if _width(rows[j])), header + 1)
    layout.update(header_row=header, data_row=data)

    after = rows[data - 1:]
    total = next((r for r in after if TOTALISH.match(_first(r))), None)
    if total is not None:
        layout.update(stop="text", stop_text=TOTALISH.match(_first(total)).group(0).strip().title())
        return layout
    blank = next((k for k, r in enumerate(after) if not _width(r)), None)
    if blank is not None:
        rest = [r for r in after[blank:] if _width(r)]
        if rest and all(_width(r) < 0.6 * typical for r in rest):  # notes or a footer, not more data
            layout["stop"] = "blank"
    return layout


# ------------------------------------------------------------------ cutting the table out

def clean_layout(layout: dict[str, Any] | None) -> dict[str, Any]:
    out = {**DEFAULT_LAYOUT, **(layout or {})}
    out["header_row"] = int(out.get("header_row") or 0)
    out["data_row"] = int(out.get("data_row") or 1)
    if out["header_row"] < 0 or out["data_row"] < 1:
        raise LayoutError("Row numbers start at 1")
    if out["header_row"] and out["data_row"] <= out["header_row"]:
        raise LayoutError("The data has to start below the header row")
    if out["stop"] not in ("end", "blank", "text"):
        raise LayoutError(f"Unknown stop rule “{out['stop']}”")
    if out["stop"] == "text" and not (out.get("stop_text") or "").strip():
        raise LayoutError("Say what text the stopping row starts with, e.g. Total")
    return out


def apply_layout(grid: Grid, layout: dict[str, Any] | None) -> tuple[pd.DataFrame, list[str]]:
    """The table the layout points at, as all-text columns, plus notes on what was left out."""
    lay = clean_layout(layout)
    rows, notes = grid.rows, []
    h, d = lay["header_row"], lay["data_row"]
    if h > len(rows):
        raise LayoutError(f"The file only has {len(rows)} rows, so row {h} can't be the header")

    body: list[list[str]] = []
    stopped_at = None
    for n in range(d - 1, len(rows)):
        r = rows[n]
        if lay["stop"] == "blank" and not _width(r):
            stopped_at = (n + 1, "the first blank row")
            break
        if lay["stop"] == "text" and _first(r).lower().startswith(lay["stop_text"].strip().lower()):
            stopped_at = (n + 1, f"“{_first(r)}”")
            break
        if _width(r):
            body.append(r)

    header = rows[h - 1] if h else []
    width = max([len(header)] + [len(r) for r in body] or [0])
    # Drop columns at the right that have no name and no data (spreadsheets often have these).
    while width and not (header[width - 1] if width <= len(header) else "") and not any(
        len(r) >= width and r[width - 1] for r in body
    ):
        width -= 1

    names, seen, unnamed = [], Counter(), []
    for j in range(width):
        name = (header[j] if j < len(header) else "").strip() or f"column_{j + 1}"
        if name == f"column_{j + 1}" and h:
            unnamed.append(name)
        seen[name] += 1
        names.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    if unnamed:
        notes.append(f"{len(unnamed)} column(s) had no header and were named {', '.join(unnamed)}")

    above = d - 1 - (1 if h else 0)
    if above > 0:
        notes.append(f"Skipped {above} row{'s' if above != 1 else ''} above the {'headers' if h else 'data'}")
    if stopped_at:
        left = sum(1 for r in rows[stopped_at[0] - 1:] if _width(r))
        notes.append(f"Stopped at row {stopped_at[0]} ({stopped_at[1]}), leaving out {left} row{'s' if left != 1 else ''} from there down")

    frame = pd.DataFrame([(r + [""] * width)[:width] for r in body], columns=names, dtype=str)
    return frame, notes


def describe(layout: dict[str, Any] | None, grid: Grid | None = None) -> str:
    """The layout in words, for the Activity log and the pages that show it."""
    lay = {**DEFAULT_LAYOUT, **(layout or {})}
    parts = []
    if lay.get("sheet") or (grid and grid.sheets):
        parts.append(f"sheet “{lay.get('sheet') or (grid.sheet if grid else '')}”")
    if lay["header_row"]:
        parts.append(f"column headers on row {lay['header_row']}")
    else:
        parts.append("no header row (columns named column_1, column_2, …)")
    stop = {"end": "to the end", "blank": "until the first blank row",
            "text": f"until a row starting with “{lay.get('stop_text')}”"}[lay["stop"]]
    parts.append(f"data from row {lay['data_row']} {stop}")
    return ", ".join(parts)


def is_default(layout: dict[str, Any] | None) -> bool:
    lay = {**DEFAULT_LAYOUT, **(layout or {})}
    return lay["header_row"] == 1 and lay["data_row"] == 2 and lay["stop"] == "end"


def read_table(data: bytes, filename: str, layout: dict[str, Any] | None = None
               ) -> tuple[pd.DataFrame, list[str], str]:
    """(table, notes, layout in words). The one entry point the loader uses."""
    grid = read_grid(data, filename, (layout or {}).get("sheet"))
    df, notes = apply_layout(grid, layout)
    return df, notes, describe(layout, grid)
