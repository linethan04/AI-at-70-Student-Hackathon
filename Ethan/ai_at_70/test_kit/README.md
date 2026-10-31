# AI at 70 test kit

Everything needed to click through every page of the AI at 70 clinician page. All patients and visits are made up.

## Start

```bash
cd AI-at-70-Student-Hackathon
source .venv/bin/activate
python Ethan/ai_at_70/app.py                          # then open http://localhost:5070
python Ethan/ai_at_70/test_kit/make_test_audio.py     # once, only to test audio upload (macOS)
```

"Address already in use" means the server is already running: just open the page, or free the port with
`lsof -ti tcp:5070 | xargs kill`.

## The test patients

Each row uses three files, in the page's order: check-in (`checkins/`), conversation (`conversations/` or `audio/`),
then the clinician note: upload it from `Ethan/conversion_library/samples/synthetic_<name>.txt`.

| # | Patient (language) | 1. Check-in (`checkins/`) | 3. Note (`samples/synthetic_…txt`) | 2. Conversation (`conversations/` or `audio/`) | What it shows |
|---|---|---|---|---|---|
| 1 | Maria Rodriguez (Spanish) | `1_maria_rodriguez_spanish.json` | diabetes_followup | `1_maria_rodriguez_diabetes` | Lower and higher dose tags; "inputs disagree": lisinopril is on her check-in list and in the conversation but not in the note; email to the patient and her daughter Sofia |
| 2 | Wei Chen (Mandarin) | `2_wei_chen_mandarin.json` | heart_failure_followup | `2_wei_chen_heart_failure` | **Allergy warning**: the check-in says warfarin caused bleeding and the note has warfarin; family-only consent (daughter Lily); many Mandarin translation flags |
| 3 | Fatima Haddad (Arabic) | `3_fatima_haddad_arabic.json` | copd_uk_style | `3_fatima_haddad_copd` | Right-to-left page; UK-style note (999); son Omar gets the email; no disagreements |
| 4 | Ana Souza (Portuguese) | `4_ana_souza_portuguese.json` | uti_older_woman | `4_ana_souza_uti` | "Inputs disagree": ibuprofen (check-in and conversation, not in the note); patient and daughter both consent |
| 5 | John Miller (English) | `5_john_miller_english.json` | afib_new_dx | `5_john_miller_afib` | English only; new medicines; no family consent, so email and call go to the patient only |
| 6 | No check-in | Skip | back_pain_uk (or any) | Skip | Type a name with the note; works without a check-in or a conversation |

The English demo (`../demo/`) is the same visit as patient 1, in English: `maria_checkin.json`, `maria_visit.wav` (or
`maria_conversation.txt`) and a photo of Dr. Lee's note, `maria_note_photo.jpg`, to try the photo upload.

The page opens in the check-in's language (Spanish for Maria, Mandarin for Wei, ...). The English page is
always there too.

## Page by page

**Landing page**: what AI at 70 does; "Start a visit".

**1. Check-in**
- Drag a file from `checkins/` onto the box (or Choose file). The banner shows the patient, language and
  consent chips. It moves on to step 2 by itself.
- "Open the check-in questionnaire" opens Max's questionnaire in a new tab: fill it in, export, upload.
- "Skip" goes on without one (patient 6).

**2. Conversation** (any one, or Skip)
- Upload transcript (.txt) → `conversations/…txt` (instant).
- Upload audio → `audio/…wav` (transcribed on this computer, about a minute; check the speakers after).
- Record visit → read a few lines aloud, then Stop.
- "Skip" goes on without one.

**3. Clinician note**
- "Upload note or photo" → the note from the table (`Ethan/conversion_library/samples/`), a .pdf, or a photo of a
  written note (`../demo/maria_note_photo.jpg`: read with the Mac's text recognition; check the text). Or paste.
- Fill in your name (e.g. `Dr. Lee`) and office phone (e.g. `555-0100`): they appear on the printout,
  email and call. Then "Write the summary" (always at a 5th-grade reading level).

**4. Review and approve**
- Left: the patient's page. "Patient view" is what prints; "Show changes" strikes through the note's words
  and shows the plain words (English page). Click any English sentence to edit it.
- Language buttons: the page, email and call all switch together. Each translation adds a
  "Translation" group to the checklist with every doubtful line (English, translation, back-translation).
- Right: "Please check": inputs that disagree first, then medicines, changed words, translation. Tick each
  one, or "Select all". "Approve summary" unlocks when all are ticked: enter your name, confirm.
- Automatic checks (reader level, everyday talk, medicines listed, numbers kept, no jargon, what was left out,
  sources) are in the "Automatic checks" dropdown under the print, email and call tabs.
- Try: change the language after approving: the approval is removed until you approve again.

**5. Print, email, call** (tabs under the page; locked until approved)
- Printout → "Print patient copy" (print preview: only the patient's page, large print, no changes shown).
- Email → choose the person (only people with consent and an email address) → "Open email draft" opens your
  mail app; nothing is sent until you press Send there. Or "Copy text".
- Phone call → choose the person, read the script, or "▶ Play the message": a natural neural voice for the
  language (Kokoro; Piper for Arabic), made on this computer, highlighting each line as it's read.
  "Call from this device" needs a phone number and a phone app.

## What to look for

- Every medicine in the note is listed, with its plain name first and the note's name in parentheses.
- No doctor wording ("worsening", "severe", "shortness of breath") on the English page.
- Medicine names, doses and test names stay exactly as written in every language.
- Disagreements between the note, the conversation and the check-in are flagged, never fixed silently.
- Nothing can be printed, emailed or played before approval.
