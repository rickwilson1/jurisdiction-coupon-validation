# Session Handoff — Sacramento Coupon Email Extraction

**Saved:** Tuesday, May 19, 2026, 1:46 PM PT
**Chat reference:** [Coupon Email Extract Setup](abfc75d2-36b7-4cc0-b483-5421d321e995)

---

## Goal
Extract names and emails of customers who received/used the Sacramento coupon code `CITYSACCOMB26`, originally from `sales@agromin.com`.

## What we built

A Power Automate flow named **`Coupon Email Extract`** in Rick Wilson's default environment.

### Trigger
- **Manually trigger a flow**
- Input: text field named `coupon_code`

### Action 1 — Office 365 Outlook → Get emails (V3)
```json
{
  "importance": "Any",
  "fetchOnlyWithAttachment": false,
  "folderPath": "Inbox",
  "fetchOnlyUnread": false,
  "mailboxAddress": "sales@agromin.com",
  "includeAttachments": false,
  "searchQuery": "@triggerBody()?['text']",
  "top": 1000
}
```
Connection: `shared_office365` (signed in as `rickwilson@agromin.com`).

### Action 2 — OneDrive for Business → Create file
```json
{
  "folderPath": "/",
  "name": "coupons-emails-CITYSACCOMB26.json",
  "body": "@string(body('Get_emails_(V3)')?['value'])"
}
```
Connection: `shared_onedriveforbusiness` (signed in as `rickwilson@agromin.com`). `transferMode: Chunked`.

---

## Test result (CITYSACCOMB26 — May 19, 1:37 PM)

- Status: succeeded in 2 seconds
- Returned exactly **1 email** (Content-Length 36,152 bytes of JSON)
- File saved at: OneDrive root → `coupons-emails-CITYSACCOMB26.json`

### The one email

| Field | Value |
|---|---|
| From | Kendall Avrea `<kendall@agromin.com>` |
| To | `sales@agromin.com`, `mrsmikki0321@gmail.com` |
| Subject | Re: New Account Access |
| Date | 2026-04-24 17:54 UTC |
| Body excerpt | "Coupon Code for Bags - **CITYSACCOMB26**" / "Coupon Code for Bulk material- CITYSACCOM26" |

### Customer extracted from the embedded CIMcloud "New Account" form in the email

| Field | Value |
|---|---|
| Name | MICHELLE CHARLES |
| Username | mrsmikki0321 |
| Phone | 916-919-0643 |
| Email | mrsmikki0321@gmail.com |
| Address | 1017 Nogales St, Sacramento, CA 95838-4417 |
| Company | MICHELLE CHARLES |
| Account created | 2026-04-23 |

---

## Why only 1 result (interpretation)

1. Sacramento program is brand-new — code first issued April 24, 2026 (~3 weeks before this session).
2. Kendall Avrea distributes the code by emailing customers individually from her own mailbox (`kendall@agromin.com`). The `sales@agromin.com` shared mailbox only receives a copy when she CC's it — only Michelle's thread had that CC.
3. The "thousands of emails" Rick saw in `sales@` are OCWR program emails (different campaign, different codes), not Sacramento.

---

## Parked decision — where to search next

When resuming, pick one of:

1. **Search Kendall's Sent Items** (`kendall@agromin.com → Sent Items`) — most likely the master list of every customer she emailed the code to. Requires Kendall granting "delegated/shared" access OR Rick being signed in as Kendall in the OneDrive/O365 connector.
2. **Other folders of sales@agromin.com** — Archive, Sent Items, Deleted Items (clone the flow, change `folderPath` per run).
3. **Tenant-wide search** via Microsoft Purview / eDiscovery (Compliance Center) — finds the code across every Agromin mailbox in one query. Requires Compliance Admin or eDiscovery Manager role.
4. **Accept the 1 result** — produce a single-row CSV for Michelle Charles and call it done.

---

## To resume

### To re-run the existing flow
1. Power Automate → My flows → `Coupon Email Extract`
2. Click Run → enter coupon code (e.g. try `CITYSACCOM26` for bulk variant)
3. Wait for completion, download JSON from OneDrive root

### To search Kendall's Sent Items
- Clone flow `Coupon Email Extract` → "Save As"
- In the cloned flow's Get emails (V3) action, change:
  - `mailboxAddress` → `kendall@agromin.com`
  - `folderPath` → `Sent Items`
- Note: requires `Mail.Read.Shared` on Kendall's mailbox. If the O365 connector errors with 403, Rick needs Kendall to either share the mailbox OR sign in as Kendall to create the connection. Wayne shouldn't be needed — Kendall can grant shared access from Outlook Web (right-click mailbox → Permissions → Add Rick with Read).

### Parser (pending)
We have a CIMcloud HTML email parser inlined in `coupon_extract.py` (workspace root). It can parse the `body` HTML of each email object in the JSON file. To use it on the downloaded `coupons-emails-CITYSACCOMB26.json`:

```bash
cd /Users/rickwilson/Documents/Active_Projects/Agromin/coupon-dispatch
source .venv/bin/activate
# (parser script for this JSON file not yet written — request when resuming)
```

The parser handles:
- CIMcloud "Order Confirmation" emails → extracts order#, items, totals, ship-to
- CIMcloud "New Account" emails → extracts name, email, phone, address (this is what the 1 result is)
- Direct human emails → falls back to From/Subject/Body snippet
- Dedupes by `conversationId`

---

## Related files in workspace
- `coupon_extract.py` — original Graph API extraction script (blocked by admin consent earlier, see chat); the inlined CIMcloud parser is reusable
- `dispatch/main.py` — canonical CIMcloud parser (Stage A / Stage B logic)
- `SYSTEM_ARCHITECTURE.md` — overall data flow doc
- `docs/coupon-validator.html` / `docs/ocwr-dispatch.html` — service one-pagers
