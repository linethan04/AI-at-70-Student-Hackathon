# scripts/

The scripts you run. Everything here uses the tools in [`../tools/`](../tools/).

Run all commands from the repository root, inside the virtual environment (`source .venv/bin/activate`).

| Script | What it does | Run |
|---|---|---|
| [`run_ai_at_70.py`](run_ai_at_70.py) | Starts the AI at 70 app: the clinician's page, the patient check-in form, the visit recorder and the summary, translation and voice services | `python scripts/run_ai_at_70.py`, then open http://localhost:5070 (`--port 5071` to change the port) |
| [`setup/`](setup/) | One-time downloads and data builds | see [setup/README.md](setup/README.md) |
| [`video/`](video/) | Builds the demo video from the real app | see [video/README.md](video/README.md) |

## `run_ai_at_70.py` in more detail

| Address | What it serves |
|---|---|
| `/` | the clinician's page, [`outputs/interface/index.html`](../outputs/interface/index.html) |
| `/questionnaire` | the patient check-in form, [`tools/questionnaire/questionnaire.html`](../tools/questionnaire/questionnaire.html) |
| `/audio/…` | the visit recorder, [`tools/transcription/app.py`](../tools/transcription/app.py), which records, uploads and transcribes |
| `POST /api/read-file` | reads an uploaded note (.txt, .pdf, or a photo on macOS) |
| `POST /api/summary` | writes the plain-language summary from the note (`tools/plain_language/visit_summary.py`) and cross-checks it against the check-in and the conversation |
| `POST /api/outputs` | the printout, email and phone script in a chosen language (`deliver.py` + `translate.py`) |
| `POST /api/speak` | one line of the phone script as audio (`tools/voice/voices.py`) |
| `GET /api/config` | which languages and voices are installed, and whether API keys are set |

Optional keys go in `.env` at the repository root:

- `ANTHROPIC_API_KEY`: Claude writes the summary and the translations.
- `ELEVENLABS_API_KEY`: ElevenLabs transcribes.

Without them, everything runs offline.

**Troubleshooting:**

- **"Address already in use":** the server is already running, so just open the page.
- **"Can't reach the AI at 70 server":** open http://localhost:5070. Opening the HTML file directly won't work.
- **`ModuleNotFoundError`:** activate `.venv` first, and don't use another Python such as Anaconda's.
