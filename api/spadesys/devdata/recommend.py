"""Recommend a column type and fake-value generator from a column name
(and, when we have it, what the database says about the column).

Every recommendation carries a plain-English reason so the user can judge it.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from ..ingest.infer import snake_case
from .generators import DEFAULT_FOR_TYPE, GENERATORS


class FieldSpec(BaseModel):
    name: str
    type: str
    generator: str
    params: dict[str, Any] = {}
    null_percent: int = 0
    unique: bool = False
    max_length: int | None = None
    # informational
    db_type: str | None = None
    nullable: bool = True
    reason: str | None = None
    warning: str | None = None


ID_REASON = (
    "Looks like an ID or code. Those are labels, not amounts: you never add them up, "
    "and leading zeros (00123) must survive. Text is the safer type."
)

CHOICES = {
    "status": "active,inactive,pending",
    "gender": "female,male,nonbinary",
    "priority": "low,medium,high",
    "tier": "bronze,silver,gold",
    "type": "standard,premium,basic",
    "category": "A,B,C",
    "kind": "standard,special",
    "stage": "new,in_progress,done",
    "level": "beginner,intermediate,advanced",
}

# (test on snake_case name/tokens, type, generator, params, reason). First match wins.
Rule = tuple[Any, str, str, dict[str, Any], str]


def _ends(*suffixes: str):
    return lambda n, t: any(n == s or n.endswith("_" + s) for s in suffixes)


def _has(*words: str):
    return lambda n, t: any(w in t for w in words)


def _is(*names: str):
    return lambda n, t: n in names


RULES: list[Rule] = [
    (_has("uuid", "guid"), "uuid", "uuid", {}, "Name says UUID."),
    (_has("email", "e_mail"), "text", "email", {}, "Looks like an email address."),
    (_has("phone", "mobile", "fax", "tel", "cell"), "text", "phone",
     {}, "Phone numbers contain +, dashes and leading zeros, so store them as text."),
    (_has("zip", "zipcode", "postal", "postcode"), "text", "postal_code",
     {}, "ZIP/postal codes have leading zeros (02134), so store them as text."),
    (_is("id"), "integer", "sequence", {}, "This table's own row number."),
    (_has("sku"), "text", "sku", {}, "Product codes mix letters and digits."),
    (_ends("id", "key", "code", "number", "no", "num", "ref") , "text", "id_code", {}, ID_REASON),
    (_has("ssn", "iban"), "text", "id_code", {}, ID_REASON),
    (_ends("by"), "text", "id_code", {}, "Who did it, usually a user's ID. IDs are labels, so text."),
    (_is("first_name", "firstname", "fname", "given_name"), "text", "first_name", {}, "Looks like a first name."),
    (_is("last_name", "lastname", "lname", "surname", "family_name"), "text", "last_name", {}, "Looks like a last name."),
    (_is("username", "user_name", "login", "handle"), "text", "username", {}, "Looks like a username."),
    (_has("company", "organization", "organisation", "employer", "vendor", "supplier"), "text", "company", {}, "Looks like a company name."),
    (_is("name", "full_name", "fullname", "customer_name", "contact_name", "display_name"), "text", "full_name", {}, "Looks like a person's name."),
    (_has("city", "town"), "text", "city", {}, "Looks like a city."),
    (_has("state", "province", "region"), "text", "state", {}, "Looks like a state/region."),
    (_has("country"), "text", "country", {}, "Looks like a country."),
    (_has("address", "street", "addr"), "text", "street_address", {}, "Looks like a street address."),
    (_has("lat", "latitude"), "decimal", "latitude", {}, "Looks like a latitude."),
    (_has("lng", "lon", "longitude"), "decimal", "longitude", {}, "Looks like a longitude."),
    (_has("url", "website", "link", "homepage"), "text", "url", {}, "Looks like a web address."),
    (_has("title", "job", "role", "position"), "text", "job_title", {}, "Looks like a job title."),
    (_has("dob", "birthday", "birthdate", "birth"), "date", "birth_date", {}, "Looks like a birth date."),
    (lambda n, t: n.endswith("_at") or _has("timestamp", "datetime", "created", "updated", "modified", "login")(n, t),
     "timestamp", "timestamp_recent", {}, "Names ending in _at / created / updated are usually a date and time."),
    (lambda n, t: n.endswith("_on") or _has("date", "day")(n, t), "date", "date_past", {}, "Looks like a date."),
    (lambda n, t: t[0] in ("is", "has", "can", "should", "allow") or _has("active", "enabled", "flag", "verified", "deleted")(n, t),
     "boolean", "boolean", {}, "Names like is_… / has_… / active are yes-or-no."),
    (_has("price", "amount", "total", "cost", "balance", "salary", "fee", "revenue", "tax", "discount", "subtotal", "payment"),
     "decimal", "money", {}, "Money: needs exact decimals (use decimal, never float)."),
    (_has("pct", "percent", "percentage", "rate", "ratio"), "decimal", "decimal_range", {"min": 0, "max": 100, "places": 2}, "Looks like a percentage."),
    (_has("age"), "integer", "integer_range", {"min": 18, "max": 90}, "Looks like an age."),
    (_has("rating", "stars"), "integer", "integer_range", {"min": 1, "max": 5}, "Looks like a 1–5 rating."),
    (_has("qty", "quantity", "count", "units", "score", "rank", "points", "year"), "integer", "integer_range", {}, "Looks like a count or quantity, so a real number."),
    (_has("description", "notes", "note", "comment", "comments", "bio", "summary", "message", "body", "details"),
     "text", "sentence", {}, "Free text."),
]


def _choice_rule(n: str, t: list[str]) -> tuple[str, dict[str, Any]] | None:
    for word, choices in CHOICES.items():
        if word in t:
            return word, {"choices": choices}
    return None


def recommend(
    name: str,
    *,
    db_type: str | None = None,  # standard type from the database, if known
    db_type_raw: str | None = None,
    is_pk: bool = False,
    autoincrement: bool = False,
    fk_ref: str | None = None,  # "schema.table.column"
    enum_values: list[str] | None = None,
    max_length: int | None = None,
    nullable: bool = True,
    unique: bool = False,
) -> FieldSpec:
    n = snake_case(name)
    tokens = [x for x in n.split("_") if x] or [n]

    def spec(type_: str, generator: str, reason: str, params: dict | None = None, warning: str | None = None):
        g = GENERATORS[generator]
        return FieldSpec(
            name=name, type=type_, generator=generator, params={**g.defaults, **(params or {})},
            unique=unique or is_pk, max_length=max_length, db_type=db_type_raw, nullable=nullable,
            reason=reason, warning=warning,
        )

    # Facts from the database come first.
    if fk_ref:
        return spec(db_type or "text", "existing", f"Points at {fk_ref}. Uses values that already exist there, so the database accepts the rows.", {"ref": fk_ref})
    if is_pk and autoincrement and db_type == "integer":
        return spec("integer", "skip", "The database numbers these itself (auto-increment).")
    if is_pk and db_type == "integer":
        return spec("integer", "sequence", "Primary key: counts up so every row is unique.")
    if is_pk and db_type == "uuid":
        return spec("uuid", "uuid", "Primary key stored as a UUID.")
    if enum_values:
        return spec(db_type or "text", "choice", "The database only allows these values.", {"choices": ",".join(enum_values)})

    # Then the name.
    hit: tuple[str, str, dict, str] | None = None
    for test, type_, generator, params, reason in RULES:
        if test(n, tokens):
            hit = (type_, generator, params, reason)
            break
    if hit is None and (c := _choice_rule(n, tokens)):
        hit = ("text", "choice", c[1], f"Looks like a {c[0]}: a short list of allowed values. Edit the list to match yours.")

    if db_type is None:
        if hit:
            return spec(hit[0], hit[1], hit[3], hit[2])
        return spec("text", "word", "No strong clue from the name, so plain text. Change it if you know better.")

    # We know the database type: it wins, but say so if the name disagrees.
    if hit and db_type in GENERATORS[hit[1]].types:
        return spec(db_type, hit[1], hit[3], hit[2])
    if hit and hit[0] == "text" and db_type in ("integer", "decimal") and hit[1] in ("id_code", "postal_code", "phone"):
        g = "sequence" if hit[1] == "id_code" and unique else "integer_range"
        params = {"min": 1, "max": 99999} if g == "integer_range" else {}
        return spec(
            db_type, g, f"The database stores this as a {db_type}.", params,
            warning="Heads up: this looks like an ID/code, but the database stores it as a number. "
            "Leading zeros (00123) will be lost and nobody should do math on it. Consider text.",
        )
    return spec(db_type, DEFAULT_FOR_TYPE[db_type], f"The database stores this as {db_type_raw or db_type}.")


_US_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_US_TS_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}")


def sample_type(samples: list[str]) -> str | None:
    """What type do the pasted example values look like? None when there are none."""
    import pandas as pd

    from ..ingest.infer import TYPE_ORDER, _matches, is_null

    vals = [str(v).strip() for v in samples if not is_null(v)]
    if not vals:
        return None
    series = pd.Series(vals, dtype=str)
    t = next(t for t in TYPE_ORDER if _matches(t, series))
    if t == "text":  # spreadsheets like 1/5/2024
        if all(_US_DATE_RE.match(v) for v in vals):
            return "date"
        if all(_US_TS_RE.match(v) for v in vals):
            return "timestamp"
    return t


def apply_samples(f: FieldSpec, samples: list[str]) -> FieldSpec:
    """Refine a name-based recommendation using example values pasted under the header."""
    from ..ingest.infer import is_null

    vals = [str(v).strip() for v in samples if not is_null(v)]
    t = sample_type(vals)
    if t is None:
        return f
    shown = ", ".join(vals[:3])
    name_had_clue = not (f.reason or "").startswith("No strong clue")

    if name_had_clue:
        all_digits = all(v.isdigit() for v in vals)
        if f.type == "text" and all_digits and f.generator in ("id_code", "postal_code", "phone", "sequence"):
            zeros = any(v[:1] == "0" for v in vals)
            f.reason = (f.reason or "") + (
                f" Your examples ({shown}) have leading zeros, so text." if zeros
                else f" Your examples ({shown}) are all digits, but it's still a label, so text."
            )
            if f.generator == "id_code":
                f.params["length"] = max(len(v) for v in vals)
        else:
            f.reason = (f.reason or "") + f" (Your examples: {shown}.)"
    else:
        distinct = list(dict.fromkeys(vals))
        if t in ("text", "integer") and len(vals) >= 4 and len(distinct) <= len(vals) / 2:
            f.type, f.generator = t, "choice"
            f.params = {"choices": ",".join(distinct)}
            f.reason = f"Your examples repeat a few values ({', '.join(distinct[:5])}), so it picks from that list."
        else:
            g = DEFAULT_FOR_TYPE[t]
            f.type, f.generator, f.params = t, g, dict(GENERATORS[g].defaults)
            f.reason = f"Your examples ({shown}) look like {t}."

    # Ranges follow the examples.
    if f.generator in ("integer_range", "decimal_range", "money"):
        try:
            nums = [float(v.replace(",", "").lstrip("$")) for v in vals]
            lo, hi = min(nums), max(nums)
            if lo != hi:
                f.params["min"], f.params["max"] = (int(lo), int(hi)) if f.generator == "integer_range" else (lo, hi)
        except ValueError:
            pass
    return f


def parse_pasted_table(text: str) -> tuple[list[str], list[list[str]]]:
    """Header names plus any example rows under them.

    Handles a copied spreadsheet/table range (tab separated), a CSV header with or without rows,
    or one column name per line.
    """
    import csv
    import io

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], []
    first = lines[0]
    delim = next((d for d in ("\t", ",", ";", "|") if d in first), None)
    if delim is None:  # one name per line
        return parse_pasted(text), []
    reader = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    header = [h.strip() for h in reader[0]]
    keep = [i for i, h in enumerate(header) if h]
    names, seen = [], set()
    cols = []
    for i in keep:
        if header[i].lower() not in seen:
            seen.add(header[i].lower())
            names.append(header[i])
            cols.append(i)
    rows = [[(r[i].strip() if i < len(r) else "") for i in cols] for r in reader[1:]]
    return names, rows


def parse_pasted(text: str) -> list[str]:
    """Accept column names separated by commas, tabs, or new lines (e.g. a pasted CSV header)."""
    parts = re.split(r"[,\t\r\n;|]+", text)
    seen, out = set(), []
    for p in parts:
        p = p.strip().strip('"').strip("'").strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out
