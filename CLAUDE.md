# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

A Claude hackathon project ("AI at 70"): a clinician tool for primary care that turns the raw material of a geriatric patient's visit into plain-language communication for the patient and their family.

Inputs (any combination):
- Intake / questionnaire responses
- Clinician (doctor) notes
- Voice recording of the appointment (transcribed first)

Outputs (clinician chooses one or more):
- Printout: a large-print, one-to-two page visit summary
- Phone call: a spoken summary (text-to-speech) for the patient or a family member
- Email: a summary sent to family members / caregivers

Who it's for: older adults and their families, including non-English speakers, many of whom have low health literacy or low baseline reading comprehension. Everything patient-facing must be easy to read, easy to hear, and easy to act on.

### Pipeline (intended)

```
questionnaire ─┐
clinician notes ┼─> normalize ─> Claude: extract facts ─> Claude: plain-language rewrite ─> clinician review ─> print / call / email
audio recording ┘   (transcribe)   (diagnoses, meds, follow-ups,      (per output format)          (edit + approve)
                                    warning signs, to-dos)
```

### Scope

In scope: the three inputs and three outputs above, with clinician review before anything is sent, for English and non-English speakers.
Out of scope for now: health record (EHR) integration, patient accounts or logins, real patient data.

## Repository layout

The repo is early-stage. Each teammate has a working folder:

- `Ethan/audio_workflow/` — audio input (pipeline step 1)
  - `EL_audio.py`: records the visit from the mic (or takes a file) and transcribes it. Engines: ElevenLabs Scribe (`scribe_v2`, speaker labels, medical keyterms) or local `faster-whisper` (offline, no speaker labels). Writes `Ethan/audio_workflow/transcripts/<name>.txt` and `.json`; the JSON `segments` list (`speaker`, `start`, `end`, `text`) is the input contract for the Claude steps.
  - `clean_transcript.py`: step 1b. Claude (`claude-opus-5-5`, structured output) assigns each sentence to Speaker 1/2/3 with a role, using conversation context (and ElevenLabs' acoustic labels as hints), and proposes fixes for garbled medical terms. Each fix is applied only if the term exists in an NLM vocabulary and sounds like what was heard; otherwise it's flagged. Claude never edits text directly; the script does the exact substitution. Writes `<name>.clean.txt` / `.clean.json`.
  - `offline_cleanup.py`: no-API-key fallback used automatically by `clean_transcript.py`. Speakers are separated by voice (NVIDIA TitaNet speaker model via `sherpa-onnx`, run locally; sentences grouped by voice similarity); roles guessed from word use. Terms: unknown words fuzzy-matched (`rapidfuzz`) against RxNorm + a ~98k medical spelling list; strong matches corrected, weaker ones suggested. Can't decode multi-word garbles ("glitz preside"); Claude can.
  - `medical_dictionary.py`: free NLM lookups, no key needed: RxNorm (drugs, generic and brand; full list cached in `Ethan/audio_workflow/.cache/`), RxClass (drug classes), ICD-10-CM and Conditions (diagnoses), LOINC (labs), HCPCS (procedures)
  - `make_sample_audio.py`: builds a synthetic two-voice visit with macOS `say` for testing
  - `app.py` + `static/`: web app (Flask). `/` is the simple mobile-first page (`static/site/`: Record / Upload audio, then the transcript); `/advanced` has settings and saved recordings. `--public` hides `/advanced` and browse-by-name routes so visitors only see their own result.
  - `fetch_test_audio.py` / `evaluate.py`: download a PriMock57 mock GP consultation (CC BY 4.0) with its human transcript, and score the pipeline against it (word error rate, speaker accuracy, drug names found).
- `Ethan/conversion_library/` — clinician notes → plain language (start of the printout / email / phone-call outputs)
  - `build_dictionaries.py`: builds two dictionaries. **Medical vocabulary** (for detecting jargon): ~98k-word medical spelling list + RxNorm drug names + MedlinePlus technical names. **Lay dictionary** `data/lay_dictionary.json` (committed), following the Rules' source order: CDC Everyday Words (PDF), MedlinePlus health topics + lab tests, and the Federal Plain Language Guidelines word list (plainlanguage.gov, archived copy; for everyday non-medical words) as standard sources, plus Wikipedia's medical abbreviation lists (CC BY-SA, used only to expand abbreviations, not as plain wording). The Consumer Health Vocabulary needs a sign-up at GWU, so it isn't included yet. Safety rules built in: never rename a drug, MedlinePlus titles are the plain target, broader topics aren't treated as synonyms ("dizziness" ≠ "dizziness and vertigo"), disease words must map to a condition phrase ("hyperlipidemia" ≠ "cholesterol"), definitions must actually define the term.
  - `convert_note.py`: layer 1 (offline): expands abbreviations (ambiguous ones resolved from context, e.g. "furosemide BD" → twice a day, else flagged), swaps jargon for standard-source plain words, keeps drug names and lab names and explains them, flags everything else as "no standard source", and flags dosing abbreviations. Layer 2 (`--claude`, needs `ANTHROPIC_API_KEY`): full plain-language rewrite at the target grade grounded in layer 1's word choices, then checks every number and drug name survived. Writes a clinician review copy `output/<note>.plain.md` (original vs. plain, word list, flags, sources).
  - `data/simple_words.json`: hand-made simple wording (model knowledge) for common words no standard source covers ("bilaterally" → "on both sides", "abx", "5/7" → "5 days"). Used only after the standard sources; every use is flagged "no standard source". Edit freely. Its `phrases` table turns whole clinical phrases into what a person would say ("worsening breathlessness" → "your breathing has gotten worse", "referral to cardiology" → "you will be sent to a heart doctor"); keys starting with `~` are regular expressions. Phrases are matched before single words (the longest match wins), and a standard source's plain wording for the exact same phrase still wins.
  - `make_printout.py`: offline layer 2, no API key. Regroups the note's headings into patient sections (what we found, what to do next, your medicines, when to come back or get help, tests, why you came in, history), leaves the exam off (listed for the clinician), splits into short bullets, applies plain-phrasing rules ("the patient" → "you", "denies" → "no"), and checks no number or medicine name went missing. Writes a large-print page `output/<note>.printout.html` with a clinician review panel (SMOG, flags, sentence changes, sources). Rule-based rewriting lowers Flesch-Kincaid but not SMOG to grade 5–7; that needs the Claude rewrite.
  - `visit_summary.py`: the patient visit summary. Say each thing once, in its most basic form:
    - **Your visit**: 2 sentences (3 at most): why you came in, then what the doctor found without repeating it ("Your blood sugar and blood pressure are still too high." for conditions "not at goal"). Long definitions only for words the reader wouldn't know.
    - **Your medicines**: **plain category** (exact name from the note), e.g. **Blood pressure medicine** (Amlodipine). The category comes from the reason the note gives ("for rate control" → Heart rate medicine), else the drug class on its MedlinePlus page ("diuretics" → Water pill), else the use that fits the note. A bold instruction from the note with the amount in parentheses: "Take 1 pill (5 mg) each day." ("1 pill" is assumed from the dose and flagged for the clinician to confirm; never for grams or combination doses), or a blank line if the note has no dose. Tags: New / Higher dose / Lower dose / Stopped. A plan that only says "discuss" or "consider" a change is not shown as a change; it's flagged. Combination medicines stay together ("Sacubitril/valsartan"); vaccines go under next steps, not medicines. A problem the note blames on a medicine goes under it ("This medicine may be causing the swelling in both legs.").
    - **What to do next**: direct commands: what, when, with whom, not why ("Go to the lab today for blood tests (TSH, CBC and BMP).", "You will be sent to a heart doctor.", "You will get a heart scan (echocardiogram).", "Go to your follow-up visit in 4 weeks with Dr. Lee (Internal Medicine)."). When to get help: who to call, then "if you have …"; a long list is split in two sentences.
    Changed words stay highlighted on screen (medical: red struck → green; everyday: purple struck → blue); the printed copy shows plain words. Readability is judged by the reader check (`reader.py`), not SMOG: up to 6 rewrites until a reader at the chosen grade knows 98+ of every 100 words with short sentences; the best try is always shown. Other checks: sounds like everyday talk (no word or phrase from `reader.DOCTOR_TALK` left outside parentheses), every medicine listed, every number kept or in the clinician's "left out" list, no jargon left. `--claude` uses the same rules and sends Claude the check results until it passes.
  - `reader.py` + `build_reader_baseline.py`: the reader model. A word counts as known if most students know it by the target grade (default 5; Living Word Vocabulary, Brysbaert & Biemiller 2017) or, for words not in that list, 99% of adults know it (word prevalence, Brysbaert et al. 2019). Because the readers are adults, a word first tested by grade 8 (the list tests at grades 4, 6, 8, …) also counts if 99% of adults know it ("urine", "diabetes", "cholesterol"). Both datasets come from OSF; `data/word_knowledge.json` is committed. Medicine names, numbers, words explained in the text and names kept in parentheses ("(echocardiogram)") don't count. `DOCTOR_TALK` lists clinician wording a patient wouldn't say ("worsening", "severe", "shortness of breath", "referral"); the summary swaps these at every try. SMOG is still reported for reference.
  - `drug_info.py`: what a medicine does, from MedlinePlus drug information via RxNav + MedlinePlus Connect (UK names mapped to US ones). Cached in `data/drug_info.json` (committed); new medicines are looked up once, online.
  - `app.py` + `templates/`: web page (Flask, port 5051) to paste / upload (.txt, .pdf) a note or pick a sample. Shows the summary and a clinician checklist (with Select all); "Print patient copy" unlocks only after every item is ticked. Untick "Show changes" for the patient's view. `samples/` holds synthetic notes.
  - `deliver.py`: the three outputs from the checked English summary: the printout page, an email to the patient or an authorized family member (next of kin), and a phone script written to be heard ("5 milligrams", "9 1 1", parentheses read as pauses, the changed medicines and when-to-get-help repeated at the end). Family versions say up front that "you" means the patient.
  - `voices.py` + `build_voices.py`: the phone-call voice, neural text-to-speech made on this computer: Kokoro v1.0 (`kokoro-onnx`; English af_heart, Spanish ef_dora, Portuguese pf_dora), Kokoro through sherpa-onnx with its Chinese lexicon (Mandarin), Piper ar_JO-kareem (`piper-tts`, Arabic). ~770 MB in `data/voices/` (git-ignored). The page plays the script line by line, preparing the next line while one plays.
  - `translate.py` + `build_translation_models.py`: translation into Mandarin, Spanish, Portuguese and Arabic, always from the checked plain-language English, line by line. Medicine names, test names, doses, doctor names and phone numbers are swapped for placeholders first so they stay exactly as written. Offline engine: Argos Translate's OPUS-MT models run locally with CTranslate2 (~900 MB in `data/translation_models/`, git-ignored; `build_translation_models.py` downloads them). With `ANTHROPIC_API_KEY`, Claude translates and the offline model still does the back-translation check. Every line is back-translated to English; lines whose meaning may have drifted or that lost a number are flagged with the English, the translation and the back-translation. Page headings and tags are fixed hand-written labels per language (`LABELS`). Offline quality: Spanish and Portuguese are usually close; Mandarin and Arabic get many flags, so use Claude or a qualified reviewer before sending.
  - `fetch_test_notes.py` / `run_tests.py`: download PriMock57 clinician notes (57) and MTSamples general medicine + discharge summaries (~120), run the converter and printout on all, and write `output/test_report.md`. `--summaries` runs only the visit summary on `samples/` and the primary care notes and writes `output/summaries.html` (each summary with its checks, linked).
- `Ethan/ai_at_70/app.py` — the clinician's page, joining the finished tools (Flask, port 5070). Serves `Max/AI-at-70 (5).html` (Max's design) and the check-in questionnaire (`/questionnaire`), mounts the Visit Recorder at `/audio`, and adds `/api/summary` (visit_summary.py on the clinician note) and `/api/outputs` (deliver.py + translate.py). Flow: landing page → 1 check-in JSON (sets the language and who consented to get the summary) → 2 conversation (record, upload audio, or paste; or Skip) → 3 clinician note (type, .txt/.pdf, or a photo of a written note read with macOS text recognition via `ocrmac`, with common misreadings like "9ll" → "911" fixed and shown) → write the summary, always at a 5th-grade reading level → 4 review: the patient's page on the left (patient view or show changes; click a sentence to edit it), the clinician checklist on the right (Select all; inputs that disagree, medicines, changed words, translation flags), language buttons for all three outputs → approve (every item ticked + name) → 5 print, email draft (mailto, only to people with consent), or phone script (read it, play it in the neural voice for that language, or dial). The automatic checks are a dropdown under those tabs. Changing the language or editing removes the approval. Cross-checks: medicines in the conversation or on the check-in but not in the note, and check-in allergies that match a medicine in the note. The offline summary uses the note only; with Claude, the conversation and check-in are context (disagreements become flags).
  - `demo/`: the demo video, one story throughout (Maria Rodriguez, 78; her daughter Sofia; Dr. Lee). `maria_checkin.json`, `maria_conversation.txt`, `make_note_photo.py` (a photo of the note), `capture_app.py` (records the real page with Chrome's fake microphone playing the visit), `cartoon.html` (the cartoon scenes) and `make_video.py` (renders the cartoon frame by frame, cuts the recording, adds Kokoro narration and the phone voice; ~60 s → `demo/video/ai_at_70_demo.mp4`, git-ignored).
  - `test_kit/`: five made-up patients (Spanish, Mandarin, Arabic, Portuguese, English), each a check-in JSON + a matching sample note + a conversation (.txt; `make_test_audio.py` voices them as .wav, git-ignored), and `README.md`, a page-by-page walkthrough of what each one shows (dose changes, an allergy warning, medicines the note leaves out, family-only consent).
- `Max/` — check-in questionnaire (`PCP_Questionnaire_5_Languages_With_Name_And_DOB.html`: English, Mandarin, Spanish, Portuguese, Arabic; exports JSON) and the AI at 70 page (`AI-at-70 (5).html`, served by `Ethan/ai_at_70/app.py`; it needs that server)
- `Jason/`, `Tanner/` — personal scratch folders (placeholders for now)

Shared code should move into a common package (e.g. `app/` or `src/`) once pieces start connecting. Update this file when that happens.

## How to run

No app entry point exists yet, and the stack isn't fixed. Each component can use whatever language or tooling its author prefers.

Audio transcription (`Ethan/audio_workflow/`, Python):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r Ethan/audio_workflow/requirements.txt
python Ethan/audio_workflow/make_sample_audio.py                                   # synthetic test visit (macOS)
python Ethan/audio_workflow/EL_audio.py transcribe Ethan/audio_workflow/recordings/sample_visit.wav --keyterms "lisinopril,metformin,A1C"
python Ethan/audio_workflow/EL_audio.py record                                     # live mic; press Enter to stop
python Ethan/audio_workflow/EL_audio.py transcribe <file.wav> --clean              # + speakers and medical term check
python Ethan/audio_workflow/clean_transcript.py Ethan/audio_workflow/transcripts/<name>.json [--num-speakers 2]   # cleanup on its own
python Ethan/audio_workflow/medical_dictionary.py medication glipizide             # check a single term
python Ethan/audio_workflow/app.py                                                 # web app: http://localhost:5050 (full settings at /advanced)
python Ethan/audio_workflow/app.py --public & cloudflared tunnel --protocol http2 --url http://localhost:5050   # phone access: prints an https://….trycloudflare.com link (brew install cloudflared)
```

Plain-language conversion (`Ethan/conversion_library/`, Python):

```bash
pip install -r Ethan/conversion_library/requirements.txt
python Ethan/conversion_library/build_dictionaries.py        # only needed to refresh data/lay_dictionary.json (~35 MB of downloads)
python Ethan/conversion_library/convert_note.py <note.txt> [--claude] [--grade 5]
python Ethan/conversion_library/make_printout.py <note.txt> [--name "Mary Smith"]   # offline printout
python Ethan/conversion_library/visit_summary.py <note.txt> [--name "Mary Smith"] [--grade 5|6|7] [--claude]   # writes output/<note>.summary.html
python Ethan/conversion_library/reader.py "Some text"          # what a grade-7 reader would know
python Ethan/conversion_library/build_reader_baseline.py      # only to refresh data/word_knowledge.json
python Ethan/conversion_library/app.py                        # web page: http://localhost:5051
python Ethan/conversion_library/fetch_test_notes.py && python Ethan/conversion_library/run_tests.py
python Ethan/conversion_library/run_tests.py --summaries      # visit summaries only: samples + 134 primary care notes -> output/summaries.html
python Ethan/conversion_library/build_translation_models.py   # once: offline Mandarin/Spanish/Portuguese/Arabic models (~900 MB)
python Ethan/conversion_library/translate.py es "Take 1 pill (5 mg) each day."   # one line, with its back-translation
```

AI at 70 (the clinician's page: all inputs and outputs together):

```bash
pip install -r Ethan/conversion_library/requirements.txt -r Ethan/audio_workflow/requirements.txt -r Ethan/ai_at_70/requirements.txt
python Ethan/conversion_library/build_translation_models.py   # once, for the language buttons
python Ethan/ai_at_70/app.py                                  # http://localhost:5070
python Ethan/conversion_library/build_voices.py              # once, for the phone-call voices (~770 MB)
python Ethan/ai_at_70/test_kit/make_test_audio.py             # optional: test recordings for the audio upload (macOS)
python Ethan/ai_at_70/demo/make_note_photo.py && python Ethan/ai_at_70/demo/capture_app.py && python Ethan/ai_at_70/demo/make_video.py   # the demo video (server running)
```

`convert_note.py` and `run_tests.py` also need `data/medical_vocab.txt` and `data/raw/rxnorm_display_names.json`, which `build_dictionaries.py` creates (git-ignored).

`--clean` and `clean_transcript.py` use Claude when `ANTHROPIC_API_KEY` is in `.env`, and otherwise fall back to the offline method (`--engine auto|claude|offline`). The first offline run downloads the speaker model (~40 MB) and medical word list into `Ethan/audio_workflow/.cache/`.

The engine defaults to ElevenLabs when `ELEVENLABS_API_KEY` is set (in `.env` or the environment), otherwise local Whisper. Force one with `--engine elevenlabs|whisper`. Recordings and transcripts are git-ignored.

- Put secrets in a local `.env` (git-ignored); never hard-code API keys.
- Whenever a component gets dependencies or an entry point (`requirements.txt`, `package.json`, a server, a frontend), add its exact install and run commands here.

## Rules

### Patient-facing language
- Target a 5th–7th grade reading level as needed, ideally 5th grade or lower. Short sentences, common words, active voice.
- Say it the way you would say it out loud to the patient, not the way the note says it. Knowing every word isn't enough: "worsening breathlessness" is made of common words but is doctor talk. Use everyday verbs and phrases ("your breathing has gotten worse", "trouble breathing", "very bad", "a bladder infection", "you will be sent to a heart doctor"), not clinical nouns and qualifiers ("worsening", "shortness of breath", "severe", "acute cystitis", "referral to cardiology"). Drop qualifiers that don't change what the patient does ("stage 2", "hemodynamically stable", "uncomplicated", "no red flags" → "no signs of anything serious"); the clinician keeps the note's full wording. Keep only the essence: one idea per sentence, each thing said once, definitions cut to their main idea ("COPD is a lung disease that makes it hard to breathe").
- Check reading level with SMOG for English, and with Fernández-Huerta or INFLESZ for Spanish (English formulas don't transfer). Scores are a guide, not a substitute for clinician review.
- Explain or replace medical jargon ("hypertension" → "high blood pressure"). If a term must stay (e.g. a drug name), explain it in plain words right after.
- Use established plain-language sources for word choices: CDC Everyday Words for Public Health Communication and MedlinePlus first, then other standardized sources such as the Consumer Health Vocabulary, plainlanguage.gov, and NIA older-adult materials (more may be added). If no standard source covers a term, use a simple replacement and flag it for the clinician as "no standard source." Never present an unsourced rewording as standard.
- Sources on request: when the clinician asks, produce a short reference list for that specific output showing which sources supported its word choices. Keep it with the clinician review copy, not on the patient-facing output unless asked. Only cite a source that was actually provided in the pipeline or that can be named specifically; mark anything from model knowledge as "from model knowledge, verify." Never invent a citation.
- Write in English unless the user specifies another preferred language; if they do, use that language with the same plain-language standards (see Translation).
- Lead with what matters most: what we found, what to do, when to come back, and when to call the doctor or 911.
- Use concrete instructions ("Take 1 pill every morning with food"), not vague ones ("take as directed"), but only from what the clinician actually wrote (see Clinical safety).
- Printouts: large font (≥14pt), high contrast, plenty of white space, headings, bullet lists.
- Phone script: written to be heard. Short sentences, repeat key instructions, avoid abbreviations and symbols, say numbers clearly.
- Respectful tone toward older adults: never condescending or childish.
- For every medicine and test, lead with plain words for what it is for, then the name in parentheses (Blood pressure medicine (Amlodipine); a blood test (BMP)). Tag any medicine the clinician changed (New, Higher dose, Lower dose, Stopped). Follow with one action line that says how many, how much, how often, and when (Take 1 pill (5 mg) twice a day, with meals). Spell out every abbreviation (BID, qhs, PRN, ER) in everyday words. Drug and test names stay only as the parenthetical name.

### Translation
- English is the standard. The plain-language English version is the base output, and it can be translated into these optional languages: Mandarin, Spanish, Portuguese, and Arabic.
- Write the plain-language English version first, then translate that version (not the original clinical wording). The clinician reviews the English.
- If an official translation exists (e.g. MedlinePlus or CDC Spanish), use it. Translate on your own only when none exists.
- Meaning must not change. Do not add, drop, or soften any diagnosis, instruction, warning, or "when to call."
- Drug names, doses, numbers, and times stay exactly as written in the notes. Do not translate drug names.
- Keep the same plain-language standards in the target language: short sentences, common words, no idioms or slang. Use the patient's stated language variety if given.
- Mark every term translated on your own (not from an official source) and flag it for clinician review. Run a back-translation check to English and flag any drift in meaning.
- If the clinician can't read the target language, mark the output "translation not verified by a speaker of this language" until a qualified reviewer confirms it.
- The same language applies to all three outputs (printout, email, phone call). Translate the plain-language English after it passes its checks, never the clinician's note. Changing the language needs a new approval.
- Use the same layout in every language. Translate the purpose words, change tags, and action lines into everyday words in the target language (twice a day, at bedtime, as needed). Keep drug names, doses, and test names exactly as written in the parentheses. Never carry English abbreviations into the translation.

### Clinical safety
- Never invent clinical content. Every diagnosis, medication, dose, and instruction must trace back to the source inputs. If something is unclear or missing, flag it for the clinician; don't guess.
- Do not add medical advice, diagnoses, or treatment suggestions that the clinician didn't give.
- Medications: names, doses, and schedules come exactly from the clinician's notes. Rewrite them as plain, concrete instructions only when that information is in the notes. Never create a medication instruction that isn't there; if a dose, schedule, or instruction is missing, flag it for the clinician. Medications get the most careful review.
- Medication wording may follow standard label phrasing (USP <17>) and Universal Medication Schedule times (morning, noon, evening, bedtime) only when the notes support it. If the notes say something that doesn't map cleanly (e.g. "BID"), keep the meaning and flag it.
- Plain-language explanations of a condition or medicine (e.g. from MedlinePlus or FDA) are used only for things the clinician documented. Never add warnings or side effects the clinician didn't mention.
- A clinician must review and approve every output before it reaches a patient or family member. Nothing is sent automatically.
- Contradictions between inputs (e.g. notes vs. transcript) are surfaced to the clinician, not silently resolved.
- Link a symptom to a medicine, or call a medicine a cause, only if the clinician wrote it, and keep their level of certainty (“may be”).

### Privacy (PHI)
- Use synthetic / de-identified data only for development and demos. Never commit real patient data, recordings, or transcripts.
- Don't log full patient records or audio contents.
- Family-member outputs should only go to contacts the patient/clinician has authorized.

### Code
- No fixed language or framework: use whatever the person you're working with wants (Python, JavaScript/TypeScript, etc.). Follow the conventions already used in the folder you're editing. Keep things simple and demo-able; this is a hackathon.
- All language-model steps (extracting facts, plain-language rewriting) use Claude through the Anthropic SDK for the language in use. Default to the latest Claude models (e.g. `claude-opus-5-5`, or `claude-sonnet-5-5` / `claude-haiku-5-5` for cheaper or faster steps). Transcription and text-to-speech may use other services (e.g. ElevenLabs, Whisper).
- Keep prompts in their own files or constants so they're easy to iterate on.
- The rewrite and translation steps return their flags (unsourced terms, terms translated on your own, unclear or missing medication details) as structured output so the clinician review screen can show them, and the per-output source list when requested.
