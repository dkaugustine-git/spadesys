"""Faker-based test data: customers -> orders -> order_items, plus an item catalog.

This shape matches the planned Doris hybrid model: orders/items nest under a
customer as ARRAY<STRUCT>, while item details stay in a lookup table.

CLI:
    python -m spadesys.generators.commerce --out ../data --customers 500 --orders 5000
"""

from __future__ import annotations

import argparse
import csv
import io
import random
from decimal import Decimal
from pathlib import Path

from faker import Faker

CATEGORIES = ["Hardware", "Software", "Books", "Garden", "Kitchen", "Outdoors", "Toys", "Office"]


def generate(customers: int = 200, items: int = 50, orders: int = 1_000, seed: int | None = None) -> dict[str, list[dict]]:
    fake = Faker()
    rng = random.Random(seed)
    if seed is not None:
        Faker.seed(seed)

    customer_rows = [
        {
            "customer_id": i,
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "email": fake.unique.email(),
            "phone": fake.phone_number(),
            "city": fake.city(),
            "state": fake.state_abbr(),
            "postal_code": fake.postcode(),  # keeps leading zeros -> inferred as text
            "signup_date": fake.date_between("-3y", "-30d").isoformat(),
            "is_active": rng.random() > 0.1,
        }
        for i in range(1, customers + 1)
    ]

    item_rows = [
        {
            "item_id": i,
            "sku": f"SKU-{fake.unique.bothify('??-#####').upper()}",
            "name": fake.catch_phrase(),
            "category": rng.choice(CATEGORIES),
            "unit_price": str(Decimal(rng.randint(199, 49_999)) / 100),
        }
        for i in range(1, items + 1)
    ]
    prices = {r["item_id"]: Decimal(r["unit_price"]) for r in item_rows}

    order_rows, order_item_rows = [], []
    line_id = 1
    for oid in range(1, orders + 1):
        lines = []
        for item_id in rng.sample(range(1, items + 1), k=min(items, rng.randint(1, 5))):
            qty = rng.randint(1, 4)
            lines.append(
                {
                    "order_item_id": line_id,
                    "order_id": oid,
                    "item_id": item_id,
                    "quantity": qty,
                    "unit_price": str(prices[item_id]),
                }
            )
            line_id += 1
        order_item_rows += lines
        order_rows.append(
            {
                "order_id": oid,
                "customer_id": rng.randint(1, customers),
                "ordered_at": fake.date_time_between("-2y", "now").isoformat(timespec="seconds"),
                "status": rng.choices(["completed", "shipped", "pending", "cancelled"], [70, 15, 10, 5])[0],
                "order_total": str(sum(Decimal(line["unit_price"]) * line["quantity"] for line in lines)),
            }
        )

    return {"customers": customer_rows, "items": item_rows, "orders": order_rows, "order_items": order_item_rows}


def to_csv_bytes(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="data", type=Path)
    p.add_argument("--customers", type=int, default=200)
    p.add_argument("--items", type=int, default=50)
    p.add_argument("--orders", type=int, default=1_000)
    p.add_argument("--seed", type=int)
    a = p.parse_args()

    a.out.mkdir(parents=True, exist_ok=True)
    for name, rows in generate(a.customers, a.items, a.orders, a.seed).items():
        path = a.out / f"{name}.csv"
        path.write_bytes(to_csv_bytes(rows))
        print(f"wrote {len(rows):>6} rows -> {path}")


if __name__ == "__main__":
    main()
