"""
Weekly coupon activity report.

Builds the Monday-morning summary of coupon-program orders from Firestore
`order_events`: the prior Monday-to-Sunday week, a trailing weekly series,
program-to-date by jurisdiction, and a monthly rollup. Renders an HTML email
body (table layout, inline CSS, Outlook-safe), a plain-text alternative, and an
Excel workbook with order-level detail for the accountants.

Pure functions over plain dicts so the whole module runs without Firestore or
Graph credentials; `main.py` supplies the documents and sends the result.
"""

import html
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Optional: only needed to read the coupon master from GCS. The report degrades
# to the abbreviation fallback when the library or the bucket is unavailable.
try:
    from google.cloud import storage as gcs_storage
except ImportError:  # pragma: no cover
    gcs_storage = None

logger = logging.getLogger(__name__)

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

# Monday 7am PT blast. Rick's list of 2026-09-14; override with WEEKLY_REPORT_TO
# (comma-separated) without a code change.
DEFAULT_RECIPIENTS = [
    "jim@agromin.com",
    "bcamarillo@agromin.com",
    "cody@agromin.com",
    "kendall@agromin.com",
    "kristen@agromin.com",
    "mike@agromin.com",
    "rickwilson@agromin.com",
    "dcamarillo@agromin.com",
    "greg@agromin.com",
    "brian@agromin.com",
    "craig@agromin.com",
    "dgreen@agromin.com",
    "msmith@agromin.com",
]

# Orders that exist in Firestore only because someone exercised the pipeline.
# Override with WEEKLY_REPORT_EXCLUDE (comma-separated order numbers).
DEFAULT_EXCLUDED_ORDERS = {"A1"}

# OCWR program launch (Rick, 2026-09-14). Orders dated earlier are soft-launch
# or test activity: they appear as a single pre-launch row in the monthly table
# and nowhere else. Override with WEEKLY_REPORT_PROGRAM_START (YYYY-MM-DD).
DEFAULT_PROGRAM_START = date(2026, 8, 28)

# This report covers the OCWR program only. Ventura and Sacramento orders land
# in the same Firestore collection with their own `region` value and must stay
# out. Override with WEEKLY_REPORT_REGION; set it to an empty string for all.
DEFAULT_REGION = "oc"
PROGRAM_NAME = "OCWR"

# Trailing weeks shown in the weekly table (the report week is the last row).
# The table never reaches back before the launch week.
WEEKS_BACK = 8

# Fallback when the coupon master is unreachable. Keyed by the abbreviation
# between the CITY/COU prefix and the COM/CM/COMB suffix. Confirmed against the
# OCWR jurisdiction list; extend as codes appear.
_ABBREVIATION_FALLBACK = {
    "ANA": "Anaheim",
    "BUP": "Buena Park",
    "DAP": "Dana Point",
    "IRV": "Irvine",
    "IRVINE": "Irvine",
    "NPB": "Newport Beach",
    "PLA": "Placentia",
    "SAA": "Santa Ana",
    "SCL": "San Clemente",
    "SAC": "Sacramento",
    "V": "Ventura",
}

_CODE_RE = re.compile(r"^(?:CITY|COU)?([A-Z]+?)(?:COMB|COM|CM)\d{2}$")
_DATE_PREFIX_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

ROUTING_LABELS = {
    "delivery": "Delivery",
    "pickup_staff_load": "Staff-load pickup",
    "pickup_self_load": "Self-load pickup",
}


def recipients_from_env() -> list[str]:
    raw = os.environ.get("WEEKLY_REPORT_TO")
    if raw is None:
        return list(DEFAULT_RECIPIENTS)
    return [e.strip() for e in raw.split(",") if e.strip()]


def excluded_orders_from_env() -> set[str]:
    raw = os.environ.get("WEEKLY_REPORT_EXCLUDE")
    if raw is None:
        return set(DEFAULT_EXCLUDED_ORDERS)
    return {e.strip().upper() for e in raw.split(",") if e.strip()}


def program_start_from_env() -> date:
    raw = os.environ.get("WEEKLY_REPORT_PROGRAM_START")
    if not raw:
        return DEFAULT_PROGRAM_START
    return date.fromisoformat(raw.strip())


def region_from_env() -> str | None:
    """Region filter; None means no filter."""
    raw = os.environ.get("WEEKLY_REPORT_REGION")
    if raw is None:
        return DEFAULT_REGION
    return raw.strip().lower() or None


# ---------------------------------------------------
# Dates
# ---------------------------------------------------
def report_week(today: date) -> tuple[date, date]:
    """Most recent complete Monday-to-Sunday week strictly before `today`."""
    end = today - timedelta(days=today.weekday() + 1)
    return end - timedelta(days=6), end


def parse_order_date(raw) -> date | None:
    """CIMcloud writes '4/16/2026 11:38:23 AM PT'; take the calendar date."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    m = _DATE_PREFIX_RE.search(str(raw))
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _to_pacific_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo("UTC"))
        return value.astimezone(PACIFIC_TZ).date()
    return parse_order_date(value)


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_qty(qty: float) -> str:
    return str(int(qty)) if qty == int(qty) else f"{qty:g}"


# ---------------------------------------------------
# Jurisdiction lookup
# ---------------------------------------------------
def load_jurisdiction_map(bucket_name: str = "agromin-coupon-data") -> dict[str, str]:
    """Coupon code -> jurisdiction name from the coupon master in GCS.

    Returns an empty dict on any failure so the report falls back to the
    abbreviation table rather than failing the send.
    """
    if gcs_storage is None:
        logger.warning("google-cloud-storage not installed; using abbreviation fallback")
        return {}
    try:
        blob = gcs_storage.Client().bucket(bucket_name).blob("coupons.xlsx")
        if not blob.exists():
            return {}
        wb = load_workbook(BytesIO(blob.download_as_bytes()), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows)]
        try:
            code_idx = header.index("Coupon")
            jur_idx = header.index("Jurisdiction")
        except ValueError:
            return {}
        mapping = {}
        for row in rows:
            code = row[code_idx] if code_idx < len(row) else None
            jur = row[jur_idx] if jur_idx < len(row) else None
            if code and jur:
                mapping[str(code).strip().upper()] = str(jur).strip()
        return mapping
    except Exception as e:
        logger.warning("Coupon master unavailable (%s); using abbreviation fallback", e)
        return {}


def jurisdiction_for(code: str, mapping: dict[str, str] | None = None) -> str:
    code = (code or "").strip().upper()
    if mapping and code in mapping:
        return mapping[code]
    m = _CODE_RE.match(code)
    if m and m.group(1) in _ABBREVIATION_FALLBACK:
        return _ABBREVIATION_FALLBACK[m.group(1)]
    return code or "Unknown"


# ---------------------------------------------------
# Order normalization
# ---------------------------------------------------
@dataclass
class ReportOrder:
    order_number: str
    order_date: date
    coupon_code: str
    jurisdiction: str
    routing: str
    region: str
    shipping_method: str
    material: str
    total_qty: float
    bulk_cubic_yards: float | None
    customer_name: str
    customer_email: str
    customer_phone: str
    shipping_address: str
    subtotal: float | None
    coupon_amount: float | None
    tax: float | None
    shipping: float | None
    order_total: float | None
    status: str

    @property
    def routing_label(self) -> str:
        return ROUTING_LABELS.get(self.routing, self.routing or "Unknown")

    @property
    def week_start(self) -> date:
        return self.order_date - timedelta(days=self.order_date.weekday())

    @property
    def month(self) -> tuple[int, int]:
        return (self.order_date.year, self.order_date.month)


def normalize_events(
    docs: list[dict],
    jurisdiction_map: dict[str, str] | None = None,
    excluded: set[str] | None = None,
    region: str | None = "",
) -> list[ReportOrder]:
    """Turn Firestore `order_events` dicts into ReportOrder rows.

    Order date comes from the CIMcloud `order_date` string; when that is
    missing or unparseable the Pacific calendar date of `processed_at` is used.
    Documents with neither are dropped with a warning. `region` keeps only
    documents whose `region` field matches (case-insensitive); pass None for
    no filter. The default sentinel "" resolves from the environment.
    """
    excluded = excluded if excluded is not None else excluded_orders_from_env()
    if region == "":
        region = region_from_env()
    region = region.strip().lower() if region else None
    out = []
    for d in docs:
        number = str(d.get("order_number") or "").strip()
        if not number or number.upper() in excluded:
            continue
        if region and str(d.get("region") or "").strip().lower() != region:
            continue
        order_date = parse_order_date(d.get("order_date")) or _to_pacific_date(
            d.get("processed_at")
        )
        if order_date is None:
            logger.warning("order_events %s has no usable date; skipped", number)
            continue
        code = str(d.get("coupon_code") or "").strip().upper()
        out.append(
            ReportOrder(
                order_number=number,
                order_date=order_date,
                coupon_code=code,
                jurisdiction=jurisdiction_for(code, jurisdiction_map),
                routing=str(d.get("routing") or ""),
                region=str(d.get("region") or ""),
                shipping_method=str(d.get("shipping_method") or ""),
                material=str(d.get("material") or ""),
                total_qty=_num(d.get("total_qty")) or 0.0,
                bulk_cubic_yards=_num(d.get("bulk_cubic_yards")),
                customer_name=str(d.get("customer_name") or ""),
                customer_email=str(d.get("customer_email") or ""),
                customer_phone=str(d.get("customer_phone") or ""),
                shipping_address=str(d.get("shipping_address") or ""),
                subtotal=_num(d.get("subtotal")),
                coupon_amount=_num(d.get("coupon_amount")),
                tax=_num(d.get("tax")),
                shipping=_num(d.get("shipping")),
                order_total=_num(d.get("order_total")),
                status=str(d.get("status") or ""),
            )
        )
    out.sort(key=lambda o: (o.order_date, o.order_number))
    return out


# ---------------------------------------------------
# Aggregation
# ---------------------------------------------------
@dataclass
class Bucket:
    label: str
    orders: int = 0
    cubic_yards: float = 0.0
    delivery: int = 0
    staff_load: int = 0
    self_load: int = 0
    coupon_value: float = 0.0
    jurisdictions: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    first_order: date | None = None
    last_order: date | None = None

    def add(self, o: ReportOrder) -> None:
        self.orders += 1
        self.cubic_yards += o.total_qty
        if o.routing == "delivery":
            self.delivery += 1
        elif o.routing == "pickup_staff_load":
            self.staff_load += 1
        elif o.routing == "pickup_self_load":
            self.self_load += 1
        if o.coupon_amount:
            self.coupon_value += o.coupon_amount
        if o.jurisdiction not in self.jurisdictions:
            self.jurisdictions.append(o.jurisdiction)
        if o.coupon_code and o.coupon_code not in self.codes:
            self.codes.append(o.coupon_code)
        if self.first_order is None or o.order_date < self.first_order:
            self.first_order = o.order_date
        if self.last_order is None or o.order_date > self.last_order:
            self.last_order = o.order_date


@dataclass
class WeeklyReport:
    week_start: date
    week_end: date
    generated_at: datetime
    week: Bucket
    prior_week: Bucket
    weekly: list[Bucket]
    by_jurisdiction: list[Bucket]
    monthly: list[Bucket]
    by_material: list[Bucket]
    by_yard: list[Bucket]
    to_date: Bucket
    pre_launch: Bucket
    program_start: date
    week_orders: list[ReportOrder]
    all_orders: list[ReportOrder]
    financials_available: bool
    first_order_date: date | None
    jurisdiction_source: str


def _week_label(start: date) -> str:
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f"{start:%b} {start.day} to {end.day}"
    return f"{start:%b} {start.day} to {end:%b} {end.day}"


def _month_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%B %Y")


def build_report(
    orders: list[ReportOrder],
    week_start: date,
    week_end: date,
    generated_at: datetime | None = None,
    weeks_back: int = WEEKS_BACK,
    jurisdiction_source: str = "coupon master",
    program_start: date | None = None,
) -> WeeklyReport:
    generated_at = generated_at or datetime.now(PACIFIC_TZ)
    program_start = program_start or program_start_from_env()
    orders = [o for o in orders if o.order_date <= week_end]

    # Everything before launch collapses into one bucket for the monthly table.
    pre_launch = Bucket(f"Pre-launch (before {program_start:%b %-d})")
    for o in orders:
        if o.order_date < program_start:
            pre_launch.add(o)
    orders = [o for o in orders if o.order_date >= program_start]

    week_orders = [o for o in orders if week_start <= o.order_date <= week_end]
    week = Bucket(_week_label(week_start))
    for o in week_orders:
        week.add(o)

    prior_start = week_start - timedelta(days=7)
    prior = Bucket(_week_label(prior_start))
    for o in orders:
        if prior_start <= o.order_date < week_start:
            prior.add(o)

    launch_week = program_start - timedelta(days=program_start.weekday())
    weekly = []
    for i in range(weeks_back - 1, -1, -1):
        ws = week_start - timedelta(days=7 * i)
        if ws < launch_week:
            continue
        b = Bucket(_week_label(ws))
        for o in orders:
            if o.week_start == ws:
                b.add(o)
        weekly.append(b)

    by_jur: dict[str, Bucket] = {}
    for o in orders:
        by_jur.setdefault(o.jurisdiction, Bucket(o.jurisdiction)).add(o)
    by_jurisdiction = sorted(by_jur.values(), key=lambda b: (-b.orders, -b.cubic_yards, b.label))

    monthly: list[Bucket] = []
    if program_start <= week_end:
        y, m = program_start.year, program_start.month
        end_y, end_m = week_end.year, week_end.month
        while (y, m) <= (end_y, end_m):
            b = Bucket(_month_label(y, m))
            for o in orders:
                if o.month == (y, m):
                    b.add(o)
            monthly.append(b)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    by_mat: dict[str, Bucket] = defaultdict(lambda: Bucket(""))
    for o in orders:
        label = _material_group(o.material)
        by_mat[label].label = label
        by_mat[label].add(o)
    by_material = sorted(by_mat.values(), key=lambda b: (-b.cubic_yards, b.label))

    by_yard_map: dict[str, Bucket] = {}
    for o in orders:
        label = o.shipping_method or "Unknown"
        by_yard_map.setdefault(label, Bucket(label)).add(o)
    by_yard = sorted(by_yard_map.values(), key=lambda b: (-b.orders, b.label))

    to_date = Bucket("Program to date")
    for o in orders:
        to_date.add(o)

    return WeeklyReport(
        week_start=week_start,
        week_end=week_end,
        generated_at=generated_at,
        week=week,
        prior_week=prior,
        weekly=weekly,
        by_jurisdiction=by_jurisdiction,
        monthly=monthly,
        by_material=by_material,
        by_yard=by_yard,
        to_date=to_date,
        pre_launch=pre_launch,
        program_start=program_start,
        week_orders=week_orders,
        all_orders=orders,
        financials_available=any(o.coupon_amount for o in orders),
        first_order_date=orders[0].order_date if orders else None,
        jurisdiction_source=jurisdiction_source,
    )


def _material_group(description: str) -> str:
    d = (description or "").lower()
    if "mulch" in d:
        return "Cover mulch"
    if "compost" in d:
        return "Compost"
    if "bag" in d or "pallet" in d:
        return "Bagged"
    return description or "Unknown"


# ---------------------------------------------------
# Rendering: subject, HTML, text
# ---------------------------------------------------
def _range_label(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start:%B} {start.day} to {end.day}, {end.year}"
    return f"{start:%B} {start.day} to {end:%B} {end.day}, {end.year}"


def subject_line(r: WeeklyReport) -> str:
    return (
        f"{PROGRAM_NAME} Coupon Activity, Week of {_range_label(r.week_start, r.week_end)}: "
        f"{r.week.orders} order{'s' if r.week.orders != 1 else ''}, "
        f"{format_qty(r.week.cubic_yards)} CY; "
        f"{r.to_date.orders} orders / {format_qty(r.to_date.cubic_yards)} CY to date"
    )


def _summary_sentences(r: WeeklyReport) -> list[str]:
    w, p, t = r.week, r.prior_week, r.to_date
    if w.orders == 0:
        first = f"No coupon orders were recorded for {_range_label(r.week_start, r.week_end)}."
    else:
        parts = []
        if w.self_load:
            parts.append(f"{w.self_load} self-load")
        if w.staff_load:
            parts.append(f"{w.staff_load} staff-load")
        if w.delivery:
            parts.append(f"{w.delivery} delivery")
        mix = ", ".join(parts)
        cities = ", ".join(w.jurisdictions)
        first = (
            f"{w.orders} coupon order{'s' if w.orders != 1 else ''} for "
            f"{format_qty(w.cubic_yards)} cubic yards came through in the week of "
            f"{_range_label(r.week_start, r.week_end)} ({mix}), from {cities}."
        )
    if p.orders == w.orders:
        delta = "flat against"
    elif w.orders > p.orders:
        delta = f"up from {p.orders} order{'s' if p.orders != 1 else ''} and {format_qty(p.cubic_yards)} CY in"
    else:
        delta = f"down from {p.orders} order{'s' if p.orders != 1 else ''} and {format_qty(p.cubic_yards)} CY in"
    second = f"That is {delta} the prior week."
    third = (
        f"Program to date (launched {r.program_start:%B %-d, %Y}): {t.orders} orders and "
        f"{format_qty(t.cubic_yards)} cubic yards; "
        f"{t.self_load} self-load, {t.staff_load} staff-load, {t.delivery} delivery; "
        f"{len(r.by_jurisdiction)} jurisdiction{'s' if len(r.by_jurisdiction) != 1 else ''} active."
    )
    return [first, second, third]


_FONT = "font-family:Aptos,Calibri,'Segoe UI',Arial,sans-serif;"
_TD = f"{_FONT}font-size:10.5pt;color:#1a1a1a;padding:5px 8px;border-bottom:1px solid #e3e3e3;"
_TH = (
    f"{_FONT}font-size:10.5pt;color:#ffffff;background:#2e5e3a;padding:6px 8px;"
    "text-align:left;font-weight:bold;"
)
_P = f"{_FONT}font-size:11pt;line-height:1.45;color:#1a1a1a;margin:0 0 10px 0;"
_H = f"{_FONT}font-size:13pt;color:#2e5e3a;margin:22px 0 8px 0;font-weight:bold;"


def _table(
    headers: list[str], rows: list[list], numeric: set[int], total: list | None = None
) -> str:
    def cell(v, i, tag="td", style=_TD, bold=False):
        align = "text-align:right;" if i in numeric else ""
        weight = "font-weight:bold;" if bold else ""
        # Labels and numbers stay on one line; only free-text columns wrap.
        nowrap = "white-space:nowrap;" if (i == 0 or i in numeric) else ""
        return f'<{tag} style="{style}{align}{weight}{nowrap}">{html.escape(str(v))}</{tag}>'

    out = [
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'width="100%" style="border-collapse:collapse;margin:0 0 6px 0;">'
    ]
    out.append("<tr>" + "".join(cell(h, i, "th", _TH) for i, h in enumerate(headers)) + "</tr>")
    for r_i, row in enumerate(rows):
        bg = "background:#f6f8f6;" if r_i % 2 else ""
        out.append(
            "<tr>" + "".join(cell(v, i, style=_TD + bg) for i, v in enumerate(row)) + "</tr>"
        )
    if total:
        out.append(
            "<tr>"
            + "".join(
                cell(v, i, style=_TD + "border-top:2px solid #2e5e3a;", bold=True)
                for i, v in enumerate(total)
            )
            + "</tr>"
        )
    out.append("</table>")
    return "".join(out)


def _weekly_rows(r: WeeklyReport) -> tuple[list[str], list[list], set[int]]:
    headers = [
        "Week (Mon to Sun)",
        "Orders",
        "CY",
        "Self-load",
        "Staff-load",
        "Delivery",
        "Jurisdictions",
    ]
    rows = [
        [
            b.label,
            b.orders,
            format_qty(b.cubic_yards),
            b.self_load,
            b.staff_load,
            b.delivery,
            ", ".join(b.jurisdictions),
        ]
        for b in r.weekly
    ]
    return headers, rows, {1, 2, 3, 4, 5}


def _jurisdiction_rows(r: WeeklyReport) -> tuple[list[str], list[list], set[int], list]:
    headers = ["Jurisdiction", "Codes used", "Orders", "CY", "First order", "Last order"]
    if r.financials_available:
        headers.insert(4, "Coupon value")
    rows = []
    for b in r.by_jurisdiction:
        row = [
            b.label,
            ", ".join(b.codes),
            b.orders,
            format_qty(b.cubic_yards),
            f"{b.first_order:%b %-d}" if b.first_order else "",
            f"{b.last_order:%b %-d}" if b.last_order else "",
        ]
        if r.financials_available:
            row.insert(4, f"${b.coupon_value:,.2f}")
        rows.append(row)
    t = r.to_date
    total = [
        "Total",
        f"{len(t.codes)} codes",
        t.orders,
        format_qty(t.cubic_yards),
        f"{t.first_order:%b %-d}" if t.first_order else "",
        f"{t.last_order:%b %-d}" if t.last_order else "",
    ]
    numeric = {2, 3}
    if r.financials_available:
        total.insert(4, f"${t.coupon_value:,.2f}")
        numeric = {2, 3, 4}
    return headers, rows, numeric, total


def _monthly_rows(r: WeeklyReport) -> tuple[list[str], list[list], set[int], list]:
    headers = ["Month", "Orders", "CY", "Self-load", "Staff-load", "Delivery"]
    rows = []
    if r.pre_launch.orders:
        p = r.pre_launch
        rows.append(
            [p.label, p.orders, format_qty(p.cubic_yards), p.self_load, p.staff_load, p.delivery]
        )
    for b in r.monthly:
        label = b.label
        if (r.week_end.year, r.week_end.month) == _month_key(b.label) and r.week_end.day < 28:
            label = f"{b.label} (to {r.week_end.day})"
        rows.append(
            [label, b.orders, format_qty(b.cubic_yards), b.self_load, b.staff_load, b.delivery]
        )
    t = r.to_date
    total = [
        "Program to date",
        t.orders,
        format_qty(t.cubic_yards),
        t.self_load,
        t.staff_load,
        t.delivery,
    ]
    return headers, rows, {1, 2, 3, 4, 5}, total


def _month_key(label: str) -> tuple[int, int]:
    d = datetime.strptime(label, "%B %Y")
    return (d.year, d.month)


def render_html(r: WeeklyReport) -> str:
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width"><title>{PROGRAM_NAME} Coupon Activity</title></head>'
        '<body style="margin:0;padding:0;background:#ffffff;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">'
        '<tr><td align="center" style="padding:16px 8px;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="680" '
        'style="max-width:680px;width:100%;">'
        '<tr><td style="padding:0 8px;">'
    ]
    parts.append(
        f'<p style="{_FONT}font-size:15pt;font-weight:bold;color:#2e5e3a;margin:0 0 4px 0;">'
        f"{PROGRAM_NAME} Coupon Program Activity</p>"
        f'<p style="{_FONT}font-size:10pt;color:#666;margin:0 0 14px 0;">'
        f"Week of {html.escape(_range_label(r.week_start, r.week_end))} &middot; "
        f"generated {r.generated_at:%A, %B %-d, %Y %-I:%M %p} PT</p>"
    )
    for s in _summary_sentences(r):
        parts.append(f'<p style="{_P}">{html.escape(s)}</p>')

    if r.week_orders:
        parts.append(f'<p style="{_H}">This week&rsquo;s orders</p>')
        rows = [
            [
                o.order_number,
                f"{o.order_date:%a %b %-d}",
                o.jurisdiction,
                _material_group(o.material),
                format_qty(o.total_qty),
                o.routing_label,
                o.shipping_method.replace(" Landfill Pick Up", "").replace(" Pick Up", ""),
            ]
            for o in r.week_orders
        ]
        parts.append(
            _table(
                ["Order", "Date", "Jurisdiction", "Material", "CY", "Routing", "Site"], rows, {4}
            )
        )

    parts.append(f'<p style="{_H}">Last {len(r.weekly)} weeks</p>')
    h, rows, num = _weekly_rows(r)
    parts.append(_table(h, rows, num))

    parts.append(f'<p style="{_H}">Program to date by jurisdiction</p>')
    h, rows, num, total = _jurisdiction_rows(r)
    parts.append(_table(h, rows, num, total))

    parts.append(f'<p style="{_H}">Monthly</p>')
    h, rows, num, total = _monthly_rows(r)
    parts.append(_table(h, rows, num, total))

    if r.by_material or r.by_yard:
        parts.append(f'<p style="{_H}">Material and site, program to date</p>')
        rows = [[b.label, b.orders, format_qty(b.cubic_yards)] for b in r.by_material]
        parts.append(_table(["Material", "Orders", "CY"], rows, {1, 2}))
        rows = [[b.label, b.orders, format_qty(b.cubic_yards)] for b in r.by_yard]
        parts.append(_table(["Pickup site / method", "Orders", "CY"], rows, {1, 2}))

    parts.append(
        f'<p style="{_FONT}font-size:9pt;color:#888;margin:18px 0 0 0;">'
        "Sent by coupon-dispatch (Cloud Run, juris-coupon-valid). Reply to rickwilson@agromin.com "
        "with corrections.</p>"
    )
    parts.append("</td></tr></table></td></tr></table></body></html>")
    return "".join(parts)


def _text_table(headers: list[str], rows: list[list], total: list | None = None) -> str:
    all_rows = (
        [headers]
        + [[str(c) for c in r] for r in rows]
        + ([[str(c) for c in total]] if total else [])
    )
    widths = [max(len(r[i]) for r in all_rows) for i in range(len(headers))]
    lines = []
    for idx, r in enumerate(all_rows):
        lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip())
        if idx == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def render_text(r: WeeklyReport) -> str:
    out = [
        f"{PROGRAM_NAME} COUPON PROGRAM ACTIVITY",
        f"Week of {_range_label(r.week_start, r.week_end)}; generated "
        f"{r.generated_at:%A, %B %-d, %Y %-I:%M %p} PT",
        "",
        *_summary_sentences(r),
        "",
    ]
    if r.week_orders:
        out += ["THIS WEEK'S ORDERS", ""]
        rows = [
            [
                o.order_number,
                f"{o.order_date:%a %b %-d}",
                o.jurisdiction,
                _material_group(o.material),
                format_qty(o.total_qty),
                o.routing_label,
                o.shipping_method,
            ]
            for o in r.week_orders
        ]
        out += [
            _text_table(
                ["Order", "Date", "Jurisdiction", "Material", "CY", "Routing", "Site"], rows
            ),
            "",
        ]
    h, rows, _ = _weekly_rows(r)
    out += [f"LAST {len(r.weekly)} WEEKS", "", _text_table(h, rows), ""]
    h, rows, _, total = _jurisdiction_rows(r)
    out += ["PROGRAM TO DATE BY JURISDICTION", "", _text_table(h, rows, total), ""]
    h, rows, _, total = _monthly_rows(r)
    out += ["MONTHLY", "", _text_table(h, rows, total)]
    return "\n".join(out)


# ---------------------------------------------------
# Excel attachment
# ---------------------------------------------------
_APTOS = Font(name="Aptos", size=11)
_APTOS_BOLD = Font(name="Aptos", size=11, bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="2E5E3A")

_ORDER_COLUMNS = [
    ("Order", lambda o: o.order_number),
    ("Order date", lambda o: o.order_date),
    ("Week starting", lambda o: o.week_start),
    ("Coupon code", lambda o: o.coupon_code),
    ("Jurisdiction", lambda o: o.jurisdiction),
    ("Region", lambda o: o.region),
    ("Material", lambda o: o.material),
    ("Material group", lambda o: _material_group(o.material)),
    ("Quantity (CY)", lambda o: o.total_qty),
    ("Bulk CY", lambda o: o.bulk_cubic_yards),
    ("Routing", lambda o: o.routing_label),
    ("Shipping method", lambda o: o.shipping_method),
    ("Customer", lambda o: o.customer_name),
    ("Email", lambda o: o.customer_email),
    ("Phone", lambda o: o.customer_phone),
    ("Shipping address", lambda o: o.shipping_address),
    ("Subtotal", lambda o: o.subtotal),
    ("Coupon amount", lambda o: o.coupon_amount),
    ("Tax", lambda o: o.tax),
    ("Shipping", lambda o: o.shipping),
    ("Order total", lambda o: o.order_total),
    ("Status", lambda o: o.status),
]


def _write_sheet(ws, headers: list[str], rows: list[list], total: list | None = None) -> None:
    ws.append(headers)
    for c in ws[1]:
        c.font = _APTOS_BOLD
        c.fill = _HEADER_FILL
        c.alignment = Alignment(vertical="center")
    for row in rows:
        ws.append(row)
    if total:
        ws.append(total)
        for c in ws[ws.max_row]:
            c.font = Font(name="Aptos", size=11, bold=True)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row if not total else ws.max_row - 1):
        for c in row:
            c.font = _APTOS
            if isinstance(c.value, date):
                c.number_format = "yyyy-mm-dd"
    for i, h in enumerate(headers, start=1):
        width = max(
            [len(str(h))] + [len(str(r[i - 1])) for r in rows if r[i - 1] is not None] + [8]
        )
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 48)
    ws.freeze_panes = "A2"


def build_xlsx(r: WeeklyReport) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Week orders"
    headers = [h for h, _ in _ORDER_COLUMNS]
    _write_sheet(ws, headers, [[f(o) for _, f in _ORDER_COLUMNS] for o in r.week_orders])

    ws = wb.create_sheet("All orders")
    _write_sheet(ws, headers, [[f(o) for _, f in _ORDER_COLUMNS] for o in r.all_orders])

    ws = wb.create_sheet("Weekly")
    weekly_rows = [
        [
            b.label,
            b.orders,
            b.cubic_yards,
            b.self_load,
            b.staff_load,
            b.delivery,
            ", ".join(b.jurisdictions),
        ]
        for b in r.weekly
    ]
    _write_sheet(
        ws,
        [
            "Week (Mon to Sun)",
            "Orders",
            "CY",
            "Self-load",
            "Staff-load",
            "Delivery",
            "Jurisdictions",
        ],
        weekly_rows,
    )

    ws = wb.create_sheet("By jurisdiction")
    jur_rows = [
        [
            b.label,
            ", ".join(b.codes),
            b.orders,
            b.cubic_yards,
            b.coupon_value or None,
            b.first_order,
            b.last_order,
        ]
        for b in r.by_jurisdiction
    ]
    t = r.to_date
    _write_sheet(
        ws,
        ["Jurisdiction", "Codes used", "Orders", "CY", "Coupon value", "First order", "Last order"],
        jur_rows,
        [
            "Total",
            f"{len(t.codes)} codes",
            t.orders,
            t.cubic_yards,
            t.coupon_value or None,
            t.first_order,
            t.last_order,
        ],
    )

    ws = wb.create_sheet("Monthly")
    month_rows = [
        [b.label, b.orders, b.cubic_yards, b.self_load, b.staff_load, b.delivery] for b in r.monthly
    ]
    _write_sheet(
        ws,
        ["Month", "Orders", "CY", "Self-load", "Staff-load", "Delivery"],
        month_rows,
        ["Program to date", t.orders, t.cubic_yards, t.self_load, t.staff_load, t.delivery],
    )

    ws = wb.create_sheet("Material and site")
    rows = [["Material", b.label, b.orders, b.cubic_yards] for b in r.by_material]
    rows += [["Site / method", b.label, b.orders, b.cubic_yards] for b in r.by_yard]
    _write_sheet(ws, ["Dimension", "Value", "Orders", "CY"], rows)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def attachment_filename(r: WeeklyReport) -> str:
    return f"Coupon_Activity_{r.week_start:%Y-%m-%d}_to_{r.week_end:%Y-%m-%d}.xlsx"
