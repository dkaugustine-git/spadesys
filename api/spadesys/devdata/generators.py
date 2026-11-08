"""Catalog of fake-value generators ("what kind of values go in this column").

Each generator declares which standard column types it can fill and its
default parameters. The UI lists them; the engine calls them.
"""

from __future__ import annotations

import random
import string
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from faker import Faker

TYPES = ["text", "integer", "decimal", "boolean", "date", "timestamp", "uuid"]
ALL = TYPES

TYPE_LABELS = {
    "text": "Text",
    "integer": "Whole number",
    "decimal": "Decimal number",
    "boolean": "True / false",
    "date": "Date",
    "timestamp": "Date + time",
    "uuid": "UUID",
}


@dataclass
class Ctx:
    fake: Faker
    rng: random.Random
    ref_values: dict[str, list[Any]] = field(default_factory=dict)


@dataclass
class Generator:
    key: str
    label: str
    group: str
    types: list[str]
    defaults: dict[str, Any]
    fn: Callable[[Ctx, dict[str, Any], int, str], Any]


GENERATORS: dict[str, Generator] = {}


def gen(key: str, label: str, group: str, types: list[str], **defaults: Any):
    def deco(fn):
        GENERATORS[key] = Generator(key, label, group, types, defaults, fn)
        return fn

    return deco


# ------------------------------------------------------------------ IDs
@gen("sequence", "Counting up: 1, 2, 3…", "IDs", ["integer", "text"], start=1)
def _seq(c, p, i, f):
    return int(p["start"]) + i


@gen("id_code", "ID code: digits kept as text (00482913)", "IDs", ["text"], length=8)
def _id_code(c, p, i, f):
    n = int(p["length"])
    return str(c.rng.randrange(10**n)).zfill(n)


@gen("uuid", "UUID (random unique id)", "IDs", ["uuid", "text"])
def _uuid(c, p, i, f):
    return uuid.UUID(int=c.rng.getrandbits(128), version=4)


@gen("sku", "Product-style code (ABX-48213)", "IDs", ["text"], prefix_letters=3, digits=5)
def _sku(c, p, i, f):
    letters = "".join(c.rng.choices(string.ascii_uppercase, k=int(p["prefix_letters"])))
    return f"{letters}-{str(c.rng.randrange(10 ** int(p['digits']))).zfill(int(p['digits']))}"


@gen("existing", "Values that already exist in another table", "IDs", ALL, ref="")
def _existing(c, p, i, f):
    values = c.ref_values.get(f) or [None]
    return c.rng.choice(values)


# ---------------------------------------------------------------- people
@gen("first_name", "First name", "People", ["text"])
def _first(c, p, i, f):
    return c.fake.first_name()


@gen("last_name", "Last name", "People", ["text"])
def _last(c, p, i, f):
    return c.fake.last_name()


@gen("full_name", "Full name", "People", ["text"])
def _full(c, p, i, f):
    return c.fake.name()


@gen("email", "Email address", "People", ["text"])
def _email(c, p, i, f):
    return c.fake.email()


@gen("phone", "Phone number", "People", ["text"])
def _phone(c, p, i, f):
    return c.fake.phone_number()


@gen("username", "Username", "People", ["text"])
def _user(c, p, i, f):
    return c.fake.user_name()


@gen("job_title", "Job title", "People", ["text"])
def _job(c, p, i, f):
    return c.fake.job()


@gen("company", "Company name", "People", ["text"])
def _company(c, p, i, f):
    return c.fake.company()


# ---------------------------------------------------------------- places
@gen("street_address", "Street address", "Places", ["text"])
def _street(c, p, i, f):
    return c.fake.street_address()


@gen("city", "City", "Places", ["text"])
def _city(c, p, i, f):
    return c.fake.city()


@gen("state", "State (2-letter)", "Places", ["text"])
def _state(c, p, i, f):
    return c.fake.state_abbr()


@gen("postal_code", "ZIP / postal code (text, keeps leading zeros)", "Places", ["text"])
def _zip(c, p, i, f):
    return c.fake.postcode()


@gen("country", "Country", "Places", ["text"])
def _country(c, p, i, f):
    return c.fake.country()


@gen("latitude", "Latitude", "Places", ["decimal", "text"])
def _lat(c, p, i, f):
    return Decimal(str(round(c.rng.uniform(-90, 90), 6)))


@gen("longitude", "Longitude", "Places", ["decimal", "text"])
def _lng(c, p, i, f):
    return Decimal(str(round(c.rng.uniform(-180, 180), 6)))


@gen("url", "Web address", "Places", ["text"])
def _url(c, p, i, f):
    return c.fake.url()


# --------------------------------------------------------------- numbers
@gen("integer_range", "Whole number between min and max", "Numbers", ["integer", "decimal", "text"], min=1, max=100)
def _int_range(c, p, i, f):
    lo, hi = int(p["min"]), int(p["max"])
    return c.rng.randint(min(lo, hi), max(lo, hi))


@gen("decimal_range", "Decimal number between min and max", "Numbers", ["decimal", "text"], min=0, max=1000, places=2)
def _dec_range(c, p, i, f):
    lo, hi, places = float(p["min"]), float(p["max"]), int(p["places"])
    return Decimal(str(round(c.rng.uniform(min(lo, hi), max(lo, hi)), places))).quantize(Decimal(1).scaleb(-places))


@gen("money", "Money amount", "Numbers", ["decimal", "text"], min=1, max=500)
def _money(c, p, i, f):
    lo, hi = float(p["min"]), float(p["max"])
    return Decimal(str(round(c.rng.uniform(min(lo, hi), max(lo, hi)), 2))).quantize(Decimal("0.01"))


# ------------------------------------------------------------ true/false
@gen("boolean", "True / false", "Other", ["boolean", "integer", "text"], true_percent=50)
def _bool(c, p, i, f):
    return c.rng.random() * 100 < float(p["true_percent"])


# ------------------------------------------------------------ dates
@gen("date_past", "Date in the past N years", "Dates", ["date", "timestamp", "text"], years=3)
def _date_past(c, p, i, f):
    return date.today() - timedelta(days=c.rng.randint(0, int(float(p["years"]) * 365)))


@gen("birth_date", "Birth date (age 18–80)", "Dates", ["date", "text"])
def _birth(c, p, i, f):
    return date.today() - timedelta(days=c.rng.randint(18 * 365, 80 * 365))


@gen("date_future", "Date in the next N days", "Dates", ["date", "timestamp", "text"], days=365)
def _date_future(c, p, i, f):
    return date.today() + timedelta(days=c.rng.randint(0, int(p["days"])))


@gen("timestamp_recent", "Date + time in the last N days", "Dates", ["timestamp", "date", "text"], days=365)
def _ts_recent(c, p, i, f):
    secs = c.rng.randint(0, int(p["days"]) * 86400)
    return (datetime.now(timezone.utc) - timedelta(seconds=secs)).replace(microsecond=0)


# ------------------------------------------------------------ text
@gen("choice", "Pick from a list", "Text", ["text", "integer"], choices="active,inactive,pending")
def _choice(c, p, i, f):
    options = [s.strip() for s in str(p["choices"]).split(",") if s.strip()] or [""]
    return c.rng.choice(options)


@gen("word", "A random word", "Text", ["text"])
def _word(c, p, i, f):
    return c.fake.word()


@gen("sentence", "A short sentence", "Text", ["text"])
def _sentence(c, p, i, f):
    return c.fake.sentence()


@gen("paragraph", "A paragraph", "Text", ["text"])
def _para(c, p, i, f):
    return c.fake.paragraph()


# ------------------------------------------------------------ special
@gen("skip", "Leave out: the database fills it in", "Other", ALL)
def _skip(c, p, i, f):
    return None


@gen("empty", "Always empty (NULL)", "Other", ALL)
def _empty(c, p, i, f):
    return None


DEFAULT_FOR_TYPE = {
    "text": "word",
    "integer": "integer_range",
    "decimal": "decimal_range",
    "boolean": "boolean",
    "date": "date_past",
    "timestamp": "timestamp_recent",
    "uuid": "uuid",
}


def catalog() -> dict[str, Any]:
    return {
        "types": [{"key": t, "label": TYPE_LABELS[t]} for t in TYPES],
        "generators": [
            {"key": g.key, "label": g.label, "group": g.group, "types": g.types, "defaults": g.defaults}
            for g in GENERATORS.values()
        ],
    }
