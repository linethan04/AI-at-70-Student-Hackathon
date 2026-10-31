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
  - `build_dictionaries.py`: builds two dictionaries. **Medical vocabulary** (for detecting jargon): ~98k-word medical spelling list + RxNorm drug names + MedlinePlus technical names. **Lay dictionary** `data/lay_dictionary.json` (committed), following the Rules' source order: CDC Everyday Words (PDF) and MedlinePlus health topics + lab tests (standard sources), plus Wikipedia's medical abbreviation lists (CC BY-SA, used only to expand abbreviations, not as plain wording). The Consumer Health Vocabulary needs a sign-up at GWU, so it isn't included yet. Safety rules built in: never rename a drug, MedlinePlus titles are the plain target, broader topics aren't treated as synonyms ("dizziness" ≠ "dizziness and vertigo"), disease words must map to a condition phrase ("hyperlipidemia" ≠ "cholesterol"), definitions must actually define the term.
  - `convert_note.py`: layer 1 (offline): expands abbreviations (ambiguous ones resolved from context, e.g. "furosemide BD" → twice a day, else flagged), swaps jargon for standard-source plain words, keeps drug names and lab names and explains them, flags everything else as "no standard source", and flags dosing abbreviations. Layer 2 (`--claude`, needs `ANTHROPIC_API_KEY`): full plain-language rewrite at the target grade grounded in layer 1's word choices, then checks every number and drug name survived. Writes a clinician review copy `output/<note>.plain.md` (original vs. plain, word list, flags, sources).
  - `fetch_test_notes.py` / `run_tests.py`: download PriMock57 clinician notes (57) and MTSamples general medicine + discharge summaries (~120), run the converter on all, and write `output/test_report.md`.
- `Jason/`, `Max/`, `Tanner/` — personal scratch folders (placeholders for now)

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
python Ethan/conversion_library/convert_note.py <note.txt> [--claude] [--grade 6]
python Ethan/conversion_library/fetch_test_notes.py && python Ethan/conversion_library/run_tests.py
```

`convert_note.py` and `run_tests.py` also need `data/medical_vocab.txt` and `data/raw/rxnorm_display_names.json`, which `build_dictionaries.py` creates (git-ignored).

`--clean` and `clean_transcript.py` use Claude when `ANTHROPIC_API_KEY` is in `.env`, and otherwise fall back to the offline method (`--engine auto|claude|offline`). The first offline run downloads the speaker model (~40 MB) and medical word list into `Ethan/audio_workflow/.cache/`.

The engine defaults to ElevenLabs when `ELEVENLABS_API_KEY` is set (in `.env` or the environment), otherwise local Whisper. Force one with `--engine elevenlabs|whisper`. Recordings and transcripts are git-ignored.

- Put secrets in a local `.env` (git-ignored); never hard-code API keys.
- Whenever a component gets dependencies or an entry point (`requirements.txt`, `package.json`, a server, a frontend), add its exact install and run commands here.

## Rules

### Patient-facing language
- Target a 5th–7th grade reading level as needed, ideally 5th grade or lower. Short sentences, common words, active voice.
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
