# tools/questionnaire/

[`questionnaire.html`](questionnaire.html) is the patient check-in form, in **English, Mandarin, Spanish, Portuguese and Arabic**.

The patient answers a few simple questions on arrival:

- visit type
- what brings them in
- medicines and allergies
- what makes a care plan hard to follow
- how they like to get instructions
- who may receive the summary (consent for email, and for a family member or caregiver)

**Export** downloads the answers as JSON. The clinician uploads that file in step 1 of the app, and it sets:

- the patient's name
- the language for the outputs
- who may get the email or phone call

The app also cross-checks it against the visit note: medicines missing from the note, and allergies that match a prescribed medicine.

**Run:**

- With the app running, open http://localhost:5070/questionnaire, or use "Patient check-in form" on the landing page.
- It also works on its own: just open the HTML file in a browser.

**Example export:** [`scripts/video/maria_checkin.json`](../../scripts/video/maria_checkin.json)
