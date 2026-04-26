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
import re
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO

from fastapi import FastAPI, Header, HTTPException
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

SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

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
        "address": "1942 N. Valencia Ave, Brea, CA 92823",
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
# FIRESTORE
# ---------------------------------------------------
_firestore_db = None


def get_firestore():
    global _firestore_db
    if _firestore_db is None:
        _firestore_db = firestore_client.Client()
    return _firestore_db


# ---------------------------------------------------
# EMAIL
# ---------------------------------------------------
def send_email(to: str, subject: str, body: str, cc: list = None):
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured — email skipped (to=%s)", to)
        return
    try:
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg.attach(MIMEText(body, "plain"))
        recipients = [to] + (cc or [])
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(SMTP_USER, recipients, msg.as_string())
        logger.info("Email sent to %s subject: %s", to, subject)
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

{sb1383_note}
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
Delivery Address: {shipping_address}
Material:         {qty} cubic yards of {material}
Coupon Code:      {coupon_code}

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
# POST /api/ingest-order
# ---------------------------------------------------
@app.post("/api/ingest-order")
async def ingest_order(
    order: OrderPayload,
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    if x_api_key != DISPATCH_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

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
            shipping_address=order.shipping_address,
            qty=qty_str,
            material=material,
            coupon_code=coupon_code,
        )
        alert_subject = f"New Delivery Order #{order.order_number} — Action Required"
        for coordinator in get_delivery_coordinator_emails(region):
            send_email(coordinator, alert_subject, alert_body)
    else:
        yard = get_yard_for_order(order.shipping_method)
        sb1383 = SB1383_PARAGRAPH + "\n" if yard.get("qr_url") else ""
        template = PICKUP_SELF_LOAD_TEMPLATE if routing == "pickup_self_load" else PICKUP_STAFF_LOAD_TEMPLATE
        body = template.format(
            order_number=order.order_number,
            customer_name=order.customer_name,
            qty=qty_str,
            material=material,
            yard_name=yard["name"],
            yard_address=yard["address"],
            yard_phone=yard["phone"],
            yard_hours=yard["hours"],
            sb1383_note=sb1383,
        )
        subject = f"Your Agromin Order #{order.order_number} — Pickup Instructions"
        send_email(order.customer_email, subject, body, cc=cc_list)

    return {
        "status": "processed",
        "order_number": order.order_number,
        "routing": routing,
        "region": region,
        "total_qty": total_qty,
    }


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
