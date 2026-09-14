#!/usr/bin/env python3
"""Parse the Sacramento coupon-emails JSON dump from Power Automate into a CSV.

Input:  ./coupons-emails-CITYSACCOMB26.json  (an array of Office 365 message objects
        from the Power Automate `Coupon Email Extract` flow against sales@agromin.com → NorCal)
Output: ./coupon_orders_CITYSACCOMB26.csv

Dedupes by order number extracted from subject. For each unique order, extracts the
customer name, email, phone, ship-to address, items, and totals from the CIMcloud
"Order Summary" block embedded in the email body (which is consistent across the
order confirmation, internal approval forwards, and the scheduling reply chain).

Usage:
    python3 parse_coupon_emails.py [input.json] [output.csv]
"""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_IN = ROOT / "coupons-emails-CITYSACCOMB26.json"
DEFAULT_OUT = ROOT / "coupon_orders_CITYSACCOMB26.csv"

ORDER_RE = re.compile(r"\b(?:Order\s*(?:Number|#)?\s*)?A?#?(1\d{5})\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(\d{3}[\s.\-]?\d{3}[\s.\-]?\d{4})(?!\d)")
ACCOUNT_RE = re.compile(r"^W\d{5,7}$")
CSZ_RE = re.compile(r"^(.+?),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?$")
QTY_LINE_RE = re.compile(r"^\s*\|?\s*(\d{1,4})\s*\|\s*(.+?)\s*(?:SKU:\s*(\S+))?\s*\|", re.MULTILINE)
COUPON_LINE_RE = re.compile(r"Coupon\s*Code\s*:\s*\|?\s*([A-Z0-9]+)", re.IGNORECASE)
USERNAME_LINE_RE = re.compile(r"Username\s*:\s*\|?\s*(\S+)", re.IGNORECASE)
SUBTOTAL_RE = re.compile(r"Subtotal\s*\|?\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)
TOTAL_RE = re.compile(r"Total\s*\|?\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)
AGROMIN_DOMAIN = "agromin.com"
PICKUP_YARDS = ("florin perkins",)


def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<script[^>]*>.*?</script>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</p>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</div>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</tr>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</td>", " | ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def parse_order_summary(text: str) -> dict[str, str]:
    """Parse a CIMcloud `Order Summary` block.

    The block has the shape (line-by-line, after table stripping):

        Order Summary |
        <Name>
        <Name or Company>
        W<account_id>
        <street>
        <City>, <ST> <ZIP>
        USA
        <phone>
        <email>
        | Payment Method: | ... |
        Coupon Code: | <CODE> |
        Account: | 02-W<account_id> |
        Username: | <username> |
        ...
        Shipment Details
        Shipping Address | Shipping Method |
        <pickup yard line>
        <pickup yard street>
        <pickup yard city/state/zip>
        | <shipping method>
        Image | Qty | Description | Unit Price | Price |
        | <qty> | <product> SKU: <sku> | $<unit> | $<total> |
        ...
        Subtotal | $<n>
        Coupon | $<n>
        Total | $<n>
    """
    out: dict[str, str] = {}
    idx = text.lower().find("order summary")
    if idx < 0:
        return out
    chunk = text[idx : idx + 3500]
    lines = [line.strip(" |") for line in chunk.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 6:
        return out

    body_lines = lines[1:]
    name_candidates: list[str] = []
    while body_lines:
        line = body_lines[0]
        if ACCOUNT_RE.match(line):
            break
        if CSZ_RE.match(line):
            break
        if EMAIL_RE.search(line):
            break
        if PHONE_RE.search(line):
            break
        if line.lower().startswith(("payment method", "coupon code", "account", "username")):
            break
        if line.lower() in {"usa", "us"}:
            break
        name_candidates.append(line)
        body_lines.pop(0)
        if len(name_candidates) >= 3:
            break

    if name_candidates:
        out["customer_name"] = name_candidates[0]
        if len(name_candidates) > 1 and name_candidates[1].lower() != name_candidates[0].lower():
            out["customer_company"] = name_candidates[1]

    for line in body_lines[:12]:
        if ACCOUNT_RE.match(line) and "account_id" not in out:
            out["account_id"] = line
            continue
        m_csz = CSZ_RE.match(line)
        if m_csz and "city" not in out:
            out["city"] = m_csz.group(1).strip()
            out["state"] = m_csz.group(2).strip()
            out["zip"] = m_csz.group(3).strip()
            continue
        m_phone = PHONE_RE.search(line)
        if m_phone and "phone" not in out:
            digits = re.sub(r"\D", "", m_phone.group(1))
            out["phone"] = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
            continue
        m_email = EMAIL_RE.search(line)
        if m_email and "email" not in out:
            addr = m_email.group(0).lower()
            if not addr.endswith("@" + AGROMIN_DOMAIN):
                out["email"] = addr
            continue
        if line.lower() in {"usa", "us"}:
            continue
        if line.lower().startswith(("payment method", "coupon code", "account", "username", "shipment", "shipping")):
            break
        if "street" not in out and not line.lower().startswith("agromin"):
            stripped = line.strip()
            if (
                re.match(r"^\d", stripped)
                or re.search(r"\b(street|st|ave|avenue|road|rd|drive|dr|lane|ln|way|blvd|boulevard|court|ct|place|pl|circle|cir|terrace|ter)\b\.?$", stripped, re.IGNORECASE)
                or re.search(r"\b(street|st|ave|avenue|road|rd|drive|dr|lane|ln|way|blvd|boulevard|court|ct|place|pl|circle|cir|terrace|ter)\b", stripped, re.IGNORECASE)
            ):
                if not any(yard in stripped.lower() for yard in PICKUP_YARDS):
                    out["street"] = stripped

    m_coupon = COUPON_LINE_RE.search(chunk)
    if m_coupon:
        out["coupon_code"] = m_coupon.group(1).upper()
    m_user = USERNAME_LINE_RE.search(chunk)
    if m_user:
        out["username"] = m_user.group(1)

    items: list[str] = []
    for q, prod, _sku in QTY_LINE_RE.findall(chunk):
        prod_clean = re.sub(r"SKU:.*", "", prod).strip()
        prod_clean = re.sub(r"\s+", " ", prod_clean)
        if not prod_clean or prod_clean.lower().startswith("description"):
            continue
        items.append(f"{q} \u00d7 {prod_clean}")
        if len(items) >= 6:
            break
    if items:
        out["items"] = "; ".join(items)

    m_sub = SUBTOTAL_RE.search(chunk)
    if m_sub:
        out["subtotal"] = m_sub.group(1)
    m_tot = TOTAL_RE.search(chunk)
    if m_tot:
        out["total"] = m_tot.group(1)

    return out


def order_numbers_for(message: dict[str, Any]) -> list[str]:
    subj = message.get("subject") or ""
    return sorted(set(ORDER_RE.findall(subj)))


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def merge(into: dict[str, str], more: dict[str, str]) -> None:
    """Merge `more` into `into`, only filling blanks (no overwrite)."""
    for k, v in more.items():
        if v and not into.get(k):
            into[k] = v


def main(in_path: Path, out_path: Path) -> None:
    raw = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        sys.exit(f"Expected a JSON array at top level; got {type(raw).__name__}")

    print(f"Loaded {len(raw)} emails from {in_path}")

    by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    orphan: list[dict[str, Any]] = []
    for msg in raw:
        nums = order_numbers_for(msg)
        if nums:
            for n in nums:
                by_order[n].append(msg)
        else:
            orphan.append(msg)

    print(f"Unique orders: {len(by_order)}  | orphan emails (admin notices etc.): {len(orphan)}")

    rows: list[dict[str, Any]] = []
    for order, msgs in sorted(by_order.items(), key=lambda kv: int(kv[0])):
        all_dates = sorted(d for d in (parse_date(m.get("receivedDateTime")) for m in msgs) if d)
        coordinator_emails: Counter[str] = Counter()
        merged: dict[str, str] = {}
        latest_subject = ""
        for m in msgs:
            body_text = strip_html(m.get("body") or "")
            parsed = parse_order_summary(body_text)
            merge(merged, parsed)
            if m.get("subject"):
                latest_subject = m.get("subject")
            sender = (m.get("from") or "").lower()
            if sender.endswith("@" + AGROMIN_DOMAIN):
                coordinator_emails[sender] += 1

        coordinator = coordinator_emails.most_common(1)[0][0] if coordinator_emails else ""
        rows.append(
            {
                "order_number": order,
                "customer_name": merged.get("customer_name", ""),
                "customer_email": merged.get("email", ""),
                "phone": merged.get("phone", ""),
                "street": merged.get("street", ""),
                "city": merged.get("city", ""),
                "state": merged.get("state", ""),
                "zip": merged.get("zip", ""),
                "items": merged.get("items", ""),
                "subtotal": merged.get("subtotal", ""),
                "total": merged.get("total", ""),
                "coupon_code": merged.get("coupon_code", ""),
                "username": merged.get("username", ""),
                "account_id": merged.get("account_id", ""),
                "company": merged.get("customer_company", ""),
                "coordinator_email": coordinator,
                "first_email_date": all_dates[0].strftime("%Y-%m-%d") if all_dates else "",
                "last_email_date": all_dates[-1].strftime("%Y-%m-%d") if all_dates else "",
                "email_count": len(msgs),
                "latest_subject": latest_subject,
            }
        )

    fieldnames = [
        "order_number",
        "customer_name",
        "customer_email",
        "phone",
        "street",
        "city",
        "state",
        "zip",
        "items",
        "subtotal",
        "total",
        "coupon_code",
        "username",
        "account_id",
        "company",
        "coordinator_email",
        "first_email_date",
        "last_email_date",
        "email_count",
        "latest_subject",
    ]

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out_path}")

    cov = lambda key: sum(1 for r in rows if r[key])  # noqa: E731
    print(
        "Coverage: "
        f"name={cov('customer_name')}/{len(rows)}  "
        f"email={cov('customer_email')}/{len(rows)}  "
        f"phone={cov('phone')}/{len(rows)}  "
        f"street={cov('street')}/{len(rows)}  "
        f"items={cov('items')}/{len(rows)}  "
        f"total={cov('total')}/{len(rows)}"
    )


if __name__ == "__main__":
    args = sys.argv[1:]
    in_p = Path(args[0]) if args else DEFAULT_IN
    out_p = Path(args[1]) if len(args) > 1 else DEFAULT_OUT
    main(in_p, out_p)
