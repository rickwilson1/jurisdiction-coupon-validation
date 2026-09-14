#!/usr/bin/env python3
"""Fill column R (Email) of ~/Desktop/Open-No.xlsx using order# → email lookup
from the parsed Sacramento coupon data.

Join key: column C ("Agromin SO#") in the form `A109066` ↔ `order_number` 109066
from coupon_orders_CITYSACCOMB26.csv.

Saves to ~/Desktop/Open-No_with_emails.xlsx by default to avoid clobbering the
original. Pass --overwrite to write back to Open-No.xlsx.

Usage:
    python3 enrich_open_no.py [--overwrite]
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent
ORDERS_CSV = ROOT / "coupon_orders_CITYSACCOMB26.csv"
DESKTOP = Path.home() / "Desktop"
IN_XLSX = DESKTOP / "Open-No.xlsx"
DEFAULT_OUT = DESKTOP / "Open-No_with_emails.xlsx"

SO_RE = re.compile(r"A?(\d{6})", re.IGNORECASE)
EMAIL_COL = 18  # R
SO_COL = 3      # C
NAME_COL = 1    # A
HEADER_ROW = 2


def normalize_name(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.strip().lower())


def load_order_lookups() -> tuple[dict[str, str], dict[str, str]]:
    """Return (by_order_number, by_name) → email."""
    by_order: dict[str, str] = {}
    by_name: dict[str, list[str]] = {}
    with ORDERS_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ordn = row.get("order_number", "").strip()
            email = row.get("customer_email", "").strip()
            name = row.get("customer_name", "").strip()
            if ordn and email:
                by_order[ordn] = email
            if name and email:
                by_name.setdefault(normalize_name(name), []).append(email)
    # Collapse name lookup to single email (most common). When name maps to
    # multiple emails we keep the first and flag it.
    by_name_single: dict[str, str] = {}
    name_ambiguous: dict[str, list[str]] = {}
    for k, emails in by_name.items():
        uniq = list(dict.fromkeys(emails))
        if len(uniq) == 1:
            by_name_single[k] = uniq[0]
        else:
            name_ambiguous[k] = uniq
    if name_ambiguous:
        print(f"  Note: {len(name_ambiguous)} customer names map to multiple emails (kept first):")
        for k, emails in list(name_ambiguous.items())[:5]:
            print(f"    {k!r} → {emails}")
    return by_order, by_name_single


def main(out_path: Path) -> None:
    by_order, by_name = load_order_lookups()
    print(f"Loaded {len(by_order)} order→email mappings and {len(by_name)} name→email mappings")

    wb = load_workbook(IN_XLSX)
    ws = wb.active
    print(f"Opened {IN_XLSX}  →  sheet: {ws.title}, {ws.max_row} rows × {ws.max_column} cols")

    # Verify column R header
    r_header = ws.cell(HEADER_ROW, EMAIL_COL).value
    if r_header and "email" not in str(r_header).lower():
        print(f"  Warning: column R header is {r_header!r}, not 'Email'. Continuing anyway.")

    matched_by_so = 0
    matched_by_name = 0
    overwritten = 0
    unmatched = 0
    unmatched_rows: list[tuple[int, str, str]] = []

    for row in range(HEADER_ROW + 1, ws.max_row + 1):
        name_val = ws.cell(row, NAME_COL).value
        so_val = ws.cell(row, SO_COL).value
        existing_email = ws.cell(row, EMAIL_COL).value

        # Skip blank rows (no name, no SO)
        if (name_val in (None, "")) and (so_val in (None, "")):
            continue

        email: str | None = None
        match_source = ""

        # Primary: match by SO#
        if so_val:
            m = SO_RE.fullmatch(str(so_val).strip())
            if m:
                ordn = m.group(1)
                if ordn in by_order:
                    email = by_order[ordn]
                    match_source = "SO#"

        # Fallback: match by name
        if not email and name_val:
            key = normalize_name(str(name_val))
            if key in by_name:
                email = by_name[key]
                match_source = "name"

        if email:
            if existing_email and str(existing_email).strip() and str(existing_email).strip().lower() != email.lower():
                overwritten += 1
            ws.cell(row, EMAIL_COL, value=email)
            if match_source == "SO#":
                matched_by_so += 1
            else:
                matched_by_name += 1
        else:
            unmatched += 1
            if name_val or so_val:
                unmatched_rows.append((row, str(name_val or ""), str(so_val or "")))

    wb.save(out_path)

    print()
    print(f"Matched by SO#:  {matched_by_so}")
    print(f"Matched by name: {matched_by_name}")
    print(f"Total filled:    {matched_by_so + matched_by_name}")
    print(f"Cells overwritten (had a different prior value): {overwritten}")
    print(f"Unmatched rows with a name or SO#: {unmatched}")
    if unmatched_rows:
        print("\nSample unmatched rows (first 15):")
        for r, n, s in unmatched_rows[:15]:
            print(f"  row {r:>4}: name={n!r}  SO#={s!r}")
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    out = IN_XLSX if "--overwrite" in sys.argv else DEFAULT_OUT
    main(out)
