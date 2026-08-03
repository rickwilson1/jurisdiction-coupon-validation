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

import html
import logging
import os
import quopri
import re
import textwrap
import time
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import msal
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from google.cloud import firestore as firestore_client
from pydantic import BaseModel
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

# Internal staff who get a blind copy of every customer confirmation so they
# can see exactly what the customer received. BCC rather than CC keeps Agromin
# addresses off the customer-visible header. Set CONFIRMATION_BCC to a
# comma-separated list to override; set it to an empty string to disable.
_confirmation_bcc_env = os.environ.get("CONFIRMATION_BCC")
if _confirmation_bcc_env is None:
    CONFIRMATION_BCC = [e for e in [KENDALL_EMAIL] if e]
else:
    CONFIRMATION_BCC = [e.strip() for e in _confirmation_bcc_env.split(",") if e.strip()]

SUPPORT_EMAIL = "sales@agromin.com"
SUPPORT_PHONE = "(805) 485-9200"


# ---------------------------------------------------
# OCWR GREENERIES
# Customer-facing pickup locations for the OC program.
#
# `map_url` values were verified by opening each PDF: the heading on the PDF
# must name the same greenery as the block it appears under. The source Word
# templates had these three URLs rotated by one position (Bee Canyon pointed at
# the Olinda/Valencia map, Capistrano at the Bowerman/Bee Canyon map, Valencia
# at the Prima/Capistrano map), which would have sent every pickup customer to
# the wrong site map.
# ---------------------------------------------------
GREENERIES = [
    {
        "greenery": "Bee Canyon Greenery",
        "landfill": "Frank R. Bowerman Landfill",
        "yard_key": "Frank R. Bowerman",
        "hours": "M-Sat | 8am - 4pm",
        "address_lines": ["11002 Bee Canyon Access Rd.", "Irvine, CA 92602"],
        "phone": "(949) 551-7100",
        "map_url": (
            "https://oclandfills.com/sites/ocwr/files/2025-10/"
            "2025_10_25_FRANK%20R.%20BOWERMAN%20Map%20-%20Compost%20and%20Mulch-part-1.pdf"
        ),
    },
    {
        "greenery": "Capistrano Greenery",
        "landfill": "Prima Deshecha Landfill",
        "yard_key": "Prima Deshecha",
        "hours": "M-Sat | 8am - 4pm",
        "address_lines": ["32250 Avenida La Pata", "San Juan Capistrano, CA 92675"],
        "phone": "(949) 728-3040",
        "map_url": (
            "https://oclandfills.com/sites/ocwr/files/2024-07/"
            "2024_07_19_PRIMA%20Map%20-%20Compost%20and%20Mulch_0.pdf"
        ),
    },
    {
        "greenery": "Valencia Greenery",
        "landfill": "Olinda Alpha Landfill",
        "yard_key": "Olinda Alpha",
        "hours": "M-Sat | 7am - 3pm",
        "address_lines": ["1942 Valencia Avenue", "Brea, CA 92823"],
        "phone": "(714) 993-7396",
        "map_url": (
            "https://oclandfills.com/sites/ocwr/files/2025-12/"
            "Olinda%20New%20Compost%20%26%20Mulch%20Pick%20Up%20Area%20%284%29.pdf"
        ),
    },
]

PICKUP_APPOINTMENT_URL = (
    "https://outlook.office365.com/book/"
    "CompostMulchPickupAppointments@ocgov.onmicrosoft.com/"
    "?ismsaljsauthenabled=true"
)
COMPOST_TIPS_URL = "https://oclandfills.com/compost-mulch/greeneries-compost-tips"


# ---------------------------------------------------
# YARD LOCATIONS
# Matching uses case-insensitive substring search on match_keys.
#
# Only `name` and `region` are read at runtime: `name` identifies which yard the
# customer picked at checkout, `region` routes the delivery alert. The address /
# phone / hours here are NOT what customers see. GREENERIES below is the single
# source of truth for customer-facing greenery details — edit it, not this, when
# OCWR changes an address or its hours.
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
                return {
                    "name": yard_name,
                    **{k: v for k, v in yard_info.items() if k != "match_keys"},
                }
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
    ventura_cities = [
        "ventura",
        "oxnard",
        "camarillo",
        "fillmore",
        "ojai",
        "santa paula",
        "port hueneme",
    ]
    if any(re.search(rf"\b{c}\b", a) for c in ventura_cities):
        return "ventura"
    return "oc"


def get_delivery_coordinator_emails(region: str) -> list:
    if region == "sacramento":
        return [e for e in [ROSA_EMAIL] if e]
    if region == "ventura":
        return [e for e in [CHRIS_EMAIL] if e]
    return [e for e in [GREG_EMAIL, BRIAN_EMAIL, KENDALL_EMAIL] if e]


# Name used in the delivery email's "I am CC'ing ..." sentence. It has to track
# whoever get_delivery_coordinator_emails() actually puts on the CC line, or a
# Ventura customer is told Greg will call while Chris gets the order.
DELIVERY_COORDINATOR_NAMES = {
    "oc": "Greg Jackson",
    "ventura": "Chris",
    "sacramento": "Rosa",
}


def get_delivery_coordinator_name(region: str) -> str:
    return DELIVERY_COORDINATOR_NAMES.get(region, DELIVERY_COORDINATOR_NAMES["oc"])


def get_reply_to(routing: str, region: str) -> list:
    """Who a customer reaches when they hit Reply on a confirmation.

    Without this the reply lands in dispatch@agromin.com, a mailbox nobody
    signs into, and sits until someone happens to look. The owner is listed
    first, with the dispatch mailbox alongside so the thread stays visible to
    everyone with access and survives the owner being out.

    Delivery goes to the coordinator the email already names as following up,
    so the reply reaches the person the customer was just told to expect.
    Ofelia stays a CC rather than a reply target: she is the OCWR escalation
    path, and county staff should not be the default front line for Agromin's
    customer mail.
    """
    if routing == "delivery":
        coordinators = get_delivery_coordinator_emails(region)
        owners = coordinators[:1]
    else:
        owners = [KENDALL_EMAIL] if KENDALL_EMAIL else []

    recipients = []
    for addr in [*owners, MAIL_SENDER]:
        if addr and addr not in recipients:
            recipients.append(addr)
    return recipients


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
    today = datetime.now(UTC).astimezone(_PACIFIC_TZ).date()
    today_short = f"{today.month}/{today.day}/{today.year % 100:02d}"
    note = f"Auto-imported {today_short}. Origin TBD — Greg to assign yard."

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

        rows.append(
            {
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
            }
        )
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

    result = _msal_app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])

    if "access_token" not in result:
        raise RuntimeError(
            f"Graph token acquisition failed: {result.get('error')} — "
            f"{result.get('error_description')}"
        )

    _token_cache["token"] = result["access_token"]
    _token_cache["expires_at"] = now + int(result.get("expires_in", 3600))
    return _token_cache["token"]


def send_email(
    to: str,
    subject: str,
    body: str,
    cc: list = None,
    bcc: list = None,
    html_body: str = None,
    reply_to: list = None,
) -> bool:
    """Send an email via Microsoft Graph as MAIL_SENDER (dispatch@agromin.com).

    Sends `html_body` as HTML when supplied so hyperlinks are clickable,
    otherwise sends `body` as plain text. Returns True only when Graph accepts
    the message so callers can log a real send result instead of assuming
    success.

    Returns False if Graph credentials are not configured (useful for local dev).
    """
    if not (GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET):
        logger.warning("Graph credentials not configured — email skipped (to=%s)", to)
        return False

    try:
        token = _get_graph_token()

        content_type, content = ("HTML", html_body) if html_body else ("Text", body)

        message = {
            "subject": subject,
            "body": {"contentType": content_type, "content": content},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": c}} for c in cc]
        if bcc:
            message["bccRecipients"] = [{"emailAddress": {"address": b}} for b in bcc]
        if reply_to:
            message["replyTo"] = [{"emailAddress": {"address": r}} for r in reply_to]

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
            logger.info(
                "Email sent to=%s cc=%s bcc=%s subject=%s",
                to,
                cc or [],
                bcc or [],
                subject,
            )
            return True

        logger.error(
            "Graph sendMail failed (status=%s) for to=%s: %s",
            resp.status_code,
            to,
            resp.text,
        )
        return False
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to, e)
        return False


# ---------------------------------------------------
# CUSTOMER EMAIL CONTENT
#
# Body copy is transcribed from Kendall's July 2026 Word templates:
#   Email Template - UNDER 5 yards Coupon Order Instructions.docx
#   Email Template- OVER 5 yards Coupon Order Instructions.docx
#   Email Template- Delivery Request Receipt.docx
#
# These are sent as HTML because the copy relies on hyperlinks ("use this
# LINK", "link to printable PDF map"). A plain-text send would strip the
# anchors and leave the customer with unclickable words and no URL.
# ---------------------------------------------------
_BODY_STYLE = (
    "font-family:Aptos,Calibri,'Segoe UI',Arial,sans-serif;"
    "font-size:11pt;line-height:1.4;color:#1a1a1a;"
)

_BAGGED_UNIT_RE = re.compile(r"\b\d+\s*(?:cf|cu\.?\s*ft\.?|cubic\s+f(?:oo|ee)t)\b")


def _display_material(description: str) -> tuple[str, str]:
    """Return (material name, singular unit) for customer-facing prose.

    Deliberately separate from `classify_material`, which drives Greg's Master
    Sheet columns and maps bagged compost to 'Compost'. Customer copy also
    needs the unit: a "Organic Harvest Compost 1cf" order is counted in bags,
    not cubic yards, and telling that customer "8 cubic yards" would overstate
    the order by three orders of magnitude.
    """
    d = (description or "").lower()

    if "mulch" in d:
        name = "mulch"
    elif "compost" in d:
        name = "compost"
    else:
        name = "material"

    if "pallet" in d:
        unit = "pallet"
    elif "bag" in d or _BAGGED_UNIT_RE.search(d):
        unit = "bag"
    else:
        unit = "cubic yard"

    return name, unit


def _pluralize(unit: str, qty: float) -> str:
    if qty == 1:
        return unit
    return "cubic yards" if unit == "cubic yard" else f"{unit}s"


def describe_materials(order: "OrderPayload") -> str:
    """Customer-facing quantity phrase, e.g. '3 cubic yards of compost'.

    Groups line items by material and unit so a multi-material order reads
    '3 cubic yards of compost and 2 cubic yards of mulch' rather than
    attributing the combined quantity to whichever line item happened to be
    first, which is what the previous single-material template did.
    """
    totals: dict[tuple[str, str], float] = {}
    for item in order.line_items:
        key = _display_material(item.description)
        totals[key] = totals.get(key, 0.0) + item.qty

    if not totals:
        return "your requested material"

    parts = [
        f"{format_qty(qty)} {_pluralize(unit, qty)} of {name}"
        for (name, unit), qty in totals.items()
    ]

    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def bulk_cubic_yards(order: "OrderPayload") -> float:
    """Cubic yards across all line items, which is what the 5-yard split measures.

    Mixed orders must be added up: 2 yards of compost plus 4 of mulch is a
    6-yard order and needs the staff-load email, even though no single line
    item clears 5.

    Only cubic-yard items count. Line items carry mixed units, so summing raw
    quantities would score a 10-bag order as 10 against a threshold denominated
    in yards, and send someone with a car boot full of 1cf bags instructions
    demanding a commercial truck and a weigh-in.
    """
    return sum(
        item.qty
        for item in order.line_items
        if _display_material(item.description)[1] == "cubic yard"
    )


def clean_display_address(addr: str) -> str:
    """Trim CIMcloud shipping-address noise for customer-facing display.

    CIMcloud prefixes the block with a recipient or company name and appends
    ', USA', neither of which belongs in the sentence 'delivered to ...'.
    """
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    if parts and parts[-1].upper().replace(".", "") in ("USA", "US", "UNITED STATES"):
        parts.pop()
    if len(parts) > 1 and not re.match(r"^\d", parts[0]) and re.match(r"^\d", parts[1]):
        parts.pop(0)
    return ", ".join(parts)


def _selected_greenery(selected_yard_key: str | None) -> dict | None:
    """The greenery bought at checkout, or None if shipping_method didn't resolve."""
    for site in GREENERIES:
        if site["yard_key"] == selected_yard_key:
            return site
    return None


def _sites_to_show(selected_yard_key: str | None) -> list[dict]:
    """Under-5: only the yard chosen at checkout.

    Over-5 uses the OCWR template instead, which lists all three and invites
    the customer to choose any one. That open-choice path does not go through
    this helper.
    """
    site = _selected_greenery(selected_yard_key)
    return [site] if site else list(GREENERIES)


def _greenery_block_html(selected_yard_key: str | None = None) -> str:
    """Render the customer's greenery, or all three if the yard didn't resolve."""
    blocks = []
    for site in _sites_to_show(selected_yard_key):
        heading = html.escape(site["greenery"])
        if site.get("note"):
            heading += f" {html.escape(site['note'])}"
        address = "<br>".join(html.escape(line) for line in site["address_lines"])
        blocks.append(
            f'<p style="margin:0 0 14px 0;"><strong>{heading}</strong><br>'
            f"{html.escape(site['hours'])}<br>"
            f"{address}<br>"
            f"{html.escape(site['phone'])}<br>"
            f'<a href="{site["map_url"]}">Link to printable PDF map</a> for '
            f"{html.escape(site['greenery'])} at {html.escape(site['landfill'])}</p>"
        )
    return "".join(blocks)


def _greenery_block_text(selected_yard_key: str | None = None) -> str:
    lines = []
    for site in _sites_to_show(selected_yard_key):
        heading = site["greenery"]
        if site.get("note"):
            heading += f" {site['note']}"
        lines.append(heading)
        lines.append(site["hours"])
        lines.extend(site["address_lines"])
        lines.append(site["phone"])
        lines.append(
            f"Printable PDF map for {site['greenery']} at {site['landfill']}: {site['map_url']}"
        )
        lines.append("")
    return "\n".join(lines)


# OCWR over-5 template hours and Valencia address. Kept separate from GREENERIES
# so the under-5 email (Kendall's template) keeps M-Sat shorthand, phones, and
# the Valencia address without the N.
_OCWR_OVER5_HOURS = {
    "Frank R. Bowerman": "Monday - Saturday | 8 a.m. – 4 p.m.",
    "Prima Deshecha": "Monday - Saturday | 8 a.m. – 4 p.m.",
    "Olinda Alpha": "Monday - Saturday | 7 a.m. – 3 p.m.",
}
_OCWR_OVER5_ADDRESS = {
    "Olinda Alpha": ["1942 N. Valencia Ave", "Brea, CA 92823"],
}


def _ocwr_over5_greenery_block_html() -> str:
    """All three greeneries as the OCWR over-5 template lists them: no phones."""
    blocks = []
    for site in GREENERIES:
        hours = _OCWR_OVER5_HOURS[site["yard_key"]]
        address_lines = _OCWR_OVER5_ADDRESS.get(site["yard_key"], site["address_lines"])
        address = "<br>".join(html.escape(line) for line in address_lines)
        blocks.append(
            f'<p style="margin:0 0 14px 0;"><strong>{html.escape(site["greenery"])}</strong><br>'
            f"{html.escape(hours)}<br>"
            f"{address}<br>"
            f'<a href="{site["map_url"]}">Link to printable PDF map</a> for '
            f"{html.escape(site['greenery'])} at {html.escape(site['landfill'])}</p>"
        )
    return "".join(blocks)


def _ocwr_over5_greenery_block_text() -> str:
    lines = []
    for site in GREENERIES:
        hours = _OCWR_OVER5_HOURS[site["yard_key"]]
        address_lines = _OCWR_OVER5_ADDRESS.get(site["yard_key"], site["address_lines"])
        lines.append(site["greenery"])
        lines.append(hours)
        lines.extend(address_lines)
        lines.append(
            f"Printable PDF map for {site['greenery']} at {site['landfill']}: {site['map_url']}"
        )
        lines.append("")
    return "\n".join(lines)


def _appointment_location_clause(selected_yard_key: str | None) -> str:
    """Tell the customer which location to book, rather than inviting a choice."""
    site = _selected_greenery(selected_yard_key)
    if site:
        return f"be sure to select {site['greenery']}, the location you chose at checkout"
    return "be sure to select the preferred service location (Valencia, Capistrano or Bee Canyon)"


def _footer_html() -> str:
    return (
        f'<p style="margin:0 0 14px 0;">If you have any questions, reply to this '
        f"email or call {SUPPORT_PHONE}.</p>"
        f'<p style="margin:0;">Thank you,<br>Agromin</p>'
    )


def _footer_text() -> str:
    return (
        f"If you have any questions, reply to this email or call {SUPPORT_PHONE}.\n\n"
        "Thank you,\nAgromin"
    )


def _order_reference_html(order: "OrderPayload", material_phrase: str | None = None) -> str:
    """Order-number callout. Both pickup templates ask the customer to present
    their order confirmation on arrival, so the number has to be easy to find.
    """
    detail = f"<br>{html.escape(material_phrase)}" if material_phrase else ""
    return (
        '<p style="margin:0 0 14px 0;padding:10px 12px;background:#f4f6f4;'
        'border-left:3px solid #1f6f3f;">'
        f"<strong>Order #{html.escape(order.order_number)}</strong>{detail}</p>"
    )


def build_pickup_self_load_email(order: "OrderPayload", yard: dict) -> tuple:
    """Under 5 cubic yards: self-service pickup, scheduled via OCWR Bookings."""
    material_phrase = describe_materials(order)
    selected = yard.get("name")

    html_body = f"""<html><body style="{_BODY_STYLE}">
<p style="margin:0 0 14px 0;">Hello {html.escape(order.customer_name or "")},</p>
{_order_reference_html(order, material_phrase)}
<p style="margin:0 0 14px 0;">Thank you for participating in the Orange County Waste
and Recycling&rsquo;s Free Compost and Mulch Program.</p>
<p style="margin:0 0 14px 0;">Please review the following pick-up instructions for
your material.</p>
<p style="margin:0 0 14px 0;"><strong>Use this
<a href="{PICKUP_APPOINTMENT_URL}">LINK</a> to schedule an appointment to pick up your
compost/mulch</strong> - {_appointment_location_clause(selected)}</p>
<p style="margin:0 0 14px 0;">You will receive email confirmation when you submit your
request with instructions on when, where, and how to pick up your compost/mulch.</p>
<p style="margin:0 0 14px 0;"><strong>Please note that for any order under 5 yards, the
greeneries are self-service sites</strong> that require you to bring your own tools and
containers to load your material (shovels, buckets, bags, etc.).</p>
<p style="margin:0 0 14px 0;">There will be 5 gallon buckets available to help you load
material into your own containers. Please leave these for the next customers.</p>
<p style="margin:0 0 14px 0;">There will be a QR code at the self-serve sites for you to
submit confirmation of your order fulfillment. This is extremely helpful as we track
procurement for state mandated SB 1383 requirements.</p>
<p style="margin:0 0 14px 0;">Please bring a copy of your email confirmation.</p>
<p style="margin:0 0 14px 0;">Visit <a href="{COMPOST_TIPS_URL}">Compost and Mulch
Tips</a> website for details on the difference between compost and mulch and for tips on
composting.</p>
{_greenery_block_html(selected)}
{_footer_html()}
</body></html>"""

    text_body = f"""Hello {order.customer_name},

Order #{order.order_number}
{material_phrase}

Thank you for participating in the Orange County Waste and Recycling's Free
Compost and Mulch Program.

Please review the following pick-up instructions for your material.

Use this link to schedule an appointment to pick up your compost/mulch -
{textwrap.fill(_appointment_location_clause(selected), 76)}:
{PICKUP_APPOINTMENT_URL}

You will receive email confirmation when you submit your request with
instructions on when, where, and how to pick up your compost/mulch.

Please note that for any order under 5 yards, the greeneries are self-service
sites that require you to bring your own tools and containers to load your
material (shovels, buckets, bags, etc.).

There will be 5 gallon buckets available to help you load material into your
own containers. Please leave these for the next customers.

There will be a QR code at the self-serve sites for you to submit confirmation
of your order fulfillment. This is extremely helpful as we track procurement
for state mandated SB 1383 requirements.

Please bring a copy of your email confirmation.

Visit Compost and Mulch Tips for details on the difference between compost and
mulch and for tips on composting:
{COMPOST_TIPS_URL}

{_greenery_block_text(selected)}
{_footer_text()}"""

    subject = f"Your Agromin Order #{order.order_number} — Compost/Mulch Pick-Up Instructions"
    return subject, text_body, html_body


def build_pickup_staff_load_email(order: "OrderPayload", yard: dict) -> tuple:
    """5 cubic yards and over: greenery crew loads with heavy equipment.

    Body copy follows OCWR's Over 5 Cubic Yard Email Template Updated 7.29.26.
    Map URLs stay the verified pairings in GREENERIES (the Word file rotates
    them). Tips link stays the clean oclandfills.com URL (the Word file wraps
    it in Proofpoint). Greeting and order reference stay for automation.
    """
    material_phrase = describe_materials(order)
    _ = yard  # retained for call-site compatibility; OCWR lists all three sites

    html_body = f"""<html><body style="{_BODY_STYLE}">
<p style="margin:0 0 14px 0;">Hello {html.escape(order.customer_name or "")},</p>
{_order_reference_html(order, material_phrase)}
<p style="margin:0 0 14px 0;">Thank you for participating in the OC Waste and
Recycling&rsquo;s Free Compost and Mulch Program.</p>
<p style="margin:0 0 14px 0;">Please review the following pick up instructions for your
material:</p>
<p style="margin:0 0 14px 0;"><strong>You must have a commercial truck or heavy-duty
trailer for at least 5 cubic yards of bulk material</strong> in order for our greenery
crew to assist with loading using heavy equipment. Trailers will require solid sides and
flooring, or you MUST bring your own tarps to prevent spilling during transport.</p>
<p style="margin:0 0 14px 0;">NO CARS. NO MINIVANS. If you do not have a commercial truck
or heavy-duty trailer, you will be redirected to the public self-haul area to
self-load.</p>
<p style="margin:0 0 14px 0;">When you arrive at the landfill, check in at the fee booth,
present your email confirmation, and weigh in at the scales.</p>
<p style="margin:0 0 14px 0;">You will then be directed to the greenery for loading
assistance. NO SELF-LOADING at the greenery.</p>
<p style="margin:0 0 14px 0;">Upon exiting the landfill, your vehicle must be weighed
before leaving the site.</p>
<p style="margin:0 0 14px 0;">For your reference, 1 Cubic Yard of Compost covers 150 Sq.
Feet at 3&quot; Layer/Depth. Most mid-sized pick-up trucks can hold &frac12; - 1 &frac12;
Cubic Yards of Compost per load.</p>
<p style="margin:0 0 14px 0;">Visit <a href="{COMPOST_TIPS_URL}">Compost and Mulch
Tips</a> website for details on the difference between compost and mulch and for tips on
composting.</p>
<p style="margin:0 0 14px 0;"><strong>Choose any one of the greenery locations below for
pickup and present your confirmation email at the fee booth.</strong></p>
{_ocwr_over5_greenery_block_html()}
{_footer_html()}
</body></html>"""

    text_body = f"""Hello {order.customer_name},

Order #{order.order_number}
{material_phrase}

Thank you for participating in the OC Waste and Recycling's Free Compost and
Mulch Program.

Please review the following pick up instructions for your material:

You must have a commercial truck or heavy-duty trailer for at least 5 cubic
yards of bulk material in order for our greenery crew to assist with loading
using heavy equipment. Trailers will require solid sides and flooring, or you
MUST bring your own tarps to prevent spilling during transport.

NO CARS. NO MINIVANS. If you do not have a commercial truck or heavy-duty
trailer, you will be redirected to the public self-haul area to self-load.

When you arrive at the landfill, check in at the fee booth, present your email
confirmation, and weigh in at the scales.

You will then be directed to the greenery for loading assistance. NO
SELF-LOADING at the greenery.

Upon exiting the landfill, your vehicle must be weighed before leaving the
site.

For your reference, 1 Cubic Yard of Compost covers 150 Sq. Feet at 3"
Layer/Depth. Most mid-sized pick-up trucks can hold 1/2 - 1 1/2 Cubic Yards of
Compost per load.

Visit Compost and Mulch Tips for details on the difference between compost and
mulch and for tips on composting:
{COMPOST_TIPS_URL}

Choose any one of the greenery locations below for pickup and present your
confirmation email at the fee booth.

{_ocwr_over5_greenery_block_text()}
{_footer_text()}"""

    subject = f"Your Agromin Order #{order.order_number} — Compost/Mulch Pick Up Instructions"
    return subject, text_body, html_body


def build_delivery_email(order: "OrderPayload", coordinator_name: str = "Greg Jackson") -> tuple:
    """Delivery request receipt. The named coordinator is CC'd, as the copy says."""
    material_phrase = describe_materials(order)
    address = clean_display_address(order.shipping_address)

    # The bold sentence in Kendall's template names the quantity, material and
    # delivery address. All three parse out of the CIMcloud order, so the
    # sentence is populated rather than dropped. If the address is somehow
    # missing, fall back to a generic sentence instead of emailing a customer
    # "delivered to ''".
    if address:
        request_html = (
            f"Your request for <strong>{html.escape(material_phrase)}</strong> to be "
            f"delivered to <strong>{html.escape(address)}</strong> has been received."
        )
        request_text = (
            f"Your request for {material_phrase} to be delivered to {address} has been received."
        )
    else:
        request_html = (
            f"Your request for <strong>{html.escape(material_phrase)}</strong> has been received."
        )
        request_text = f"Your request for {material_phrase} has been received."

    html_body = f"""<html><body style="{_BODY_STYLE}">
<p style="margin:0 0 14px 0;">Hello {html.escape(order.customer_name or "")},</p>
{_order_reference_html(order)}
<p style="margin:0 0 14px 0;">{request_html}</p>
<p style="margin:0 0 14px 0;">Please note that, due to the coordination required for
hauling and scheduling, it may take <strong>1&ndash;2 weeks</strong> before a delivery
date is available.</p>
<p style="margin:0 0 14px 0;"><strong>{html.escape(coordinator_name)}</strong> is copied on
this email and will follow up with you directly to provide a hauling quote along with a
proposed delivery date and time.</p>
<p style="margin:0 0 14px 0;">For your reference, a cubic yard is 27 cubic feet, which
covers about 108 square feet at 3 inches.</p>
<p style="margin:0 0 14px 0;">If you have any updates or questions in the meantime, feel
free to reply to this email.</p>
<p style="margin:0;">Thank you,<br>Agromin</p>
</body></html>"""

    text_body = f"""Hello {order.customer_name},

Order #{order.order_number}

{request_text}

Please note that, due to the coordination required for hauling and scheduling,
it may take 1-2 weeks before a delivery date is available.

{coordinator_name} is copied on this email and will follow up with you directly
to provide a hauling quote along with a proposed delivery date and time.

For your reference, a cubic yard is 27 cubic feet, which covers about 108 square
feet at 3 inches.

If you have any updates or questions in the meantime, feel free to reply to
this email.

Thank you,
Agromin"""

    subject = f"Your Agromin Delivery Request #{order.order_number} — Received"
    return subject, text_body, html_body


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
    subject: str | None = None


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
            return quopri.decodestring(body.encode("latin-1")).decode("utf-8", errors="replace")
        except Exception:
            return body
    return body


def _value_after_label(soup: BeautifulSoup, label: str) -> str | None:
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


def _parse_qty(text: str) -> float | None:
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
            "Qty" in header_text and "Description" in header_text and "Unit Price" in header_text
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
            description = (
                strong.get_text(strip=True)
                if strong
                else desc_cell.get_text(strip=True).split("SKU:")[0].strip()
            )
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
        comment_idx = next(i for i, h in enumerate(header_texts) if "order comment" in h.lower())
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
        raise CimcloudParseError("Email body has no 'Coupon Code:' field — not a program order")

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
            ln.strip() for ln in billing_td.get_text(separator="\n").split("\n") if ln.strip()
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
                    ln.strip() for ln in addr_td.get_text(separator="\n").split("\n") if ln.strip()
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
    bulk_qty = bulk_cubic_yards(order)
    material = order.line_items[0].description if order.line_items else "material"
    qty_str = format_qty(total_qty)

    if "delivery" in order.shipping_method.lower():
        routing = "delivery"
        region = infer_region_from_address(order.shipping_address)
    else:
        routing = "pickup_self_load" if bulk_qty < 5 else "pickup_staff_load"
        yard = get_yard_for_order(order.shipping_method)
        region = yard.get("region", "unknown")

    try:
        db = get_firestore()
        db.collection("order_events").document(order.order_number).set(
            {
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
                "bulk_cubic_yards": bulk_qty,
                "material": material,
                "order_date": order.order_date,
                "customer_phone": order.customer_phone,
                "status": "success",
            }
        )
    except Exception as e:
        logger.error("Firestore write failed for order %s: %s", order.order_number, e)

    cc_list = [OFELIA_EMAIL] if OFELIA_EMAIL else []
    reply_to = get_reply_to(routing, region)

    if routing == "delivery":
        # Kendall's delivery copy tells the customer "I am CC'ing Greg Jackson",
        # so Greg has to be a real CC on this message, not only a recipient of
        # the separate internal alert below.
        coordinators = get_delivery_coordinator_emails(region)
        primary_coordinator = coordinators[0] if coordinators else None
        if primary_coordinator and primary_coordinator not in cc_list:
            cc_list = cc_list + [primary_coordinator]

        subject, text_body, html_body = build_delivery_email(
            order, coordinator_name=get_delivery_coordinator_name(region)
        )
        customer_email_sent = send_email(
            order.customer_email,
            subject,
            text_body,
            cc=cc_list,
            bcc=CONFIRMATION_BCC,
            html_body=html_body,
            reply_to=reply_to,
        )

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
        for coordinator in coordinators:
            send_email(coordinator, alert_subject, alert_body)
    else:
        yard = get_yard_for_order(order.shipping_method)
        if routing == "pickup_self_load":
            subject, text_body, html_body = build_pickup_self_load_email(order, yard)
        else:
            subject, text_body, html_body = build_pickup_staff_load_email(order, yard)
        customer_email_sent = send_email(
            order.customer_email,
            subject,
            text_body,
            cc=cc_list,
            bcc=CONFIRMATION_BCC,
            html_body=html_body,
            reply_to=reply_to,
        )

    # Record whether the customer email actually left the building. Without this
    # a Graph rejection is invisible after the fact and "I never got the email"
    # cannot be answered from the order record.
    try:
        get_firestore().collection("order_events").document(order.order_number).update(
            {
                "customer_email_sent": customer_email_sent,
                "customer_email_cc": cc_list,
                "customer_email_bcc": CONFIRMATION_BCC,
                "customer_email_reply_to": reply_to,
            }
        )
    except Exception as e:
        logger.error("Firestore email-status update failed for order %s: %s", order.order_number, e)

    master_sheet_rows = build_master_sheet_rows(order, routing)

    return {
        "status": "processed",
        "order_number": order.order_number,
        "routing": routing,
        "region": region,
        "total_qty": total_qty,
        "customer_email_sent": customer_email_sent,
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
    x_email_subject: str | None = Header(None, alias="X-Email-Subject"),
):
    if x_api_key != DISPATCH_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    content_type = (request.headers.get("content-type") or "").lower()
    raw_body = await request.body()

    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from e
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
        raise HTTPException(status_code=400, detail=f"Parse error: {e}") from e

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
    info_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
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
    customer_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
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
    order_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
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
    sig_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ]
        )
    )
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
                    orders.append(
                        {
                            "order_number": data.get("order_number"),
                            "order_date": data.get("order_date"),
                            "processed_at": processed_at.isoformat()
                            if hasattr(processed_at, "isoformat")
                            else str(processed_at),
                            "customer_name": data.get("customer_name"),
                            "customer_phone": data.get("customer_phone"),
                            "shipping_address": data.get("shipping_address"),
                            "material": data.get("material"),
                            "total_qty": data.get("total_qty"),
                            "region": data.get("region"),
                            "coupon_code": data.get("coupon_code"),
                        }
                    )
        orders.sort(key=lambda x: x.get("processed_at", ""), reverse=True)
        return {"status": "ok", "count": len(orders), "orders": orders}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
