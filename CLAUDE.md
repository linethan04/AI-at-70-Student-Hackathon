# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

A Claude hackathon project ("AI at 70"): a **clinician tool for primary care** that turns the raw material of a geriatric patient's visit into plain-language communication for the patient and their family.

**Inputs** (any combination):
- Intake / questionnaire responses
- Clinician (doctor) notes
- Voice recording of the appointment (transcribed first)

**Outputs** (clinician chooses one or more):
- **Printout**: a large-print, one-to-two page visit summary
- **Phone call**: a spoken summary (text-to-speech) for the patient or a family member
- **Email**: a summary sent to family members / caregivers

**Who it's for:** older adults and their families, including non-English speakers, many of whom have low health literacy or low baseline reading comprehension. Everything patient-facing must be easy to read, easy to hear, and easy to act on.

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

- `Ethan/` — audio input (pipeline step 1)
  - `EL_audio.py`: records the visit from the mic (or takes a file) and transcribes it. Engines: ElevenLabs Scribe (`scribe_v2`, speaker labels, medical keyterms) or local `faster-whisper` (offline, no speaker labels). Writes `Ethan/transcripts/<name>.txt` and `.json`; the JSON `segments` list (`speaker`, `start`, `end`, `text`) is the input contract for the Claude steps.
  - `make_sample_audio.py`: builds a synthetic two-voice visit with macOS `say` for testing
- `Jason/`, `Max/`, `Tanner/` — personal scratch folders (placeholders for now)

Shared code should move into a common package (e.g. `app/` or `src/`) once pieces start connecting. Update this file when that happens.

## How to run

No app entry point exists yet, and the stack isn't fixed. Each component can use whatever language or tooling its author prefers.

**Audio transcription (`Ethan/`, Python):**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r Ethan/requirements.txt
python Ethan/make_sample_audio.py                                   # synthetic test visit (macOS)
python Ethan/EL_audio.py transcribe Ethan/recordings/sample_visit.wav --keyterms "lisinopril,metformin,A1C"
python Ethan/EL_audio.py record                                     # live mic; press Enter to stop
```

The engine defaults to ElevenLabs when `ELEVENLABS_API_KEY` is set (in `.env` or the environment), otherwise local Whisper. Force one with `--engine elevenlabs|whisper`. Recordings and transcripts are git-ignored.

- Put secrets in a local `.env` (git-ignored); never hard-code API keys.
- Whenever a component gets dependencies or an entry point (`requirements.txt`, `package.json`, a server, a frontend), add its exact install and run commands here.

## Rules

### Patient-facing language
- Target a **5th–7th grade reading level** as needed, ideally **5th grade or lower**. Short sentences, common words, active voice.
- Explain or replace medical jargon ("hypertension" → "high blood pressure"). If a term must stay (e.g. a drug name), explain it in plain words right after.
- Use established plain-language sources for word choices: CDC Everyday Words for Public Health Communication and MedlinePlus (more may be added).
- Write in English unless the user specifies another preferred language; if they do, use that language with the same plain-language standards.
- Lead with what matters most: what we found, what to do, when to come back, and **when to call the doctor or 911**.
- Use concrete instructions ("Take 1 pill every morning with food"), not vague ones ("take as directed"), but only from what the clinician actually wrote (see Clinical safety).
- Printouts: large font (≥14pt), high contrast, plenty of white space, headings, bullet lists.
- Phone script: written to be heard. Short sentences, repeat key instructions, avoid abbreviations and symbols, say numbers clearly.
- Respectful tone toward older adults: never condescending or childish.

### Clinical safety
- **Never invent clinical content.** Every diagnosis, medication, dose, and instruction must trace back to the source inputs. If something is unclear or missing, flag it for the clinician; don't guess.
- Do not add medical advice, diagnoses, or treatment suggestions that the clinician didn't give.
- **Medications:** names, doses, and schedules come exactly from the clinician's notes. Rewrite them as plain, concrete instructions only when that information is in the notes. **Never create a medication instruction that isn't there**; if a dose, schedule, or instruction is missing, flag it for the clinician. Medications get the most careful review.
- **A clinician must review and approve every output before it reaches a patient or family member.** Nothing is sent automatically.
- Contradictions between inputs (e.g. notes vs. transcript) are surfaced to the clinician, not silently resolved.

### Privacy (PHI)
- Use **synthetic / de-identified data only** for development and demos. Never commit real patient data, recordings, or transcripts.
- Don't log full patient records or audio contents.
- Family-member outputs should only go to contacts the patient/clinician has authorized.

### Code
- No fixed language or framework: use whatever the person you're working with wants (Python, JavaScript/TypeScript, etc.). Follow the conventions already used in the folder you're editing. Keep things simple and demo-able; this is a hackathon.
- All language-model steps (extracting facts, plain-language rewriting) use Claude through the Anthropic SDK for the language in use. Default to the latest Claude models (e.g. `claude-opus-5-5`, or `claude-sonnet-5-5` / `claude-haiku-5-5` for cheaper or faster steps). Transcription and text-to-speech may use other services (e.g. ElevenLabs, Whisper).
- Keep prompts in their own files or constants so they're easy to iterate on.
- Work in your own folder or a feature branch. Don't edit a teammate's folder without checking with them.

