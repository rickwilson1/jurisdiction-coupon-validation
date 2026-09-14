# Agromin OCWR Order Dispatch — System Architecture & Operational Dependencies

**Document version:** 1.0
**Last updated:** 2026-05-01
**Audience:** Development team, future maintainers, IT vendors who inherit this system
**Owner:** Rick Wilson (rickwilson@agromin.com)

---

## 1. Purpose of this document

This is the canonical technical reference for the Agromin OCWR Order Dispatch system. It documents:

1. What the system does and how it is composed
2. Which cloud platforms host which components, and why
3. Which dependencies live inside Agromin's Microsoft 365 tenant (managed by Converged) versus inside the Google Cloud project (managed by the development team)
4. How to deploy, operate, and troubleshoot the system
5. What to do if the development team or the M365 service provider changes

It is intentionally written to stand alone — a new developer or vendor should be able to read this document and understand the system without consulting the project's session handoff notes or chat history.

---

## 2. System overview

### What the system does

The OCWR Order Dispatch system automates the fulfillment workflow for Agromin's Orange County Waste & Recycling (OCWR) coupon program. When an OC resident places a free compost or mulch order at `shop.agromin.com` using a valid OCWR coupon, the system:

1. **Receives the order** as a "Pending Approval" email from CIMcloud (Agromin's e-commerce platform) into the `sales@agromin.com` mailbox
2. **Parses the order** to extract customer, address, material, quantity, and shipping method
3. **Routes the order** to the correct fulfillment path:
   - **Self-load pickup** (under 5 cubic yards): customer drives to a yard and self-serves
   - **Staff-load pickup** (5+ cubic yards): customer drives to a yard, OCWR staff loads with equipment
   - **Delivery**: scheduled delivery to the customer's address
4. **Sends a customer-facing email** with pickup or delivery instructions, sender `dispatch@agromin.com`, with Ofelia (OCWR liaison) CC'd
5. **Sends a coordinator alert** for delivery orders to Greg, Brian, and Kendall (Agromin scheduling team)
6. **Logs the order** to Firestore (audit trail) and, for delivery orders, appends a row to Greg's master tracking spreadsheet on SharePoint

The system handles all valid order types end-to-end without human intervention until the moment a delivery needs to be physically scheduled (Greg's job) or picked up (the resident's job).

### Volume and scale

- **Current volume:** ~10 orders per week during program peaks, near zero off-peak
- **Expected peak:** under 50 orders per week even at maximum program scale
- **Users of internal tools:** 5–10 (Agromin scheduling team + OCWR liaisons)

The system is designed for this scale; it does not need horizontal scaling, sharding, or load balancing.

---

## 3. Architecture diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         Microsoft 365 (Agromin tenant)            │
│                         Managed by: Converged (third-party MSP)   │
│                                                                   │
│   ┌────────────────┐   ┌──────────────────┐   ┌──────────────┐    │
│   │ Outlook        │   │ Power Automate   │   │ SharePoint   │    │
│   │ sales@         │──▶│ Agromin Order    │   │ OCWRxAgromin │    │
│   │ (CIMcloud      │   │ Dispatch flow    │   │ site         │    │
│   │  emails)       │   └────────┬─────────┘   └──────▲───────┘    │
│   └────────────────┘            │                    │            │
│   ┌────────────────┐            │                    │ Excel API  │
│   │ Outlook        │            │                    │            │
│   │ dispatch@      │◀───────────┼────────────────────┘            │
│   │ (system mail)  │            │                                 │
│   └───────▲────────┘            │                                 │
│           │ Graph API           │ HTTPS POST                      │
│           │ (Mail.Send)         │ (X-API-Key)                     │
└───────────┼─────────────────────┼─────────────────────────────────┘
            │                     ▼
            │       ┌───────────────────────────────┐
            │       │   Google Cloud Platform        │
            │       │   Project: juris-coupon-valid  │
            │       │   Managed by: dev team         │
            │       │                                │
            │       │   ┌────────────────────────┐   │
            └───────│──▶│ Cloud Run service:     │   │
                    │   │ coupon-dispatch        │   │
                    │   │ (FastAPI + Python 3.11)│   │
                    │   └─────────┬──────────────┘   │
                    │             │                  │
                    │             ▼                  │
                    │   ┌────────────────────────┐   │
                    │   │ Firestore              │   │
                    │   │ (order audit log)      │   │
                    │   └────────────────────────┘   │
                    │                                │
                    │   ┌────────────────────────┐   │
                    │   │ Secret Manager         │   │
                    │   │ (API keys, Graph creds)│   │
                    │   └────────────────────────┘   │
                    └───────────────────────────────┘
```

**Data flow:**

1. CIMcloud sends an order email to `sales@agromin.com` (M365)
2. Power Automate flow detects the email, POSTs the body to Cloud Run (GCP) over HTTPS with an API key
3. Cloud Run parses the order, decides routing, sends customer email + coordinator alert via Microsoft Graph API back into M365
4. Cloud Run writes the order to Firestore for audit and returns a structured response
5. Power Automate parses the response and, for delivery orders, appends a row to the SharePoint Excel file via the Excel Online connector

---

## 4. Cloud platform decision: GCP for application hosting

### Decision

The application layer (compute and database) is hosted on **Google Cloud Platform**. The integration touchpoints (mail, scheduling, file storage) are hosted on **Microsoft 365** because that is Agromin's existing productivity platform.

This is intentional and is the planned long-term architecture. Phase 2 (the scheduling web application, currently in design) will continue to use GCP for application hosting.

### Rationale

The decision was made on operational, not technical, grounds. The two platforms are technically comparable for an application of this scale and shape; Azure App Service / Container Apps could host the same workload with similar performance and cost. The decisive factors were:

| Factor | Why it favored GCP |
|---|---|
| **Operational ownership** | The development team has direct administrative control over the GCP project. M365 is administered by a third-party managed services provider (Converged), which means every Azure-side configuration change becomes a vendor ticket with associated coordination cost and billing impact for Agromin. |
| **Change velocity** | Application changes (deploys, environment variables, secret rotations, log inspection) happen in seconds on the platform the developer controls directly. Equivalent changes on a vendor-administered platform would be queued behind the vendor's SLA. |
| **Vendor concentration risk** | Hosting the application on the same platform that Agromin's IT vendor administers would couple the application's operational availability to the vendor relationship. Hosting on a separate platform preserves continuity if Agromin changes IT vendors. |
| **Cost predictability** | GCP's free-tier coverage absorbs the entire workload at current and projected volumes (Cloud Run scale-to-zero, Firestore free quota). Application hosting cost is effectively zero. |

### What was considered and rejected

- **Azure App Service / Container Apps:** technically equivalent to Cloud Run for this workload. Rejected because of the operational-ownership factor above.
- **Power Apps + Dataverse:** rejected because the per-user/per-app licensing cost model is unfavorable for a 5–10 user internal tool that runs frequently, and because of long-term flexibility constraints if the system grows beyond a basic CRUD/calendar app.
- **Self-hosted on Agromin infrastructure:** not considered seriously; Agromin does not operate server infrastructure.

### When to revisit this decision

This decision should be re-evaluated only if Agromin changes its IT staffing model — for example, if Agromin in-houses a Microsoft-stack developer, or if Converged's contract is restructured to include custom application operations. Absent one of those changes, GCP remains the correct platform.

---

## 5. GCP resources (development team controlled)

All GCP resources are in the project **`juris-coupon-valid`**, region **`us-west1`**.

| Resource | Identifier | Purpose |
|---|---|---|
| Cloud Run service | `coupon-dispatch` | Hosts the FastAPI application that parses orders and sends mail |
| Cloud Run URL | `https://coupon-dispatch-751008504644.us-west1.run.app` | Public HTTPS endpoint Power Automate calls |
| Firestore database | (default) | Document store for order audit log |
| Secret Manager | (multiple secrets — see §7) | Stores API keys and Microsoft Graph client secret |
| Service account | Cloud Run default | Identity Cloud Run uses for Firestore and Secret Manager access |
| Container Registry | `gcr.io/juris-coupon-valid/coupon-dispatch` | Container images built during deploy |

**Deployment command (run from `dispatch/` directory):**

```bash
gcloud run deploy coupon-dispatch \
  --source . \
  --region us-west1 \
  --project juris-coupon-valid \
  --allow-unauthenticated \
  --quiet
```

**Logs:**

```bash
gcloud beta run services logs tail coupon-dispatch \
  --region=us-west1 \
  --project=juris-coupon-valid
```

**Source code:** `dispatch/main.py` (single-file FastAPI application). Dependencies in `dispatch/requirements.txt`. Container build in `dispatch/Dockerfile`.

---

## 6. Microsoft 365 resources (Converged controlled)

These resources live inside Agromin's M365 tenant. The development team **does not have administrative control** over them; changes require a request to Converged.

### 6.1 Mailboxes

| Mailbox | Type | Purpose | Required configuration |
|---|---|---|---|
| `dispatch@agromin.com` | Shared / service mailbox | System sender for all customer-facing email | Mailbox exists; SMTP auth not required (uses Graph API) |
| `sales@agromin.com` | Shared mailbox | Receives CIMcloud order emails | Subfolder `OCWR` exists; Power Automate has read access |
| `ofelia.velarde-garcia@ocwr.ocgov.com` | External | CC'd on all customer emails (OCWR liaison) | External recipient — no tenant config needed |
| `greg@agromin.com`, `brian@agromin.com`, `kendall@agromin.com` | User mailboxes | Receive coordinator alerts for delivery orders | Standard mailboxes |

### 6.2 Azure AD app registration

| Item | Value |
|---|---|
| Display name | *(to be confirmed with Converged — capture during next ticket)* |
| Application (client) ID | *(stored in Secret Manager; obtain from Converged for documentation)* |
| Directory (tenant) ID | *(stored in Secret Manager; obtain from Converged for documentation)* |
| Authentication mode | Client credentials (app-only, no user context) |
| Client secret rotation | Required quarterly; ticket Converged when expiry approaches |

**Granted Microsoft Graph permissions (application, admin-consented):**

| Permission | Scope | Used for |
|---|---|---|
| `Mail.Send` | Restricted to `dispatch@agromin.com` only via Exchange RBAC | Sending customer and coordinator emails |

The `Mail.Send` permission is scoped via Exchange Online RBAC so the app cannot send mail from any other mailbox in the tenant. This was configured by Converged at app registration time.

### 6.3 SharePoint

| Item | Value |
|---|---|
| Site | `https://agromincorp.sharepoint.com/sites/OCWRxAgromin` |
| Document library | `Documents` |
| Primary file | `Delivery Requests/OCWR-Agromin Deliveries.xlsx` |
| Excel table within file | `Table1` (range A1:W) — 23 columns |
| Access for Power Automate | `rickwilson@agromin.com` connection (member of site) |

The application does not access SharePoint directly. All SharePoint writes happen via Power Automate's Excel Online connector running under the `rickwilson@agromin.com` connection account.

### 6.4 Power Automate flow

| Item | Value |
|---|---|
| Flow name | `Agromin Order Dispatch` |
| Owner | `rickwilson@agromin.com` |
| Trigger | New email in `sales@agromin.com / OCWR` folder, subject contains "Pending Approval for Order Number" |
| Actions (in order) | (1) HTTP POST to Cloud Run with email body and `X-API-Key`; (2) Parse JSON response; (3) Apply to each `master_sheet_rows` → Add a row to `Table1` |
| Connections used | Office 365 Outlook (`sales@`), HTTP, Excel Online (Business) (`rickwilson@`) |

**Configuration reference:** see `power_automate_setup.md` for step-by-step setup of this flow.

---

## 7. Secrets and credentials

All secrets are stored in **GCP Secret Manager** in the `juris-coupon-valid` project, mounted as environment variables into the Cloud Run service at deploy time.

| Secret name | Purpose | Rotation responsibility | Rotation cadence |
|---|---|---|---|
| `DISPATCH_API_KEY` | Shared secret between Power Automate and Cloud Run; protects the ingest endpoint | Development team | Annual or on suspicion of compromise |
| `GRAPH_CLIENT_ID` | Azure AD app registration client ID | Converged | Static (rotates only if app is re-registered) |
| `GRAPH_TENANT_ID` | Azure AD tenant ID | Converged | Static |
| `GRAPH_CLIENT_SECRET` | Azure AD app registration client secret | Converged | Quarterly (Azure AD enforces 24-month max lifetime; recommend 90-day rotation) |

**Rotation procedure for `GRAPH_CLIENT_SECRET`:**

1. Open a ticket with Converged 30 days before expected expiry, requesting a new client secret on the existing app registration
2. Converged provides the new secret value (typically via a secure share)
3. Add the new secret value as a new version in Secret Manager: `gcloud secrets versions add GRAPH_CLIENT_SECRET --data-file=- --project=juris-coupon-valid`
4. Redeploy Cloud Run service to pick up the new version
5. Verify by sending a test email; confirm in logs that Graph authentication succeeds
6. Once confirmed, ask Converged to invalidate the old secret

---

## 8. Operational roles and responsibilities

| Function | Owner | Notes |
|---|---|---|
| Application code, deploys, GCP infrastructure | Development team (Rick Wilson) | Direct admin access to `juris-coupon-valid` project |
| Application monitoring and incident response | Development team | Cloud Logging alerts route to dev team email |
| M365 tenant administration (mailboxes, app registrations, Exchange RBAC) | Converged | Third-party MSP; engagement via ticket |
| SharePoint site permissions and structure | Agromin internal SharePoint site owner (currently Greg Jackson) | Not Converged-managed; site-owner responsibility |
| Power Automate flow ownership and editing | Development team via `rickwilson@agromin.com` | Flow lives in Rick's M365 account; if Rick leaves, flow ownership must transfer before account is disabled |
| CIMcloud platform configuration | Agromin (commerce team) | Out of scope for this system |
| Customer-facing email content | Development team (templates in code) | Changes require code deploy |

---

## 9. Deploy, operate, and troubleshoot

### Deploy a code change

```bash
cd dispatch/
gcloud run deploy coupon-dispatch \
  --source . \
  --region us-west1 \
  --project juris-coupon-valid \
  --allow-unauthenticated \
  --quiet
```

The first deploy from a fresh machine requires `gcloud auth login` and `gcloud config set project juris-coupon-valid`.

### Read logs

```bash
gcloud beta run services logs tail coupon-dispatch \
  --region=us-west1 \
  --project=juris-coupon-valid
```

For historical logs, use the Cloud Run console → Logs tab.

### Inspect Firestore records

GCP Console → Firestore → Data → `orders` collection. Each document is keyed by order number and contains the parsed payload, routing decision, and timestamps.

### Health check

```bash
curl https://coupon-dispatch-751008504644.us-west1.run.app/health
```

Expected response: `{"status": "ok"}` with HTTP 200.

### Common failure modes

| Symptom | Likely cause | Remediation |
|---|---|---|
| 401 from Cloud Run on Power Automate POST | `X-API-Key` mismatch | Confirm Power Automate header matches `DISPATCH_API_KEY` in Secret Manager |
| 500 from Cloud Run with `MSAL` error | Expired Graph client secret | Rotate per §7 procedure |
| Customer email never sent, no error in Cloud Run logs | Graph throttling or transient M365 issue | Check Microsoft 365 service health in M365 admin center; retry the order via PA flow's "Resubmit" |
| New row missing from SharePoint Excel | Power Automate connection expired or Excel table renamed | Open the PA flow, check connection status; verify `Table1` still exists in the workbook |
| Power Automate trigger not firing | New CIMcloud email subject format | Inspect the email; update PA trigger filter if subject changed |

---

## 10. Disaster recovery and handoff

### If the development team changes

The next developer should be able to take over with this document, the source code in `dispatch/`, and access to the GCP project. Required handover steps:

1. Grant the new developer Owner role on the `juris-coupon-valid` GCP project
2. Transfer ownership of the `Agromin Order Dispatch` Power Automate flow from `rickwilson@agromin.com` to the new developer's Agromin account (must happen *before* `rickwilson@agromin.com` is disabled, or the flow is orphaned)
3. Rotate `DISPATCH_API_KEY` and update Power Automate's HTTP step
4. Update the "Owner" line at the top of this document

### If Converged is replaced as M365 vendor

The next M365 service provider must:

1. Preserve the `dispatch@agromin.com` mailbox (do not delete or convert)
2. Preserve the existing Azure AD app registration and its `Mail.Send` permission scoped to `dispatch@agromin.com`
3. Provide the development team with continued access to rotate the client secret on that app registration

If the app registration is lost (deleted, not migrated), the development team must:

1. Request a new app registration in Agromin's tenant with `Mail.Send` permission, RBAC-scoped to `dispatch@agromin.com` only
2. Update `GRAPH_CLIENT_ID`, `GRAPH_TENANT_ID`, and `GRAPH_CLIENT_SECRET` secrets
3. Redeploy the Cloud Run service
4. Smoke-test by sending a test customer email

This recovery is feasible from this document alone; no out-of-band knowledge is required.

### If the Cloud Run service is deleted or the GCP project is lost

Application source is in version control. To rebuild from scratch:

1. Create a new GCP project (or restore the old one if recoverable)
2. Enable Cloud Run, Firestore, and Secret Manager APIs
3. Recreate secrets per §7 (values must come from Converged for the Graph credentials)
4. Deploy: `gcloud run deploy coupon-dispatch --source . --region us-west1 --project <new-project> --allow-unauthenticated`
5. Update Power Automate's HTTP step with the new Cloud Run URL

Time to recovery: approximately 2 hours assuming Graph credentials are available.

### Current account ownership limitation (interim state)

The GCP project `juris-coupon-valid` was provisioned in the developer's personal GCP account during initial Phase 1 development. This is an interim state, not the long-term arrangement. The planned remediation — migrating the project to an Agromin-owned GCP organization — is documented in §12.

Until that migration is complete, the developer should ensure:

- Source code remains in version control (not solely on local disk)
- All secrets are documented in §7 of this document so they can be re-provisioned in a new project if needed
- Agromin leadership is aware that account-level continuity (as distinct from code-level continuity) depends on the developer's personal Google account remaining in good standing
- The disaster recovery rebuild procedure above is exercised at least once before Phase 2 launches, to validate that the system can be reconstructed from this document alone

---

## 11. Decision log

Architectural decisions are recorded here so future maintainers understand the reasoning without re-litigating.

| Date | Decision | Rationale |
|---|---|---|
| 2026-04 | Use GCP for application hosting (not Azure) | Operational ownership boundary; see §4 |
| 2026-04 | Use Cloud Run (not Compute Engine, not Cloud Functions) | Container-based, scale-to-zero, simplest deployment for a small FastAPI app |
| 2026-04 | Use Firestore (not Cloud SQL) | NoSQL fits the order-document shape; free tier covers volume |
| 2026-04 | Use Microsoft Graph API for outbound mail (not SMTP) | App-only auth via Azure AD app registration; eliminates need for shared mailbox passwords |
| 2026-04 | Power Automate as the email-trigger glue (not Cloud Run pulling from Outlook) | Avoids storing Outlook credentials in GCP; lets Converged manage the M365 boundary |
| 2026-04 | Power Automate writes to SharePoint Excel directly (not Cloud Run via Graph Excel API) | Lower implementation cost; keeps the SharePoint write logic visible to Agromin in the PA portal |
| 2026-05 | Phase 2 web application will also use GCP | Consistency with Phase 1, operational ownership; see §4 |
| 2026-05 | Phase 2 will use the application database as the system of record (not SharePoint Excel) | Excel files are fragile to user editing; database is durable and schema-enforced |
| 2026-05 | Establish an Agromin-owned GCP organization (Cloud Identity Free + organization, not loose project under a single email) | Agromin will have multiple cloud projects in the future; org-level governance, billing, IAM, and policies are essential for managing more than one project |
| 2026-05 | Defer GCP organization migration until after Phase 2 ships | Avoid changing the deployment substrate while validating Phase 1 and building Phase 2; project transfer is a stable-state activity, not something to do mid-build |

---

## 12. Planned future work: Migrate to Agromin-owned GCP organization

This section documents work that is **planned but not yet executed**. Target timing: after Phase 2 has shipped and stabilized in production. It is recorded here so that the migration can be picked up by any future developer (or by the current developer, after time has passed) without re-deriving the plan.

### 12.1 Why migrate

The GCP project is currently provisioned in the developer's personal GCP account. This is appropriate for initial development but creates several risks for Agromin's long-term operations:

| Risk | Consequence |
|---|---|
| **Account continuity** | If the developer's personal Google account is suspended, frozen for a billing issue, or otherwise inaccessible, Agromin's production system loses its administrative path |
| **Bus factor** | If the developer is incapacitated, Agromin has no inheritance path — Google does not transfer ownership of personal accounts to third parties, even with a contractual claim |
| **Data residency / liability** | Customer personally identifiable information (names, addresses, phones, emails) currently resides in a personal cloud account; standard practice is for client data to live in client-owned infrastructure |
| **Cost overrun exposure** | Although current cost is zero (free tier), any future overrun (a runaway loop, an unexpected scaling event) bills the developer's personal credit card rather than Agromin |
| **Audit / compliance posture** | A security review or compliance audit would flag personal-account ownership as a governance gap |
| **Multi-project growth** | Agromin is expected to add more cloud projects (Phase 2 scheduling tool, future business automations). Without an organization-level structure, each new project compounds the per-project administrative cost |

### 12.2 Target state

| Layer | Current | Target |
|---|---|---|
| Identity provider for GCP | Developer's personal Google account | Cloud Identity Free for `agromin.com` (Google's free directory service) |
| GCP organization | None (project lives outside any org) | `agromin.com` organization |
| Project location | `juris-coupon-valid` (loose project) | `agromin-coupon-dispatch-prod` inside `Production` folder of `agromin.com` org |
| Billing | Developer's personal billing account | Agromin-owned billing account, attached at organization level |
| Org Admin | N/A | Developer (primary), Agromin executive (e.g., CFO) as fallback Org Owner |
| Future projects | Each provisioned independently | Inherit billing, IAM, policies from organization |

### 12.3 Recommended organizational structure

```
Organization: agromin.com
│
├─ Folder: Production
│  ├─ Project: agromin-coupon-dispatch-prod   (Phase 1, post-transfer)
│  ├─ Project: agromin-scheduling-prod        (Phase 2, built directly here)
│  └─ Project: agromin-{future}-prod
│
├─ Folder: Development                         (optional — add when needed)
│  └─ Project: agromin-{purpose}-dev
│
└─ Folder: Shared                              (optional — add when needed)
   └─ Project: agromin-shared-services
```

**Project naming convention:** `agromin-{purpose}-{env}` — descriptive, scoped, no ambiguity. Avoid legacy or non-obvious project IDs.

### 12.4 Pre-flight check (before starting the migration)

Before initiating the Cloud Identity Free signup, verify there are no consumer Google account conflicts on the `agromin.com` domain:

> If anyone at Agromin has previously signed up for Gmail, Google Drive, YouTube, or any other consumer Google product using their `@agromin.com` email address, those count as "consumer Google accounts" tied to the domain. When verifying the domain for Cloud Identity, Google flags these and requires a "domain conflict resolution" process where consumer accounts are migrated or renamed.

Procedure to check:
1. Ask Converged (or Agromin's M365 admin) to list all `@agromin.com` accounts that have ever been used outside the M365 tenant
2. Alternatively, attempt domain verification and read Google's response — Google will report any conflicts before you commit
3. If conflicts exist, follow Google's documented domain-conflict process; budget an extra day for the migration ceremony

This check costs nothing and prevents the migration from being interrupted partway through.

### 12.5 Migration sequence

Once the pre-flight check is complete and Phase 2 has shipped:

**Phase 0 — Establish the GCP foundation (one-time)**

1. Wayne (or Agromin M365 admin) creates the mailbox `cloud@agromin.com` (or similar — `gcp-admin@`, `infrastructure@`)
2. Sign up for Cloud Identity Free at `cloud.google.com/identity` using the new mailbox
3. Verify domain ownership via DNS TXT record (one Converged ticket — they add the record to Agromin's DNS)
4. Once verified, the `agromin.com` GCP organization auto-provisions
5. Designate Org Admins: developer (primary), Agromin executive (fallback Org Owner)
6. Set up the Agromin-owned billing account; attach at the organization level
7. Create folders: `Production` (and others as desired)
8. Apply baseline org policies: region restriction (`us-west1`), no public buckets, audit logging required

**Phase 1 — Transfer the dispatch service**

9. Create new project `agromin-coupon-dispatch-prod` inside the `Production` folder
10. Enable Cloud Run, Firestore, Secret Manager APIs
11. Recreate the four secrets in the new project's Secret Manager (values per §7)
12. Add the developer's personal Google account as co-Owner on the new project (so deploys can continue without account switching during transition)
13. Deploy the dispatch service to the new project: `gcloud run deploy coupon-dispatch --source . --region us-west1 --project agromin-coupon-dispatch-prod --allow-unauthenticated --quiet`
14. Note the new Cloud Run URL
15. Smoke-test against parked `.eml` fixtures — verify response, email sending, Firestore writes
16. Update Power Automate's HTTP step to point to the new Cloud Run URL
17. Update Power Automate's `X-API-Key` header to match the new `DISPATCH_API_KEY` value
18. Run one real test order through the pipeline end-to-end
19. Keep the old project running for ~7 days as a fallback (zero incremental cost)

**Phase 2 — Optional Firestore data migration**

20. If historical orders matter: export Firestore from old project to Cloud Storage (`gcloud firestore export`), then import into new project
21. If historical orders do not matter: skip — the dispatch service is fundamentally an event processor; loss of audit log is recoverable from M365 sent-mail history

**Phase 3 — Decommission**

22. Delete the old Cloud Run service
23. Delete the old Firestore database
24. Delete the `juris-coupon-valid` project
25. Remove personal-account access from any residual resources
26. Update this document: revise §5, §10, §13 to reflect the completed migration in past tense
27. Update §11 decision log with completion date

### 12.6 Effort estimate

- **Pre-flight check:** ~1 hour (mostly waiting for Wayne's response)
- **Phase 0 (org setup):** ~2 hours of focused work, plus DNS propagation wait (typically under 30 minutes)
- **Phase 1 (project transfer):** ~3 hours of focused work
- **Phase 2 (data migration):** ~1 hour if doing it, zero if skipping
- **Phase 3 (decommission):** ~30 minutes

**Total:** under 8 hours of work spread across roughly one week (calendar time mostly determined by waiting on Converged for the mailbox creation and DNS record).

### 12.7 What this migration does not change

- No application code changes are required (the code is platform-agnostic within GCP)
- No changes to M365-side resources (Outlook, Power Automate, SharePoint, app registration, mailbox)
- No changes to the user-facing experience (customers, scheduling team, OCWR liaisons see no difference)
- No changes to the Microsoft Graph integration (same client ID, same tenant ID, same client secret, just stored in a new Secret Manager instance)

The migration is **infrastructure-only**, not architectural.

---

## 13. Glossary

| Term | Definition |
|---|---|
| **CIMcloud** | Agromin's e-commerce platform that hosts `shop.agromin.com` and sends order emails |
| **Converged** | Third-party managed services provider that administers Agromin's Microsoft 365 tenant |
| **Graph API** | Microsoft Graph — the unified REST API for Microsoft 365 services (mail, files, users, etc.) |
| **OCWR** | Orange County Waste & Recycling — county agency partnered with Agromin on the coupon program |
| **Power Automate** | Microsoft's workflow automation product; used here to bridge Outlook email events to Cloud Run HTTPS calls |
| **SB 1383** | California Senate Bill 1383, which mandates organic waste diversion and end-product procurement |
| **SharePoint** | Microsoft's document management platform; hosts Agromin's shared Excel workbooks |
| **Stage A** | The Phase 1 increment that auto-appends new orders to Greg's master tracking spreadsheet |

---

*End of document.*
