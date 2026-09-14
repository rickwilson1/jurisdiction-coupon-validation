function createPhase2SchedulingForm() {
  var form = FormApp.create('Phase 2: Scheduling — Team Input');

  form.setDescription(
    'From: Rick Wilson\n' +
    'Send to: Greg, Brian, Kendall, Ofelia, Emily\n' +
    'Takes about: 10–15 minutes (you only fill in the sections for you)\n\n' +
    'Before we build the delivery scheduling tool, I want to make sure it fits how each of you actually works. ' +
    'Fill in the sections marked for you and skip the rest. No wrong answers.'
  );

  // Section: Everyone — Start Here
  form.addSectionHeaderItem().setTitle('Everyone — Start Here');

  form.addMultipleChoiceItem()
    .setTitle('1. Who are you?')
    .setChoiceValues([
      'Greg Jackson',
      'Brian Camarillo',
      'Kendall',
      'Ofelia',
      'Emily Serna',
      'Someone else'
    ]);

  // Section: Greg & Brian
  form.addSectionHeaderItem()
    .setTitle('For Greg & Brian — Daily Delivery Workflow')
    .setHelpText('Skip this section if you are Ofelia or Kendall.');

  form.addParagraphTextItem()
    .setTitle('2. When a delivery order comes in today, what do you do first?');

  form.addParagraphTextItem()
    .setTitle('3. Where do you currently track pending and scheduled deliveries?')
    .setHelpText('Spreadsheet, calendar, whiteboard, something else — or a mix?');

  form.addTextItem()
    .setTitle('4. On average, how many delivery orders do you handle in a typical week during the OCWR program?');

  form.addMultipleChoiceItem()
    .setTitle('5. When you schedule a delivery, what time windows do you offer customers?')
    .setChoiceValues([
      'A specific time (e.g. 10am)',
      'A half-day window (morning or afternoon)',
      'Just a day — no specific time',
      'It varies by customer or situation'
    ]);

  form.addParagraphTextItem()
    .setTitle('6. What other information do you need from the customer beyond a date and time?');

  form.addParagraphTextItem()
    .setTitle('7. How often do customers not pick up or not call back? What do you do in that situation?');

  form.addMultipleChoiceItem()
    .setTitle('8. Would customers be okay receiving an email or text to pick a delivery window, or do they expect a personal phone call?')
    .setChoiceValues([
      'Email or text would be fine',
      'They expect a phone call',
      'It depends on the customer',
      'Not sure'
    ]);

  form.addParagraphTextItem()
    .setTitle('9. After you confirm a date with a customer, how do you notify them?')
    .setHelpText('Phone call, email, both? When the scheduling tool is live, should it send the customer a confirmation email automatically the moment you click confirm — or would you want to review it before it goes out?');

  form.addMultipleChoiceItem()
    .setTitle('10. When looking at a list of pending delivery orders, how would you want them sorted or prioritized?')
    .setChoiceValues([
      'Oldest order first (date received)',
      'By delivery area / zip code',
      'By quantity (largest first)',
      'No preference — just show them all'
    ]);

  form.addMultipleChoiceItem()
    .setTitle('11. When working delivery orders day-to-day, where are you primarily working from?')
    .setChoiceValues([
      'At a desk on a computer',
      'On a phone in the field',
      'On a tablet',
      'Mix of desk and field'
    ]);

  form.addParagraphTextItem()
    .setTitle('12. How often do deliveries get rescheduled after they\'re confirmed?')
    .setHelpText('When that happens, who initiates it — you or the customer — and what do you do?');

  form.addParagraphTextItem()
    .setTitle('13. Do customers ever cancel a confirmed delivery? How often, and what do you do when it happens?');

  form.addParagraphTextItem()
    .setTitle('14. How do you currently let Ofelia know what\'s scheduled?')
    .setHelpText('Is a weekly summary enough, or does she need updates as they happen?');

  // Section: Brian only
  form.addSectionHeaderItem()
    .setTitle('For Brian — Trucks, Haulers & the Greenery Log')
    .setHelpText('Skip this section if you are Greg, Ofelia, or Kendall.');

  form.addTextItem()
    .setTitle('15. How many trucks or haulers do you have available for OCWR deliveries?');

  form.addParagraphTextItem()
    .setTitle('16. Are deliveries for OC, Ventura, and Sacramento handled the same way — same haulers, same process — or does it differ by region?');

  form.addParagraphTextItem()
    .setTitle('16b. The OCWR program spec mentions a "Delivery Request Workbook" where all delivery requests are managed. What does this workbook look like today?')
    .setHelpText('Is it a spreadsheet, where does it live, who has access, and what does a typical entry contain? If easier, attach a screenshot or a copy when you reply.');

  form.addParagraphTextItem()
    .setTitle('16c. The spec also mentions a "Hauling Schedule Workbook" that tracks confirmed delivery times. Is this the same as the Delivery Request Workbook, or a separate thing?')
    .setHelpText('If separate, walk me through what\'s in it and how the two relate.');

  form.addParagraphTextItem()
    .setTitle('17. Do you ever run multiple deliveries on the same day? If so, do you plan the route geographically?');

  form.addParagraphTextItem()
    .setTitle('18. Are your haulers Agromin employees or contractors? What information does the driver need to complete the delivery?');

  form.addParagraphTextItem()
    .setTitle('19. After a delivery is made, what do you do to close it out?')
    .setHelpText('Is there anything you log, submit to OCWR, or send to Ofelia confirming it happened?');

  form.addParagraphTextItem()
    .setTitle('19b. The hauler gets a manifest slip when they pick up material at the yard, signed upon delivery. What does the current manifest look like?')
    .setHelpText('What fields does it include, who creates it, and where do the signed copies end up? Attach or screenshot a sample if possible. We have started building an automated PDF version (one is generated per order through the new dispatch tool) and want to make sure it matches what you and your haulers actually need.');

  form.addMultipleChoiceItem()
    .setTitle('20. Is there an OCWR representative or inspector present at the delivery site?')
    .setChoiceValues([
      'Yes — someone from OCWR signs off',
      'No — no OCWR presence at the delivery',
      'Sometimes, depending on the site',
      'Not sure'
    ]);

  form.addParagraphTextItem()
    .setTitle('21. When you record a confirmed delivery, what information do you write down?')
    .setHelpText('Walk me through a typical entry — what fields or details you capture.');

  form.addMultipleChoiceItem()
    .setTitle('22. What is the Greenery Log?')
    .setChoiceValues([
      'A spreadsheet',
      'A paper form',
      'Something else'
    ]);

  form.addParagraphTextItem()
    .setTitle('22b. Where does the Greenery Log live, and who has access to it?');

  form.addParagraphTextItem()
    .setTitle('23. Can you walk me through what gets recorded for each entry?')
    .setHelpText('What fields or information does a single row contain?');

  form.addParagraphTextItem()
    .setTitle('24. Who fills in the Greenery Log — you, yard staff, someone else? Is there a specific yard manager at each site who owns this?');

  form.addParagraphTextItem()
    .setTitle('25. Does OCWR require the Greenery Log in a specific format? Do you submit it on a regular schedule?');

  form.addMultipleChoiceItem()
    .setTitle('26. Do yard staff have a tablet or computer at the gate, or is it paper-based at the point of loading?')
    .setChoiceValues([
      'Tablet or computer available',
      'Paper-based at the gate',
      'Mix of both',
      'Not sure'
    ]);

  form.addParagraphTextItem()
    .setTitle('27. Could you attach or forward a copy of the Greenery Log (or a screenshot of a few rows)?')
    .setHelpText('Seeing the real thing is much faster than describing it. Reply to the email with an attachment if easier.');

  // Section: Ofelia
  form.addSectionHeaderItem()
    .setTitle('For Ofelia — Schedule View & OCWR Reporting')
    .setHelpText('Skip this section if you are Greg, Brian, or Kendall.');

  form.addParagraphTextItem()
    .setTitle('28. You currently receive a weekly Friday email summary of scheduled deliveries. What information in that email do you actually use — and is there anything missing that you wish you had?');

  form.addParagraphTextItem()
    .setTitle('29. If you had a live web page showing the current delivery schedule instead of a weekly email, what would you need to see on it?')
    .setHelpText('e.g. customer name, address, material, quantity, scheduled date, hauler, status');

  form.addMultipleChoiceItem()
    .setTitle('30. How far out do you need visibility into the schedule?')
    .setChoiceValues([
      'This week only',
      'This week and next week',
      'Rolling 30 days',
      'All upcoming deliveries regardless of date'
    ]);

  form.addParagraphTextItem()
    .setTitle('31. For OCWR compliance reporting: what exact columns or fields does the report need to include? Is there a required format (Excel, CSV, PDF)?');

  form.addParagraphTextItem()
    .setTitle('32. How often do you currently submit or pull compliance data? Is there a fixed deadline or reporting schedule?');

  form.addMultipleChoiceItem()
    .setTitle('33. Does anyone else at OCWR also need access to the live schedule view, or just you?')
    .setChoiceValues([
      'Just me',
      'One other person — I\'ll specify below',
      'A few others — I\'ll specify below',
      'Not sure'
    ]);

  form.addParagraphTextItem()
    .setTitle('34. Is there anything in the current process — emails, calls, spreadsheets — that you\'d want us to make sure the new tool doesn\'t break or replace?');

  // Section: Kendall
  form.addSectionHeaderItem()
    .setTitle('For Kendall — Yard Log & Compliance Export')
    .setHelpText('Skip this section if you are Greg, Brian, or Ofelia.');

  form.addParagraphTextItem()
    .setTitle('35. You currently monitor QR code submissions from the yards. What information from those submissions do you use most?');

  form.addParagraphTextItem()
    .setTitle('36. For the SB 1383 compliance export: what exact columns does it need to include? Is there a required format (Excel, CSV, PDF)?');

  form.addParagraphTextItem()
    .setTitle('37. How often do you pull or submit this data? Is there a fixed deadline or reporting schedule from OCWR?');

  form.addParagraphTextItem()
    .setTitle('38. How do you currently reconcile QR code check-ins with the Greenery Log — are they cross-referenced, or tracked separately?');

  form.addParagraphTextItem()
    .setTitle('39. Is there a specific yard manager at each site you coordinate with for fulfillment logging?');

  form.addParagraphTextItem()
    .setTitle('40. If the yard log became a tablet app at the gate instead of paper, what would yard staff need to enter for each delivery?')
    .setHelpText('Walk us through what a single completed entry should look like.');

  // Section: Emily
  form.addSectionHeaderItem()
    .setTitle('For Emily — Customer Support')
    .setHelpText('Skip this section if you are Greg, Brian, Kendall, or Ofelia.');

  form.addMultipleChoiceItem()
    .setTitle('40b. Roughly how many customer emails do you handle per week related to OCWR coupon codes during the program season?')
    .setChoiceValues([
      'Less than 5',
      '5–15',
      '15–30',
      'More than 30',
      'It varies a lot week to week'
    ]);

  form.addParagraphTextItem()
    .setTitle('40c. What are the most common issues customers contact you about?')
    .setHelpText('e.g. coupon code does not apply, delivery vs pickup confusion, address out of service area, can\'t find the right yard, etc.');

  form.addParagraphTextItem()
    .setTitle('40d. If we built a self-service help page customers could check before emailing — what 2–3 questions would it need to answer to cut your inbox in half?');

  form.addMultipleChoiceItem()
    .setTitle('40e. When the new automated dispatch tool sends a customer their pickup or delivery email, would you want to be CC\'d so you can see what they were told?')
    .setChoiceValues([
      'Yes — CC me on every customer email',
      'Only when something looks unusual or fails',
      'No — I\'ll just look at the order if a customer reaches out',
      'Not sure'
    ]);

  // Section: Everyone — Most Important Question
  form.addSectionHeaderItem().setTitle('Everyone — The Most Important Question');

  form.addParagraphTextItem()
    .setTitle('41. If you could change one thing about how delivery orders are handled today, what would it be?');

  // Section: Everyone — Anyone Else
  form.addSectionHeaderItem().setTitle('Everyone — Anyone Else I Should Talk To?');

  form.addParagraphTextItem()
    .setTitle('42. Is there anyone else — a yard manager, hauler, or someone at OCWR — I should speak with before we build this?');

  Logger.log('Form URL (send to team): ' + form.getPublishedUrl());
  Logger.log('Edit URL (your admin link): ' + form.getEditUrl());
}
