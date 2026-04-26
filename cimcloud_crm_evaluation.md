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

*Agromin · OCWR Free Compost & Mulch Program · CIMcloud CRM evaluation · April 2026*
