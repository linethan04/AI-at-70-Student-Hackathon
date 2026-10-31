# AI at 70

**Visit summaries older patients and their families can understand.**

AI at 70 is a tool for primary-care clinicians. It takes the material from an older patient's visit and turns it into a short, plain-language summary at about a 5th-grade reading level:

- **Check-in:** the patient's answers to a short questionnaire.
- **Typed visit note:** the clinician's note from the appointment.
- **Conversation recording:** optional, but it adds helpful detail.

The clinician reviews and approves every word. The summary can then go out three ways:

- a large-print **printout**
- an **email** to the patient or to family members the patient chose
- a **phone call** read by a natural neural voice

Each output is available in English, Spanish, Mandarin, Portuguese or Arabic.

Everything runs on one computer. With no API keys, nothing leaves the machine. All patients, notes and recordings in this repository are made up.

| | |
|---|---|
| Demo video | [outputs/video/ai_at_70_demo.mp4](outputs/video/ai_at_70_demo.mp4) (about 80 seconds) |
| The app | [outputs/interface/](outputs/interface/), run with `python scripts/run_ai_at_70.py` and open http://localhost:5070 |
| Sources | [REFERENCES.md](REFERENCES.md) |
| Project history | [docs/PROJECT_HISTORY.md](docs/PROJECT_HISTORY.md) (every decision so far, written for teammates and Claude) |

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# one-time downloads (git-ignored)
python scripts/setup/build_translation_models.py   # offline translation, ~900 MB
python scripts/setup/build_voices.py               # phone-call voices, ~770 MB

# run the app
python scripts/run_ai_at_70.py                     # then open http://localhost:5070
```

To try it, open http://localhost:5070 and use Maria's made-up visit in [scripts/video/](scripts/video/):

1. **Start a visit.** Upload `maria_checkin.json`.
2. **Conversation.** Record or upload audio, paste `maria_conversation.txt`, or **Skip**.
3. **Clinician note.** Upload `maria_note.txt`, add "Dr. Lee" and an office phone number, then click **Write the summary**.
4. **Review.** Click **Select all**, type your name, then **Approve summary**.
5. **Send.** Choose **Printout / Email / Phone call**, and pick a language button if needed.

Optional keys go in a local `.env` file, which is never committed:

- `ANTHROPIC_API_KEY`: Claude writes the summary and the translations.
- `ELEVENLABS_API_KEY`: ElevenLabs transcribes the recordings.

Without keys, offline methods are used.

---

## How it works

```
check-in (JSON) ──┐
typed note ───────┼─> plain-language summary ──> clinician review ──> printout / email / phone call
recording ────────┘   (tools/plain_language)      (checklist,          (tools/translation for other
 (tools/transcription)                              Select all,           languages, tools/voice for
                                                    approve)              the call)
```

---

## Repository map

```
.
├── README.md                  this page
├── REFERENCES.md              every source, dataset, model and library used
├── CLAUDE.md                  rules for Claude Code in this repo (plain language, translation, clinical safety, privacy)
├── requirements.txt           one install for everything
│
├── docs/
│   ├── README.md
│   └── PROJECT_HISTORY.md     what was built, why, and every decision so far
│
├── scripts/                   the main scripts: run these
│   ├── README.md
│   ├── run_ai_at_70.py        the app's server (port 5070): page, check-in, recorder, summary, outputs, voice
│   ├── setup/                 one-time downloads and data builds
│   │   ├── README.md
│   │   ├── build_translation_models.py   offline translation models  -> tools/translation/models/
│   │   ├── build_voices.py               neural voices               -> tools/voice/models/
│   │   ├── build_dictionaries.py         lay dictionary + medical word list -> tools/plain_language/data/
│   │   └── build_reader_baseline.py      word-knowledge data for the reading check
│   └── video/                 builds the demo video from the real app
│       ├── README.md
│       ├── maria_checkin.json, maria_conversation.txt, maria_note.txt   the made-up visit
│       ├── make_visit_audio.py   voices the conversation (macOS)
│       ├── capture_app.py        records the real app going through the visit
│       ├── cartoon.html          the animated scenes
│       └── make_video.py         puts it together -> outputs/video/ai_at_70_demo.mp4
│
├── tools/                     the main tools (each also runs on its own)
│   ├── README.md
│   ├── questionnaire/         the patient check-in form (5 languages, exports JSON)
│   ├── transcription/         records and transcribes the visit, separates speakers, checks medical terms
│   │   └── static/            its own small web page (mounted at /audio by the app)
│   ├── plain_language/        clinician note -> checked plain-language summary + the three outputs
│   │   ├── data/              plain-wording dictionaries and word-knowledge data
│   │   └── templates/         HTML for the printable summary
│   ├── translation/           Spanish, Mandarin, Portuguese, Arabic, with back-translation checks
│   └── voice/                 natural voices for the phone call
│
└── outputs/                   the main products
    ├── README.md
    ├── interface/             the clinician's web page (the app) + screenshots
    └── video/                 the demo video and the prompt to remake it with other AI tools
```

Each folder has its own `README.md` with what is in it and how to run it.

---

## Safety and privacy, in short

These rules come from [CLAUDE.md](CLAUDE.md):

- **Never invent clinical content.** Every medicine, dose and instruction comes from the clinician's note. Anything unclear is flagged, not guessed.
- **Nothing is sent automatically.** The clinician must tick every item and approve, and changing the language or editing removes the approval.
- **Translations are checked.** Every translated line is back-translated and checked, and each one is marked "not verified by a speaker of this language".
- **Synthetic data only.** Recordings and transcripts are git-ignored, and real patient data must never be committed.
