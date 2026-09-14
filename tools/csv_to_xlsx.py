#!/usr/bin/env python3
"""Convert the coupon CSVs into a formatted XLSX workbook with two sheets.

Sheet 1: Customers (deduped, sorted by bag_total desc)
Sheet 2: Orders (one row per order_number)

Formatting: bold header row, frozen header, autofilter, sensible column widths,
currency format on $ columns.

Usage:
    python3 csv_to_xlsx.py [out.xlsx]
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent
CUSTOMERS_CSV = ROOT / "coupon_customers_CITYSACCOMB26.csv"
ORDERS_CSV = ROOT / "coupon_orders_CITYSACCOMB26.csv"
DEFAULT_OUT = ROOT / "Sacramento_Coupon_Program_CITYSACCOMB26.xlsx"

HEADER_FILL = PatternFill("solid", fgColor="2E7D32")  # Agromin-green-ish
HEADER_FONT = Font(bold=True, color="FFFFFF")
TOTALS_FONT = Font(bold=True)
CURRENCY_FMT = "$#,##0.00"

CUSTOMER_COL_WIDTHS = {
    "customer_email": 32,
    "customer_name": 28,
    "phone": 16,
    "street": 30,
    "city": 14,
    "state": 6,
    "zip": 8,
    "order_count": 7,
    "bag_total": 7,
    "amount_total": 12,
    "order_numbers": 22,
    "first_email_date": 12,
    "last_email_date": 12,
    "username": 18,
    "account_id": 10,
    "coordinator_email": 22,
}

ORDER_COL_WIDTHS = {
    "order_number": 9,
    "customer_name": 24,
    "customer_email": 30,
    "phone": 16,
    "street": 30,
    "city": 14,
    "state": 6,
    "zip": 8,
    "items": 36,
    "subtotal": 10,
    "total": 10,
    "coupon_code": 16,
    "username": 18,
    "account_id": 10,
    "company": 24,
    "coordinator_email": 22,
    "first_email_date": 12,
    "last_email_date": 12,
    "email_count": 7,
    "latest_subject": 60,
}

CURRENCY_COLS = {"amount_total", "subtotal", "total"}


def load_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return reader.fieldnames or [], rows


def write_sheet(ws, fieldnames: list[str], rows: list[dict], col_widths: dict[str, int]) -> None:
    ws.append(fieldnames)
    for col_idx, fname in enumerate(fieldnames, 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", horizontal="left")
        ws.column_dimensions[get_column_letter(col_idx)].width = col_widths.get(fname, 14)

    for r_idx, row in enumerate(rows, 2):
        for c_idx, fname in enumerate(fieldnames, 1):
            value = row.get(fname, "")
            if fname in CURRENCY_COLS and value not in (None, ""):
                try:
                    value = float(str(value).replace(",", "").replace("$", ""))
                except ValueError:
                    pass
            elif fname in {"order_count", "bag_total", "email_count"} and value not in (None, ""):
                try:
                    value = int(value)
                except ValueError:
                    pass
            cell = ws.cell(row=r_idx, column=c_idx, value=value)
            if fname in CURRENCY_COLS:
                cell.number_format = CURRENCY_FMT

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def add_totals_row(ws, fieldnames: list[str], rows: list[dict], sum_fields: dict[str, str]) -> None:
    """Add a TOTALS row at the bottom. `sum_fields` maps colname -> 'int'|'money'."""
    target_row = len(rows) + 2
    label_col = 1
    ws.cell(row=target_row, column=label_col, value="TOTALS").font = TOTALS_FONT
    for col_idx, fname in enumerate(fieldnames, 1):
        if fname not in sum_fields:
            continue
        col_letter = get_column_letter(col_idx)
        cell = ws.cell(
            row=target_row,
            column=col_idx,
            value=f"=SUM({col_letter}2:{col_letter}{target_row - 1})",
        )
        cell.font = TOTALS_FONT
        if sum_fields[fname] == "money":
            cell.number_format = CURRENCY_FMT


def main(out_path: Path) -> None:
    cust_fields, cust_rows = load_csv(CUSTOMERS_CSV)
    ord_fields, ord_rows = load_csv(ORDERS_CSV)

    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Customers"
    write_sheet(ws1, cust_fields, cust_rows, CUSTOMER_COL_WIDTHS)
    add_totals_row(
        ws1,
        cust_fields,
        cust_rows,
        {"order_count": "int", "bag_total": "int", "amount_total": "money"},
    )

    ws2 = wb.create_sheet("Orders")
    write_sheet(ws2, ord_fields, ord_rows, ORDER_COL_WIDTHS)
    add_totals_row(ws2, ord_fields, ord_rows, {"subtotal": "money", "total": "money"})

    summary = wb.create_sheet("Summary", 0)
    summary["A1"] = "Sacramento Coupon Program — CITYSACCOMB26"
    summary["A1"].font = Font(bold=True, size=16, color="2E7D32")
    summary["A3"] = "Source"
    summary["B3"] = "sales@agromin.com → NorCal folder (Outlook)"
    summary["A4"] = "Extract date"
    summary["B4"] = "2026-05-19"
    summary["A5"] = "Date range of orders"
    if cust_rows:
        first = min(r["first_email_date"] for r in cust_rows if r["first_email_date"])
        last = max(r["last_email_date"] for r in cust_rows if r["last_email_date"])
        summary["B5"] = f"{first}  —  {last}"
    summary["A6"] = "Unique customers"
    summary["B6"] = len(cust_rows)
    summary["A7"] = "Unique orders"
    summary["B7"] = len(ord_rows)
    summary["A8"] = "Total bags issued"
    summary["B8"] = sum(int(r["bag_total"]) for r in cust_rows if r["bag_total"])
    summary["A9"] = "Total redemption value"
    summary["B9"] = sum(
        float(str(r["amount_total"]).replace(",", "").replace("$", ""))
        for r in cust_rows
        if r["amount_total"]
    )
    summary["B9"].number_format = CURRENCY_FMT
    summary["A11"] = "Notes"
    summary["A11"].font = Font(bold=True)
    summary["A12"] = "• Sheet 'Customers' is deduped by customer_email and sorted by bag_total desc."
    summary["A13"] = "• Sheet 'Orders' is the raw per-order data (one row per CIMcloud order number)."
    summary["A14"] = "• Family accounts may show multiple customer names per email — both are preserved."
    summary["A15"] = (
        "• Order 109536 (Josh Hagen) has minor garble in the per-order 'items' field — "
        "totals are correct."
    )
    summary.column_dimensions["A"].width = 28
    summary.column_dimensions["B"].width = 50

    wb.save(out_path)
    print(f"Wrote {out_path}")
    print("  Sheet 'Summary'   : program overview")
    print(f"  Sheet 'Customers' : {len(cust_rows)} unique customers")
    print(f"  Sheet 'Orders'    : {len(ord_rows)} unique orders")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    main(out)
