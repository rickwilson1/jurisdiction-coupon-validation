# Phase 2: Scheduling — Team Input Form
**From:** Rick Wilson  
**Send to:** Greg, Brian, Kendall, Ofelia  
**Takes about:** 10–15 minutes (you only fill in the sections for you)

Before we build the delivery scheduling tool, I want to make sure it fits how each of you actually works. Please fill in the sections marked for you and skip the rest. No wrong answers.

> **Internal design note (do not include when sending to the team):** Phase 2 is built on the principle that the web app is the system of record and spreadsheets are output artifacts only. See `SESSION_HANDOFF_2026-04-30.md` §17 for the full rationale and architecture. When reviewing answers below, interpret every "where do you track..." or "what format do you need..." question through that lens — the answer drives either an in-app feature (internal users) or an export format (external boundary like OCWR or SAGE).

---

## Everyone — Start Here

1. Who are you?
   - Greg Jackson
   - Brian
   - Kendall
   - Ofelia
   - Someone else

---

## For Greg & Brian — Daily Delivery Workflow

*(Skip if you're Ofelia or Kendall)*

2. When a delivery order comes in today, what do you do first?

3. Where do you currently track pending and scheduled deliveries?  
   *(Spreadsheet, calendar, whiteboard, something else — or a mix?)*

4. On average, how many delivery orders do you handle in a typical week during the OCWR program?

5. When you schedule a delivery, what time windows do you offer customers?
   - A specific time (e.g. 10am)
   - A half-day window (morning or afternoon)
   - Just a day — no specific time
   - It varies by customer or situation

6. What other information do you need from the customer beyond a date and time?

7. How often do customers not pick up or not call back? What do you do in that situation?

8. Would customers be okay receiving an email or text to pick a delivery window, or do they expect a personal phone call?
   - Email or text would be fine
   - They expect a phone call
   - It depends on the customer
   - Not sure

9. After you confirm a date with a customer, how do you notify them — phone call, email, both? When the scheduling tool is live, should it send the customer a confirmation email automatically the moment you click confirm — or would you want to review it before it goes out?

10. When you're looking at a list of pending delivery orders, how would you want them sorted or prioritized?
    - Oldest order first (date received)
    - By delivery area / zip code
    - By quantity (largest first)
    - No preference — just show them all

11. When you're working delivery orders day-to-day, where are you primarily working from?
    - At a desk on a computer
    - On a phone in the field
    - On a tablet
    - Mix of desk and field

12. How often do deliveries get rescheduled after they're confirmed? When that happens, who initiates it — you or the customer — and what do you do?

13. Do customers ever cancel a confirmed delivery? How often, and what do you do when it happens?

14. How do you currently let Ofelia know what's scheduled? Is a weekly summary enough, or does she need updates as they happen?

---

## For Brian — Trucks, Haulers & the Greenery Log

*(Skip if you're Greg, Ofelia, or Kendall)*

15. How many trucks or haulers do you have available for OCWR deliveries?

16. Are deliveries for OC, Ventura, and Sacramento handled the same way — same haulers, same process — or does it differ by region?

17. Do you ever run multiple deliveries on the same day? If so, do you plan the route geographically?

18. Are your haulers Agromin employees or contractors? What information does the driver need to complete the delivery?

19. After a delivery is made, what do you do to close it out? Is there anything you log, submit to OCWR, or send to Ofelia confirming it happened?

20. Is there an OCWR representative or inspector present at the delivery site? Does anyone from OCWR physically sign off on the delivery?

21. When you record a confirmed delivery in your workbook or schedule, what information do you write down? Walk me through a typical entry.

22. What is the Greenery Log — is it a spreadsheet, a paper form, or something else? Where does it live, and who has access to it?

23. Can you walk me through what gets recorded for each entry? What fields or information does a single row contain?

24. Who fills in the Greenery Log — you, yard staff, someone else? Is there a specific yard manager at each site who owns this?

25. Does OCWR require the Greenery Log in a specific format? Do you submit it to them on a regular schedule?

26. Do the yard staff at each site have a tablet or computer available at the gate, or is it paper-based at the point of loading?

27. Could you attach or forward a copy of the Greenery Log (or a screenshot of a few rows)? Seeing the real thing is much faster than describing it — it'll make sure we don't miss any columns when we build the replacement.

---

## For Ofelia — Schedule View & OCWR Reporting

*(Skip if you're Greg, Brian, or Kendall)*

28. You currently receive a weekly Friday email summary of scheduled deliveries. What information in that email do you actually use — and is there anything missing from it you wish you had?

29. If you had a live web page showing the current delivery schedule instead of a weekly email, what would you need to see on it?  
    *(e.g. customer name, address, material, quantity, scheduled date, hauler, status)*

30. How far out do you need visibility — "this week and next week" or a longer window?

31. For OCWR compliance reporting: what exact columns or fields does the report need to include? Is there a required format (Excel, CSV, PDF)?

32. How often do you currently submit or pull compliance data? Is there a fixed deadline or reporting schedule?

33. Does David also need access to the live schedule view, or just you?

34. Is there anything in the current process — emails, calls, spreadsheets — that you'd want us to make sure the new tool doesn't break or replace?

---

## For Kendall — Yard Log & Compliance Export

*(Skip if you're Greg, Brian, or Ofelia)*

35. You currently monitor QR code submissions from the yards. What information from those submissions do you use most?

36. For the SB 1383 compliance export: what exact columns does it need to include? Is there a required format (Excel, CSV, PDF)?

37. How often do you pull or submit this data? Is there a fixed deadline or reporting schedule from OCWR?

38. How do you currently reconcile QR code check-ins with the Greenery Log — are they cross-referenced, or tracked separately?

39. Is there a specific yard manager at each site you coordinate with for fulfillment logging?

40. If the yard log became a tablet app at the gate instead of paper, what would yard staff need to enter for each delivery?  
    *(Walk us through what a single completed entry should look like.)*

---

## Everyone — The Most Important Question

41. If you could change one thing about how delivery orders are handled today, what would it be?

---

## Everyone — Anyone Else I Should Talk To?

42. Is there anyone else — a yard manager, hauler, or someone at OCWR — I should speak with before we build this?

---

*Thanks — this will save us from building something that doesn't fit. Happy to go through any of this on a call.*
