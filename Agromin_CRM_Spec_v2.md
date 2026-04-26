# AGROMIN
## Commercial Operations Modernization
### CRM Evaluation & Sales Inbox Specification

| | |
|---|---|
| **Prepared by** | Rick Wilson, PhD, MBA |
| **Date** | April 2026 |
| **Status** | DRAFT — For Company Review |
| **Version** | 2.0 |

---

## Executive Summary

This document presents findings from an audit of Agromin's `sales@agromin.com` shared mailbox, a CRM evaluation framework, and a proposed two-phase commercial operations modernization plan. It is intended to align the leadership team on the problem, the options, and the decision needed.

**Key Findings**

- **Current state:** 13 people manually search through a shared inbox with no routing, no automation, and no CRM. Sales leads are buried in order confirmation noise.
- **The mailbox receives an estimated 80% automated CIMcloud order traffic** and only 5–20% actual sales inquiries per week, creating a significant signal-to-noise problem.
- **Two parallel automation workstreams** are now underway that both touch the same inbox and must be coordinated: (1) sales email triage and routing, and (2) order dispatch automation for the OCWR compost program.
- **Phase 1** (email triage + order dispatch) can be built immediately at $0 incremental cost using existing Microsoft 365 licenses, idle Azure OpenAI resource already provisioned, and existing Google Cloud infrastructure.
- **Phase 2** (CRM) requires a formal evaluation. Sage 100 native integration is the make-or-break criterion. Most CRMs require $300–500/month additional middleware, inflating true total cost materially above license price alone.
- **Method:CRM and Sage CRM** offer native Sage 100 integration at significantly lower cost than Dynamics 365 or Salesforce. **Method:CRM is the leading candidate** based on cost, Sage 100 integration depth, and fit for Agromin's scale.

**Decisions Requested**

1. Approve Phase 1 email triage build to proceed immediately (no new budget required).
2. Approve Phase 1 order dispatch build to proceed immediately (GCP infrastructure already in place).
3. Authorize demos of top 3 CRM candidates (Method:CRM, Sage CRM, D365 Sales) within 30 days.
4. Designate a CRM decision owner and target decision date.

---

## 1. Current State

### 1.1 Technology Stack

| System | Vendor | Purpose | Status |
|---|---|---|---|
| Sage 100 | Sage / Blytheco | ERP: customers, products, pricing, orders, AR/AP, inventory | Active — System of Record |
| CIMcloud | Website Pipeline | B2B customer portal: online ordering, account history, pricing, inventory sync from Sage 100 | Active — Customer Portal |
| Microsoft 365 | Microsoft / MSP | Email (Exchange Online), Teams, SharePoint, Office apps — 47 Business Standard + 24 Basic seats | Active |
| Azure OpenAI | Microsoft | gpt-4.1 model deployed in rg-agromin-ai (West US). Provisioned, idle, near-zero cost. | Provisioned — Unused |
| Google Cloud Platform | Google | Cloud Run services, Cloud Storage, Firestore. Hosts coupon validator and order dispatch service. | Active |
| CRM | — | No CRM exists. No lead tracking, pipeline, opportunity management, or activity logging. | **Does Not Exist** |

### 1.2 Sales Inbox Audit Findings

| Finding | Detail |
|---|---|
| Mailbox access | 13 people have Full Access delegation. All manually browse to find relevant emails. |
| NorCal folder | ~953 items — primarily CIMcloud automated order confirmations and pending approvals (Agromin brand). |
| Santa Clarita folder | ~938 items — same pattern, California Compost brand. Two distinct go-to-market identities. |
| Noise vs. signal | Est. 80% of volume is automated CIMcloud system mail. Real sales inquiries (RFQs, quotes, new business) estimated at 5–20/week. |
| Actual sales inquiries found | Mulch quote requests, institutional RFQs, production project inquiries. High-value but buried. |
| Brands | Agromin (NorCal) and California Compost (Santa Clarita) operate as distinct go-to-market identities through the same mailbox. |
| Routing | None. No Exchange transport rules, no Power Automate flows, no triage logic. Manual only. |

---

## 2. Phase 1 — Immediate Automation (No New Budget Required)

Phase 1 consists of two parallel workstreams that both proceed immediately and independently of the CRM decision. They share the same inbox but serve different purposes and must be coordinated to avoid conflict.

### 2.1 Workstream A — Sales Email Triage

Monitors `sales@agromin.com` for inbound sales inquiries and routes them to the right person.

**What It Does**
- Monitors the mailbox in real time for new inbound emails
- Classifies each email by category (order confirmation, RFQ, new business inquiry, customer service, spam, etc.) using Azure OpenAI gpt-4.1
- Routes actionable emails (RFQs, new inquiries, project requests) to the appropriate sales rep based on territory and brand
- Logs every email — sender, subject, category, assigned rep, AI confidence score — to a SharePoint list accessible by all team members
- Runs in shadow mode for one week before going live to validate accuracy

**Architecture**

| Component | Technology | Cost |
|---|---|---|
| Email trigger | Power Automate (Office 365 Outlook connector) | $0 — included in M365 |
| AI classification | Azure OpenAI gpt-4.1 via HTTP connector | ~$0.01/email |
| Routing | Power Automate Outlook connector | $0 — included in M365 |
| Logging / view | SharePoint list + filtered views | $0 — included in M365 |
| Build license | Power Apps Premium (1 seat, already assigned) | $0 — already paid |
| **Total incremental cost** | | **$0/month** |

### 2.2 Workstream B — Order Dispatch Automation (OCWR Program)

Automates the fulfillment workflow for the OCWR free compost and mulch program. This is a separate system from sales triage and operates on different email triggers.

**What It Does**
- Monitors `sales@agromin.com` for CIMcloud order confirmation emails that contain a `Coupon Code:` field — identifying them as OCWR program orders
- Parses order details and routes them to the Cloud Run dispatch service
- Dispatch service determines fulfillment type: delivery vs. pickup, quantity threshold (<5 cu yds self-load / ≥5 cu yds staff-load)
- Sends the correct instructions email to the customer automatically
- Alerts Greg Jackson on every delivery order
- Logs order to Firestore (Google Cloud) as the operational record
- Generates PDF delivery manifests on request

**Why these two workstreams must be coordinated:** Both Workstream A and Workstream B watch `sales@agromin.com`. The triage classifier in Workstream A must be configured to recognize CIMcloud order confirmation emails as a known, handled category — not classify them as sales inquiries. The dispatch Power Automate flow processes these emails first; Workstream A should exclude them from its routing logic. This must be designed explicitly before either workstream goes to production.

**Architecture**

| Component | Technology | Cost |
|---|---|---|
| Email trigger | Power Automate (Office 365 Outlook connector) | $0 — included in M365 |
| Order parsing | Power Automate — HTML body parsing | $0 |
| Dispatch service | Google Cloud Run | ~$0 (free tier at this volume) |
| Data store | Google Cloud Firestore | ~$0 (free tier) |
| Email sending | M365 SMTP relay (smtp.office365.com) | $0 |
| **Total incremental cost** | | **$0–2/month** |

### 2.3 Phase 1 Does NOT Replace a CRM

Phase 1 routes emails, dispatches orders, and provides operational logs. It does not manage pipelines, opportunities, forecasts, customer history, or sales activity. It is a triage and routing layer that sits in front of whatever CRM Agromin selects — and feeds it.

---

## 3. CRM Evaluation

### 3.1 Why CRM Now

- No system of record exists for sales leads, opportunities, customer relationships, or sales activity. This information lives in individual email inboxes and people's heads.
- CIMcloud manages transactional customer relationships (orders, account history). It does **not** manage pre-sale (lead, opportunity, pipeline) or relationship management (activity, follow-up, forecasting).
- As Agromin grows, the absence of a CRM creates scaling risk: lost leads, no visibility into pipeline, no ability to forecast, no onboarding path for new sales hires.
- The order dispatch system (Workstream B) also needs a structured data destination for operational records. The selected CRM should serve both the sales team and the dispatch workflow if its API supports programmatic writes.

### 3.2 Decision Criteria

| # | Criterion | Why It Matters | Weight |
|---|---|---|---|
| 1 | **Sage 100 integration quality** | Sage 100 is the system of record. Without sync, CRM has no customer history, AR aging, pricing, or order data. Middleware adds $300–500/month and introduces failure points. | **CRITICAL** |
| 2 | **Total cost (license + middleware)** | License price alone is misleading. D365 at $65/seat looks comparable to Method:CRM at $44/seat until you add $500/month Sage middleware. Evaluate fully-loaded cost. | HIGH |
| 3 | **CIMcloud coexistence** | CIMcloud stays as the customer B2B portal. The CRM should not duplicate or conflict with CIMcloud's customer-facing function. Clean handoff required. | HIGH |
| 4 | **User adoption / UX simplicity** | A CRM that sales reps won't use is worthless. Evaluate with the actual sales team. Mobile access is required. | HIGH |
| 5 | **M365 / Outlook integration** | Reps live in Outlook. Email activity should log to CRM automatically. Teams integration is a plus. | MEDIUM |
| 6 | **Implementation complexity** | Agromin does not have an internal IT team for CRM implementation. Simpler = faster time to value and lower risk. | MEDIUM |
| 7 | **Scalability** | Must support additional reps, territories, product lines, and potentially Agromin + California Compost as separate entities. | MEDIUM |
| 8 | **Dispatch system API** | The order dispatch service (Workstream B) needs to write operational records to the CRM programmatically. REST API with custom field support required. If absent, Firestore serves as a separate fallback at $0 cost — this is not a blocker for CRM selection but is a factor. | MEDIUM |
| 9 | **Marketing automation** | D365 Customer Insights is $1,500/month flat. Only justified if Agromin runs structured outbound campaigns. Validate the use case before committing. | EVALUATE |

### 3.3 Evaluation Methodology

Each CRM candidate is evaluated through a structured demo and scored using the rubric below. Each criterion is scored 1–5 and multiplied by its weight. The vendor with the highest weighted total advances to final negotiation. A score of 1 or 2 on any **CRITICAL** criterion is an automatic disqualifier.

**Scoring Scale**

| Score | Definition |
|---|---|
| 5 | Fully meets requirement. Native capability, no workaround or add-on needed. |
| 4 | Meets requirement with minor configuration. No custom development or middleware. |
| 3 | Partially meets requirement. Requires paid add-on, middleware, or moderate customization. |
| 2 | Significant gap. Requires heavy customization, unreliable third-party integration, or manual workaround. |
| 1 | Does not meet requirement. No viable path to compliance. |

**Weighted Scoring Rubric** *(complete one per vendor per evaluator)*

| # | Criterion | Weight | What to Evaluate in Demo |
|---|---|---|---|
| 1 | Sage 100 Integration | 5x | Live demo of Sage 100 sync: customer master, AR aging, order history, pricing. Confirm sync direction, latency, failure handling. **GATE: Score ≤ 2 = auto-disqualify.** |
| 2 | Total Cost | 4x | Fully-loaded monthly cost at 8 reps: license + middleware + implementation amortized over 12 months. Vendor must provide written quote. |
| 3 | CIMcloud Coexistence | 4x | Confirm CRM does not duplicate CIMcloud portal functions. Both pull from Sage 100 as master — no data conflict or dual entry. |
| 4 | User Adoption / UX | 4x | Sales reps score ease of use during demo. Mobile app walkthrough required. Can a new hire be productive in under 1 day? |
| 5 | M365 / Outlook Integration | 3x | Demo Outlook sidebar or email tracking. Auto-log emails to contacts/opportunities. Teams integration a plus. |
| 6 | Implementation Complexity | 3x | Vendor provides implementation timeline, resource requirements, and who does the work. No internal IT team available. |
| 7 | Scalability | 2x | Can the platform support additional reps, territories, brands, and product lines without re-architecture? |
| 8 | Dispatch System API | 2x | Does the platform provide a REST API for programmatic record creation and update? Can custom fields be added to deal/contact records? Demo a test write via API. |
| 9 | Marketing Automation | 1x | Does the platform offer or integrate with marketing automation? Evaluate only if Agromin confirms structured outbound campaign plans. |
| | **Max weighted score** | **130** | Sum of (Score × Weight) across all criteria. Highest total wins, subject to no CRITICAL disqualifier. |

---

## 4. CRM Options Evaluated

> **Note — Method:CRM removed from consideration (April 2026):** Method:CRM is built exclusively for QuickBooks and Xero. It does not integrate with Sage 100. It was included in the original v1.1 spec in error and has been removed. Sage CRM is now the sole native Sage 100 candidate.

### 4.1 Comparison Matrix — Cost & Integration

| CRM | Sage 100 Integration | $/user/mo | Middleware/mo | Total @ 8 Reps/mo |
|---|---|---|---|---|
| **Sage CRM** | Native — same vendor, guaranteed sync | ~$45 | $0 | ~$360/mo |
| D365 Sales | Middleware required (Commercient SYNC) | $65–135 | ~$500 | ~$1,580/mo |
| Salesforce | Middleware required (Commercient SYNC) | $75–150 | ~$500 | ~$1,700/mo |
| HubSpot CRM | Generic middleware only (Zapier/Boomi) | $0–800 flat | ~$300+ | Variable |
| Zoho CRM | Sage connector available, lower quality | $14–52 | ~$200+ | ~$620/mo |
| Method:CRM | QuickBooks/Xero only — no Sage 100 | $25–44 | N/A | **Not applicable** |

### 4.1b Comparison Matrix — Features & Fit

| CRM | M365 / Outlook | Dispatch API | Recommendation |
|---|---|---|---|
| **Sage CRM** | Yes | Verify in demo | **TOP PICK** |
| D365 Sales | Native | Yes — excellent | Viable if Microsoft stack committed |
| Salesforce | Yes | Yes — excellent | Not recommended |
| HubSpot CRM | Yes | Yes — excellent | Not recommended — middleware cost + no native Sage 100 sync |
| Zoho CRM | Partial | Partial | Not recommended |
| Method:CRM | Yes | Yes | **Not applicable** — QuickBooks only |

### 4.2 Top Candidates — Detail

**Sage CRM** *(Leading Candidate)*

Same vendor as Sage 100. Native integration is guaranteed and maintained by the vendor — not dependent on a third-party connector.

- Native bidirectional sync with Sage 100: customer master, AR aging, order history, pricing
- Single-vendor relationship reduces implementation risk and support complexity
- Sales reps see complete customer picture from Sage 100 without leaving the CRM
- ~$45/user/month. At 8 reps ≈ $360/month total. No middleware cost
- CIMcloud coexists cleanly — both pull from Sage 100 as the master
- UX is older than newer platforms — evaluate user adoption risk with the sales team before committing
- **Key verification needed:** REST API capability for programmatic writes from the dispatch service. Confirm in demo.

**Dynamics 365 Sales** *(High Cost — Evaluate if Microsoft Stack Is the Direction)*

Strong platform with deep Microsoft ecosystem integration (Teams, Outlook, LinkedIn, Power Platform, Copilot AI).

- AI-native: Copilot for Sales, conversation intelligence, relationship analytics
- Does **not** integrate natively with Sage 100. Requires Commercient SYNC or equivalent middleware (~$500/month additional)
- At 8 reps (Premium): $1,080 license + $500 middleware = **$1,580/month** — approximately 4.4x the cost of Sage CRM
- D365 Customer Insights (Marketing): $1,500/month flat tenant fee. Only justified with structured outbound campaigns. Evaluate separately
- Correct path **only** if Agromin makes a strategic commitment to the Microsoft commercial stack and can justify the cost delta
- A trial has been self-initiated internally. The trial should be treated as one input into the formal evaluation, not as a de facto commitment. Trials will not auto-convert to paid. Preserve until evaluation is complete, then convert or allow to expire based on the formal decision

---

## 5. ERP Horizon — A Decision That Shapes CRM Selection

The CRM recommendation in this document is optimized for Agromin's current ERP: **Sage 100**. Before committing to a Sage-native CRM, leadership should answer one question:

> **Is Sage 100 a 5-year platform for Agromin, or are we likely to outgrow it?**

This matters because the leading CRM candidate — Sage CRM — derives its primary advantage from native Sage 100 integration. If Agromin migrates to a cloud ERP within 2–3 years, that advantage disappears and the switching cost is paid twice.

### Signs Sage 100 may have a limited horizon

- Growing complexity in multi-entity operations, inventory, or distribution that Sage 100 handles with workarounds
- Increasing integration tax — every new tool (CRM, ecommerce, dispatch) requires custom connectors because Sage 100's API is limited
- Sage is actively migrating its customer base toward Sage Intacct (cloud) and X3 for larger operations; Sage 100 is a mature, declining product line

### What a cloud ERP migration would mean for CRM

Most modern cloud ERPs (NetSuite, Sage Intacct, Microsoft Business Central) have native connectors to HubSpot, Salesforce, and Dynamics 365 — platforms with stronger ecosystems, better AI features, and broader user adoption. If Agromin is on a cloud ERP within 3 years, the correct CRM choice today may be different.

### Recommendation

If the internal answer is **"Sage 100 for 5+ years"** — proceed with Sage CRM as recommended. The native sync is a genuine operational advantage worth optimizing for.

If the answer is **"uncertain"** or **"we're actively discussing a move"** — have the ERP conversation before committing to a Sage-native CRM. A 30-day pause to answer that question is cheaper than buying a platform optimized for a system you're about to leave.

This document does not recommend an ERP change. It recommends that the question be asked and answered explicitly before the CRM decision is finalized.

---

## 6. CIMcloud — Role Clarification

CIMcloud is Agromin's B2B customer portal. It is **not a CRM** and should not be evaluated as one. Its role is distinct and should be preserved regardless of CRM selection.

| CIMcloud Does | CIMcloud Does NOT Do |
|---|---|
| B2B customer self-service portal | Lead management or pipeline tracking |
| Online order entry by customers | Sales rep activity logging |
| Account history and order status | Opportunity management or forecasting |
| Real-time inventory and pricing from Sage 100 | Inbound lead capture or routing |
| Customer-facing account management | Sales performance reporting |

The CRM and CIMcloud serve complementary, non-overlapping functions. The CRM manages the pre-sale and relationship layer; CIMcloud manages the transactional customer portal. Both are required and neither replaces the other.

---

## 6. Dispatch System and CRM — Integration Approach

The order dispatch system (Workstream B) writes one structured record per program order. The destination is configurable. The preferred approach depends on CRM selection:

**If selected CRM has a workable REST API (likely):**
The dispatch service writes directly to the CRM. Order routing decisions, scheduled delivery dates, customer details, and fulfillment status sit alongside the full customer record in one system. Greg and Ofelia manage delivery workflow inside the CRM using its built-in views and fields.

**If selected CRM API is insufficient (fallback):**
The dispatch service writes to Google Cloud Firestore — a zero-cost, serverless NoSQL store already in use. Firestore serves as the operational data layer for dispatch workflow only. The CRM handles sales pipeline and relationship management. The two systems do not conflict. This fallback adds no cost and no new platform dependency.

Either path is acceptable. The dispatch system is designed so this choice is a one-line configuration change, not a rebuild.

---

## 7. Recommendation

### 7.1 Phase 1 — Proceed Immediately (Both Workstreams)

**Workstream A — Sales email triage:** Authorize build of the `sales@agromin.com` triage and routing system. No new budget required. Uses existing M365 licenses, Power Apps Premium seat (already assigned), and idle Azure OpenAI resource. 4-week build timeline.

**Workstream B — Order dispatch:** Authorize build of the OCWR order dispatch service. No new budget required. GCP infrastructure already in place. Dispatch service writes to Firestore initially; destination updated once CRM is selected.

**Coordination requirement:** Both workstreams must be designed together before either goes to production. The triage classifier must recognize and exclude CIMcloud order confirmation emails. The dispatch Power Automate flow takes priority on those emails.

### 7.2 Phase 2 — CRM Evaluation and Decision Path

The recommendation follows a clear decision sequence. Each stage only triggers if the previous one fails.

---

**Stage 1 — Evaluate Sage CRM (30 days)**

Sage CRM is the only CRM with native, vendor-maintained Sage 100 integration at a reasonable cost. It is the logical first choice for a Sage 100 shop and should be evaluated seriously before any other platform.

Conduct a structured demo and score against the rubric in Section 3.3.

| Week | Activity | Participants | Output |
|---|---|---|---|
| 1 | Sage CRM demo | Rick Wilson, Rosa Bon, sales lead, 2 reps | Scored evaluation sheet |
| 2 | D365 Sales demo (for comparison) | Same group | Scored evaluation sheet |
| 3 | Scoring review + cost modeling | Rick Wilson + sales lead | Final recommendation memo |
| 4 | Leadership decision meeting | Full leadership team | Signed CRM decision |

**Sage CRM proceeds if:**
1. Sage 100 sync works as demonstrated with live customer data
2. Sales team scores UX at 3 or above — adoption is the primary risk
3. REST API supports programmatic writes for the dispatch service

---

**Stage 2 — If Sage CRM fails: Custom-build the operational layer**

If Sage CRM's UX drives poor adoption, or the API is insufficient, **do not default to an expensive platform.** The correct fallback is a lightweight custom-built operational tool built on the existing GCP stack.

What this covers:
- Greg's delivery queue — pending and scheduled deliveries in one view
- Schedule form — Greg logs confirmed date/time, triggers customer email automatically
- Ofelia's schedule view — live read-only dashboard
- Yard fulfillment log — browser form replacing shared Excel Greenery Log
- Firestore as the data store — already in use, zero incremental cost

Estimated build time: 2–3 weeks. No per-seat licensing cost. No vendor dependency. Fully controlled by Agromin.

For the sales CRM function specifically (pipeline, lead management, reps), Sage CRM failing on UX grounds still leaves D365 as a viable option if Agromin is prepared to accept the $1,580/month fully-loaded cost and the Microsoft commercial stack commitment that comes with it.

---

**Stage 3 — If the integration tax becomes unsustainable: Evaluate ERP migration**

If Agromin reaches a point where every new tool (CRM, dispatch, ecommerce, marketing) requires custom middleware or workarounds because Sage 100's API is too limited — that is the signal to evaluate a cloud ERP migration, not to keep adding connectors.

Modern cloud ERPs (NetSuite, Sage Intacct, Microsoft Business Central) have native connectors to HubSpot, Salesforce, and Dynamics 365. An ERP migration resolves the integration problem at the root rather than patching it repeatedly.

This is not a recommendation to migrate now. It is a recognition that the correct response to a failing integration stack is an ERP decision, not another middleware purchase. That conversation should happen at the leadership level if and when Stage 1 and Stage 2 prove insufficient.

---

**Summary decision sequence**

| Stage | Trigger | Action |
|---|---|---|
| 1 | Starting point | Evaluate and deploy Sage CRM |
| 2 | Sage CRM fails on UX or API | Custom-build dispatch operational layer; evaluate D365 for sales CRM |
| 3 | Integration tax becomes unsustainable | Evaluate cloud ERP migration — unlocks better CRM options |

### 7.3 CRM Selection Criteria for Dispatch Integration

Add these two questions to every vendor demo:

1. **Does the platform provide a REST API for creating and updating records programmatically?** (Required for the dispatch service to write without manual entry)
2. **Can custom fields be added to deal or contact records?** (Required to store routing decision, scheduled delivery date, material type, quantity)

A score of 3 or below on Criterion 8 (Dispatch System API) does not disqualify a CRM — Firestore and a custom-built operational layer serve as the fallback at zero cost. But a strong API score eliminates the need for custom development and is preferred.

**Note:** Method:CRM was included in a prior draft as a Sage 100 candidate. This was incorrect — Method:CRM integrates with QuickBooks and Xero only and is not applicable to Agromin's stack.

---

## 8. Action Items

| # | Action | Owner | Due | Status |
|---|---|---|---|---|
| 1 | Approve Phase 1 Workstream A (email triage) to proceed | Leadership | Apr 14, 2026 | PENDING |
| 2 | Approve Phase 1 Workstream B (order dispatch) to proceed | Leadership | Apr 14, 2026 | PENDING |
| 3 | Schedule 30-min interview with Rosa Bon — current mailbox workflow, routing logic, pain points | Rick Wilson | Apr 14, 2026 | PENDING |
| 4 | Schedule 30-min call re: D365 trial — status, scope, Sage integration plan, budget assumptions | Rick Wilson | Apr 14, 2026 | PENDING |
| 5 | Designate CRM decision owner and confirm decision timeline | Leadership | Apr 14, 2026 | PENDING |
| 6 | Request Method:CRM demo — Sage 100 sync walkthrough, REST API demo, fully-loaded cost proposal | CRM decision owner | Apr 18, 2026 | PENDING |
| 7 | Request Sage CRM demo — same format as Method:CRM for direct comparison | CRM decision owner | Apr 18, 2026 | PENDING |
| 8 | Confirm sales rep roster, territory assignments, and brand split (Agromin vs California Compost) | Sales lead | Apr 18, 2026 | PENDING |
| 9 | Complete inbox email sample analysis (500 emails) to finalize triage classification categories | Rick Wilson | Apr 18, 2026 | IN PROGRESS |
| 10 | Design inbox coordination spec — dispatch filter + triage classifier sequencing | Rick Wilson | Before Phase 1 production | PENDING |
| 11 | Company meeting: present Phase 1 demo, CRM evaluation results, and decision | Rick Wilson | May 12, 2026 | SCHEDULED |

---

*Agromin — Confidential and Proprietary. April 2026. Version 2.0*
