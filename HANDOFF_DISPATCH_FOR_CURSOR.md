# Dispatch App Handoff (for Cursor)

**Scope:** the `coupon-dispatch` Cloud Run service only (`dispatch/main.py`). This is the post-checkout order-routing service, not the validator and not the accountant reporting app. The task in front of you is to review, commit, and deploy a set of working-tree changes that capture order financials and order comments, and to do so without disturbing the live order path.

---

## 1. What this service does

`coupon-dispatch` processes confirmed Agromin coupon-program orders. The flow:

1. A customer orders free compost/mulch at `shop.agromin.com` (CIMcloud storefront) using a jurisdiction coupon code.
2. CIMcloud emails a "Pending Approval for Order Number XXXXXX" message from `Sales@agromin.com` to the `sales@agromin.com` shared mailbox.
3. A Power Automate flow forwards the raw HTML body to `POST /api/ingest-cimcloud-email` (header `X-API-Key`). Filters: From `Sales@agromin.com`, Subject starts with `Pending Approval for Order Number`, Body contains `Coupon Code:`.
4. The service parses the email into an `OrderPayload`, decides pickup vs. delivery, emails the customer (CC Ofelia), alerts the delivery coordinator on delivery orders, writes a record to Firestore `order_events`, and returns master-sheet rows that Power Automate appends to Greg's delivery workbook.

Endpoints (do not change their contracts): `POST /api/ingest-order` (structured JSON), `POST /api/ingest-cimcloud-email` (raw email, the production path), `POST /api/generate-manifest` (delivery PDF), `GET /api/delivery-schedule` (last 7 days of deliveries), `GET /health`, `GET /`.

Deployment: GCP project `juris-coupon-valid`, region `us-west1`, service URL `https://coupon-dispatch-751008504644.us-west1.run.app`. **Deploys are manual — there is no auto-deploy. Pushing to `main` does NOT deploy** (the only GitHub Actions workflow, `update-cdtfa-data.yml`, is an unrelated scheduled data updater, and `juris-coupon-valid` has no Cloud Build trigger). To ship a new revision, run from `dispatch/`:

```bash
gcloud run deploy coupon-dispatch --source . --region us-west1 --project juris-coupon-valid
```

This builds the image from `dispatch/Dockerfile` via Cloud Build, pushes to the `cloud-run-source-deploy` Artifact Registry repo, and rolls out a new revision. Existing env vars (`DISPATCH_API_KEY`, `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `MAIL_SENDER`, `OFELIA_EMAIL`) are preserved across a `--source` redeploy.

---

## 2. Critical repo-state warning — read before committing

The working tree is **not** a clean checkout of HEAD.

```
HEAD = 331af40 "Split dispatch into separate Cloud Run service; restore validator to pre-dispatch state"
Branch: main, up to date with origin/main (nothing pushed beyond HEAD)
```

Almost the entire current `dispatch/main.py` is uncommitted relative to HEAD. The Microsoft Graph email sender, the master-sheet row builder, the full CIMcloud HTML parser, and the order-summary/comments extraction all live in the working tree and have never been committed. HEAD only contains the early service-split scaffold.

> **Status update (2026-06-28):** the working tree has drifted well beyond the three files this section originally listed. As of this update, `git status` shows roughly nine modified/deleted tracked files (including unrelated doc edits — `README.md`, `brian_questionnaire.md`, `cimcloud_crm_evaluation.md`, `phase1_open_questions.md` — and two deleted CRM specs) plus ~50 untracked files (architecture diagrams, coupon-extract tooling, session-handoff notes, and customer-data artifacts). **Do not `git add -A`.** Stage the dispatch service files explicitly. The customer-data artifacts (`*.eml`, `coupon_customers_*.csv`, `coupon_orders_*.csv`, `Sacramento_Coupon_Program_*.xlsx`, other `*.xlsx`) are now covered by `.gitignore` and must never be committed — they contain customer PII.

Do not assume `git diff HEAD` shows "the change." It shows a large body of prior uncommitted work plus the two newest edits described in Section 3. Before doing anything, run `git status` and `git diff` and decide how to stage. Recommended: commit the dispatch service body as one legible commit (parser + Graph sender + master-sheet builder + the Section 3 financials/comments edits travel together since they were never separately committed), distinct from any unrelated doc churn. If any of the prior uncommitted work is known-good and already running in a previously deployed image, confirm that with Rick before assuming the working tree matches production.

`dispatch/requirements.txt` adds `msal`, `requests`, `beautifulsoup4`, and `tzdata` on top of the committed set (`fastapi`, `uvicorn`, `pydantic`, `google-cloud-firestore`, `reportlab`). These are required by the parser and Graph sender; they must ship with whatever commit deploys the current `main.py`, or the container will fail to import. Verified 2026-06-28: `pip install -r dispatch/requirements.txt` resolves cleanly and the module imports.

---

## 3. The newest changes (capture financials + order comments)

Two business needs drove these edits, both confirmed with Rick: Greg's delivery spreadsheet should receive the order financials (it had blank money columns), and the delivery coordinator should see the customer's order comments in the alert email.

What was added to `dispatch/main.py`:

**`OrderPayload` model** gained `order_comments: str = ""`, `subtotal`, `tax`, `shipping`, `coupon_amount`, `order_total` (all `float = 0.0`). The CIMcloud email carries these in its order-summary block; they were previously parsed by nobody.

**`parse_cimcloud_email`** now also calls two new helpers and populates the new fields:

- `_summary_amount(soup, label)` reads a dollar figure from the order-summary totals block (rows like `Subtotal | $179.75`, `Tax | $10.47`, `Shipping | $135.00`, `Coupon | $179.75`, `Total | $145.47`). It matches the label cell case-insensitively, ignoring a trailing colon, and returns the last numeric value in that row, or 0.0 if absent.
- `_parse_order_comments(soup)` reads the free-text Order Comments cell from the shipment-details table. **Important subtlety:** CIMcloud nests the whole email inside one outer `<table>` that also contains the string "Order Comments", so a naive header scan matches the wrong table and returns the email greeting. The helper guards against this by requiring a tight header row of 2–4 columns containing both "Shipping Method" and "Order Comments". Do not "simplify" this guard away; it is the difference between extracting "TEST ORDER" (correct) and "Thanks for your order..." (wrong).

**`build_master_sheet_rows`** now fills the previously-blank financial columns. Per line item it writes the material total as `qty * unit_price` into the matching Compost/Mulch/Bags total column. The delivery fee comes from the parsed `shipping` value, falling back to a `$NNN` amount embedded in the `shipping_method` string. The pre-tax total (`Total (No Tax)`) is `material_subtotal + delivery_fee`. On multi-material orders the delivery fee and pre-tax total are written to the **first emitted row only** to avoid double-counting. The two Origin columns remain intentionally blank (Greg assigns the yard manually).

**`DELIVERY_ALERT_TEMPLATE`** gained an `Order Comments:` line, and the alert `.format(...)` call passes `order.order_comments or "(none)"`. Delivery coordinators now see the comment in the alert.

What was **not** touched: routing logic (delivery vs. pickup, the <5/≥5 cubic-yard self-load vs. staff-load split), customer email templates and sending, the manifest PDF, the Firestore write shape, coordinator routing by region, and all endpoint contracts. Behavior on the live path is unchanged except that the coordinator alert has one extra line and the master-sheet rows now carry dollar values.

---

## 4. Key domain facts the parser depends on

A program order is identified by **coupon-code presence only**. Do not gate on order total or payment method. Delivery orders carry a coupon and still show a credit-card payment and a nonzero total, because the coupon zeroes the material but tax and the delivery fee are charged separately. Order #A110413 is the canonical example: coupon `CITYVCOM26`, payment "Credit or Debit Card", subtotal $179.75, coupon $179.75, tax $10.47, shipping $135.00, total $145.47. Any logic that assumes couponed orders are $0.00 or "No Payment Required" is wrong.

`shipping_method` is the pickup-vs-delivery switch: the substring "delivery" (case-insensitive) means delivery, anything else is pickup. Pickup quantity under 5 cubic yards is self-load, 5 or more is staff-load.

SKUs vary by material and program (`COM` for Compost 100, `ES2` for Cover Mulch, etc.). Do not hard-code SKUs. Material classification keys off the description text via `classify_material`, which matches "compost", "mulch", or "bag"/"pallet" substrings.

Greg's master sheet is an Excel Table whose column headers contain embedded newlines (e.g. `"Compost\n(Quantity)"`). Power Automate's "Add a row to a table" action binds by exact header string, so `MASTER_SHEET_HEADERS` keys must match the live workbook headers character-for-character, newlines included. Do not normalize or rename these.

---

## 5. Verification already done

The current edits were tested against the real `Pending Approval for Order Number 109591.eml` in the repo root and a reconstructed #A110413 delivery email. Confirmed: financial extraction is exact ($107.85 subtotal/coupon on the pickup order; $179.75 / $10.47 / $135.00 / $179.75 / $145.47 on the delivery order), order comments extract correctly from the tight shipment-details table, the master-sheet row carries compost total $179.75, delivery fee $135.00, and pre-tax total $314.75, and the alert template renders the comment line.

**Re-verified 2026-06-28** against the real `.eml` fixture and a reconstruction of delivery order #A110413 (John Ross, `CITYVCOM26`): `_summary_amount` extracted subtotal $179.75 / tax $10.47 / shipping $135.00 / coupon $179.75 / total $145.47; `_parse_order_comments` returned the shipment-details comment (and `TEST ORDER` on the real fixture, not the greeting); `build_master_sheet_rows` produced Compost Total $179.75, Delivery Fee $135.00, Total (No Tax) $314.75 on the first row; and the coordinator alert rendered the `Order Comments:` line. The four added dependencies install cleanly.

What has **not** been done: a local container build, the project's own test suite (if any), and any deploy. Treat the changes as code-reviewed by a targeted parser harness, not production-verified. The final pre-prod check remains: POST a real A110413-style email to `/api/ingest-cimcloud-email` after deploy and confirm Greg's row carries the dollar values and the alert shows the comment.

---

## 6. Recommended next steps for Cursor

1. `git status` and `git diff` to see the full working-tree state. Do not assume HEAD is the baseline (Section 2).
2. Confirm with Rick whether the prior uncommitted body of `main.py` matches what is currently running in Cloud Run, so you know whether you are deploying one change or a backlog of changes.
3. Stage and commit in legible units. Suggested: one commit for the prior parser/Graph/master-sheet body if it is genuinely uncommitted, then one commit titled along the lines of "Capture order financials and comments; populate master-sheet money columns and coordinator alert" for the Section 3 edits.
4. Build the container locally (`docker build dispatch/`) or let the `gcloud run deploy --source .` Cloud Build step do it, to confirm the four added dependencies install and the module imports.
5. Smoke-test `POST /api/ingest-cimcloud-email` with the repo's `.eml` body before deploying.
6. Commit, then deploy manually with `gcloud run deploy coupon-dispatch --source . --region us-west1 --project juris-coupon-valid` (run from `dispatch/`). Pushing to `main` is for version control only and does not deploy. Confirm the new Cloud Run revision comes up healthy (`GET /` → 200).
7. After deploy, run one real order end to end (CIMcloud "Resend Confirmation Email" on a known program order) and confirm Greg's sheet row carries the dollar values and the coordinator alert shows the comment line.

---

## 7. Reference files

- `dispatch/main.py` — the service. `_process_order` routes and writes Firestore; `parse_cimcloud_email` is the parser; `build_master_sheet_rows` builds Greg's rows; `_summary_amount` and `_parse_order_comments` are the new helpers.
- `dispatch/requirements.txt` — note the four added deps.
- `Pending Approval for Order Number 109591.eml` (repo root) — a real CIMcloud email, the parser test fixture.
- `CURSOR_HANDOFF.md` (repo root) — the original dispatch build handoff; routing rules and field provenance, but note its "No Payment Required" program-order test is superseded by the coupon-presence rule in Section 4.
- `docs/API_INTEGRATION.md` — endpoint and Power Automate integration detail.
