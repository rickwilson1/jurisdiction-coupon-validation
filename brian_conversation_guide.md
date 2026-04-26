# Conversation Guide — Brian / Delivery Operations
**Purpose:** Understand current delivery workflow before building Phase 2 scheduling tools  
**Format:** Casual conversation, not an interview. Share the Phase 1 flow doc as context first.  
**Time needed:** 20–30 minutes

---

## Before you start

Share `dispatch_phase1_intake.html` on screen or print it. Use it to explain what Phase 1 does so Brian understands the context — he's not being asked to evaluate software, just to describe how he currently works.

Opening line:

> "We're building a system to handle the OCWR order intake automatically — routing emails, notifying customers, that kind of thing. Before we build the scheduling piece, I want to make sure we build something that actually fits the way you work. Can you walk me through what happens when a delivery order comes in today?"

---

## Section 1 — Current workflow

Let him talk. Don't interrupt. Take notes.

**Prompt questions if he stalls:**

- "What do you do first when you find out there's a delivery order?"
- "Where do you write it down or track it?"
- "How do you know what's been scheduled vs. what's still pending?"
- "What does a typical delivery week look like — how many orders, spread over how many days?"

**What you're listening for:**
- Does he have a system (spreadsheet, calendar, whiteboard) or is it in his head?
- How many deliveries per week during the OCWR program?
- What's the biggest source of friction right now?

---

## Section 2 — Customer scheduling

> "When you call the customer to schedule — walk me through that. What do you need to find out from them?"

Follow-ups:
- "How often do customers not pick up or not call back? What do you do then?"
- "Do customers ever ask to reschedule after you've confirmed?"
- "Would customers be okay getting a text or email to choose a time slot, or do they expect a phone call?"

**What you're listening for:**
- Whether self-service scheduling is realistic or if customers expect a personal call
- How often scheduling gets stuck waiting on the customer
- Whether there's a pattern to when customers are available

---

## Section 3 — Truck and logistics

> "Once you have a date confirmed — how do you assign the truck or hauler?"

Follow-ups:
- "How many trucks or haulers do you have available for OCWR deliveries?"
- "Do you ever run multiple deliveries on the same day? Do you route them geographically?"
- "Who's actually driving — Agromin employees or contractors? Do they need anything beyond the delivery address?"

**What you're listening for:**
- Whether capacity (trucks) or availability (customers) is the more common constraint
- Whether a simple schedule view is enough or whether route optimization would matter

---

## Section 4 — Ofelia's visibility

> "How does Ofelia find out what's scheduled for the week?"

Follow-ups:
- "Does she ask you, or do you send her something proactively?"
- "What does she actually need to know — just what's scheduled, or does she need to approve anything?"
- "Is there ever a situation where she needs to adjust or override a scheduled delivery?"

**What you're listening for:**
- Whether Ofelia needs read-only visibility or active involvement
- Whether a live schedule view replaces current communication or supplements it

---

## Section 5 — The Greenery Log

> "Can you tell me about the Greenery Log — what is it, who fills it in, and what happens to it?"

Follow-ups:
- "Is it a spreadsheet? Where does it live?"
- "Who fills it in — you, the yard staff, someone else?"
- "Does OCWR require it in a specific format? Do you submit it to them on a schedule?"
- "Do the yard staff have a tablet or computer at the gate, or is it paper first?"

**What you're listening for:**
- Current format (Excel, paper, something else)
- Who the user is at the yard — determines whether a browser form is practical
- What OCWR actually requires — determines how much structure the replacement needs
- Whether a device is available at the gate

---

## Section 6 — Pain points

This is the most important part. Ask it simply and then be quiet.

> "If you could change one thing about how delivery orders are handled today, what would it be?"

Let him answer fully before following up.

Then:

> "What takes the most time out of your week on the delivery side?"

> "Is there anything that falls through the cracks sometimes — orders that get delayed or customers who don't hear back in time?"

---

## Section 7 — React to Phase 2 sketch

Pull up or print `dispatch_phase2_sketch.html`. Walk through it briefly.

> "Based on what you've told me, here's roughly what we're thinking for Phase 2. Does this match how you'd want to work, or is something off?"

Key things to confirm:
- **Greg's delivery queue** — "Would a list like this, where you can see pending and scheduled deliveries in one place, be useful? Or do you already have something that works?"
- **Schedule form** — "After you call the customer and confirm a date, would logging it in a simple form like this work? And we'd send the customer an automatic confirmation email at that point."
- **Ofelia's view** — "Would a live page like this replace you having to update Ofelia separately?"
- **Yard log form** — "For the Greenery Log — if there was a simple form on a tablet at the gate where staff enter the order number and confirm what was loaded, would that work? Or is paper better for how the yards operate?"

---

## Wrap up

> "This is really helpful. A couple of last questions:"

- "Is there anyone else I should talk to before we build this — yard managers, the hauler, anyone at OCWR?"
- "Is there anything about the current delivery process I haven't asked about that I should know?"

Close with:

> "We're going to build Phase 1 first — that handles the intake and routing automatically. Once that's running, we'll come back and build the scheduling piece based on what you've told me today. I'll share what we build before we go live so you can tell us if something's off."

---

## After the conversation — notes to capture

- [ ] Current tracking method (spreadsheet / calendar / memory)
- [ ] Average deliveries per week during OCWR season
- [ ] Primary constraint: customer availability vs. truck availability
- [ ] Whether customers expect a phone call or would accept digital scheduling
- [ ] Greenery Log format and OCWR submission requirements
- [ ] Device availability at yard gates
- [ ] Anyone else to talk to before building Phase 2
- [ ] Brian's single biggest pain point (his answer to the open question)

---

*Agromin · OCWR Free Compost & Mulch Program · Brian conversation prep · April 2026*
