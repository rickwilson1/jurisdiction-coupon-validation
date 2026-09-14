# Security Keys — Flow Diagram

```
  shop.agromin.com
  (customer places order)
         |
         | CIMcloud sends "Pending Approval" email
         v
  sales@agromin.com  (shared mailbox)
  folder: Inbox/OCWR
         |
         | Power Automate watches this mailbox
         | subject filter: "Pending Approval for Order Number"
         v
  Power Automate
  "Agromin Order Dispatch" flow
  HTTP POST to Cloud Run
  header: X-API-Key: AgrominDispatch2026Secret  ←── DISPATCH_API_KEY
         |                                            (guards this door)
         v
  Cloud Run  (coupon-dispatch)
  https://coupon-dispatch-751008504644.us-west1.run.app
  /api/ingest-cimcloud-email
         |
         |──── parse order
         |──── write Firestore (order_events)
         |──── append row → Greg's Master Sheet (SharePoint)
         |
         | needs to send email, calls Microsoft Graph API:
         |
         |  GRAPH_TENANT_ID     ←── "which M365 org" (agromincorp)
         |  GRAPH_CLIENT_ID     ←── "which app registration"
         |  GRAPH_CLIENT_SECRET ←── "proof of identity"  ⚠ needs rotation
         |
         v
  Microsoft Graph API
  POST /users/dispatch@agromin.com/sendMail
         |
         |──── customer confirmation email  (dispatch@agromin.com)
         └──── coordinator alert            (greg@, brian@, kendall@, ofelia@ CC)
```

## Keys that need action

```
  DISPATCH_API_KEY     ⚠  weak + exposed in chat  →  rotate, update PA flow header
  GRAPH_CLIENT_SECRET  ⚠  sent via chat by Wayne   →  rotate in Entra ID, update Cloud Run env var
```

## Rotation checklist

- [x] Generate new `DISPATCH_API_KEY` (2026-05-02)
- [x] `gcloud run services update coupon-dispatch --update-env-vars DISPATCH_API_KEY=<rotated> --region us-west1 --project juris-coupon-valid` — revision `coupon-dispatch-00009-mtb`
- [x] Update `X-API-Key` header in Power Automate → "Agromin Order Dispatch" flow → HTTP action
- [ ] Confirm on next live order (first real OCWR order after rotation)
- [ ] Have Wayne rotate Graph client secret in Entra ID (Azure portal → App registrations → coupon-dispatch app → Certificates & secrets → New client secret → delete old)
- [ ] `gcloud run services update coupon-dispatch --update-env-vars GRAPH_CLIENT_SECRET=<new> --region us-west1 --project juris-coupon-valid`
- [ ] Verify a test email sends successfully after Graph secret rotation
- [ ] Mirror all env vars to production service (`coupon-validator`)
