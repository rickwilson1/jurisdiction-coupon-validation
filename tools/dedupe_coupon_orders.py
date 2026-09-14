#!/usr/bin/env python3
"""Collapse the per-order CSV into a per-customer CSV.

Reads coupon_orders_CITYSACCOMB26.csv (one row per order) and writes
coupon_customers_CITYSACCOMB26.csv (one row per unique customer email),
aggregating order numbers, bag counts, and totals.

Usage:
    python3 dedupe_coupon_orders.py [orders.csv] [customers.csv]
"""

from __future__ import annotations

import csv
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_IN = ROOT / "coupon_orders_CITYSACCOMB26.csv"
DEFAULT_OUT = ROOT / "coupon_customers_CITYSACCOMB26.csv"

BAG_RE = re.compile(r"(\d+)\s*[\u00d7x]\s*([A-Za-z][^;]*?)(?=;|$)", re.IGNORECASE)


def parse_bags(items: str) -> int:
    total = 0
    for qty, prod in BAG_RE.findall(items or ""):
        prod_l = prod.lower()
        if "coupon" in prod_l or "shipping" in prod_l or "discount" in prod_l:
            continue
        try:
            total += int(qty)
        except ValueError:
            continue
    return total


def parse_money(s: str) -> float:
    if not s:
        return 0.0
    s = s.replace(",", "").replace("$", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def first_nonblank(values: list[str]) -> str:
    for v in values:
        if v and v.strip():
            return v.strip()
    return ""


def join_unique(values: list[str], sep: str = "; ") -> str:
    seen: OrderedDict[str, None] = OrderedDict()
    for v in values:
        v = (v or "").strip()
        if v and v not in seen:
            seen[v] = None
    return sep.join(seen.keys())


def main(in_path: Path, out_path: Path) -> None:
    with in_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} order rows from {in_path}")

    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r.get("customer_email") or "").strip().lower()
        if not key:
            key = f"__noemail__{r.get('order_number')}"
        grouped[key].append(r)

    out_rows = []
    for email, items in grouped.items():
        items_sorted = sorted(items, key=lambda r: int(r.get("order_number") or 0))
        names = join_unique([r["customer_name"] for r in items_sorted])
        phones = join_unique([r["phone"] for r in items_sorted])
        order_numbers = "; ".join(r["order_number"] for r in items_sorted)
        order_count = len(items_sorted)
        bag_total = sum(parse_bags(r["items"]) for r in items_sorted)
        amount_total = sum(parse_money(r["total"]) for r in items_sorted)
        first_date = min((r["first_email_date"] for r in items_sorted if r["first_email_date"]), default="")
        last_date = max((r["last_email_date"] for r in items_sorted if r["last_email_date"]), default="")

        out_rows.append(
            {
                "customer_email": "" if email.startswith("__noemail__") else email,
                "customer_name": names,
                "phone": phones,
                "street": first_nonblank([r["street"] for r in items_sorted]),
                "city": first_nonblank([r["city"] for r in items_sorted]),
                "state": first_nonblank([r["state"] for r in items_sorted]),
                "zip": first_nonblank([r["zip"] for r in items_sorted]),
                "order_count": order_count,
                "bag_total": bag_total,
                "amount_total": f"{amount_total:.2f}",
                "order_numbers": order_numbers,
                "first_email_date": first_date,
                "last_email_date": last_date,
                "username": first_nonblank([r.get("username", "") for r in items_sorted]),
                "account_id": first_nonblank([r.get("account_id", "") for r in items_sorted]),
                "coordinator_email": first_nonblank([r.get("coordinator_email", "") for r in items_sorted]),
            }
        )

    out_rows.sort(key=lambda r: (-int(r["bag_total"]), r["customer_name"].lower()))

    fieldnames = [
        "customer_email",
        "customer_name",
        "phone",
        "street",
        "city",
        "state",
        "zip",
        "order_count",
        "bag_total",
        "amount_total",
        "order_numbers",
        "first_email_date",
        "last_email_date",
        "username",
        "account_id",
        "coordinator_email",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    total_bags = sum(int(r["bag_total"]) for r in out_rows)
    total_amount = sum(parse_money(r["amount_total"]) for r in out_rows)
    multi_order = sum(1 for r in out_rows if r["order_count"] > 1)
    print(f"Wrote {len(out_rows)} unique customers to {out_path}")
    print(f"  Customers with multiple orders: {multi_order}")
    print(f"  Total bags issued: {total_bags}")
    print(f"  Total redemption value: ${total_amount:,.2f}")


if __name__ == "__main__":
    args = sys.argv[1:]
    in_p = Path(args[0]) if args else DEFAULT_IN
    out_p = Path(args[1]) if len(args) > 1 else DEFAULT_OUT
    main(in_p, out_p)
