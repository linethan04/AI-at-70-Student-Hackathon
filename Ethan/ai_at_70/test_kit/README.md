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

Each row uses three files. The note is in the sample list on step 2; the other two are in this folder.

| # | Patient (language) | 1. Check-in (`checkins/`) | 2. Note (sample list) | 3. Conversation (`conversations/` or `audio/`) | What it shows |
|---|---|---|---|---|---|
| 1 | Maria Rodriguez (Spanish) | `1_maria_rodriguez_spanish.json` | diabetes followup | `1_maria_rodriguez_diabetes` | Lower and higher dose tags; "inputs disagree": lisinopril is on her check-in list and in the conversation but not in the note; email to the patient and her husband |
| 2 | Wei Chen (Mandarin) | `2_wei_chen_mandarin.json` | heart failure followup | `2_wei_chen_heart_failure` | **Allergy warning**: the check-in says warfarin caused bleeding and the note has warfarin; family-only consent (daughter Lily); many Mandarin translation flags |
| 3 | Fatima Haddad (Arabic) | `3_fatima_haddad_arabic.json` | copd uk style | `3_fatima_haddad_copd` | Right-to-left page; UK-style note (999); son Omar gets the email; no disagreements |
| 4 | Ana Souza (Portuguese) | `4_ana_souza_portuguese.json` | uti older woman | `4_ana_souza_uti` | "Inputs disagree": ibuprofen (check-in and conversation, not in the note); patient and daughter both consent |
| 5 | John Miller (English) | `5_john_miller_english.json` | afib new dx | `5_john_miller_afib` | English only; new medicines; no family consent, so email and call go to the patient only |
| 6 | No check-in | Skip | back pain uk (or any) | none | Type a name on step 2; works without a check-in or a conversation |

The page opens in the check-in's language (Spanish for Maria, Mandarin for Wei, ...). The English page is
always there too.

## Page by page

**1. Check-in**
- Drag a file from `checkins/` onto the box (or Choose file). The banner shows the patient, language and
  consent chips. It moves on to step 2 by itself.
- "Open the check-in questionnaire" opens Max's questionnaire in a new tab: fill it in, export, upload.
- "Skip" goes on without one (patient 6).

**2. Clinician note**
- "Or try a sample note…" → pick the note from the table. Or upload a .txt/.pdf, or paste.
- Fill in your name (e.g. `Dr. Lee`) and office phone (e.g. `555-0100`): they appear on the printout,
  email and call. Next.

**3. Conversation** (any one)
- Upload transcript (.txt) → `conversations/…txt` (instant).
- Upload audio → `audio/…wav` (transcribed on this computer, about a minute; check the speakers after).
- Record visit → read a few lines aloud, then Stop.
- Leave it empty to skip.

Then "Write the summary".

**4. Review and approve**
- Left: the patient's page. "Patient view" is what prints; "Show changes" strikes through the note's words
  and shows the plain words (English page). Click any English sentence to edit it.
- Language buttons: the page, email and call all switch together. Each translation adds a
  "Translation" group to the checklist with every doubtful line (English, translation, back-translation).
- Right: "Please check": inputs that disagree first, then medicines, changed words, translation. Tick each
  one, or "Select all". "Approve summary" unlocks when all are ticked: enter your name, confirm.
- Automatic checks: reader level, everyday talk, medicines listed, numbers kept, no jargon; "Left out of the
  summary" and "Sources" open below.
- Try: change the language after approving: the approval is removed until you approve again.

**5. Print, email, call** (tabs under the page; locked until approved)
- Printout → "Print patient copy" (print preview: only the patient's page, large print, no changes shown).
- Email → choose the person (only people with consent and an email address) → "Open email draft" opens your
  mail app; nothing is sent until you press Send there. Or "Copy text".
- Phone call → choose the person, read the script, or "▶ Play the message" (the computer's voice for that
  language; add voices in System Settings → Accessibility → Spoken Content if one is missing).
  "Call from this device" needs a phone number and a phone app.

## What to look for

- Every medicine in the note is listed, with its plain name first and the note's name in parentheses.
- No doctor wording ("worsening", "severe", "shortness of breath") on the English page.
- Medicine names, doses and test names stay exactly as written in every language.
- Disagreements between the note, the conversation and the check-in are flagged, never fixed silently.
- Nothing can be printed, emailed or played before approval.
