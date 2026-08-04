"""Routing rules for OCWR pickup orders.

Dependency-free so it runs with `python tests/test_routing.py`; pytest will also
collect it if that ever gets added.

The rule these lock down came from Kendall on 2026-08-04. The crew loads with a
bucket loader from a single pile, so the 5-yard threshold is per material, not
per order, and OCWR will not coordinate mixed loads. Summing the order was the
earlier bug: it sent a customer with 2 yards of compost and 4 of mulch an email
demanding a commercial truck and a weigh-in at the scales.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GRAPH_TENANT_ID", "test")
os.environ.setdefault("GRAPH_CLIENT_ID", "test")
os.environ.setdefault("GRAPH_CLIENT_SECRET", "test")

from dispatch.main import (  # noqa: E402
    OrderPayload,
    bulk_yards_by_material,
    classify_pickup,
)

_FAILURES = []
_RUN = []


def check(label, actual, expected):
    _RUN.append(label)
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}: got {actual!r}, expected {expected!r}")
        _FAILURES.append(label)


def order(*items, shipping_method="Frank R. Bowerman Landfill Pick Up"):
    """items are (description, qty) pairs."""
    return OrderPayload(
        order_number="T1",
        order_date="08/04/2026",
        coupon_code="OCWR2026",
        payment_method="Coupon",
        customer_name="Test Customer",
        customer_email="test@example.com",
        customer_phone="555-0100",
        shipping_address="123 Main St, Irvine, CA 92618",
        billing_address="123 Main St, Irvine, CA 92618",
        shipping_method=shipping_method,
        line_items=[
            {"sku": d[:4].upper(), "description": d, "qty": q, "unit_price": 0.0} for d, q in items
        ],
        order_comments="",
    )


print("\nsingle material")
check("3 yards compost is self-load", classify_pickup(order(("Compost", 3))), "pickup_self_load")
check("4 yards compost is self-load", classify_pickup(order(("Compost", 4))), "pickup_self_load")
check(
    "5 yards compost is crew-load",
    classify_pickup(order(("Compost", 5))),
    "pickup_staff_load",
)
check(
    "8 yards mulch is crew-load",
    classify_pickup(order(("Mulch", 8))),
    "pickup_staff_load",
)

print("\nmixed, every material under 5: self-load however large the total")
check(
    "2 compost + 4 mulch is self-load, not crew-load",
    classify_pickup(order(("Compost", 2), ("Mulch", 4))),
    "pickup_self_load",
)
check(
    "4 compost + 4 mulch is self-load at 8 yards total",
    classify_pickup(order(("Compost", 4), ("Mulch", 4))),
    "pickup_self_load",
)

print("\nmixed, one material at 5 or more: special order")
check(
    "5 compost + 2 mulch is a special order",
    classify_pickup(order(("Compost", 5), ("Mulch", 2))),
    "pickup_special_order",
)
check(
    "4 compost + 5 mulch is a special order",
    classify_pickup(order(("Compost", 4), ("Mulch", 5))),
    "pickup_special_order",
)
check(
    "10 compost + 10 mulch is a special order",
    classify_pickup(order(("Compost", 10), ("Mulch", 10))),
    "pickup_special_order",
)

print("\naggregation is by material, not by line item")
check(
    "six 1-yard compost lines is one 6-yard material, so crew-load",
    classify_pickup(order(*[("Compost 1 CY", 1)] * 6)),
    "pickup_staff_load",
)
check(
    "six 1-yard compost lines total 6 yards of compost",
    bulk_yards_by_material(order(*[("Compost 1 CY", 1)] * 6)),
    {"compost": 6.0},
)

print("\nnon-yard units never score against a yard threshold")
check(
    "10 bags of compost is self-load",
    classify_pickup(order(("Organic Harvest Compost 1cf", 10))),
    "pickup_self_load",
)
check(
    "bags are excluded from the yard tally",
    bulk_yards_by_material(order(("Organic Harvest Compost 1cf", 10))),
    {},
)
check(
    "6 yards compost plus 10 bags is crew-load, not special",
    classify_pickup(order(("Compost", 6), ("Organic Harvest Compost 1cf", 10))),
    "pickup_staff_load",
)

print("\nedge cases")
check("empty order is self-load", classify_pickup(order()), "pickup_self_load")
check(
    "fractional yards under 5 is self-load",
    classify_pickup(order(("Compost", 4.5))),
    "pickup_self_load",
)

print(f"\n{len(_RUN) - len(_FAILURES)} passed, {len(_FAILURES)} failed\n")
sys.exit(1 if _FAILURES else 0)
