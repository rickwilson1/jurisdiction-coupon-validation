# CIMcloud CRM Evaluation
**Purpose:** Determine if CIMcloud CRM can serve as the data and visibility layer for the Agromin dispatch system, replacing the need for a separate CRM (HubSpot, Airtable) or custom-built Phase 2 UI.  
**Format:** 30-minute call with CIMcloud account rep  
**Prerequisite:** Confirm whether CRM module is included in current subscription or requires an upgrade.

---

## The five questions

**1. Can you create custom fields on an order record?**

We need to store dispatch-specific data against each order that CIMcloud doesn't capture natively:
- Routing decision (delivery / pickup-self-load / pickup-staff-load)
- Scheduled delivery date
- Delivery time window (e.g. 8am–10am)
- Yard assigned
- Fulfillment confirmed (yes/no + timestamp)

Can these be added as custom fields on the order object? Are they queryable and filterable?

---

**2. Can a user see a filtered view of delivery orders?**

Greg needs a queue — a live list of delivery orders filtered to show only those where routing = delivery, sorted by status (pending → scheduled → fulfilled). 

Can CIMcloud CRM display a filtered, sorted order view like this without custom development? Can Greg update the status and log a scheduled date directly in that view?

---

**3. Can a second user see a read-only schedule view?**

Ofelia needs visibility into confirmed deliveries for the current and upcoming week — customer name, delivery address, material, quantity, scheduled date and time. She should not be able to edit records.

Does CIMcloud CRM support role-based read-only views? Can a view be filtered by scheduled date range?

---

**4. Does CIMcloud have an API that supports writing back to order records?**

The dispatch service (a Cloud Run API) needs to programmatically create or update order records in CIMcloud when an order is processed — writing routing decisions, status changes, and scheduled dates without manual entry.

Is there a REST API endpoint for updating custom fields on an order? Is authentication via API key or OAuth? Is there documentation available?

---

**5. What does it cost to activate the CRM module?**

Is the CRM module included in the current CIMcloud subscription, or does it require an upgrade or add-on? If there is a cost, what is the per-user or monthly pricing?

---

## Decision criteria

| Answer | Next step |
|---|---|
| Yes to all five | Use CIMcloud CRM as the Phase 2 data layer — no new platform needed |
| Yes to 1–3, No to 4 | CIMcloud CRM for visibility; dispatch service writes to Firestore or HubSpot |
| No to 2 or 3 | Evaluate HubSpot Free or Airtable |
| Included in subscription | Strong reason to proceed even if partially capable |
| Requires paid upgrade | Weigh cost against HubSpot Free ($0) before committing |

---

## CRM tier evaluation — alternatives if CIMcloud is not the answer

If the CIMcloud call rules out using the existing platform, here are the alternatives ranked by fit for the OCWR Coupon Program workflow (order intake → delivery scheduling → driver manifest → customer notification → revenue split tracking).

### Workflow we are trying to unify

| Stage | Current tool | What a CRM would unify |
|---|---|---|
| Order intake | CIMcloud → email | Order object with status |
| Delivery scheduling | Greg's `OCWR-Agromin Deliveries.xlsx` | Calendar / dispatch board |
| Driver manifest | `Manifest Slip.docx` (hand-filled) | Mobile work order |
| Customer notification | Power Automate → Cloud Run → Graph API | Built-in templated comms |
| Revenue split tracking | Brian's `Agromin Outbound Log` + SAGE | Native invoicing / AR module |
| Multi-org collaboration | SharePoint | Role-based access |

A CRM that handles all 6 stages eliminates the Cloud Run + Power Automate + Excel duct tape we are building.

---

### Tier 1 — Field Service Management (best workflow fit)

| Tool | Why it fits | Price (rough) | Risk |
|---|---|---|---|
| **Jobber** | Built for dispatch + scheduling + customer comms + invoicing. Used by lawn care, landscape, hauling. Most natural fit. Has customer portal and driver mobile app. | $69-$199 / user / mo | Low — fast onboarding, familiar small-biz UX. **Gap:** integrates with QuickBooks/Xero, not SAGE |
| **Housecall Pro** | Similar to Jobber, slightly simpler. | $65-$200 / user / mo | Low |
| **ServiceTitan** | Enterprise dispatch (HVAC/plumbing roots). Overkill unless 50+ orders/week. | $300-$500 / user / mo | High — long implementation, training cost |

**Top pick from this tier:** Jobber. Customer → job → schedule → driver → invoice → done.

---

### Tier 2 — Microsoft-native (you are already on M365)

| Tool | Why it fits | Price (rough) | Risk |
|---|---|---|---|
| **Dynamics 365 Field Service** | Native to M365, integrates with SharePoint / Teams / Outlook. Schedule board, mobile manifest, customer comms. | $95 / user / mo + implementation | Medium — Microsoft implementation projects are notoriously slow; budget 3-6 months |
| **Power Apps + Dataverse** | Build a custom dispatch app on the Power Platform. Same data store as Power Automate. Essentially what we are building today, but with a real UI instead of Excel. | ~$20 / user / mo | Medium — you build the app yourself (or hire). Wayne could likely help |

---

### Tier 3 — General CRM with workflows

| Tool | Considered because | Why probably not |
|---|---|---|
| **HubSpot Service Hub** | Strong workflow + custom objects | Not designed for material dispatch — forcing a sales CRM into an ops role |
| **Salesforce Field Service** | Most powerful option on the market | $165+ / user / mo, 6-month implementation, total overkill |
| **Zoho One** ($45 / user / mo all-in) | Cheap, includes CRM + Inventory + Books + custom modules | Fragmented UX; everything works but nothing feels great |
| **Odoo** (self-host or cloud) | Open source, modular (Sales + Inventory + Field Service + Accounting). Could replace SAGE too. | Steeper learning curve; needs admin care |

---

### Tier 4 — Industry-specific (waste / recycling)

| Tool | Note |
|---|---|
| Soft-Pak, AMCS, Routeware, Encompass | Built for waste haulers — billing/routing focused. **Probably wrong tool** — OCWR Coupon Program is more like landscape supply than waste hauling |
| **Carryt** | Modern waste dispatch platform. Worth a 30-min look if Tier 1/2 don't fit |

---

### Tier 5 — CIMcloud (the questions above)

If the 5 questions in this document return Yes/Yes/Yes/Yes/affordable, **this is the cheapest answer** — data already lives there, no migration, no new vendor. Run this evaluation first before pursuing anything in Tiers 1-4.

---

## Honest comparison: continue current build vs replace with a CRM

### Why the current Cloud Run + Power Automate + Excel build is rational right now
1. **Free** — Cloud Run + Power Automate + M365 already paid for
2. **No team retraining** — Greg keeps his Excel, Brian keeps SAGE, customers see no change
3. **Incremental** — ship Stage A this week, Stage B next, no Big Bang risk
4. **No vendor lock-in** — we own the code
5. **Two-org workflow handled naturally** — Agromin + OCWR partnership doesn't fit a single-org CRM model
6. **Volume is low** — at ~5-15 orders/week, manual Excel scales fine

### When a CRM becomes worth the switch
- Order volume scales **10x+** (manual Excel won't keep up)
- A **third partner organization** is added (each one repeats the integration work)
- Drivers need a **mobile app** for load tickets, photos, signatures
- Brian wants to **replace SAGE** with an integrated AR system
- A **customer self-service portal** becomes a requirement
- **Audit / compliance reporting** becomes formal (Title 14, MRV)

### Crossover trigger to put on the roadmap

> "We're building light middleware now because volume doesn't justify a CRM yet. At ~30 OCWR orders/week, or when a third partner organization is added, the right move is **Jobber** (Tier 1) or **Dynamics 365 Field Service** (Tier 2)."

---

## Recommended decision path

| Phase | Action |
|---|---|
| **Now (Phase 1)** | Stay the course — finish Cloud Run + Power Automate + Excel integration. Do not introduce a CRM mid-build. |
| **Phase 2 planning (~next month)** | Run the 5-question CIMcloud evaluation call documented above. If yes → migrate to CIMcloud as source of truth. If no → re-open this tier evaluation. |
| **Phase 2 build** | If CIMcloud rules out, evaluate Jobber (Tier 1) and Power Apps + Dataverse (Tier 2) head-to-head with a 30-min demo of each. Pick based on Brian's accounting integration needs and Greg's UX preference. |
| **12+ months out** | Revisit when any crossover trigger fires (30 orders/week, third partner, mobile-driver requirement, SAGE replacement, customer portal demand) |

---

*Agromin · OCWR Free Compost & Mulch Program · CIMcloud CRM evaluation · April 2026*
