"""
Agromin Phase 1 — Process Diagram
Generates a Graphviz diagram of the two parallel automation workstreams:
  Workstream A: Sales Email Triage (sales@agromin.com → AI classification → rep routing)
  Workstream B: Order Dispatch Automation (OCWR CIMcloud orders → Cloud Run → fulfillment emails)

Output: phase1_process_diagram.pdf  (also renders .png if format changed below)

Requirements:
  pip install graphviz
  Graphviz binaries must be installed:
    macOS:  brew install graphviz
    Ubuntu: sudo apt-get install graphviz
"""

from graphviz import Digraph

# ── Color palette ────────────────────────────────────────────────────────────
C = {
    "inbox":      {"fill": "#dde8f8", "border": "#2d5fa6", "font": "#1e4080"},  # blue  – trigger
    "pa":         {"fill": "#e8e8f8", "border": "#5555aa", "font": "#33337a"},  # indigo – Power Automate
    "decision":   {"fill": "#fff6cc", "border": "#c49a00", "font": "#7a5c00"},  # amber – decision
    "ws_a":       {"fill": "#ddf0e8", "border": "#2e7d4f", "font": "#1d5c36"},  # green  – WS-A auto
    "ws_b":       {"fill": "#fde9cc", "border": "#c47c1a", "font": "#9a5e10"},  # orange – WS-B auto
    "log":        {"fill": "#f0eaff", "border": "#7c4dcc", "font": "#4a1a9e"},  # purple – logging/storage
    "email_out":  {"fill": "#e8f6ff", "border": "#1a7fc4", "font": "#0d4c7a"},  # sky    – outbound email
    "alert":      {"fill": "#ffe8e8", "border": "#c43030", "font": "#8a1515"},  # red    – alert
    "note":       {"fill": "#f5f5f5", "border": "#aaaaaa", "font": "#555555"},  # grey   – annotation
}

EDGE = "#666666"
EDGE_WS_A = "#2e7d4f"
EDGE_WS_B = "#c47c1a"


def node(g: Digraph, name: str, label: str, style: dict,
         shape: str = "box", extra: str = "") -> None:
    g.node(
        name,
        label=label,
        shape=shape,
        style="filled,rounded" if shape != "diamond" else "filled",
        fillcolor=style["fill"],
        color=style["border"],
        fontcolor=style["font"],
        fontname="Helvetica Neue,Helvetica,Arial,sans-serif",
        fontsize="11",
        penwidth="1.8",
        margin="0.18,0.1",
        **({} if not extra else {"tooltip": extra}),
    )


def diamond(g: Digraph, name: str, label: str, style: dict) -> None:
    g.node(
        name,
        label=label,
        shape="diamond",
        style="filled",
        fillcolor=style["fill"],
        color=style["border"],
        fontcolor=style["font"],
        fontname="Helvetica Neue,Helvetica,Arial,sans-serif",
        fontsize="10",
        penwidth="1.8",
    )


def edge(g: Digraph, src: str, dst: str, label: str = "",
         color: str = EDGE, style: str = "solid") -> None:
    g.edge(
        src, dst,
        label=label,
        color=color,
        fontcolor=color,
        fontname="Helvetica Neue,Helvetica,Arial,sans-serif",
        fontsize="9",
        arrowsize="0.7",
        penwidth="1.5",
        style=style,
        labeldistance="2.0",
    )


# ── Build diagram ─────────────────────────────────────────────────────────────
dot = Digraph(
    name="phase1",
    comment="Agromin Phase 1 — Automation Process Diagram",
    format="pdf",
)
dot.attr(
    rankdir="TB",
    splines="polyline",
    nodesep="0.55",
    ranksep="0.65",
    bgcolor="white",
    label=(
        "<<B>Agromin — Phase 1 Automation</B><BR/>"
        "<FONT POINT-SIZE='10' COLOR='#666666'>"
        "Workstream A: Sales Email Triage  |  "
        "Workstream B: OCWR Order Dispatch<BR/>"
        "Both workstreams monitor sales@agromin.com and must be coordinated before production</FONT>>"
    ),
    labelloc="t",
    fontname="Helvetica Neue,Helvetica,Arial,sans-serif",
    fontsize="14",
    pad="0.5",
)

# ── Shared entry ──────────────────────────────────────────────────────────────
node(dot, "inbox",
     "<<B>sales@agromin.com</B><BR/>"
     "<FONT POINT-SIZE='9'>Shared inbox — 13 delegates<BR/>"
     "~80% CIMcloud order noise / ~20% sales signal</FONT>>",
     C["inbox"])

node(dot, "pa_trigger",
     "<<B>Power Automate trigger</B><BR/>"
     "<FONT POINT-SIZE='9'>Office 365 Outlook connector<BR/>"
     "fires on every new inbound email</FONT>>",
     C["pa"])

diamond(dot, "d_coupon",
        "Contains\n\"Coupon Code:\"\nfield?",
        C["decision"])

edge(dot, "inbox", "pa_trigger", color=EDGE)
edge(dot, "pa_trigger", "d_coupon", color=EDGE)

# ── COORDINATION NOTE ─────────────────────────────────────────────────────────
dot.node(
    "coord_note",
    label=(
        "<<I>Coordination rule: Workstream B takes priority.<BR/>"
        "Workstream A triage classifier must recognize<BR/>"
        "CIMcloud order emails as already-handled<BR/>"
        "and exclude them from routing logic.</I>>"
    ),
    shape="note",
    style="filled",
    fillcolor=C["note"]["fill"],
    color=C["note"]["border"],
    fontcolor=C["note"]["font"],
    fontname="Helvetica Neue,Helvetica,Arial,sans-serif",
    fontsize="9",
    penwidth="1.2",
)
dot.edge("d_coupon", "coord_note", style="dashed", color="#aaaaaa",
         arrowhead="none", penwidth="1.0")

# ═══════════════════════════════════════════════════════════════════════════════
# WORKSTREAM B — Order Dispatch (left branch — YES path)
# ═══════════════════════════════════════════════════════════════════════════════
with dot.subgraph(name="cluster_ws_b") as b:
    b.attr(
        label=(
            "<<B>  Workstream B — OCWR Order Dispatch  </B><BR/>"
            "<FONT POINT-SIZE='9' COLOR='#9a5e10'>"
            "Technology: Power Automate → Google Cloud Run → Firestore | Cost: ~$0–2/mo</FONT>>"
        ),
        style="rounded,filled",
        fillcolor="#fff9f3",
        color=C["ws_b"]["border"],
        fontname="Helvetica Neue,Helvetica,Arial,sans-serif",
        fontsize="11",
        penwidth="2.0",
        labelloc="t",
    )

    node(b, "b_parse",
         "<<B>Parse order details</B><BR/>"
         "<FONT POINT-SIZE='9'>Power Automate HTML body parsing<BR/>"
         "extracts: customer, address, material,<BR/>"
         "quantity, coupon code</FONT>>",
         C["ws_b"])

    node(b, "b_cloudrun",
         "<<B>Cloud Run dispatch service</B><BR/>"
         "<FONT POINT-SIZE='9'>Google Cloud Run (GCP)<BR/>"
         "receives structured order payload<BR/>"
         "applies fulfillment logic</FONT>>",
         C["ws_b"])

    diamond(b, "d_fulfill",
            "Delivery\nor pickup?",
            C["decision"])

    # ── DELIVERY branch ───────────────────────────────────────────────────────
    node(b, "b_del_email",
         "<<B>Send delivery instructions email</B><BR/>"
         "<FONT POINT-SIZE='9'>From: dispatch@agromin.com<BR/>"
         "To: customer — via M365 shared mailbox (Send As)</FONT>>",
         C["email_out"])

    node(b, "b_del_alert",
         "<<B>Alert delivery coordinator</B><BR/>"
         "<FONT POINT-SIZE='9'>From: dispatch@agromin.com<BR/>"
         "Notification on every delivery order</FONT>>",
         C["alert"])

    # ── PICKUP branch ─────────────────────────────────────────────────────────
    diamond(b, "d_qty",
            "Quantity\n≥ 5 cu yds?",
            C["decision"])

    node(b, "b_self_email",
         "<<B>Self-load instructions email</B><BR/>"
         "<FONT POINT-SIZE='9'>From: dispatch@agromin.com<BR/>"
         "Customer picks up &lt;5 cu yds — self-serve</FONT>>",
         C["email_out"])

    node(b, "b_staff_email",
         "<<B>Staff-load instructions email</B><BR/>"
         "<FONT POINT-SIZE='9'>From: dispatch@agromin.com<BR/>"
         "Customer picks up ≥5 cu yds — staff assists</FONT>>",
         C["email_out"])

    # ── Logging ───────────────────────────────────────────────────────────────
    node(b, "b_firestore",
         "<<B>Log order to Firestore</B><BR/>"
         "<FONT POINT-SIZE='9'>Google Cloud Firestore<BR/>"
         "operational record of every OCWR order<BR/>"
         "customer · material · fulfillment type · status</FONT>>",
         C["log"])

    node(b, "b_pdf",
         "<<B>Generate PDF delivery manifest</B><BR/>"
         "<FONT POINT-SIZE='9'>On request — coordinator workflow</FONT>>",
         C["ws_b"])

    edge(b, "b_parse",     "b_cloudrun",   color=EDGE_WS_B)
    edge(b, "b_cloudrun",  "d_fulfill",    color=EDGE_WS_B)
    edge(b, "d_fulfill",   "b_del_email",  label="delivery", color=EDGE_WS_B)
    edge(b, "b_del_email", "b_del_alert",  color=EDGE_WS_B)
    edge(b, "d_fulfill",   "d_qty",        label="pickup",   color=EDGE_WS_B)
    edge(b, "d_qty",       "b_self_email", label="no (<5)",  color=EDGE_WS_B)
    edge(b, "d_qty",       "b_staff_email",label="yes (≥5)", color=EDGE_WS_B)
    edge(b, "b_del_alert", "b_firestore",  color=EDGE_WS_B)
    edge(b, "b_self_email","b_firestore",  color=EDGE_WS_B)
    edge(b, "b_staff_email","b_firestore", color=EDGE_WS_B)
    edge(b, "b_firestore", "b_pdf",        label="on request",
         color=EDGE_WS_B, style="dashed")

# ═══════════════════════════════════════════════════════════════════════════════
# WORKSTREAM A — Sales Email Triage (right branch — NO path)
# ═══════════════════════════════════════════════════════════════════════════════
with dot.subgraph(name="cluster_ws_a") as a:
    a.attr(
        label=(
            "<<B>  Workstream A — Sales Email Triage  </B><BR/>"
            "<FONT POINT-SIZE='9' COLOR='#1d5c36'>"
            "Technology: Power Automate → Vertex AI Gemini 1.5 Flash (GCP) → SharePoint | Cost: ~$0/mo</FONT>>"
        ),
        style="rounded,filled",
        fillcolor="#f3faf6",
        color=C["ws_a"]["border"],
        fontname="Helvetica Neue,Helvetica,Arial,sans-serif",
        fontsize="11",
        penwidth="2.0",
        labelloc="t",
    )

    node(a, "a_openai",
         "<<B>Vertex AI — Gemini 1.5 Flash — classification</B><BR/>"
         "<FONT POINT-SIZE='9'>HTTP connector call to Cloud Run classifier service (GCP)<BR/>"
         "returns: category · confidence score<BR/>"
         "~$0.01/email | same GCP project as Workstream B</FONT>>",
         C["ws_a"])

    diamond(a, "d_category",
            "Email category?",
            C["decision"])

    node(a, "a_route",
         "<<B>Route to sales rep</B><BR/>"
         "<FONT POINT-SIZE='9'>Power Automate Outlook connector<BR/>"
         "assignment by territory + brand<BR/>"
         "(Agromin NorCal / California Compost SC)</FONT>>",
         C["ws_a"])

    node(a, "a_no_action",
         "<<B>No action / skip</B><BR/>"
         "<FONT POINT-SIZE='9'>CIMcloud order confirmations<BR/>"
         "already handled by Workstream B</FONT>>",
         C["note"])

    node(a, "a_spam",
         "<<B>No action / discard</B><BR/>"
         "<FONT POINT-SIZE='9'>Spam · unsolicited · out-of-scope</FONT>>",
         C["note"])

    node(a, "a_sharepoint",
         "<<B>Log to SharePoint list</B><BR/>"
         "<FONT POINT-SIZE='9'>Every email recorded:<BR/>"
         "sender · subject · category · assigned rep · AI confidence<BR/>"
         "Filtered views accessible by all 13 team members</FONT>>",
         C["log"])

    node(a, "a_shadow",
         "<<B>Shadow mode — 1 week</B><BR/>"
         "<FONT POINT-SIZE='9'>Routes logged but not sent<BR/>"
         "before going live; accuracy validated</FONT>>",
         C["ws_a"])

    edge(a, "a_openai",   "d_category",  color=EDGE_WS_A)
    edge(a, "d_category", "a_route",
         label="RFQ / new inquiry\n/ project request",     color=EDGE_WS_A)
    edge(a, "d_category", "a_no_action",
         label="order confirmation\n(CIMcloud — WS-B handled)", color=EDGE_WS_A)
    edge(a, "d_category", "a_spam",
         label="spam / other",                             color=EDGE_WS_A)
    edge(a, "a_route",    "a_sharepoint",                  color=EDGE_WS_A)
    edge(a, "a_no_action","a_sharepoint",                  color=EDGE_WS_A)
    edge(a, "a_spam",     "a_sharepoint",                  color=EDGE_WS_A)
    edge(a, "a_sharepoint","a_shadow",   style="dashed",   color=EDGE_WS_A)

# ── Cross-subgraph edges (shared trigger → workstreams) ───────────────────────
edge(dot, "d_coupon", "b_parse",
     label="YES — OCWR order", color=EDGE_WS_B)
edge(dot, "d_coupon", "a_openai",
     label="NO — other email", color=EDGE_WS_A)

# ── Render ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    dot.render(
        filename="phase1_process_diagram",
        directory=".",
        cleanup=True,
        view=False,
    )
    print("Diagram written to: phase1_process_diagram.pdf")

    dot.format = "png"
    dot.attr(dpi="150")
    dot.render(
        filename="phase1_process_diagram",
        directory=".",
        cleanup=True,
        view=False,
    )
    print("Diagram written to: phase1_process_diagram.png")
