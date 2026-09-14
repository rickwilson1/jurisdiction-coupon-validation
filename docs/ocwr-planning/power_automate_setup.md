# Power Automate — Order Dispatch Setup

**Goal:** When CIMcloud emails an order to `sales@agromin.com`, automatically forward the HTML body to the `coupon-dispatch` Cloud Run service. The service parses the email, writes Firestore, emails the customer with pickup/delivery instructions, and CC's Ofelia.

**Time:** ~10 minutes
**Cost:** Requires Power Automate Premium (HTTP connector). Most M365 Business plans include it via the standard Power Automate license.

---

## Before you start — gather these values

| Item | Value |
|---|---|
| Endpoint URL | `https://coupon-dispatch-751008504644.us-west1.run.app/api/ingest-cimcloud-email` |
| API key (header `X-API-Key`) | `AgrominDispatch2026Secret` |
| Trigger mailbox | `sales@agromin.com` (shared mailbox) |
| Folder to watch | `Inbox` (or `Inbox/OCWR` if CIMcloud emails are auto-foldered there) |
| Subject filter | `Pending Approval for Order Number` |

> Note: the API key above will be rotated soon (it was shared in a chat). I'll send the new key when we rotate; just update the HTTP action header at that point.

---

## Step 1 — Create the flow

1. Go to <https://make.powerautomate.com>
2. Sign in with an account that has delegated access to `sales@agromin.com` (Rick's account works, since you have access to that mailbox)
3. Left sidebar → **Create**
4. Choose **Automated cloud flow**
5. Flow name: `Agromin Order Dispatch`
6. Trigger: search for and select **When a new email arrives in a shared mailbox (V2)** (Office 365 Outlook connector)
7. Click **Create**

---

## Step 2 — Configure the email trigger

In the trigger card:

| Field | Value |
|---|---|
| Original Mailbox Address | `sales@agromin.com` |
| Folder | `Inbox` (click the folder icon, navigate; if CIMcloud emails go to a subfolder like `OCWR`, pick that instead) |

Click **Show advanced options** and set:

| Field | Value |
|---|---|
| To | *(leave blank)* |
| From | *(leave blank — CIMcloud sends from a noreply address that varies)* |
| Importance | Any |
| Only with Attachments | No |
| Include Attachments | No |
| Subject Filter | `Pending Approval for Order Number` |

The Subject Filter is a substring match, so it will catch `Pending Approval for Order Number 109591`, `... 109592`, etc.

---

## Step 3 — Add the HTTP POST action

1. Click **+ New step**
2. Search for **HTTP** and select the **HTTP** action (icon is a globe; it says "Premium")
3. Configure:

| Field | Value |
|---|---|
| Method | `POST` |
| URI | `https://coupon-dispatch-751008504644.us-west1.run.app/api/ingest-cimcloud-email` |
| Headers | (see table below — click "+ Add new item" twice) |
| Body | Click in this field, then in the **Dynamic content** picker on the right select **Body** (under "When a new email arrives in a shared mailbox") |
| Queries | *(leave blank)* |

**Headers table** (3 entries):

| Key | Value |
|---|---|
| `Content-Type` | `text/html` |
| `X-API-Key` | `AgrominDispatch2026Secret` |
| `X-Email-Subject` | *(click the field, then in Dynamic content pick **Subject**)* |

> Critical: the **Body** field of the HTTP action must contain ONLY the dynamic-content **Body** token from the email trigger — nothing else, no quotes, no JSON wrapper. The Cloud Run endpoint reads the request body as raw HTML when `Content-Type: text/html`.

---

## Step 4 — Save and test

1. Click **Save** (top right)
2. Click **Test** (top right) → choose **Manually**
3. Now place a test order on <https://shop.agromin.com> using a known program coupon code (e.g. `CityANAcom26`). The CIMcloud email arrives in `sales@agromin.com` within ~30 seconds.
4. Power Automate will fire automatically. Refresh the test page to see the result.

You should see:
- The HTTP action shows `200 OK` with a body like:
  ```json
  {"status":"processed","order_number":"A109592","routing":"pickup_self_load","region":"oc","total_qty":3.0}
  ```
- The customer who placed the order receives a pickup-instructions email from `dispatch@agromin.com` (with Ofelia CC'd).

---

## Step 5 — Turn it on

After a successful test:

1. Go to **My flows** → find `Agromin Order Dispatch`
2. Make sure the toggle is **On**

---

## Troubleshooting

**HTTP action returns 401 `Invalid API key`**
→ The `X-API-Key` header value doesn't match. Check spelling and capitalization — it's case-sensitive.

**HTTP action returns 200 but `{"status":"skipped","reason":"..."}`**
→ The email body has no `Coupon Code:` field. This means either (a) the order didn't use a program coupon (working as intended, the flow ignores non-program orders), or (b) CIMcloud changed its email template. If you see this on a known program order, forward me the raw email and we'll update the parser.

**HTTP action returns 400 `Parse error`**
→ The email matched the subject filter but the parser couldn't extract required fields. Forward me the raw email — likely a template variation we haven't seen.

**Trigger doesn't fire when an email arrives**
→ Check that the folder you selected is where CIMcloud emails actually land (Outlook rules may move them). Also check **Run history** in Power Automate — it logs every trigger evaluation, including ones that didn't match the subject filter.

**Want to see the logs from the Cloud Run side**
→ Recent logs (one-shot):
```bash
gcloud run services logs read coupon-dispatch --region us-west1 --project juris-coupon-valid --limit 50
```
→ Live tail (requires `gcloud components install beta` once):
```bash
gcloud beta run services logs tail coupon-dispatch --region us-west1 --project juris-coupon-valid
```

---

## What the flow does NOT need (intentionally)

We deliberately put **all** the parsing logic on the Cloud Run side, so the Power Automate flow stays minimal:
- No HTML-to-text conversion
- No regex steps to extract order number, coupon code, etc.
- No JSON-construction (which is brittle in PA when bodies contain quotes/newlines)
- No Compose actions

If CIMcloud changes its email template, you only need to update the parser in `dispatch/main.py` and redeploy — the Power Automate flow stays untouched.

---

# Stage A — Excel append to Greg's Master Sheet

After the HTTP action returns `200 OK` from Cloud Run, the response body now includes a `master_sheet_rows` array. This is the **only** new addition to the flow: read those rows and append each one to Greg's `OCWR-Agromin Deliveries.xlsx` Master Sheet.

**Pre-flight:** the Master Sheet is already an Excel Table named `Table1` (range A1:W173). No conversion needed — the "Add a row to a table" action will work as-is.

**File to write to:**
- SharePoint site: `https://agromincorp.sharepoint.com/sites/OCWRxAgromin`
- Library: `Documents` → `Delivery Requests`
- File: `OCWR-Agromin Deliveries.xlsx`
- Direct link (Greg's file): https://agromincorp.sharepoint.com/:x:/s/OCWRxAgromin/IQB6SYSCukrKRLYxUP_JbLViAYS8fC8R37HZBR9DCB0eURY
- Table name: `Table1`
- Sheet: `Master Sheet`

> Note: only Agromin-tenant users can edit this file. The PA connection must be authenticated as someone with edit rights (Rick or anyone on the Agromin team with access to the OCWRxAgromin site).

---

## Step 6 — Add a "Parse JSON" action

After the HTTP action, add a new action:

1. Click **+ New step** → search for **Parse JSON** → select it
2. Configure:

| Field | Value |
|---|---|
| Content | **Body** of the HTTP action (Dynamic content picker) |
| Schema | Paste the JSON below |

```json
{
  "type": "object",
  "properties": {
    "status": { "type": "string" },
    "order_number": { "type": "string" },
    "routing": { "type": "string" },
    "region": { "type": "string" },
    "total_qty": { "type": "number" },
    "master_sheet_rows": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "Customer": { "type": "string" },
          "STATUS": { "type": "string" },
          "Date of \nRequest": { "type": "string" },
          "Scheduled\nDelivery Date": { "type": "string" },
          "Sales Order#": {},
          "Phone #": { "type": "string" },
          "Email": { "type": "string" },
          "Delivery Address": { "type": "string" },
          "City": { "type": "string" },
          "State": { "type": "string" },
          "Zip\nCode": { "type": "string" },
          "Origin\n(Greenery Name)": { "type": "string" },
          "Origin\n(Landfill Name)": { "type": "string" },
          "Material": { "type": "string" },
          "Compost\n(Quantity)": {},
          "Mulch\n(Quantity)": {},
          "Bags\n(# of Pallets)": {},
          "Compost\nTotal $": {},
          "Mulch\nTotal $": {},
          "Bags\nTotal $": {},
          "Delivery\nFee": {},
          "Total\n(No Tax)": {},
          "Notes": { "type": "string" }
        }
      }
    }
  }
}
```

> Empty schemas (`{}`) for numeric/string-or-blank fields are intentional. Cloud Run sends an int for `Sales Order#` and may send either a number or empty string for the quantity columns. Letting PA accept any JSON value avoids "schema validation failed" runtime errors.

---

## Step 7 — Add an "Apply to each" loop with the Excel action inside

1. Click **+ New step** → search for **Apply to each** (Control connector) → select it
2. **Select an output from previous steps:** in the Dynamic content picker, choose **master_sheet_rows** (it appears under the Parse JSON action)
3. Inside the loop, click **Add an action** → search **Excel Online (Business)** → select **Add a row to a table**
4. Configure the Excel action:

| Field | Value |
|---|---|
| Location | `OneDrive for Business` will not be correct — pick **SharePoint Site** option, then enter `https://agromincorp.sharepoint.com/sites/OCWRxAgromin` |
| Document Library | `Documents` |
| File | navigate `Delivery Requests / OCWR-Agromin Deliveries.xlsx` |
| Table | `Table1` |

Once those four are set, PA will pull the column list from the live file and render 23 input fields — one per Master Sheet column. **Bind each one to the matching field from the Parse JSON output** using the Dynamic content picker:

| PA field (matches Excel column) | Bind to |
|---|---|
| Customer | `Customer` |
| STATUS | `STATUS` |
| Date of Request | `Date of \nRequest` |
| Scheduled Delivery Date | `Scheduled\nDelivery Date` |
| Sales Order# | `Sales Order#` |
| Phone # | `Phone #` |
| Email | `Email` |
| Delivery Address | `Delivery Address` |
| City | `City` |
| State | `State` |
| Zip Code | `Zip\nCode` |
| Origin (Greenery Name) | `Origin\n(Greenery Name)` |
| Origin (Landfill Name) | `Origin\n(Landfill Name)` |
| Material | `Material` |
| Compost (Quantity) | `Compost\n(Quantity)` |
| Mulch (Quantity) | `Mulch\n(Quantity)` |
| Bags (# of Pallets) | `Bags\n(# of Pallets)` |
| Compost Total $ | `Compost\nTotal $` |
| Mulch Total $ | `Mulch\nTotal $` |
| Bags Total $ | `Bags\nTotal $` |
| Delivery Fee | `Delivery\nFee` |
| Total (No Tax) | `Total\n(No Tax)` |
| Notes | `Notes` |

The PA UI will show the column names without the visible newlines, but they'll match — the Dynamic content tokens carry the literal header strings.

---

## Step 8 — Save and test Stage A

1. Save the flow.
2. Place a real or test delivery order on shop.agromin.com using a program coupon. Pickup orders will skip Stage A (the `master_sheet_rows` array will be empty and the Apply-to-each loop runs zero times — by design).
3. Verify in PA Run history:
   - HTTP returns `200 OK` with `master_sheet_rows` populated for delivery orders
   - Parse JSON action shows the array
   - Apply to each runs once per material (one iteration for single-material orders, two for orders with both compost and mulch)
   - Each "Add a row to a table" action returns success
4. Open `OCWR-Agromin Deliveries.xlsx` and verify the new row(s) appear at the bottom of the Master Sheet table:
   - `STATUS` = `In Process`
   - `Date of Request` = today (in Pacific time)
   - `Sales Order#` = stripped of the `A` prefix and stored as a number
   - `Origin (Greenery Name)` and `Origin (Landfill Name)` are blank
   - `Notes` = `Auto-imported {M/D/YY}. Origin TBD — Greg to assign yard.`

If anything goes wrong, the Cloud Run side is unchanged from Phase 1's email behavior — the customer email still sends, and Ofelia is still CC'd. Stage A failures do not block the email pipeline.

---

## What Greg sees

- He keeps using the Master Sheet exactly as he does today.
- New orders appear at the bottom of the table within ~60 seconds of CIMcloud sending the order email.
- Greg fills in the two Origin columns by picking the right yard, and the Scheduled Delivery Date once he books with the customer. Everything else is pre-filled.
- The `Notes` column flags every auto-imported row so Greg can spot-check what came in via automation vs. what he typed.
