# Session Handoff — 2026-04-30 (Phase 1 SharePoint Excel Integration)

> **STATUS 2026-04-30 8:43 PM — CONFIRMED PLAN:**
> 1. **Tomorrow AM:** Kendall places test order on shop.agromin.com → verify Phase 1 pipeline end-to-end (CIMcloud → Power Automate → Cloud Run → Firestore + dispatch emails).
> 2. **If test passes:** Proceed with **Stage A Excel integration** (auto-append new orders to Greg's `OCWR-Agromin Deliveries.xlsx` Master Sheet). Field mappings and schema details below — body of this doc is the implementation guide.
> 3. **Next week:** Send `phase2_scheduling_questionnaire.gs` to Greg, Brian, Kendall, Ofelia, Emily. Phase 2 build starts after responses come back (scope/timeline TBD).
> 4. **Phase 2 scope confirmed:** Operational Excel only (Greg's Master Sheet + Manifest doc + Greenery Log). **Brian's `Agromin Outbound Log- OCWR Material.xlsx` (SAGE accounting workbook) is OUT of Phase 2 scope** — stays manual, owned by Brian. Future Phase 3 if ever revisited.
> 5. **Stage B (status=COMPLETE → Brian's Outbound Log `Residential Deliverys` sheet) is now AMBIGUOUS** — that sheet lives inside the accounting workbook even though its content is operational. Defer Stage B decision until Greg's MVP is in use; ask Brian directly whether he wants auto-population of that sheet or prefers it stay manual.
> 6. **Stage C (auto-populate Brian's revenue tracker / SAGE)** is OUT, period.

---

**Status:** Phase 1 deployed and live; SharePoint Excel integration designed but **not yet implemented**.
**Next action tomorrow:** Wait for Kendall's test order to validate end-to-end pipeline → then implement Stage A (auto-write to Greg's Master Sheet).

---

## 1. Where Phase 1 stands tonight

### Working and deployed (dev Cloud Run)
- `coupon-dispatch` service live at `https://coupon-dispatch-751008504644.us-west1.run.app`
- Microsoft Graph API integration: `dispatch@agromin.com` can send mail (app-only auth, RBAC-scoped to that mailbox only)
- Endpoint `POST /api/ingest-cimcloud-email` accepts:
  - JSON: `{"body": "<html>", "subject": "..."}`
  - Raw HTML: `Content-Type: text/html` + `X-Email-Subject` header
- Server-side parser (`parse_cimcloud_email` in `dispatch/main.py`) extracts `OrderPayload` from CIMcloud "Pending Approval" HTML using BeautifulSoup
- Power Automate flow live, configured to:
  - Trigger on new email in `sales@agromin.com` → folder `OCWR`
  - Subject filter: `Pending Approval for Order Number`
  - POST raw email body to dev Cloud Run with `X-API-Key`

### Pending end-to-end validation
- **Kendall is placing a test order tomorrow on shop.agromin.com** (she was out today)
- Once that order arrives → CIMcloud emails sales@agromin.com → Power Automate triggers → Cloud Run parses → Firestore record + dispatch email sent
- This is the gate before we add anything else to the pipeline

### Deferred (low urgency)
- Rotate `DISPATCH_API_KEY` (currently weak)
- Rotate Graph client secret (was sent to me in chat by Wayne)
- Mirror env vars + secrets to production Cloud Run service (`coupon-validator`)

---

## 2. SharePoint Excel integration plan (to implement tomorrow)

### Source files (downloaded from SharePoint, parsed locally)
Both live in `Sales & Marketing > OCWR x Agromin > Documents`:

| File | Path | Owner | Purpose |
|---|---|---|---|
| `OCWR-Agromin Deliveries.xlsx` | `Delivery Requests/` | Greg | **Operational** — order tracking, scheduling |
| `Agromin Outbound Log- OCWR Material.xlsx` | `Agromin Outbound Material/` | Brian (`briancam` in SAGE) | **Financial** — revenue split, invoicing |
| `Manifest Slip.docx` | `Delivery Requests/` | Greg/Brian | Pre-fillable PDF/docx for material pickup |
| `Email Template - Delivery Request Response.docx` | `Delivery Requests/` | Greg | Reference (not yet inspected) |
| `OCWR Hauling Contacts.docx` | `Agromin Outbound Material/` | Kendall | Reference (not yet inspected) |

### Three-stage automation strategy (agreed with user)

| Stage | Trigger | Target | Phase |
|---|---|---|---|
| **A** | CIMcloud email arrives → order ingested | Greg's `OCWR-Agromin Deliveries.xlsx` → `Master Sheet` (append row) | **Phase 1** (do tomorrow) |
| **B** | Greg sets `STATUS = COMPLETE` in Master Sheet | Brian's `Agromin Outbound Log` → `Residential Deliverys` (append row) | Phase 1.5 |
| **C** | SAGE invoice issued | Brian's `Agromin Outbound Log` → `2026 OCWR Material Movement` | Phase 2 (needs Brian's input — high risk to automate) |

---

## 3. Greg's `OCWR-Agromin Deliveries.xlsx` — full schema

**Workbook structure:** 3 sheets — `Master Sheet` (live), `Info` (lookup tables), `DO NOT USE` (old format).

**Master Sheet — 23 columns A-W, 87 real data rows. Next empty row = 88.**

| Col | Header | Source for our automation |
|---|---|---|
| A | Customer | `customer_name` |
| B | STATUS | **Default: `In Process`** (matches Greg's pattern). Other values: `Scheduled`, `COMPLETE`, `CANCELLED` |
| C | Date of Request | today (Excel serial date — see formula below) |
| D | Scheduled Delivery Date | *(blank — Greg fills after booking)* |
| E | Sales Order# | `order_number` **with "A" prefix stripped** (CIMcloud sends `A109591`, Greg uses `109591`) |
| F | Phone # | `customer_phone` |
| G | Email | `customer_email` |
| H | Delivery Address | parsed street from `shipping_address` |
| I | City | parsed |
| J | State | parsed |
| K | Zip Code | parsed |
| L | Origin (Greenery Name) | zip → lookup (see below) |
| M | Origin (Landfill Name) | zip → lookup (see below) |
| N | Material | `Compost`, `Mulch`, or `Compost/Mulch` |
| O | Compost (Quantity) | yards if material=Compost |
| P | Mulch (Quantity) | yards if material=Mulch |
| Q | Bags (# of Pallets) | qty if material=Bags |
| R | Compost Total $ | *(blank — pricing columns abandoned)* |
| S | Mulch Total $ | *(blank)* |
| T | Bags Total $ | *(blank)* |
| U | Delivery Fee | *(blank — Greg quotes manually)* |
| V | Total (No Tax) | *(blank)* |
| W | Notes | `Auto-imported from CIMcloud {ISO timestamp}` |

### Multi-material handling
**One row per material line item.** Order #143163 (Aseem) has 2 rows: one Mulch, one Compost. Our flow must split CIMcloud line items into separate rows.

### Excel serial date conversion
- Base: 1899-12-30
- Today (2026-04-30) = serial **46141**
- Formula: `(today_date - date(1899,12,30)).days`

### Zip → Origin lookup (from `Info` sheet)
| Greenery | Landfill | City |
|---|---|---|
| Valencia | Olinda Alpha Landfill | Brea |
| Bee Canyon | Frank R Bowerman Landfill | Irvine |
| Capistrano | Prima Deshecha Landfill | San Juan Capistrano |

**Coverage gap:** No mapping exists for non-OC zips. Default behavior: leave both Origin columns blank + add note `Origin TBD - delivery zip outside standard yards` so Greg picks manually.

### Status values seen in real data
- `In Process` (active, being quoted)
- `Scheduled` (delivery date booked)
- `COMPLETE` (green highlight, delivery done)
- `CANCELLED` (red highlight)

### Notes column shorthand
- `KA` = Kendall Atkin
- `GJ` = Greg Jackson
- Format: `KA emailed 4/27 confirming delivery request. GJ 4/28 Quoted $200 Frt`

---

## 4. Brian's `Agromin Outbound Log- OCWR Material.xlsx` — schema

**8 sheets total.** Only 2 relevant for our automation:

### Sheet 2: `Residential Deliverys` (Stage B target — Phase 1.5)
**6 columns, 19 rows.** Simple structure.

| Col | Header | Source |
|---|---|---|
| A | Customer | from Master Sheet |
| B | Haul Rate | from Master Sheet "Delivery Fee" |
| C | Yards | from Master Sheet (Compost+Mulch summed) |
| D | Material | `Compost, Mulch` (comma-separated, multi-material rolled up) |
| E | Total | from Master Sheet "Total (No Tax)" |
| F | Date | Excel serial date |

Latest entry: `Joe Atherall | 200 | 3, 2 | Compost, Mulch | 200 | 4/24/2026`.

### Sheet 1: `2026 OCWR Material Movement` (Stage C — Phase 2, NOT automating)
20 columns including financial fields (Material Cost/yard, Hauling Cost, Spreading Cost, Material Handling Fee, Net Revenue Received, Agromin Net Revenue, **Total Split with OCWR**). **Brian fills manually after SAGE invoicing.** Do NOT auto-write here without Brian's explicit sign-off.

### Other sheets (not relevant to coupon program)
- `Bid Proposals` — city contracts
- `2025 OCWR Material Movement` — historical
- `Laguna Beach 2025/2026`, `Laguna Hills 2026` — city-specific bid jobs
- `Reporting SOP` — Brian's process notes

---

## 5. Manifest Slip — pre-fillable fields

`Manifest Slip.docx` structure (parsed from `/Users/rickwilson/Downloads/Manifest Slip.docx`):

```
MATERIAL PICK-UP MANIFEST SLIP
Company Name: AGROMIN
GREENERY/LANDFILL: _______________________________
Date: ____ / ____ / ______
Hauler Company: _______________________________
Driver Name: _______________________________
AGROMIN ORDER #: _______________________________
CUSTOMER NAME: _________________________________

Material Details
Material Type (check one): ☐ Compost  ☐ Mulch
Form (check one):          ☐ Bags  ☐ Wattles  ☐ Bulk
Quantity: _________________________________________

OCWR Loader Verification
Loader Name (print): _________  Signature: _________  Date: ____ / ____ / ______

AGROMIN Driver Acknowledgment
I confirm that I have received the material and product listed above. _____________
Date: ____ / ____ / ______
Additional Notes (if needed):
```

### Auto-fillable fields (when Greg sets STATUS=Scheduled)
| Field | Source |
|---|---|
| GREENERY/LANDFILL | from Master Sheet col L+M (zip lookup) |
| Date | today |
| AGROMIN ORDER # | order_number |
| CUSTOMER NAME | customer_name |
| Material Type | from Master Sheet col N |
| Form | from CIMcloud line items (default: Bulk) |
| Quantity | from Master Sheet col O/P/Q |

### Hand-filled at pickup
- Hauler Company, Driver Name, Loader Name, signatures, dates

**Phase 1.5 add-on:** When Greg sets STATUS=Scheduled, generate `Manifest_Slip_{order_number}.docx` and drop in SharePoint folder. Worth doing once Stage A is proven.

---

## 6. Tomorrow's implementation order

### Step 1 — Validate Phase 1 (wait for Kendall, ~AM)
- Kendall places test order on shop.agromin.com
- Verify in Cloud Run logs: `gcloud beta run services logs tail coupon-dispatch --region=us-west1 --project=coupon-validator-prod-470419`
- Verify Firestore record created
- Verify dispatch email arrived at customer + coordinator (Ofelia)
- **Only proceed to Step 2 if this works end-to-end**

### Step 2 — Add Excel append to Cloud Run service (~30 min)
Two implementation options:

**Option A: Power Automate handles Excel append (recommended)**
- After our HTTP POST to `/api/ingest-cimcloud-email` succeeds, Power Automate parses the JSON response
- Adds new step: `Excel Online (Business) → Add a row to a table`
- Requires:
  - `OCWR-Agromin Deliveries.xlsx` Master Sheet must be **converted to an Excel Table** (Insert → Table) — it's likely just a range now. Check first.
  - Service account / Power Automate connection has write access to SharePoint file
- Pros: zero code change, all logic in Power Automate
- Cons: Greg sees a "Table" instead of a range (visual change, no functional impact)

**Option B: Cloud Run service writes via Microsoft Graph Excel API**
- Add `POST /api/sharepoint-append` internal helper
- Use existing `msal` token (same Graph app) with `Sites.ReadWrite.All` permission
- Endpoint: `PATCH /sites/{site-id}/drive/items/{file-id}/workbook/tables/{table}/rows/add`
- Pros: keeps logic centralized, easier to extend (Stage B, C)
- Cons: requires new Graph permission grant by Wayne, more code

**Recommendation: Option A first.** Lower lift, faster validation. Migrate to Option B later if we want richer logic.

### Step 3 — Field mapping implementation (~30 min)
Build the field mapper either in Power Automate (compose action) or in our Cloud Run service. Inputs: `OrderPayload`. Output: 23 fields matching Master Sheet schema.

Special handling:
- Strip "A" prefix from order number
- Parse shipping_address into street/city/state/zip
- Compute Excel serial date for "Date of Request"
- Zip → Origin lookup (3 yards + fallback)
- Split multi-material orders into multiple rows (multiple Excel append calls)

### Step 4 — Smoke test (~15 min)
- Place a test order via Kendall (or use parked `.eml` fixture)
- Verify new row appears in Master Sheet
- Verify Greg gets a notification (he subscribes to file changes — confirm)
- Cleanup test row if needed

### Step 5 — Document and ship
- Update `power_automate_setup.md` with the new Excel step
- Update `README.md` with SharePoint integration note
- Notify Greg that automation is live

---

## 7. Open decisions (3 questions still pending answers)

1. **Coverage gap for non-OC zips** — confirm: leave Origin blank + add note flag? Or default to nearest yard?
2. **Pickup orders** — Master Sheet is delivery-only. Where do pickups go? (Brian's Greenery Logs?) Need to ask Brian.
3. **Stage B trigger mechanism** — Power Automate watches the Master Sheet for STATUS cell changes. Will need to test this works reliably (Excel "modified" triggers can be flaky).

---

## 8. Files referenced this session

### Downloaded from SharePoint and parsed (in `~/Downloads/`)
- `OCWR-Agromin Deliveries.xlsx`
- `Agromin Outbound Log- OCWR Material.xlsx`
- `Manifest Slip.docx`

### Workspace files modified earlier in session
- `dispatch/main.py` — added Graph API send_mail, parse_cimcloud_email, /api/ingest-cimcloud-email endpoint
- `dispatch/requirements.txt` — added msal, requests, beautifulsoup4
- `power_automate_setup.md` — created
- `phase2_scheduling_questionnaire.gs` — created (separate task)
- `README.md` — updated for new env vars and Cloud Run URLs

### Workspace files NOT modified (just inspected)
- `CURSOR_HANDOFF.md` — original build handoff (do not overwrite)
- `Agromin_CRM_Spec_v3.md`, `cimcloud_crm_evaluation.md` — domain references

---

## 9. Quick-resume prompt for tomorrow

When resuming, paste this into a new Cursor chat:

> Read `SESSION_HANDOFF_2026-04-30.md` — we're picking up Phase 1 SharePoint Excel integration. Kendall's test order should have arrived (or will arrive) this morning. Step 1: verify the order flowed through end-to-end (Cloud Run logs → Firestore → emails). Step 2: implement Stage A (Power Automate Excel append to Greg's Master Sheet). Field mapping and decisions are documented in the handoff doc.

---

# Day 2 — 2026-05-01 — Phase 1 functionally complete pending delivery test

**Status at end of day:** Stage A build deployed and PA flow extended end-to-end. Awaiting Kendall delivery test order to validate the auto-write to Greg's Master Sheet. If the test passes, Phase 1 is closed.

---

## 10. Kendall's pickup test (morning) — pipeline validated, 3 issues found

Kendall placed the test order described in §6 Step 1. Results:

| Check | Result |
|---|---|
| Email arrival ~1–2 min | ✅ ~2 minutes |
| Order # match | ✅ |
| Greeting name | ✅ |
| Yard name | ✅ (auto-selected from CIMcloud `shipping_method`, not address) |
| Sender = `dispatch@agromin.com` | ✅ |
| Ofelia CC'd | ✅ |
| Yard address / phone / hours | ❌ — see below |
| QR / SB1383 paragraph appearing on staff-load order | ❌ — see below |

### Issues identified and fixed in code

1. **Olinda Alpha address was wrong.** Live: `1942 N. Valencia Ave, Brea, CA 92823`. Correct (per Kendall): `1942 Valencia Avenue, Brea, CA 92823`. The "N." suffix pointed at the landfill, not the greenery.
2. **SB1383 / QR-code paragraph was appearing on staff-load (≥5 yd) emails.** It should only appear on self-load (<5 yd) emails — the QR sign is at the self-serve scoop area, not at the staff-load equipment area. Fixed by removing `{sb1383_note}` from `PICKUP_STAFF_LOAD_TEMPLATE` and gating the paragraph on `routing == "pickup_self_load"` in `_process_order`.
3. **Olinda Alpha phone number is TBD.** Kendall is asking Ofelia what number residents should be directed to (greenery vs. Ofelia's office). Decision: keep the current `(714) 993-7396` (landfill main) as the interim until Kendall reports back. Re-deploy with new number whenever it lands.

### Decision logged

> Kendall noted she "didn't get to pick a yard, it auto chooses based on address." This is incorrect — the customer picks `Frank R. Bowerman / Prima Deshecha / Olinda Alpha Landfill Pick Up` at CIMcloud checkout via the shipping-method dropdown, and our parser maps that string to the yard. Address-based auto-selection is not happening. Worth a one-line clarification back to Kendall so she can explain it correctly to residents.

---

## 11. Live SharePoint schema verification (verified, not transcribed)

The xlsx files in `/Users/rickwilson/Documents/Active_Projects/Agromin/coupon-dispatch/` were read directly via `openpyxl` (not just transcribed from §3-§4 of this doc).

### Greg's `OCWR-Agromin Deliveries.xlsx` — Master Sheet

| Item | Live value | vs. §3 transcription |
|---|---|---|
| Excel Table | **`Table1` (range A1:W173) — already exists** | §6 warned this might just be a range. **Pre-flight risk eliminated** — PA's "Add a row to a table" works as-is, no conversion needed |
| Column count | 23 (A–W) | ✅ matches |
| Headers | Several contain embedded `\n` characters: `Date of \nRequest`, `Scheduled\nDelivery Date`, `Zip\nCode`, `Origin\n(Greenery Name)`, `Origin\n(Landfill Name)`, `Compost\n(Quantity)`, `Mulch\n(Quantity)`, `Bags\n(# of Pallets)`, `Compost\nTotal $`, `Mulch\nTotal $`, `Bags\nTotal $`, `Delivery\nFee`, `Total\n(No Tax)` | §3 cleaned the newlines for readability — PA binds by literal name so newlines must be preserved |
| Sales Order# storage | Stored as **integer** (`143163`), not string | §3 said "with A prefix stripped" but didn't specify type — confirmed int |
| Multi-material rows | Aseem #143163 has 2 rows (Mulch row + Compost row), both share customer/address/order# | ✅ confirms one-row-per-line-item pattern |
| City naming quirk | `"Bee Canyon "` (trailing space) | Sloppy but consistent — flagged for any future Origin auto-fill work |

### Brian's `Agromin Outbound Log- OCWR Material.xlsx`

| Sheet | Excel Table? | Stage relevance |
|---|---|---|
| `2026 OCWR Material Movement` | ✅ `Table14` (Stage C target — out of Phase 1) | Out |
| `Residential Deliverys` | ❌ Not a Table — just a range | **Stage B blocked until conversion**; Stage B is deferred anyway |

---

## 12. Stage A — Cloud Run build (deployed)

### Code changes (`dispatch/main.py`)

Added a labeled section "MASTER SHEET FIELD MAPPING (Stage A — Phase 1)" with:

- `_PACIFIC_TZ = ZoneInfo("America/Los_Angeles")` — explicit Pacific timezone for `Date of Request`
- `MASTER_SHEET_HEADERS` constant — single source of truth for the 23 column names with literal newlines preserved
- `parse_us_address(addr)` — comma-split US address parser; tolerates leading customer name and trailing `USA`
- `classify_material(desc)` — keyword search for `compost` / `mulch` / `bag|pallet`
- `strip_a_prefix(order_number)` — `A109591` → `109591` (int); falls back to original string on non-numeric
- `build_master_sheet_rows(order, routing)` — returns `[]` for pickup, one dict per line item for delivery, with literal Excel-header keys; Origin (Greenery + Landfill) intentionally blank with `Origin TBD` Notes flag (Greg assigns yard manually based on geographic proximity, not city match — the Info-sheet city lookup only covers Brea / Irvine / San Juan Capistrano)

`_process_order()` was extended to include `master_sheet_rows: [...]` in its response. The existing email pipeline behavior is unchanged.

`requirements.txt` got `tzdata>=2024.1` added — `python:3.11-slim` doesn't bundle the timezone DB, and Python's `zoneinfo` falls back to the pip package.

### Smoke tests (7 passed locally before deploy)

| Test | Result |
|---|---|
| `parse_us_address` covers 4 variants (with/without name, with/without USA, ZIP+4, empty) | ✅ |
| `classify_material` keyword priority (`Compost > Mulch > Bags`) | ✅ |
| `strip_a_prefix` returns int for valid, string fallback for invalid | ✅ |
| `build_master_sheet_rows` returns `[]` for pickup routings | ✅ |
| Real `Pending Approval for Order Number 109591.eml` (pickup) → `[]` | ✅ |
| Synthetic single-material delivery → 1 row, 23 fields, exact header match | ✅ |
| Synthetic Aseem #143163-style multi-material delivery → 2 rows, qty splits correct | ✅ |

### Deployed revision

| | |
|---|---|
| Service | `coupon-dispatch` |
| Project | `juris-coupon-valid` |
| Region | `us-west1` |
| Revision | `coupon-dispatch-00008-glj` |
| URL | `https://coupon-dispatch-751008504644.us-west1.run.app` |
| Health | 200 OK in 215 ms post-deploy |
| Deploy command | `gcloud run deploy coupon-dispatch --source . --region us-west1 --project juris-coupon-valid --allow-unauthenticated --quiet` (run from `dispatch/`) |

---

## 13. Stage A — Power Automate flow extended

The existing `Agromin Order Dispatch` flow had its 2 actions (email trigger → HTTP) extended with **3 new actions**, all configured in the New Designer UI:

1. **Parse JSON** — reads the Cloud Run HTTP response. Schema documented in `power_automate_setup.md` Step 6. Empty `{}` schemas for `Sales Order#` + the qty/dollar columns intentional (PA accepts any value, avoiding spurious schema-validation errors).
2. **Apply to each** — loops over `Body master_sheet_rows`. One iteration per material; pickups produce empty arrays so the loop just runs zero times.
3. **Add a row into a table** (Excel Online (Business) connector, INSIDE the loop) — pointed at:
   - Location: `SharePoint Site - OCWR x Agromin` (`https://agromincorp.sharepoint.com/sites/OCWRxAgromin`)
   - Document Library: `Documents`
   - File: `Delivery Requests/OCWR-Agromin Deliveries.xlsx`
   - Table: `Table1`
   - All 23 column inputs bound to corresponding `Body <name>` tokens

**Connection:** authenticated as `rickwilson@agromin.com`. SharePoint edit access is restricted to the Agromin tenant.

### Critical bug caught during binding

The `STATUS` column was initially bound to `Body status` (lowercase) — that's the top-level response field with value `"processed"`. The correct token is `Body STATUS` (uppercase) — the inner-row column with value `"In Process"`. Fixed before save. **Without this fix, every auto-imported row would have `STATUS = processed` instead of `STATUS = In Process`** and Greg would lose his ability to filter the queue by status.

The 24th advanced parameter (`DateTime Format`) was left removed from the form — PA falls back to its default ISO-string handling, which is what we want. The form now shows "Showing 23 of 24" with no warnings.

---

## 14. End-of-day pending: Kendall delivery test

Stage A is built and deployed but unverified end-to-end. The next test:

1. Kendall places a TEST delivery order on shop.agromin.com (instructions ready, see `instructions_for_kendall_delivery_test.txt` if saved, otherwise re-derive from §6 with `routing=delivery`)
2. Within ~60 sec the customer email arrives (Delivery Confirmation, no QR/SB1383 note since this is delivery), Ofelia CC'd
3. Coordinator alert email arrives at Greg/Brian/Kendall ("New Delivery Order — Action Required")
4. **NEW: a row appears at the bottom of `Table1` in `OCWR-Agromin Deliveries.xlsx`** — `STATUS = In Process`, today's Pacific date, `Sales Order#` as int, Origin columns blank with `Origin TBD — Greg to assign yard.` in Notes

If all 4 land, **Phase 1 is closed**.

---

## 15. Phase 1 closeout follow-ups (after test passes)

Trivial, < 30 minutes total:

1. Delete the test row from Master Sheet (right-click row 174 → Delete)
2. Reply to coordinator alert: "test, ignore"
3. Update `README.md` line 22 — currently claims SharePoint write is live (becomes true after this test)
4. Commit the working tree (uncommitted: `dispatch/main.py`, `dispatch/requirements.txt`, `power_automate_setup.md`, `SESSION_HANDOFF_2026-04-30.md`, `dispatch/README.md`, plus several untracked Phase-1 docs)

Two deferred security items from §1, not urgent for OCWR rollout but should land before peak season:

5. Rotate `DISPATCH_API_KEY` (currently weak; `power_automate_setup.md` will need the new value)
6. Rotate the Graph client secret (Wayne sent it via chat originally)

---

## 16. Explicitly NOT done today (scope discipline)

The user reaffirmed mid-session: *"I only want you to work on Phase 1 of this project right now."* The following remained untouched:

- Phase 1.5 — Manifest Slip auto-fill on `STATUS = Scheduled`
- Stage B — Brian's `Residential Deliverys` sheet (deferred per §1; would also need that sheet converted to an Excel Table first)
- Stage C — SAGE / Brian's revenue tracker (out, period)
- Phase 2 — Scheduling tool, `phase2_scheduling_questionnaire.{md,gs}`, `brian_questionnaire.md`
- CIMcloud CRM evaluation call
- Production Cloud Run service mirror (`coupon-validator` still has the old codebase)

These are next-session decisions, not Phase 1 work.

---

## 17. Phase 2 architectural decision — web app as system of record (added 2026-05-01 evening)

End-of-day discussion locked in the foundational design principle for Phase 2. Captured here so it survives into the next session and the Phase 2 build doesn't drift.

### Design principle (non-negotiable)

> **The web app database is the system of record. Spreadsheets are output artifacts only. No spreadsheet content is read back into the app. Any data that needs to round-trip is captured through the web app UI.**

### Why this principle exists — Phase 1's fragility

Phase 1 makes Greg's `OCWR-Agromin Deliveries.xlsx` Master Sheet the system of record. That was the right tactical call (ship in days, integrate with Greg's existing workflow) but it exposes the pipeline to normal Excel user behavior:

| If Greg... | Phase 1 breaks how? |
|---|---|
| Renames `OCWR-Agromin Deliveries.xlsx` | PA flow can't find the file → orders silently fail to write |
| Moves it to a different SharePoint folder | Same — PA's file ID is path-based via the connector |
| Renames `Table1` to `MasterSheet` | "Add a row to a table" fails — table name is hard-coded in the action |
| Adds a new column | Blank column, doesn't break (binds by header name) |
| Reorders columns | Doesn't break (binds by header name) |
| **Deletes** a column or renames a header (e.g., `STATUS` → `Order Status`) | PA write fails with "column not found" → orders stop landing |
| Downloads, edits in desktop Excel, re-uploads | SharePoint may assign a new file ID → PA flow breaks |
| Hands the file to a new owner who reformats it | Anything could happen |

These are **normal Excel user behaviors**, not edge cases. Spreadsheets are designed to be edited freely; treating one as a database means every well-intentioned cleanup edit becomes a production incident.

### Phase 1 risk mitigation (interim — until Phase 2 ships)

1. Tell Greg explicitly: "Don't rename the file, don't rename `Table1`, don't change column headers. If you need to, tell me first."
2. Optional: SharePoint version-history / change alert so we catch breakage fast.
3. Treat the Phase 1 PA flow as a known fragility we accept in exchange for time-to-value.

### Phase 1 → Phase 2 polarity flip

| | Phase 1 (now) | Phase 2 (target) |
|---|---|---|
| Source of truth | Greg's Excel Master Sheet | Web app database (Firestore) |
| Workflow happens in | Excel | Web app |
| Spreadsheets are | Living documents people edit | Read-only exports the app generates |
| Schema enforced by | Convention + good behavior | Code (validated on every write) |
| Renaming columns | Anyone, anytime | Requires a deploy |
| Audit trail | None | Every write timestamped + logged |
| Backup / restore | Manual | Automated, point-in-time |

### The 3 places spreadsheets/files don't fully go away in Phase 2

Spreadsheets persist at the **boundary with external systems**, not internally:

1. **OCWR external reporting (regulatory).** OCWR will not log into our web app. They want submissions in a specific Excel/PDF format on a schedule. Web app generates these on demand or scheduled. Question 31 in `phase2_scheduling_questionnaire.md` captures the exact format requirement.
2. **Brian's SAGE accounting handoff.** SAGE is out of scope; Brian invoices there manually. He needs *something* telling him what to invoice — likely a web-app dashboard ("Ready to invoice" queue) plus a downloadable Excel for those who prefer that workflow. Brian's preference is captured in `brian_questionnaire.md`.
3. **Backup / audit / disaster recovery.** Weekly automated Excel snapshots are good hygiene even if no one reads them daily. If the web app is down, ops can keep moving from the snapshot.

In all three cases the spreadsheet is a **disposable artifact** the app produces — never a fragile dependency the app reads from.

### Phase 2 architecture sketch

```
       ┌──────────────────────────────────────────────┐
       │           Web App (Cloud Run)                │
       │  ┌────────────────────────────────────────┐  │
       │  │   Firestore (source of truth)          │  │
       │  └────────────────────────────────────────┘  │
       │   ▲                                       │  │
       │   │                                       ▼  │
       │  Greg's dashboard                      Exports│
       │  Brian's invoice queue                 ┌──────┤
       │  Ofelia's schedule view                │ OCWR  │  → Ofelia/Kendall download
       │  Kendall's compliance view             │ Excel │
       │  Yard tablet form (Greenery Log)       │ PDF   │  → SAGE Excel (Brian)
       │                                        │ CSV   │  → Weekly snapshot (audit)
       │                                        └──────┘
       └──────────────────────────────────────────────┘
                      ▲
                      │
              CIMcloud email (Phase 1 pipeline still feeds new orders in)
```

### Discipline required for the principle to hold

If any of these slip, we lose the durability benefit and revert to Phase-1-style fragility:

1. **No human edits to exported spreadsheets that the system cares about.** Edits go in the web app; the Excel is a printout. Document this in user-facing instructions.
2. **Exports are versioned by date** (`OCWR-Deliveries-2026-05-01.xlsx`) so people can't accidentally overwrite history.
3. **Anything that needs round-trip editing** goes through a structured import flow with validation, *not* a free-form spreadsheet edit. (Round-trip editing should be rare — design it out wherever possible.)
4. **The web app must be *better* at the daily task than Excel is** — otherwise users revert to spreadsheet editing and we're back to Phase 1's fragility.

### Implication for Phase 2 PA-flow count

Original instinct: "lots of PA flows for Phase 2." Revised: **3–5 max**, because the web app handles internally what PA had to glue together in Phase 1.

| Likely PA flow | Trigger | Action |
|---|---|---|
| Stage B — Brian's Outbound Log auto-write *(if he opts in)* | Greg sets `STATUS = COMPLETE` | Append matching row to `Residential Deliverys` |
| Manifest Slip auto-fill | Greg sets `STATUS = Scheduled` | Populate `Manifest Slip.docx` template, save to SharePoint, optionally email hauler |
| Weekly Ofelia summary | Scheduled (Friday) | Query Master Sheet (or, post-Phase-2, query the web app) → email summary |
| OCWR compliance export *(maybe)* | Scheduled monthly | Generate report in OCWR's required format → email to Ofelia/Kendall |
| Customer reminder *(maybe)* | Scheduled daily | Email/text customers with deliveries the next day |

Web-app territory (NOT PA): live schedule view, yard tablet form, customer date-picker, Greg/Brian dashboards, Brian's invoice queue.

### Change-management note for Phase 2 launch

Greg has used the Master Sheet for years. Two transition strategies:

- **Hard cut:** web app launches → spreadsheet retires immediately. Cleaner, painful in week 1.
- **Soft transition (recommended):** web app launches as the source of truth → web app *also* keeps writing to the Master Sheet for ~30 days as a familiar mirror → Greg works in whichever feels comfortable → after 30 days we sunset the Excel mirror once he's confident in the app.

Pick at Phase 2 design time based on Greg's questionnaire answers (Q3 on where he tracks deliveries today, Q11 on where he works from).

### Other items needing input from Brian

Captured for completeness — none block Phase 1 closure:

1. **Pickup tracking** (Phase 1 open question Q3) — Master Sheet is delivery-only. Where do pickups go (his Greenery Logs, separate sheet, untracked)? Currently pickups produce a customer email + Firestore record + coordinator alert but no spreadsheet row.
2. **Stage B preference** — does he want the `Residential Deliverys` sheet auto-populated when STATUS=COMPLETE? If yes, that sheet needs to be converted to an Excel Table first.
3. **Phase 2 questionnaire** — `brian_questionnaire.md` is drafted (29 questions). Don't send until Phase 1 closes.

---

# Day 3 — 2026-05-04 — End-to-end test in progress, PA flow verified

**Status at end of day:** Cloud Run and PA flow both confirmed healthy. Full end-to-end Stage A test (email → PA → Excel row) not yet completed due to email routing discovery. Phase 1 remains open pending one successful delivery order writing a row to Greg's Master Sheet.

---

## 18. What was confirmed today

### Cloud Run service
- Health check: `GET /health` → **200 OK** (6.5s cold start, normal)
- Direct API test: `POST /api/ingest-order` with synthetic delivery payload returned correct `master_sheet_rows` response:
  - `status: "processed"`, `routing: "delivery"`, `region: "oc"`
  - 1 row, all 23 columns correctly populated
  - `Sales Order# = 109999` (int, A-prefix stripped) ✅
  - Address parsed correctly ✅
  - `STATUS = "In Process"` ✅
  - `Notes = "Auto-imported 5/4/26. Origin TBD — Greg to assign yard."` ✅
- **Conclusion: Cloud Run field mapping logic is correct.**

### Power Automate flow
- Flow lives in **Rick Wilson's Environment** (not Agromin default) — important for future sessions
- Flow name: `Agromin Order Dispatch`
- Trigger confirmed: `When a new email arrives in a shared mailbox (V2)`
  - Mailbox: `sales@agromin.com`
  - Folder: **`OCWR`** (subfolder, not Inbox root)
- HTTP action confirmed: POST to `https://coupon-dispatch-751008504644.us-west1.run.app/api/ingest-cimcloud-email`
- API key confirmed rotated (new hash visible in flow — no longer `AgrominDispatch2026Secret`)
- **Conclusion: Flow is correctly configured.**

### Why test emails didn't trigger the flow
The PA trigger watches the `OCWR` subfolder specifically. Test emails sent to `sales@agromin.com` from Rick's personal and Agromin accounts landed in Inbox (or were filtered), not in `OCWR`. Real CIMcloud emails land in `OCWR` via an Outlook rule (likely sender-based). To test with a synthetic email: send to `sales@agromin.com`, then **manually drag it into the `OCWR` subfolder** — PA will fire within ~60 seconds.

### Spreadsheet filter safety confirmed
Filters applied to `OCWR-Agromin Deliveries.xlsx` (e.g. Greg filtering by STATUS for management views) do **not** affect the automation. PA writes to the underlying Table data, not the view. New rows append correctly regardless of active filters. Hidden rows remain in the data — Greg just needs to clear filters to see them.

---

## 19. Remaining gate to close Phase 1

One item still needed:

**Trigger PA with a delivery-order email that lands in the `OCWR` folder → verify new row appears in Greg's Master Sheet.**

Options (in order of preference):
1. Wait for a real CIMcloud delivery order to come in — fully automatic, zero effort
2. Send test email to `sales@agromin.com` from Agromin account → manually move it to `OCWR` folder in Outlook → PA fires within 60s → check spreadsheet
3. Ask Kendall to place a test delivery order on shop.agromin.com (requires a coupon code; delivery fee may be $0 for test)

Once a row appears in Greg's sheet, **Phase 1 is closed**. Then:
1. Delete the test row (right-click → Delete)
2. Commit working tree (see §15 for full list of uncommitted files)
3. Notify Greg automation is live

---

## 21. Coordinator alert email — customer email field added (2026-05-04)

Added `Email: {customer_email}` to the `DELIVERY_ALERT_TEMPLATE` in `dispatch/main.py` so Greg's "New Delivery Order — Action Required" alert now includes the customer's email address between Phone and Delivery Address.

**Before:**
```
Order #:          A109999
Date:             2026-05-04
Customer:         Test Customer
Phone:            555-555-5555
Delivery Address: 123 Test St, Irvine, CA 92602
```

**After:**
```
Order #:          A109999
Date:             2026-05-04
Customer:         Test Customer
Phone:            555-555-5555
Email:            customer@example.com
Delivery Address: 123 Test St, Irvine, CA 92602
```

Deployed as revision `coupon-dispatch-00010-rgn`. No other behavior changed.

---

## 20. PA flow location — important for future sessions

| Item | Value |
|---|---|
| PA environment | **Rick Wilson's Environment** (NOT Agromin default) |
| Flow name | `Agromin Order Dispatch` |
| Trigger mailbox | `sales@agromin.com` |
| Trigger folder | `OCWR` subfolder |
| API key | Rotated — retrieve from PA flow HTTP action header |
| Cloud Run URL | `https://coupon-dispatch-751008504644.us-west1.run.app` |
| GCP project | `juris-coupon-valid` |
| GCP region | `us-west1` |
