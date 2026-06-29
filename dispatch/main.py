"""
Agromin Order Dispatch Service
==============================
Standalone FastAPI service that handles post-checkout order dispatch:
  POST /api/ingest-order      — route + email customer + alert coordinator
  POST /api/generate-manifest — produce a delivery PDF manifest
  GET  /api/delivery-schedule — return last 7 days of delivery orders

Coupon validation happens upstream in the coupon-validator service at
checkout. This service trusts that any order it receives via Power
Automate is already a confirmed program order.
"""

import logging
import os
import quopri
import re
import time
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Optional
from zoneinfo import ZoneInfo

import msal
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from google.cloud import firestore as firestore_client
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Agromin Order Dispatch", version="1.0.0")

# ---------------------------------------------------
# CONFIGURATION (env vars)
# ---------------------------------------------------
DISPATCH_API_KEY = os.environ.get("DISPATCH_API_KEY", "change-this-secret-key")

GRAPH_TENANT_ID = os.environ.get("GRAPH_TENANT_ID")
GRAPH_CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID")
GRAPH_CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET")
MAIL_SENDER = os.environ.get("MAIL_SENDER", "dispatch@agromin.com")

OFELIA_EMAIL = os.environ.get("OFELIA_EMAIL")
GREG_EMAIL = os.environ.get("GREG_EMAIL", "greg@agromin.com")
BRIAN_EMAIL = os.environ.get("BRIAN_EMAIL", "brian@agromin.com")
KENDALL_EMAIL = os.environ.get("KENDALL_EMAIL", "kendall@agromin.com")
CHRIS_EMAIL = os.environ.get("CHRIS_EMAIL", "chris@agromin.com")
ROSA_EMAIL = os.environ.get("ROSA_EMAIL", "rosa@agromin.com")


# ---------------------------------------------------
# YARD LOCATIONS
# Matching uses case-insensitive substring search on match_keys.
# ---------------------------------------------------
YARD_LOCATIONS = {
    "Frank R. Bowerman": {
        "match_keys": ["bowerman"],
        "address": "11002 Bee Canyon Access Rd, Irvine, CA 92602",
        "phone": "(949) 551-7100",
        "hours": "Mon–Sat 8am–4pm",
        "qr_url": "https://forms.office.com/r/Ywy7m8jcwv",
        "qr_deployed": False,
        "region": "oc",
    },
    "Prima Deshecha": {
        "match_keys": ["deshecha"],
        "address": "32250 Avenida La Pata, San Juan Capistrano, CA 92675",
        "phone": "(949) 728-3040",
        "hours": "Mon–Sat 8am–4pm",
        "qr_url": "https://forms.office.com/r/2CsTHP7TjB",
        "qr_deployed": False,
        "region": "oc",
    },
    "Olinda Alpha": {
        "match_keys": ["olinda"],
        "address": "1942 Valencia Avenue, Brea, CA 92823",
        "phone": "(714) 993-7396",
        "hours": "Mon–Sat 7am–3pm",
        "qr_url": "https://forms.office.com/r/9LWPGvf52e",
        "qr_deployed": False,
        "region": "oc",
    },
    "Aqua-Flo Ojai": {
        "match_keys": ["ojai"],
        "address": "1940 E Ojai Ave, Ojai, CA 93023",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm | Sat 7am–12pm",
        "qr_url": None,
        "qr_deployed": False,
        "region": "ventura",
    },
    "Aqua-Flo Ventura": {
        "match_keys": ["aqua-flo ventura", "portola"],
        "address": "2471 Portola Rd #300, Ventura, CA 93003",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm | Sat 7am–12pm",
        "qr_url": None,
        "qr_deployed": False,
        "region": "ventura",
    },
    "Agromin Kinetic": {
        "match_keys": ["kinetic"],
        "address": "201 Kinetic Drive, Oxnard, CA 93030",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm | Sat 7am–12pm",
        "qr_url": None,
        "qr_deployed": False,
        "region": "ventura",
    },
}


def get_yard_for_order(shipping_method: str) -> dict:
    """Match shipping_method to yard config via case-insensitive substring on match_keys."""
    sm_lower = shipping_method.lower()
    for yard_name, yard_info in YARD_LOCATIONS.items():
        for key in yard_info.get("match_keys", []):
            if key.lower() in sm_lower:
                return {"name": yard_name, **{k: v for k, v in yard_info.items() if k != "match_keys"}}
    return {
        "name": "Agromin",
        "address": "Contact sales@agromin.com",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm",
        "qr_url": None,
        "qr_deployed": False,
        "region": "unknown",
    }


def infer_region_from_address(address: str) -> str:
    """Determine which delivery coordinator handles this delivery from the shipping address."""
    a = address.lower()
    if re.search(r"\bsacramento\b", a):
        return "sacramento"
    ventura_cities = ["ventura", "oxnard", "camarillo", "fillmore", "ojai", "santa paula", "port hueneme"]
    if any(re.search(rf"\b{c}\b", a) for c in ventura_cities):
        return "ventura"
    return "oc"


def get_delivery_coordinator_emails(region: str) -> list:
    if region == "sacramento":
        return [e for e in [ROSA_EMAIL] if e]
    if region == "ventura":
        return [e for e in [CHRIS_EMAIL] if e]
    return [e for e in [GREG_EMAIL, BRIAN_EMAIL, KENDALL_EMAIL] if e]


def format_qty(qty: float) -> str:
    return str(int(qty)) if qty == int(qty) else str(qty)


# ---------------------------------------------------
# MASTER SHEET FIELD MAPPING (Stage A — Phase 1)
# Builds row dicts for Greg's `OCWR-Agromin Deliveries.xlsx` -> `Master Sheet`
# (Excel Table `Table1`, range A1:W173, append at row 174).
# Power Automate's "Add a row to a table" action binds by column name, so the
# dict keys MUST match the live header strings exactly — including the embedded
# newline characters Greg uses in his column headers for cell wrap.
# ---------------------------------------------------
_PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

MASTER_SHEET_HEADERS = {
    "customer": "Customer",
    "status": "STATUS",
    "date_of_request": "Date of \nRequest",
    "scheduled_delivery_date": "Scheduled\nDelivery Date",
    "sales_order": "Sales Order#",
    "phone": "Phone #",
    "email": "Email",
    "delivery_address": "Delivery Address",
    "city": "City",
    "state": "State",
    "zip_code": "Zip\nCode",
    "origin_greenery": "Origin\n(Greenery Name)",
    "origin_landfill": "Origin\n(Landfill Name)",
    "material": "Material",
    "compost_qty": "Compost\n(Quantity)",
    "mulch_qty": "Mulch\n(Quantity)",
    "bags_qty": "Bags\n(# of Pallets)",
    "compost_total": "Compost\nTotal $",
    "mulch_total": "Mulch\nTotal $",
    "bags_total": "Bags\nTotal $",
    "delivery_fee": "Delivery\nFee",
    "total_no_tax": "Total\n(No Tax)",
    "notes": "Notes",
}

_STATE_ZIP_RE = re.compile(r"\b([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\b")


def parse_us_address(addr: str) -> dict:
    """Parse a comma-separated US address into street/city/state/zip components.

    Handles addresses such as:
        '20 Cielo Cresta, Mission Viejo, CA 92692'
        'Aseem Mujtaba, 20 Cielo Cresta, Mission Viejo, CA 92692, USA'

    Missing components return as empty strings. Tolerant of trailing 'USA' and
    a leading customer-name line in the comma-joined input.
    """
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    out = {"street": "", "city": "", "state": "", "zip": ""}
    if not parts:
        return out

    street_idx = next(
        (i for i, p in enumerate(parts) if re.match(r"^\d", p)),
        -1,
    )
    if street_idx >= 0:
        out["street"] = parts[street_idx]

    sz_idx = -1
    for i in range(len(parts) - 1, -1, -1):
        m = _STATE_ZIP_RE.search(parts[i])
        if m:
            out["state"] = m.group(1)
            out["zip"] = m.group(2)
            sz_idx = i
            break

    if sz_idx > 0 and sz_idx - 1 != street_idx:
        out["city"] = parts[sz_idx - 1]

    return out


def classify_material(description: str) -> str:
    """Map a CIMcloud line item description to a Master Sheet material category.

    Returns 'Compost', 'Mulch', 'Bags', or '' if the description doesn't match
    a known program material.
    """
    d = (description or "").lower()
    if "compost" in d:
        return "Compost"
    if "mulch" in d:
        return "Mulch"
    if "bag" in d or "pallet" in d:
        return "Bags"
    return ""


def strip_a_prefix(order_number: str):
    """Convert CIMcloud 'A109591' to Greg's integer 109591.

    Returns int if the stripped value is numeric, otherwise the original string
    unchanged (defensive: never blows up on unexpected formats).
    """
    cleaned = re.sub(r"^A", "", (order_number or "").strip())
    try:
        return int(cleaned)
    except ValueError:
        return order_number


def build_master_sheet_rows(order: "OrderPayload", routing: str) -> list:
    """Build one Master Sheet row per line item for delivery orders only.

    Greg's Master Sheet tracks deliveries; pickups go elsewhere (TBD with Brian).
    Pickup orders return []. Multi-material delivery orders return one row per
    line item, matching Greg's existing convention (verified against order
    #143163 in the live workbook).

    Origin (Greenery + Landfill) columns are intentionally left blank — Greg
    assigns the yard by geographic proximity, which we don't have a lookup for
    yet. The Notes column flags this for him.
    """
    if routing != "delivery":
        return []

    addr = parse_us_address(order.shipping_address)
    sales_order = strip_a_prefix(order.order_number)
    today = datetime.now(timezone.utc).astimezone(_PACIFIC_TZ).date()
    today_short = f"{today.month}/{today.day}/{today.year % 100:02d}"
    note = (
        f"Auto-imported {today_short}. Origin TBD — Greg to assign yard."
    )

    # Delivery fee is charged once per order, not per line item. Prefer the
    # parsed Shipping total; fall back to a dollar amount embedded in the
    # shipping_method string (e.g. "$135 Delivery - Minimum 3 Cubic Yards").
    delivery_fee = order.shipping
    if not delivery_fee:
        fee_match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", order.shipping_method or "")
        if fee_match:
            delivery_fee = float(fee_match.group(1).replace(",", ""))

    # Pre-tax order value: material subtotal plus delivery fee. Prefer parsed
    # subtotal; fall back to summing line items.
    material_subtotal = order.subtotal or sum(
        item.qty * item.unit_price for item in order.line_items
    )
    total_no_tax = round(material_subtotal + delivery_fee, 2)

    # Attach the per-order delivery fee and pre-tax total to the first emitted
    # row only, so a multi-material order doesn't double-count them.
    H = MASTER_SHEET_HEADERS
    rows: list = []
    first_row = True
    for item in order.line_items:
        material = classify_material(item.description)
        if not material:
            continue

        line_total = round(item.qty * item.unit_price, 2)

        rows.append({
            H["customer"]: order.customer_name,
            H["status"]: "In Process",
            H["date_of_request"]: today.isoformat(),
            H["scheduled_delivery_date"]: "",
            H["sales_order"]: sales_order,
            H["phone"]: order.customer_phone,
            H["email"]: order.customer_email,
            H["delivery_address"]: addr["street"],
            H["city"]: addr["city"],
            H["state"]: addr["state"],
            H["zip_code"]: addr["zip"],
            H["origin_greenery"]: "",
            H["origin_landfill"]: "",
            H["material"]: material,
            H["compost_qty"]: item.qty if material == "Compost" else "",
            H["mulch_qty"]: item.qty if material == "Mulch" else "",
            H["bags_qty"]: item.qty if material == "Bags" else "",
            H["compost_total"]: line_total if material == "Compost" else "",
            H["mulch_total"]: line_total if material == "Mulch" else "",
            H["bags_total"]: line_total if material == "Bags" else "",
            H["delivery_fee"]: delivery_fee if first_row else "",
            H["total_no_tax"]: total_no_tax if first_row else "",
            H["notes"]: note,
        })
        first_row = False

    return rows


# ---------------------------------------------------
# FIRESTORE
# ---------------------------------------------------
_firestore_db = None


def get_firestore():
    global _firestore_db
    if _firestore_db is None:
        _firestore_db = firestore_client.Client()
    return _firestore_db


# ---------------------------------------------------
# EMAIL — Microsoft Graph API (sends as MAIL_SENDER mailbox)
# ---------------------------------------------------
_msal_app = None
_token_cache = {"token": None, "expires_at": 0.0}


def _get_graph_token() -> str:
    """Acquire a Graph access token via client-credentials flow. Cached until 60s before expiry."""
    global _msal_app

    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            GRAPH_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}",
            client_credential=GRAPH_CLIENT_SECRET,
        )

    result = _msal_app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )

    if "access_token" not in result:
        raise RuntimeError(
            f"Graph token acquisition failed: {result.get('error')} — "
            f"{result.get('error_description')}"
        )

    _token_cache["token"] = result["access_token"]
    _token_cache["expires_at"] = now + int(result.get("expires_in", 3600))
    return _token_cache["token"]


def send_email(to: str, subject: str, body: str, cc: list = None):
    """Send a plain-text email via Microsoft Graph as MAIL_SENDER (dispatch@agromin.com).

    Silently logs and returns if Graph credentials are not configured (useful for local dev).
    """
    if not (GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET):
        logger.warning("Graph credentials not configured — email skipped (to=%s)", to)
        return

    try:
        token = _get_graph_token()

        message = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
        if cc:
            message["ccRecipients"] = [
                {"emailAddress": {"address": c}} for c in cc
            ]

        url = f"https://graph.microsoft.com/v1.0/users/{MAIL_SENDER}/sendMail"
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"message": message, "saveToSentItems": True},
            timeout=15,
        )

        if resp.status_code in (200, 202):
            logger.info("Email sent to %s subject: %s", to, subject)
        else:
            logger.error(
                "Graph sendMail failed (status=%s) for to=%s: %s",
                resp.status_code, to, resp.text,
            )
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to, e)


SB1383_PARAGRAPH = (
    "IMPORTANT — When you arrive: Look for the QR code sign near the material pickup area. "
    "Scanning it takes less than a minute and helps OCWR stay in compliance with "
    "California's SB 1383 organics diversion law. Thank you for participating."
)

PICKUP_SELF_LOAD_TEMPLATE = """\
Hello {customer_name},

Your order for {qty} cubic yards of {material} is ready for self-loading pickup.

PICKUP INSTRUCTIONS:
- Use the 5-gallon buckets provided at the site for measurement
- Bring this email confirmation AND proof of address within the county
  (valid photo ID or utility bill)
- Available during site hours: {yard_hours}

Location: {yard_name}
{yard_address}
{yard_phone}

Order #: {order_number}

{sb1383_note}
Questions? Email sales@agromin.com or call (805) 485-9200.

Thank you,
Agromin"""

PICKUP_STAFF_LOAD_TEMPLATE = """\
Hello {customer_name},

Your order for {qty} cubic yards of {material} is ready for pickup.
OCWR staff will load your vehicle using heavy equipment.

PICKUP INSTRUCTIONS:
- YOU MUST BRING A TRUCK OR TRAILER — cars and minivans cannot be loaded
- Trailers must have solid sides/floor or customer must provide tarps
- Bring this email confirmation AND proof of address within the county
  (valid photo ID or utility bill)
- Available during site hours: {yard_hours}

Location: {yard_name}
{yard_address}
{yard_phone}

Order #: {order_number}

Questions? Email sales@agromin.com or call (805) 485-9200.

Thank you,
Agromin"""

DELIVERY_TEMPLATE = """\
Hello {customer_name},

Thank you for your order. An Agromin representative will contact you within
1 business day to schedule your delivery.

Order #: {order_number}
Material: {qty} cubic yards of {material}
Delivery Address: {shipping_address}

Please note: delivery fees apply separately and will be collected at time of delivery.

Questions? Email sales@agromin.com or call (805) 485-9200.

Thank you,
Agromin"""

DELIVERY_ALERT_TEMPLATE = """\
New delivery order received — action required.

Order #:          {order_number}
Date:             {order_date}
Customer:         {customer_name}
Phone:            {customer_phone}
Email:            {customer_email}
Delivery Address: {shipping_address}
Material:         {qty} cubic yards of {material}
Coupon Code:      {coupon_code}
Order Comments:   {order_comments}

Please contact the customer within 1 business day to schedule delivery."""


# ---------------------------------------------------
# PYDANTIC MODELS
# ---------------------------------------------------
class LineItem(BaseModel):
    sku: str
    description: str
    qty: float
    unit_price: float


class OrderPayload(BaseModel):
    order_number: str
    order_date: str
    coupon_code: str
    payment_method: str
    customer_name: str
    customer_email: str
    customer_phone: str = ""
    billing_address: str
    shipping_address: str
    shipping_method: str
    line_items: list[LineItem]
    order_comments: str = ""
    subtotal: float = 0.0
    tax: float = 0.0
    shipping: float = 0.0
    coupon_amount: float = 0.0
    order_total: float = 0.0


class RawCimcloudEmail(BaseModel):
    """Raw CIMcloud 'Pending Approval' email body, posted by Power Automate.

    Power Automate forwards the email body as HTML; we accept either decoded
    HTML or quoted-printable bytes (the parser auto-detects).
    """
    body: str
    subject: Optional[str] = None


# ---------------------------------------------------
# CIMCLOUD EMAIL PARSER
# Extracts an OrderPayload from a "Pending Approval for Order Number XXXXX"
# email sent by sales@agromin.com (CIMcloud).
# ---------------------------------------------------
class CimcloudParseError(ValueError):
    """Raised when an email cannot be parsed as a CIMcloud program order."""


def _maybe_decode_quoted_printable(body: str) -> str:
    if re.search(r"=\r?\n", body) or "=3D" in body or "=3d" in body:
        try:
            return quopri.decodestring(body.encode("latin-1")).decode(
                "utf-8", errors="replace"
            )
        except Exception:
            return body
    return body


def _value_after_label(soup: BeautifulSoup, label: str) -> Optional[str]:
    """Find a <td>/<th> whose stripped text equals `label`; return next sibling cell text."""
    for cell in soup.find_all(["td", "th"]):
        if cell.get_text(strip=True) == label:
            sibling = cell.find_next_sibling(["td", "th"])
            if sibling is not None:
                return sibling.get_text(strip=True)
    return None


def _parse_money(text: str) -> float:
    cleaned = re.sub(r"[^\d.\-]", "", text or "")
    return float(cleaned) if cleaned else 0.0


def _parse_qty(text: str) -> Optional[float]:
    try:
        return float((text or "").strip())
    except (ValueError, TypeError):
        return None


def _parse_line_items(soup: BeautifulSoup) -> list[LineItem]:
    """Parse line items from the products table.

    The CIMcloud product table has a header row containing 'Image', 'Qty',
    'Description', 'Unit Price', 'Price' followed by one row per line item.
    """
    items: list[LineItem] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_text = rows[0].get_text(separator=" ", strip=True)
        if not (
            "Qty" in header_text
            and "Description" in header_text
            and "Unit Price" in header_text
        ):
            continue

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            qty = _parse_qty(cells[1].get_text(strip=True))
            if qty is None:
                continue
            desc_cell = cells[2]
            strong = desc_cell.find("strong")
            description = strong.get_text(strip=True) if strong else desc_cell.get_text(
                strip=True
            ).split("SKU:")[0].strip()
            sku_match = re.search(r"SKU:\s*(\S+)", desc_cell.get_text())
            sku = sku_match.group(1) if sku_match else ""
            unit_price = _parse_money(cells[3].get_text(strip=True))
            items.append(
                LineItem(
                    sku=sku,
                    description=description,
                    qty=qty,
                    unit_price=unit_price,
                )
            )
        break
    return items


def _summary_amount(soup: BeautifulSoup, label: str) -> float:
    """Read a dollar amount from the order-summary totals block by row label.

    The CIMcloud summary block is a right-aligned table with rows like
    'Subtotal | $179.75', 'Tax | $10.47', 'Shipping | $135.00',
    'Coupon | $179.75', 'Total | $145.47'. Finds the cell whose stripped text
    matches `label` (case-insensitive, ignoring a trailing colon) and returns
    the last numeric value in that row. Returns 0.0 if not found.
    """
    target = label.strip().rstrip(":").lower()
    for cell in soup.find_all(["td", "th"]):
        cell_text = cell.get_text(strip=True).rstrip(":").lower()
        if cell_text == target:
            row = cell.find_parent("tr")
            if row is None:
                sibling = cell.find_next_sibling(["td", "th"])
                return _parse_money(sibling.get_text(strip=True)) if sibling else 0.0
            amounts = [
                _parse_money(c.get_text(strip=True))
                for c in row.find_all(["td", "th"])
                if re.search(r"\d", c.get_text())
            ]
            return amounts[-1] if amounts else 0.0
    return 0.0


def _parse_order_comments(soup: BeautifulSoup) -> str:
    """Extract the free-text value under the 'Order Comments' column header.

    The shipment-details table has headers 'Shipping Address', 'Shipping Method',
    'Order Comments'. The comment value sits in the body row at the same column
    index as the 'Order Comments' header. Returns '' if absent.
    """
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = rows[0].find_all(["td", "th"])
        header_texts = [c.get_text(strip=True) for c in header_cells]
        # Require the tight shipment-details header, not the nested wrapper
        # table: exactly the three known columns. This avoids matching the
        # outermost table whose first cell happens to contain "Order Comments"
        # as part of a much larger blob.
        if not (
            2 <= len(header_texts) <= 4
            and any("order comment" in h.lower() for h in header_texts)
            and any("shipping method" in h.lower() for h in header_texts)
        ):
            continue
        comment_idx = next(
            i for i, h in enumerate(header_texts) if "order comment" in h.lower()
        )
        for body_row in rows[1:]:
            cells = body_row.find_all(["td", "th"])
            if len(cells) > comment_idx:
                text = cells[comment_idx].get_text(separator=" ", strip=True)
                if text:
                    return text
    return ""


def parse_cimcloud_email(html_body: str) -> OrderPayload:
    """Parse a CIMcloud 'Pending Approval' email body into an OrderPayload.

    Raises CimcloudParseError if the email is missing required fields
    (e.g. no Coupon Code → not a program order, or no order number).
    """
    body = _maybe_decode_quoted_printable(html_body or "")
    soup = BeautifulSoup(body, "html.parser")

    full_text = soup.get_text(separator="\n")
    if "Coupon Code:" not in full_text:
        raise CimcloudParseError(
            "Email body has no 'Coupon Code:' field — not a program order"
        )

    m = re.search(r"Your order number is\s+([A-Z0-9\-]+)\s*\.", full_text)
    if not m:
        raise CimcloudParseError("Could not find order number in email body")
    order_number = m.group(1)

    m = re.search(r"The order was placed on\s+(.+?)\s*\.", full_text)
    order_date = m.group(1).strip() if m else ""

    coupon_code = _value_after_label(soup, "Coupon Code:") or ""
    payment_method = _value_after_label(soup, "Payment Method:") or ""

    mailto = soup.find("a", href=re.compile(r"^mailto:", re.I))
    customer_email = mailto.get_text(strip=True) if mailto else ""

    phone_match = re.search(r"\b(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b", full_text)
    customer_phone = phone_match.group(1) if phone_match else ""

    customer_name = ""
    billing_address = ""
    billing_td = mailto.find_parent("td") if mailto else None
    if billing_td is not None:
        raw_lines = [
            ln.strip()
            for ln in billing_td.get_text(separator="\n").split("\n")
            if ln.strip()
        ]
        seen: list[str] = []
        for ln in raw_lines:
            if ln not in seen:
                seen.append(ln)
        if seen:
            customer_name = seen[0]
            addr_parts = [
                ln
                for ln in seen[1:]
                if ln != customer_email
                and ln != customer_phone
                and not re.match(r"^[A-Z]\d{6,}$", ln)
            ]
            billing_address = ", ".join(addr_parts)

    shipping_address = ""
    shipping_method = ""
    shipping_strong = None
    for strong in soup.find_all("strong"):
        s_text = strong.get_text(strip=True).lower()
        if any(kw in s_text for kw in ("pick up", "pickup", "delivery")):
            shipping_strong = strong
            break

    if shipping_strong is not None:
        shipping_method = shipping_strong.get_text(strip=True)
        method_td = shipping_strong.find_parent("td")
        if method_td is not None:
            addr_td = method_td.find_previous_sibling("td")
            if addr_td is not None:
                addr_lines = [
                    ln.strip()
                    for ln in addr_td.get_text(separator="\n").split("\n")
                    if ln.strip()
                ]
                shipping_address = ", ".join(addr_lines)

    line_items = _parse_line_items(soup)

    order_comments = _parse_order_comments(soup)
    subtotal = _summary_amount(soup, "Subtotal")
    tax = _summary_amount(soup, "Tax")
    shipping = _summary_amount(soup, "Shipping")
    coupon_amount = _summary_amount(soup, "Coupon")
    order_total = _summary_amount(soup, "Total")

    return OrderPayload(
        order_number=order_number,
        order_date=order_date,
        coupon_code=coupon_code,
        payment_method=payment_method,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        billing_address=billing_address,
        shipping_address=shipping_address,
        shipping_method=shipping_method,
        line_items=line_items,
        order_comments=order_comments,
        subtotal=subtotal,
        tax=tax,
        shipping=shipping,
        coupon_amount=coupon_amount,
        order_total=order_total,
    )


# ---------------------------------------------------
# HEALTH
# ---------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "coupon-dispatch"}


@app.get("/")
async def root():
    return {
        "service": "Agromin Order Dispatch",
        "endpoints": [
            "POST /api/ingest-order",
            "POST /api/generate-manifest",
            "GET  /api/delivery-schedule",
            "GET  /health",
        ],
    }


# ---------------------------------------------------
# CORE ORDER PROCESSING
# Shared by /api/ingest-order (structured JSON) and
# /api/ingest-cimcloud-email (raw email body).
# ---------------------------------------------------
def _process_order(order: OrderPayload) -> dict:
    coupon_code = order.coupon_code.strip().upper()
    total_qty = sum(item.qty for item in order.line_items)
    material = order.line_items[0].description if order.line_items else "material"
    qty_str = format_qty(total_qty)

    if "delivery" in order.shipping_method.lower():
        routing = "delivery"
        region = infer_region_from_address(order.shipping_address)
    else:
        routing = "pickup_self_load" if total_qty < 5 else "pickup_staff_load"
        yard = get_yard_for_order(order.shipping_method)
        region = yard.get("region", "unknown")

    try:
        db = get_firestore()
        db.collection("order_events").document(order.order_number).set({
            "order_number": order.order_number,
            "processed_at": datetime.utcnow(),
            "coupon_code": coupon_code,
            "routing": routing,
            "region": region,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "shipping_method": order.shipping_method,
            "shipping_address": order.shipping_address,
            "total_qty": total_qty,
            "material": material,
            "order_date": order.order_date,
            "customer_phone": order.customer_phone,
            "status": "success",
        })
    except Exception as e:
        logger.error("Firestore write failed for order %s: %s", order.order_number, e)

    cc_list = [OFELIA_EMAIL] if OFELIA_EMAIL else []

    if routing == "delivery":
        body = DELIVERY_TEMPLATE.format(
            order_number=order.order_number,
            customer_name=order.customer_name,
            qty=qty_str,
            material=material,
            shipping_address=order.shipping_address,
        )
        subject = f"Your Agromin Order #{order.order_number} — Delivery Confirmation"
        send_email(order.customer_email, subject, body, cc=cc_list)

        alert_body = DELIVERY_ALERT_TEMPLATE.format(
            order_number=order.order_number,
            order_date=order.order_date,
            customer_name=order.customer_name,
            customer_phone=order.customer_phone,
            customer_email=order.customer_email,
            shipping_address=order.shipping_address,
            qty=qty_str,
            material=material,
            coupon_code=coupon_code,
            order_comments=order.order_comments or "(none)",
        )
        alert_subject = f"New Delivery Order #{order.order_number} — Action Required"
        for coordinator in get_delivery_coordinator_emails(region):
            send_email(coordinator, alert_subject, alert_body)
    else:
        yard = get_yard_for_order(order.shipping_method)
        common_fields = dict(
            order_number=order.order_number,
            customer_name=order.customer_name,
            qty=qty_str,
            material=material,
            yard_name=yard["name"],
            yard_address=yard["address"],
            yard_phone=yard["phone"],
            yard_hours=yard["hours"],
        )
        if routing == "pickup_self_load":
            sb1383 = SB1383_PARAGRAPH + "\n" if yard.get("qr_url") else ""
            body = PICKUP_SELF_LOAD_TEMPLATE.format(sb1383_note=sb1383, **common_fields)
        else:
            body = PICKUP_STAFF_LOAD_TEMPLATE.format(**common_fields)
        subject = f"Your Agromin Order #{order.order_number} — Pickup Instructions"
        send_email(order.customer_email, subject, body, cc=cc_list)

    master_sheet_rows = build_master_sheet_rows(order, routing)

    return {
        "status": "processed",
        "order_number": order.order_number,
        "routing": routing,
        "region": region,
        "total_qty": total_qty,
        "master_sheet_rows": master_sheet_rows,
    }


# ---------------------------------------------------
# POST /api/ingest-order
# ---------------------------------------------------
@app.post("/api/ingest-order")
async def ingest_order(
    order: OrderPayload,
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    if x_api_key != DISPATCH_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return _process_order(order)


# ---------------------------------------------------
# POST /api/ingest-cimcloud-email
# Power Automate forwards the raw HTML body of a CIMcloud "Pending Approval"
# email here. This service parses it server-side and routes the order.
#
# Two request shapes are accepted (the endpoint auto-detects):
#   1. Power Automate friendly (preferred):
#        Content-Type: text/html
#        X-Email-Subject: <subject line>   (optional, used for logging)
#        Body: raw HTML of the email
#   2. JSON envelope (curl tests):
#        Content-Type: application/json
#        Body: {"body": "<html>...", "subject": "..."}
# ---------------------------------------------------
@app.post("/api/ingest-cimcloud-email")
async def ingest_cimcloud_email(
    request: Request,
    x_api_key: str = Header(None, alias="X-API-Key"),
    x_email_subject: Optional[str] = Header(None, alias="X-Email-Subject"),
):
    if x_api_key != DISPATCH_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    content_type = (request.headers.get("content-type") or "").lower()
    raw_body = await request.body()

    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        html_body = data.get("body", "") if isinstance(data, dict) else ""
        subject = data.get("subject") if isinstance(data, dict) else None
    else:
        html_body = raw_body.decode("utf-8", errors="replace")
        subject = x_email_subject

    try:
        order = parse_cimcloud_email(html_body)
    except CimcloudParseError as e:
        logger.info("Skipped non-program email (subject=%r): %s", subject, e)
        return {"status": "skipped", "reason": str(e)}
    except Exception as e:
        logger.exception("CIMcloud parser crashed (subject=%r)", subject)
        raise HTTPException(status_code=400, detail=f"Parse error: {e}")

    logger.info(
        "Parsed CIMcloud email subject=%r → order_number=%s coupon=%s qty=%s",
        subject,
        order.order_number,
        order.coupon_code,
        sum(li.qty for li in order.line_items),
    )
    return _process_order(order)


# ---------------------------------------------------
# POST /api/generate-manifest
# ---------------------------------------------------
@app.post("/api/generate-manifest")
async def generate_manifest(
    order: OrderPayload,
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    if x_api_key != DISPATCH_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    coupon_code = order.coupon_code.strip().upper()
    total_qty = sum(item.qty for item in order.line_items)
    material = order.line_items[0].description if order.line_items else "material"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )
    styles = getSampleStyleSheet()
    story = []

    header_style = styles["Heading1"]
    label_style = styles["Normal"]

    story.append(Paragraph("AGROMIN — DELIVERY MANIFEST", header_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black))
    story.append(Spacer(1, 0.15 * inch))

    generated_at = datetime.utcnow().strftime("%B %d, %Y %I:%M %p UTC")
    info_data = [["Order #:", order.order_number, "Generated:", generated_at]]
    info_table = Table(info_data, colWidths=[1.1 * inch, 2.5 * inch, 1.1 * inch, 2.3 * inch])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("<b>CUSTOMER INFORMATION</b>", label_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.1 * inch))

    customer_data = [
        ["Name:", order.customer_name],
        ["Phone:", order.customer_phone or "—"],
        ["Delivery Address:", order.shipping_address],
    ]
    customer_table = Table(customer_data, colWidths=[1.5 * inch, 5.5 * inch])
    customer_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(customer_table)
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("<b>ORDER DETAILS</b>", label_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.1 * inch))

    order_data = [
        ["Material:", material],
        ["Quantity:", f"{format_qty(total_qty)} cubic yards"],
        ["Coupon Code:", coupon_code],
    ]
    order_table = Table(order_data, colWidths=[1.5 * inch, 5.5 * inch])
    order_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(order_table)
    story.append(Spacer(1, 0.5 * inch))

    story.append(Paragraph("<b>SIGNATURES</b>", label_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.3 * inch))

    sig_data = [
        ["Hauler Signature:", "_" * 40, "Date:", "_" * 15],
        ["", "", "", ""],
        ["OCWR Staff Signature\nupon material pickup:", "_" * 40, "Date:", "_" * 15],
    ]
    sig_table = Table(sig_data, colWidths=[1.8 * inch, 2.8 * inch, 0.6 * inch, 1.8 * inch])
    sig_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    story.append(sig_table)

    doc.build(story)
    pdf_bytes = buf.getvalue()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=manifest_{order.order_number}.pdf"},
    )


# ---------------------------------------------------
# GET /api/delivery-schedule
# ---------------------------------------------------
@app.get("/api/delivery-schedule")
async def delivery_schedule(
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    if x_api_key != DISPATCH_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    try:
        db = get_firestore()
        cutoff = datetime.utcnow() - timedelta(days=7)
        docs = db.collection("order_events").where("routing", "==", "delivery").stream()
        orders = []
        for doc in docs:
            data = doc.to_dict()
            processed_at = data.get("processed_at")
            if processed_at and hasattr(processed_at, "replace"):
                if processed_at.replace(tzinfo=None) >= cutoff:
                    orders.append({
                        "order_number": data.get("order_number"),
                        "order_date": data.get("order_date"),
                        "processed_at": processed_at.isoformat() if hasattr(processed_at, "isoformat") else str(processed_at),
                        "customer_name": data.get("customer_name"),
                        "customer_phone": data.get("customer_phone"),
                        "shipping_address": data.get("shipping_address"),
                        "material": data.get("material"),
                        "total_qty": data.get("total_qty"),
                        "region": data.get("region"),
                        "coupon_code": data.get("coupon_code"),
                    })
        orders.sort(key=lambda x: x.get("processed_at", ""), reverse=True)
        return {"status": "ok", "count": len(orders), "orders": orders}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
