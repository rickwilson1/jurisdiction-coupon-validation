# Phase 1 — Open Questions Before Build
**Agromin · OCWR Order Dispatch · April 2026**

---

## Still Open (2 items blocking build)

### SUPERSEDED — SMTP password
No longer applicable. The dispatch service authenticates to Microsoft Graph with app-only
credentials, so no `dispatch@agromin.com` mailbox password is used anywhere in the pipeline.
The value that previously appeared below has been redacted and must be treated as compromised,
because it was committed to a public repository on 2026-04-26.

Commands originally sent to Converged:
```powershell
# Step 1 — Connect to Microsoft Online (sign in with admin credentials when prompted)
Connect-MsolService

# Step 2 — Set the password on the dispatch@agromin.com shared mailbox
Set-MsolUserPassword -UserPrincipalName dispatch@agromin.com -NewPassword "<REDACTED>" -ForceChangePassword $false

# Step 3 — Verify the account (send screenshot of output)
Get-MsolUser -UserPrincipalName dispatch@agromin.com | Select DisplayName, UserPrincipalName, StrongPasswordRequired

# Step 4 — Confirm SMTP auth is still enabled (send screenshot of output)
Get-CASMailbox -Identity dispatch@agromin.com | Select Name, SmtpClientAuthenticationDisabled
```

*Blocks: end-to-end email testing of the dispatch service*

---

## Resolved — Confirmed Answers

### People / Roles (Q1)
- **Greg Jackson** (`greg@agromin.com`) — delivery coordinator, primary alert recipient
- **Brian** (`brian@agromin.com`) — oversight and scheduling support, hauling/truck knowledge, co-manages delivery schedule workbook; receives delivery alerts
- **Kendall** (`kendall@agromin.com`) — OCWR side; receives delivery alerts, monitors QR code submissions spreadsheet
- **David (OCWR)** — copied on communications, relays Greenery movement for OCWR internal tracking; not a primary alert recipient
- **Ofelia** (`ofelia.velarde-garcia@ocwr.ocgov.com`) — CC'd on all customer emails

Delivery alert goes to: Greg + Brian + Kendall

---

### Yard Name Strings in CIMcloud (Q2)
Confirmed exact `shipping_method` strings from CIMcloud order confirmation emails:

| Yard | CIMcloud shipping_method string |
|---|---|
| Bee Canyon / Frank R. Bowerman (Irvine) | `Frank R. Bowerman Landfill Pick Up` |
| Capistrano / Prima Deshecha | `Prima Deshecha Landfill Pick Up` |
| Valencia / Olinda Alpha (Brea) | `Olinda Alpha Landfill Pick Up` |

There is also `"OCWR Yard Pick Up - JURI"` but it is not retail-facing and can be ignored.

The existing `YARD_LOCATIONS` dict in the build spec uses the correct keys — substring matching will work as written.

---

### QR Code System (Q3)
Three separate Microsoft Forms, one per yard:

| Yard | Form URL |
|---|---|
| Frank R. Bowerman | https://forms.office.com/r/Ywy7m8jcwv |
| Prima Deshecha | https://forms.office.com/r/2CsTHP7TjB |
| Olinda Alpha | https://forms.office.com/r/9LWPGvf52e |

Customer submits: Name, Order Number, picking up for someone else (Y/N), if yes: name order is under, bucket used, number of scoops.

Submissions go to SharePoint: https://agromincorp.sharepoint.com/:x:/s/OCWRxAgromin/IQDfcQPIbTGqTp9s0got1FM6AUAs_KPWor7pF00Eu-8yOww

Kendall monitors. **Not yet deployed at yards.**

**Dispatch service behavior:** Pickup confirmation emails should NOT include the form URLs. Include only a brief note that customers will see a sign at the yard asking them to log their pickup — this helps OCWR stay in compliance with SB 1383. The QR code is scanned at the yard, not before arrival.

---

### Environment Variables (Q4)

| Variable | Value |
|---|---|
| `SMTP_USER` | *(superseded, no SMTP auth in the deployed service)* |
| `SMTP_PASSWORD` | *(superseded, redacted; service uses Graph app-only credentials)* |
| `OFELIA_EMAIL` | `ofelia.velarde-garcia@ocwr.ocgov.com` |
| `GREG_EMAIL` | `greg@agromin.com` |
| `BRIAN_EMAIL` | `brian@agromin.com` |
| `KENDALL_EMAIL` | `kendall@agromin.com` |

---

### Ventura / Sacramento Coordinators (Q5)
- **Ventura**: Chris Kennedy (`chris@agromin.com`) or Benito (`benito@agromin.com`)
- **Sacramento**: Rosa Bon (`rosa@agromin.com`)

**Ventura pickup yards — corrected from original spec:**

| Yard | Address |
|---|---|
| Aqua-Flo Ventura | 2471 Portola Rd #300, Ventura, CA 93003 |
| Agromin Kinetic | 201 Kinetic Drive, Oxnard, CA 93030 · Mon–Fri 7am–4:30pm, Sat 7am–12pm |

Aqua-Flo Ojai and Agromin Oxnard (from original spec) are NOT the correct Ventura pickup yards.

---

---

## Phase 1 fragility note (added 2026-05-01)

Phase 1 currently makes Greg's `OCWR-Agromin Deliveries.xlsx` Master Sheet the system of record. Power Automate writes new rows into `Table1` via the Excel Online connector. This works but is **fragile to normal Excel user behavior**:

| If Greg... | Phase 1 breaks how? |
|---|---|
| Renames the workbook | PA can't find the file → orders silently fail to write |
| Moves it to a different SharePoint folder | Same — PA's file ID is path-based |
| Renames `Table1` | "Add a row to a table" fails — table name is hard-coded |
| Deletes a column or renames a header | PA write fails with "column not found" |
| Adds a new column or reorders columns | OK — PA binds by header name |
| Downloads, edits in desktop Excel, re-uploads | SharePoint may issue a new file ID → PA breaks |

### Interim mitigation (until Phase 2 ships the web app)

1. Tell Greg explicitly: **"Don't rename the file, don't rename `Table1`, don't change column headers. Tell me first if you need to."**
2. Optional: add a SharePoint version-history alert so we catch breakage fast.
3. Treat this as a known fragility we accept in exchange for Phase 1's fast time-to-value.

### Permanent fix (Phase 2)

The Phase 2 design principle (see `SESSION_HANDOFF_2026-04-30.md` §17) flips the polarity: web app database becomes the system of record, spreadsheets become disposable read-only exports the app produces. Once Phase 2 ships, Excel-edit fragility goes away.

---

*Last updated: May 1, 2026*
