"""AI at 70: the clinician's page that joins the finished tools into one flow.

    python Ethan/ai_at_70/app.py        # then open http://localhost:5070

Inputs (any combination):
    check-in       the patient's questionnaire (Max/PCP_Questionnaire_..., exported as JSON)
    clinician note typed, pasted, uploaded (.txt / .pdf) or a sample
    conversation   recorded or uploaded audio, transcribed by Ethan/audio_workflow (mounted at /audio), or pasted
Outputs, after the clinician ticks every check and approves:
    printout, email to the patient or family (next of kin), phone-call script; each in English, Mandarin,
    Spanish, Portuguese or Arabic (translated from the checked English, Ethan/conversion_library/translate.py)

The page itself is Max/AI-at-70 (5).html; this server gives it the tools behind it. Nothing is sent from
here: email opens a draft in the clinician's mail app, and the call script is read (or played) by a person.
"""

import argparse
import importlib.util
import io
import json
import os
import re
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.middleware.dispatcher import DispatcherMiddleware

ROOT = Path(__file__).resolve().parents[2]
CONVERSION, AUDIO, MAX = ROOT / "Ethan" / "conversion_library", ROOT / "Ethan" / "audio_workflow", ROOT / "Max"
PAGE = MAX / "AI-at-70 (5).html"
QUESTIONNAIRE = MAX / "PCP_Questionnaire_5_Languages_With_Name_And_DOB.html"
sys.path[:0] = [str(CONVERSION), str(AUDIO)]

from deliver import document, outputs  # noqa: E402  (after the path is set)
from translate import LANGUAGES, available  # noqa: E402
from visit_summary import checklist, note_medicines, sources_used, summarize_note  # noqa: E402

MAX_CHARS = 60_000
SAMPLES = CONVERSION / "samples"

load_dotenv(find_dotenv())
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


def audio_app():
    """The Visit Recorder (Ethan/audio_workflow/app.py), loaded under its own name: both folders have an app.py."""
    spec = importlib.util.spec_from_file_location("audio_workflow_app", AUDIO / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PUBLIC = False
    return module.app


@app.get("/")
def page():
    return send_from_directory(PAGE.parent, PAGE.name)


@app.get("/questionnaire")
def questionnaire():
    return send_from_directory(QUESTIONNAIRE.parent, QUESTIONNAIRE.name)


@app.get("/api/config")
def config():
    return jsonify({
        "claude": bool(os.getenv("ANTHROPIC_API_KEY")),
        "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
        "languages": [{"code": c, "name": n, "ready": available(c)} for c, n in LANGUAGES.items()],
        "samples": sorted(p.stem for p in SAMPLES.glob("*.txt")),
    })


@app.get("/api/samples/<name>")
def sample(name: str):
    path = SAMPLES / f"{Path(name).name}.txt"
    if not path.is_file():
        abort(404)
    return jsonify({"text": path.read_text()})


@app.post("/api/read-file")
def read_file():
    """A note uploaded as .txt or .pdf, as text."""
    upload = request.files.get("file")
    if not upload:
        return jsonify({"error": "No file."}), 400
    data = upload.read()
    if upload.filename.lower().endswith(".pdf"):
        from pypdf import PdfReader
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    else:
        text = data.decode("utf-8", errors="replace")
    return jsonify({"text": text.replace("\r\n", "\n")[:MAX_CHARS]})


def answers_text(q: dict) -> str:
    """The check-in answers that matter for a summary, without contact details."""
    private = {"patient_email", "caregiver_email", "patient_date_of_birth", "consent_name", "consent_date", "caregiver_phone"}
    a = {k: v for k, v in (q.get("answers") or {}).items() if k not in private and v not in ("", [], None)}
    return json.dumps(a, ensure_ascii=False)


def cross_check(note: str, transcript: str, q: dict) -> list[str]:
    """Contradictions between the inputs, for the clinician (CLAUDE.md: surface them, don't resolve them)."""
    flags = []
    in_note = note_medicines(note)
    if transcript.strip():
        said = note_medicines(transcript) - in_note
        if said:
            flags.append("Mentioned in the conversation but not in the note: " + ", ".join(sorted(said)))
    a = (q or {}).get("answers") or {}
    listed = note_medicines(str(a.get("medications", "")))
    if listed - in_note:
        flags.append("On the patient's check-in medicine list but not in the note: " + ", ".join(sorted(listed - in_note)))
    allergies = str(a.get("allergies", "")).lower()
    for med in in_note:
        if med and re.search(rf"\b{re.escape(med)}\b", allergies):
            flags.append(f"The check-in lists an allergy to {med}, which is in the note: check before giving it")
    return flags


@app.post("/api/summary")
def summary():
    data = request.get_json(force=True)
    note = (data.get("note") or "").strip()[:MAX_CHARS]
    transcript = (data.get("transcript") or "").strip()[:MAX_CHARS]
    q = data.get("questionnaire") or {}
    if not note:
        return jsonify({"error": "Add the clinician's note first: the summary is written from it."}), 400
    use_claude = bool(data.get("claude")) and bool(os.getenv("ANTHROPIC_API_KEY"))
    context = "".join([f"<visit_conversation>\n{transcript}\n</visit_conversation>\n" if transcript else "",
                       f"<questionnaire>\n{answers_text(q)}\n</questionnaire>" if q else ""])
    try:
        s = summarize_note(note, use_claude, int(data.get("grade") or 7), context)
    except Exception as e:  # Claude errors: say so instead of failing silently
        return jsonify({"error": f"Couldn't write the summary: {e.__class__.__name__}: {e}"}), 500
    r = s.readability
    return jsonify({
        "doc": document(s), "origin": s.origin, "ready": s.ready, "grade": s.grade,
        "reader": r["describe"], "smog": r.get("smog"), "checks": s.checks, "tries": s.tries,
        "checklist": checklist(s), "left_out": s.left_out, "sources": sources_used(s),
        "cross_checks": cross_check(note, transcript, q) + s.clinician_flags,
    })


@app.post("/api/outputs")
def make_outputs():
    data = request.get_json(force=True)
    lang = data.get("lang", "en")
    if lang not in LANGUAGES:
        return jsonify({"error": "Unknown language."}), 400
    if not available(lang):
        return jsonify({"error": f"The {LANGUAGES[lang]} model isn't installed: run "
                                 "python Ethan/conversion_library/build_translation_models.py"}), 400
    fields = {k: (data.get(k) or "").strip() for k in ("patient", "recipient", "relationship", "clinician", "office_phone")}
    return jsonify(outputs(data["doc"], lang, **fields))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI at 70: the clinician's page.")
    parser.add_argument("--port", type=int, default=5070)
    args = parser.parse_args()
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/audio": audio_app()})
    print(f"Open http://localhost:{args.port}")
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False)
