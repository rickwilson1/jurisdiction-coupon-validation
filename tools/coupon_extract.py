"""
Search sales@agromin.com for a coupon code and extract structured customer
data from each matching CIMcloud email body.

Uses Microsoft Graph API with delegated auth (you sign in as yourself).
Self-contained — parser logic copied from dispatch/main.py.

Requirements (installed in the project venv):
    msal, requests, beautifulsoup4

Usage:
    source .venv/bin/activate
    python coupon_extract.py CITYSACCOMB26

Output:
    ~/Desktop/coupon_extract_<CODE>_<timestamp>.csv
"""
import csv
import quopri
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import msal
import requests
from bs4 import BeautifulSoup

# ────────────────────────────────────────────────────────────────────
# Graph API config
# ────────────────────────────────────────────────────────────────────
# Microsoft Graph PowerShell public client ID — Microsoft-owned, pre-authorized
# in every Azure AD tenant for Graph delegated access. Safer than the Azure CLI
# client ID, which some tenants restrict via preauthorization policy.
CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["https://graph.microsoft.com/Mail.Read.Shared"]

SHARED_MAILBOX = "sales@agromin.com"
PAGE_SIZE = 100


# ────────────────────────────────────────────────────────────────────
# CIMcloud email parser (copied from dispatch/main.py — self-contained)
# ────────────────────────────────────────────────────────────────────
@dataclass
class LineItem:
    sku: str
    description: str
    qty: float
    unit_price: float


@dataclass
class OrderPayload:
    order_number: str
    order_date: str
    coupon_code: str
    payment_method: str
    customer_name: str
    customer_email: str
    customer_phone: str
    billing_address: str
    shipping_address: str
    shipping_method: str
    line_items: list = field(default_factory=list)


class CimcloudParseError(ValueError):
    pass


def _maybe_decode_quoted_printable(body: str) -> str:
    if re.search(r"=\r?\n", body) or "=3D" in body or "=3d" in body:
        try:
            return quopri.decodestring(body.encode("latin-1")).decode(
                "utf-8", errors="replace"
            )
        except Exception:
            return body
    return body


def _value_after_label(soup: BeautifulSoup, label: str) -> str | None:
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


def _parse_line_items(soup: BeautifulSoup) -> list:
    items = []
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
            items.append(LineItem(sku=sku, description=description, qty=qty, unit_price=unit_price))
        break
    return items


def parse_cimcloud_email(html_body: str) -> OrderPayload:
    body = _maybe_decode_quoted_printable(html_body or "")
    soup = BeautifulSoup(body, "html.parser")

    full_text = soup.get_text(separator="\n")
    if "Coupon Code:" not in full_text:
        raise CimcloudParseError("no Coupon Code field — not a program order")

    m = re.search(r"Your order number is\s+([A-Z0-9\-]+)\s*\.", full_text)
    if not m:
        raise CimcloudParseError("could not find order number")
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
        seen = []
        for ln in raw_lines:
            if ln not in seen:
                seen.append(ln)
        if seen:
            customer_name = seen[0]
            addr_parts = [
                ln for ln in seen[1:]
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
    )


# ────────────────────────────────────────────────────────────────────
# Graph API auth + search
# ────────────────────────────────────────────────────────────────────
def get_token() -> str:
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Device flow failed to start: {flow}")
    print(flow["message"])
    print("\nWaiting for sign-in to complete...")
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Auth failed: {result.get('error_description', result)}")
    return result["access_token"]


def search_messages(token: str, query: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "ConsistencyLevel": "eventual",
    }
    url = (
        f"https://graph.microsoft.com/v1.0/users/{SHARED_MAILBOX}/messages"
        f"?$search=\"{query}\""
        f"&$select=id,subject,from,receivedDateTime,parentFolderId,body"
        f"&$top={PAGE_SIZE}"
    )
    while url:
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code == 401:
            raise RuntimeError("Graph 401 — token expired. Re-run.")
        if resp.status_code == 403:
            raise RuntimeError(
                f"Graph 403 — you may lack shared-mailbox access to {SHARED_MAILBOX}."
            )
        resp.raise_for_status()
        data = resp.json()
        yield from data.get("value", [])
        url = data.get("@odata.nextLink")


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: python coupon_extract.py <COUPON_CODE>")
        sys.exit(1)
    code = sys.argv[1].strip().upper()

    print("Authenticating...\n")
    token = get_token()

    print(f"\nSearching {SHARED_MAILBOX} for {code!r}...\n")
    results = []
    errors = []
    seen_orders = set()
    scanned = 0
    skipped_non_cimcloud = 0
    skipped_wrong_code = 0

    for msg in search_messages(token, code):
        scanned += 1
        if scanned % 100 == 0:
            print(f"  scanned {scanned}, matched {len(results)} so far")

        html = (msg.get("body") or {}).get("content", "")
        try:
            order = parse_cimcloud_email(html)
        except CimcloudParseError:
            skipped_non_cimcloud += 1
            continue
        except Exception as e:
            errors.append((msg.get("id"), str(e)))
            continue

        if order.coupon_code.upper() != code:
            skipped_wrong_code += 1
            continue

        if order.order_number in seen_orders:
            continue
        seen_orders.add(order.order_number)

        results.append({
            "order_number":     order.order_number,
            "order_date":       order.order_date,
            "customer_name":    order.customer_name,
            "customer_email":   order.customer_email,
            "customer_phone":   order.customer_phone,
            "billing_address":  order.billing_address,
            "shipping_address": order.shipping_address,
            "shipping_method":  order.shipping_method,
            "coupon_code":      order.coupon_code,
            "total_qty":        sum(li.qty for li in order.line_items),
            "email_subject":    msg.get("subject"),
            "received_at":      msg.get("receivedDateTime"),
        })

    print("\n──────────────────────────────────────")
    print(f"  Messages scanned:        {scanned}")
    print(f"  Non-CIMcloud (skipped):  {skipped_non_cimcloud}")
    print(f"  Wrong coupon (skipped):  {skipped_wrong_code}")
    print(f"  Parse errors:            {len(errors)}")
    print(f"  Unique matched orders:   {len(results)}")
    print("──────────────────────────────────────")

    if not results:
        print("\nNo matching CIMcloud orders found.")
        return

    out = Path.home() / "Desktop" / (
        f"coupon_extract_{code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print(f"\n✓ CSV: {out}")


if __name__ == "__main__":
    main()
