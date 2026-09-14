"""Render a Graphviz diagram of OCWR coupon-dispatch routing.

Usage:
    python dispatch_logic_graph.py

Writes dispatch_logic.png and dispatch_logic.svg next to this file.
Requires the system Graphviz binary (`dot`); no Python graphviz package needed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOT_PATH = HERE / "dispatch_logic.dot"
PNG_PATH = HERE / "dispatch_logic.png"
SVG_PATH = HERE / "dispatch_logic.svg"

DOT_SOURCE = r"""
digraph coupon_dispatch {
  rankdir=TB;
  splines=polyline;
  nodesep=0.45;
  ranksep=0.55;
  bgcolor=white;

  node [
    shape=box,
    style="rounded,filled",
    fontname="Helvetica",
    fontsize=11,
    margin="0.18,0.12"
  ];
  edge [
    fontname="Helvetica",
    fontsize=10,
    color="#444444"
  ];

  // Intake
  intake [
    label="CIMcloud order confirmation\n→ Power Automate\n→ POST /api/ingest-cimcloud-email",
    fillcolor="#E8F1F8"
  ];
  parse [
    label="Parse order\nmaterials · yards by material\nshipping method · region",
    fillcolor="#E8F1F8"
  ];
  store [
    label="Write Firestore\norder_events",
    fillcolor="#F0F0F0"
  ];

  intake -> parse;
  parse -> store;

  // Top-level split
  ship_q [
    label="shipping_method\ncontains \"delivery\"?",
    shape=diamond,
    fillcolor="#FFF3CD"
  ];
  store -> ship_q;

  // Delivery
  subgraph cluster_delivery {
    label="Delivery";
    color="#5B8C5A";
    style=rounded;
    fontname="Helvetica";

    del_email [
      label="Customer: Delivery receipt\nCC Ofelia + primary coordinator\nBCC Kendall\nReply-To: coordinator + dispatch",
      fillcolor="#D9EAD3"
    ];
    del_alert [
      label="Internal alert\nOC: Greg, Brian, Kendall\nVentura: Chris\nSacramento: Rosa",
      fillcolor="#D9EAD3"
    ];
    del_email -> del_alert [label="also"];
  }
  ship_q -> del_email [label="yes"];

  // Pickup classifier
  pick_q [
    label="classify_pickup()\nmax yards per material\n(bulk CY only; bags ignored)",
    shape=diamond,
    fillcolor="#FFF3CD"
  ];
  ship_q -> pick_q [label="no → pickup"];

  self_q [
    label="every material\nunder 5 CY?",
    shape=diamond,
    fillcolor="#FFF3CD"
  ];
  pick_q -> self_q;

  self_email [
    label="Customer: Under-5 self-load\nlists all 3 greeneries\nCC Ofelia · BCC Kendall\nReply-To: Kendall + dispatch",
    fillcolor="#CFE2F3"
  ];
  self_q -> self_email [label="yes"];

  special_q [
    label="one material ≥ 5 CY\nAND another material?",
    shape=diamond,
    fillcolor="#FFF3CD"
  ];
  self_q -> special_q [label="no"];

  subgraph cluster_special {
    label="Special order (mixed load)";
    color="#B45F06";
    style=rounded;
    fontname="Helvetica";

    special_email [
      label="Customer: Holding note\n\"Review in Progress\"\nCC Ofelia · BCC Kendall\nReply-To: Kendall + dispatch",
      fillcolor="#FCE5CD"
    ];
    special_alert [
      label="Internal alert → Kendall\n(SPECIAL_ORDER_ALERT_TO)",
      fillcolor="#FCE5CD"
    ];
    special_email -> special_alert [label="also"];
  }
  special_q -> special_email [label="yes"];

  staff_email [
    label="Customer: Over-5 crew-load\nlists all 3 greeneries\nCC Ofelia · BCC Kendall\nReply-To: Kendall + dispatch",
    fillcolor="#D0E0E3"
  ];
  special_q -> staff_email [label="no\n(single material ≥ 5)"];

  // Examples
  examples [
    label="Examples\n3 CY compost → self-load\n8 CY compost → crew-load\n2 CY compost + 4 CY mulch → self-load\n5 CY compost + 2 CY mulch → special order",
    shape=note,
    fillcolor="#FFFDE7",
    fontsize=10
  ];
  pick_q -> examples [style=dashed, color="#999999"];
}
"""


def main() -> int:
    if not shutil.which("dot"):
        print("Graphviz `dot` not found on PATH.", file=sys.stderr)
        return 1

    DOT_PATH.write_text(DOT_SOURCE.strip() + "\n", encoding="utf-8")

    for fmt, out in (("png", PNG_PATH), ("svg", SVG_PATH)):
        subprocess.run(
            ["dot", f"-T{fmt}", str(DOT_PATH), "-o", str(out)],
            check=True,
        )
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
