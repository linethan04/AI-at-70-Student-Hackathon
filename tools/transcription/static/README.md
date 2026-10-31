# tools/transcription/static/

These are the web pages for the transcription tool's own server ([`../app.py`](../app.py), port 5050).

| Path | Page |
|---|---|
| [`site/`](site/) (`index.html`, `site.css`, `site.js`) | `/`: the simple, phone-friendly page. Record or upload, then read the transcript. |
| `index.html`, `app.css`, `app.js` | `/advanced`: settings (engine, speakers, keyterms) and saved recordings. Turned off with `--public`. |

The AI at 70 app uses this tool's API (`/audio/api/...`), not these pages.
