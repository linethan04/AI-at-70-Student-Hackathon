# Primary Care Check-In — Website Starter

Open `index.html` in a browser to preview the questionnaire. The JavaScript file renders questions and conditional caregiver fields from the configuration embedded in `questionnaire.js`. `questionnaire.schema.json` is a portable questionnaire definition (not a formal JSON Schema validation document).

## Website integration
- Copy `index.html` and `questionnaire.js` into a static site to preview.
- To edit questions, modify `questionnaire.schema.json` and regenerate/synchronize the embedded configuration in `questionnaire.js`.
- Replace the demo **Export responses as JSON** action with an authenticated HTTPS POST to your approved clinical backend; do not persist identifiable patient data in browser localStorage or analytics.
- Validate fields and consent server-side; verify identity, email addresses and authorized recipient; record consent version, timestamp, recipient and revocation.
- Route check-in responses plus clinician notes to a clinician-reviewed after-visit-summary workflow; the clinician must approve diagnosis, medications, dosing, follow-up and red flags before delivery.
- For delivery use an approved secure patient portal or properly secured email workflow with privacy/security review. A checked box alone does not establish legal sufficiency for every disclosure or email arrangement.
- Use accessibility testing, language support, clinically validated screening tools where needed, and escalation pathways for urgent symptoms.

## Privacy warning
This is a UX prototype, **not** a production-ready HIPAA-compliant system. Demo JSON export saves the entered data on the user's device; do not test with real patient information.

## Questionnaire data fields
Each field has a stable `id`, `label`, `type`, optional `options`, `required`, `show_if`, or `required_if`. Answers are exported with these IDs for easy downstream mapping.


## Multilingual interface (v1.1)
The FIRST field is a language selector: English, Mandarin (Simplified Chinese), Haitian Creole, and Spanish. Changing the selection translates the visible questions and choices without erasing answers. JSON exports include `language` and `summary_language` (ISO codes en/zh/ht/es), while option values remain canonical English for stable downstream processing. All patient-facing translations, especially clinical and consent wording, require review by qualified medical interpreters/translators before deployment. Language selection does not translate patient-entered free text or clinician notes. The prototype does not send email or provide secure data storage.
