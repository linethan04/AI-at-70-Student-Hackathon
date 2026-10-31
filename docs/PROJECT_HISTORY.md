# Project history and context

This page summarizes everything built and decided so far, so that a teammate or Claude Code can pick up the work without the original chats. The rules themselves live in [CLAUDE.md](../CLAUDE.md). This page explains **what exists, why, and what was decided**.

*Last updated: 2026-10-31 (repository cleanup).*

---

## 1. What AI at 70 is

AI at 70 is a clinician-facing tool for primary care, built for a Claude hackathon. Older patients (and their families) often leave a visit without understanding what was said. AI at 70 takes the visit's material and turns it into a plain-language summary the clinician approves before it goes out.

- **Inputs:**
  - a simple check-in questionnaire, answered on arrival
  - the clinician's **typed** visit note
  - an optional conversation recording, described as "adds helpful detail"
- **Outputs:**
  - a large-print printout
  - an email to the patient or to family members with consent
  - a phone call in a natural neural voice
- **Languages:** English first, then Spanish, Mandarin, Portuguese or Arabic. The language applies to all three outputs.
- **Reading level:** fixed at 5th grade. There is no grade selector in the app.

---

## 2. Timeline of what was asked and built

| Stage | Request | Result |
|---|---|---|
| 1 | Resolve GitHub issues | There were no issues; the real problem was a diverged branch, which was rebased onto `origin/main` and pushed. |
| 2 | Make the plain-language conversion truly simple ("worsening breathlessness" stayed) | Added the "say it the way you would say it out loud" rule to CLAUDE.md, the `phrases` table in `simple_words.json` (whole clinical phrases → spoken ones, longest match wins), `DOCTOR_TALK` in `reader.py`, and a check that the summary sounds like everyday talk. Doctor-talk instances across test summaries fell from 147 to 6, and all sample notes passed at grade 5. |
| 3 | Four to-dos: nicer output with a patient view, clinician checklist and Select all; join the tools into the AI at 70 page; make it clinician-facing (3 inputs → print, email, phone call); translation | Built the one-page app (`scripts/run_ai_at_70.py` + `outputs/interface/index.html`), `deliver.py` (the three outputs) and `translate.py` (offline OPUS-MT models, placeholders for names and doses, back-translation checks). |
| 4 | How to test each page; fix server start errors | Wrote a test walkthrough. Fixed errors from running with Anaconda Python instead of `.venv`, and from "Address already in use". |
| 5 | Landing page; step order Check-in → Conversation → Clinician note; no reading-level selector; Skip for the conversation; automatic checks as a dropdown; no sample notes; a more human phone voice; a ~60 s cartoon ad | Did all of these. The phone voice moved from the browser's voice to neural voices (Kokoro, plus Piper for Arabic). Built the video pipeline: Playwright records the real app, scenes are rendered in HTML, and Kokoro does the narration. |
| 6 | A copy-paste prompt so other AI tools can make a similar video | `outputs/video/VIDEO_PROMPT.md` |
| 7 | Move the page out of a teammate's folder | The page moved into the app's own folder. |
| 8 | Video: human anatomy, "AI" said as "ay-eye", the physician introduces AI at 70, then a 1950s cartoon style; simpler landing page | Did all of these; the landing page became a headline, one line, the steps and two buttons. Kokoro reads "A I" as "uh-eye", so narration writes "AI", and "Doctor Lee", since "Dr." gets read with a stop. |
| 9 | Video: a simple questionnaire on arrival (not "in her own words"); conversation optional; modern graphics; the physician explains inputs and outputs; end with Maria and her daughter getting the outputs; show the whole appointment | Rebuilt as one appointment start to finish, in a modern flat style. |
| 10 | Keep the "confusion" part and the earlier structure; make the narration flow like a human, not cut off; model it on real ads | Restructured as an ad: problem today → turn ("Now, the same visit, with AI at 70") → how it works → payoff ("This time, nobody's guessing") → close. One continuous voiceover with real pauses, crossfades, a warmer narrator (`af_bella`), and music-only fades. Checked with speech-to-text. |
| 11 | No emojis on the infographic; no 5th-grade mention there; recording as a "helpful supplement"; no "Today" badge; smoother wording; add translation, shown in Spanish; up to 90 s allowed | Done. The Spanish output was inconsistent (comprimido/pastilla/píldora, tú vs usted, "inflamación"), so a Spanish `GLOSSARY`/`WHOLE_LINES` was added to `translate.py`. |
| 12 | Remove the photo (not part of the workflow); the doctor uploads **typed** notes; show the real recording screen; the narrator lists every language; captions follow the narration; no emojis at the end | Done. Video is about 82 s. |
| 13 | Clean up the repository: no team member names, consolidated `scripts/`, `tools/` and `outputs/`, a README in each folder, a references page, final drafts only, and this history | This layout. Samples, test kits, test scripts, rough drafts and the per-person folders were removed (still in git history). |

---

## 3. Key design decisions (keep these)

**Plain language** (see the full rules in CLAUDE.md):

- Aim for a 5th-grade reading level, judged by `reader.py`: the reader should know 98 of every 100 words, with short sentences. A word first tested by grade 8 also counts if 99% of adults know it ("urine", "diabetes", "cholesterol").
- Say it out loud, not the way the note says it:
  - "your breathing has gotten worse", not "worsening breathlessness"
  - "you will be sent to a heart doctor", not "referral to cardiology"
  - Drop qualifiers that don't change what the patient does.
- Medicines lead with a plain category, then the exact name: **Blood pressure medicine** (Amlodipine).
  - The action line comes from the note: "Take 1 pill (5 mg) each day."
  - "1 pill" is assumed from the dose and flagged for the clinician.
  - Tags: New / Higher dose / Lower dose / Stopped.
  - A plan that only says "discuss" or "consider" is left out and flagged.
- Word sources in priority order: CDC Everyday Words → MedlinePlus → plainlanguage.gov. Anything else is flagged "no standard source".

**Clinical safety:**

- Never invent content. Every number is kept, or it goes in the clinician's "left out" list.
- Nothing is sent automatically. The clinician ticks every item (Select all is available) and approves. Editing or changing the language removes the approval.
- Inputs that disagree are surfaced, never resolved silently:
  - medicines mentioned in the conversation or check-in but not in the note
  - check-in allergies that match a medicine in the note

**Translation:**

- Translate the checked English, never the note.
- Names, doses and numbers are protected as placeholders.
- Every line is back-translated and flagged if it drifts.
- Every translation is marked "not verified by a speaker of this language".
- Offline quality: Spanish and Portuguese are good. Mandarin and Arabic need Claude or a human reviewer.

**The app flow:**

1. Landing page.
2. Check-in JSON upload, which sets the language and consent.
3. Conversation: record, upload or paste, or Skip.
4. Clinician note: type, upload a .txt or .pdf, or upload a photo (macOS; not shown in the video).
5. Review: the patient's page and the checklist; the automatic checks are a dropdown.
6. Approve, then the Printout / Email / Phone call tabs.

**Demo video** (`scripts/video/make_video.py`, `outputs/video/VIDEO_PROMPT.md`):

- **Story:** one made-up story, Maria Rodriguez (78), Dr. Lee, and Sofia at home.
- **Look:** modern flat illustration with ordinary human proportions; app clips are real recordings shown in a browser window.
- **Voices:** Kokoro `af_bella` for the narrator, speed 1.06; `af_heart` for the phone call, with a phone EQ.
- **Narration:**
  - Write "AI" and "Doctor Lee" in the script.
  - Mid-sentence lines run on with short pauses; full sentences get 0.5–0.9 s.
- **Captions follow the narration.** No emojis, no "Today" badge, no photo of notes.
- **Check:** after rebuilding, run speech-to-text on `scripts/video/build/audio.wav` to confirm no word is cut off.

---

## 4. Working preferences (from the user)

- **Commit or push only when asked.** The user usually says "commit" or "commit and push".
- **Check outputs visually.** Screenshots, video frames and speech-to-text were used to verify changes before reporting.
- **Synthetic data only.** Never commit `.env`, real recordings or transcripts.
- **Run the app with `.venv`,** not Anaconda: `source .venv/bin/activate && python scripts/run_ai_at_70.py` → http://localhost:5070.
- **Keep the repository clean:** final versions only, no per-person folders, and a README in each folder.

---

## 5. Open questions and known limits

- **Photo upload:** the app still offers "Upload note or photo" (Apple Vision OCR, macOS only). The user said photos aren't part of the workflow for the video. It's still undecided whether to remove photo upload from the app itself.
- **Translation quality:** offline Mandarin and Arabic get many flags. Use Claude (`ANTHROPIC_API_KEY`) or a qualified reviewer before sending. The Spanish glossary covers common summary words; Portuguese has none yet.
- **Not yet built:** real email sending (the app opens a mail draft) and automatic phone calls (the script is read, or played on speaker). Both need outside services.
- **Consumer Health Vocabulary:** not included, because it needs a sign-up.

---

## 6. Where things are

See the repository map in the [README](../README.md#repository-map). The short version:

- **Run the app:** `scripts/run_ai_at_70.py`
- **One-time setup:** `scripts/setup/`
- **Build the video:** `scripts/video/`
- **Tools:**
  - `tools/questionnaire`
  - `tools/transcription`
  - `tools/plain_language`
  - `tools/translation`
  - `tools/voice`
- **Products:** `outputs/interface` (the app page), `outputs/video` (the video and its prompt)
- **Sources:** `REFERENCES.md`
