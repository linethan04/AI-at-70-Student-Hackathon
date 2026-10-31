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

Read [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md) first: it has every request, decision and preference so far. The [README](README.md) has the full map; every folder has its own `README.md` with how to run it.

- `scripts/`: the main scripts (run these from the repository root).
  - `run_ai_at_70.py`: the app (Flask, port 5070). Serves `outputs/interface/index.html` at `/` and the check-in form at `/questionnaire`, and mounts `tools/transcription/app.py` at `/audio`. It also provides:
    - `/api/read-file`: .txt, .pdf, or a photo read with macOS text recognition (`ocrmac`), with misreadings like "9ll" → "911" fixed
    - `/api/summary`: `visit_summary.py`, plus cross-checks against the check-in and conversation
    - `/api/outputs`: `deliver.py` + `translate.py`
    - `/api/speak`: `voices.py`
    - `/api/config`
  - The app's flow:
    1. Landing page.
    2. Check-in JSON, which sets the language and who consented.
    3. Conversation: record, upload, paste, or Skip. It's optional but adds helpful detail.
    4. Clinician note: typed or uploaded.
    5. Summary, always at a 5th-grade level.
    6. Review: the patient's page and the checklist (Select all, language buttons, the automatic checks as a dropdown).
    7. Approve, then print, open an email draft (consenting recipients only), or phone script (read it, or play it in the neural voice).

    Editing or changing the language removes the approval. The offline summary uses the note only; with Claude, the conversation and check-in are context, and disagreements become flags.
  - `setup/`: `build_translation_models.py` (→ `tools/translation/models/`, ~900 MB), `build_voices.py` (→ `tools/voice/models/`, ~770 MB), `build_dictionaries.py` (lay dictionary + `medical_vocab.txt`), `build_reader_baseline.py` (`word_knowledge.json`).
  - `video/`: the demo video.
    - **Inputs:** Maria's made-up visit (`maria_checkin.json`, `maria_conversation.txt`, `maria_note.txt`).
    - `make_visit_audio.py`: voices the conversation (macOS `say`).
    - `capture_app.py`: records the real app with Chrome's fake microphone, and saves the printouts, the family email, the phone lines and the logo to `build/`.
    - `cartoon.html`: the scenes, in a modern flat style with ordinary human proportions.
    - `make_video.py`:
      - holds the story and narration (`STORY`)
      - renders the scenes frame by frame and crossfades every cut
      - adds one continuous Kokoro voiceover (`af_bella`) and the phone voice (`af_heart`)
      - writes `outputs/video/ai_at_70_demo.mp4`

    Narration says "AI" (read "ay-eye") and "Doctor Lee". Captions follow the narration. No emojis, no photo of notes. After a rebuild, check `build/audio.wav` with speech-to-text.
- `tools/`: the main tools; each also runs on its own.
  - `questionnaire/questionnaire.html`: the patient check-in. English, Mandarin, Spanish, Portuguese and Arabic; exports JSON.
  - `transcription/`: the visit audio, in four parts:
    - `EL_audio.py` records or loads, then transcribes. ElevenLabs Scribe when `ELEVENLABS_API_KEY` is set (speaker labels, medical keyterms); otherwise local `faster-whisper`. It writes `transcripts/<name>.txt` and `.json`; the JSON `segments` list (`speaker`, `start`, `end`, `text`) is the input format for later steps.
    - `clean_transcript.py` uses Claude to assign speakers and propose fixes for misheard medical terms. A fix is applied only if the term exists in an NLM vocabulary and sounds alike; otherwise it is flagged. Claude never edits text directly.
    - `offline_cleanup.py` is the no-key fallback: TitaNet speaker separation via `sherpa-onnx`, and fuzzy matching against RxNorm and a ~98k medical word list.
    - `medical_dictionary.py` does free NLM lookups: RxNorm, RxClass, ICD-10-CM, Conditions, LOINC and HCPCS.

    Its own web page is `app.py` + `static/` (port 5050; `--public` hides `/advanced`).
  - `plain_language/`: clinician note → plain-language summary → outputs.
    - `visit_summary.py`: the summary, with "Your visit" (2–3 sentences), "Your medicines" (**plain category** (exact name), tags New/Higher dose/Lower dose/Stopped, one action line from the note) and "What to do next" (direct commands; when to get help).
      - Up to 6 rewrites until the reader check passes; the best try is always shown.
      - Other checks: everyday talk (no `reader.DOCTOR_TALK` outside parentheses), every medicine listed, every number kept or in the "left out" list, no jargon.
      - `--claude` uses the same rules.
    - `reader.py`: the reader model. A word counts as known if most students know it by the target grade (Living Word Vocabulary). For words not in that list, it counts if 99% of adults know it (word prevalence). A word first tested by grade 8 also counts if 99% of adults know it. `DOCTOR_TALK` lists clinician wording a patient wouldn't say.
    - `convert_note.py`: the word level. Expands abbreviations (ambiguous ones are resolved from context, else flagged) and swaps jargon for standard-source wording. The `phrases` table in `data/simple_words.json` (keys starting with `~` are regular expressions) turns clinical phrases into spoken ones; phrases match before single words, the longest match wins, and a standard source's wording for the same phrase still wins. Everything else is flagged "no standard source".
    - `drug_info.py`: what a medicine is for (MedlinePlus via RxNav + Connect; cached in `data/drug_info.json`; UK names mapped to US).
    - `make_printout.py`: shared page building and templates.
    - `deliver.py`: the printout, the email (family versions say "you" means the patient) and the phone script (written to be heard: "5 milligrams", "9 1 1", parentheses read as pauses, the key points repeated).
    - Data in `data/`: `lay_dictionary.json` (CDC Everyday Words, MedlinePlus, plainlanguage.gov; Wikipedia only for abbreviations), `simple_words.json` (hand-made, flagged), `word_knowledge.json`, `drug_info.json`.
  - `translation/translate.py`: Mandarin, Spanish, Portuguese and Arabic, always from the checked English, line by line.
    - Names, tests, doses, doctor names and phone numbers become placeholders.
    - `GLOSSARY` and `WHOLE_LINES` hold fixed everyday wording so repeated words read the same every time (Spanish so far).
    - `LABELS` holds the page headings for each language.
    - Every line is back-translated and flagged on drift or a lost number.
    - Offline engine: Argos Translate OPUS-MT via CTranslate2. Claude translates when `ANTHROPIC_API_KEY` is set.
  - `voice/voices.py`: phone-call voices on this computer: Kokoro (`af_heart`, `ef_dora`, `pf_dora`; Mandarin via sherpa-onnx) and Piper `ar_JO-kareem` for Arabic.
- `outputs/`: the products. `interface/index.html` is the app page (needs the server), with screenshots. `video/` holds `ai_at_70_demo.mp4` and `VIDEO_PROMPT.md`, a prompt for remaking the video with other AI tools.
- `docs/PROJECT_HISTORY.md`: the project's history and decisions. `REFERENCES.md`: every source.

Keep this layout: final versions only, no per-person folders, a `README.md` in every folder, and update this file and the READMEs when something changes.

## How to run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/setup/build_dictionaries.py          # once: medical word list for the summary (~35 MB of downloads)
python scripts/setup/build_translation_models.py    # once: offline translation (~900 MB)
python scripts/setup/build_voices.py                # once: phone-call voices (~770 MB)
python scripts/run_ai_at_70.py                      # the app: http://localhost:5070

# tools on their own
python tools/plain_language/visit_summary.py scripts/video/maria_note.txt --name "Maria Rodriguez" [--claude]
python tools/plain_language/convert_note.py <note.txt> [--claude] [--grade 5]
python tools/plain_language/reader.py "Some text"
python tools/translation/translate.py es "Take 1 pill (5 mg) each day."
python tools/voice/voices.py en "Take 1 pill, 5 milligrams, each day." out.wav
python tools/transcription/EL_audio.py transcribe <file.wav> --clean
python tools/transcription/app.py                   # transcription page: http://localhost:5050

# the demo video (macOS, Chrome; the app must be running)
python scripts/video/make_visit_audio.py && python scripts/video/capture_app.py && python scripts/video/make_video.py
```

- Use `.venv`, not Anaconda's Python. "Address already in use" means the server is already running.
- Secrets go in a local `.env` (git-ignored): `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`. Without them, everything runs offline. Never hard-code keys.
- Recordings, transcripts, models and generated files are git-ignored (see `.gitignore`).
- When a component gets new dependencies or an entry point, add them to `requirements.txt` and its README.

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
