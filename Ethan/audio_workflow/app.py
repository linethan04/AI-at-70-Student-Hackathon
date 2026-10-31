"""Web interface for the audio pipeline: record in the browser, get a cleaned transcript.

    python Ethan/audio_workflow/app.py        # then open http://localhost:5050

Runs locally only. The browser records with the computer's microphone, uploads the audio
to this server, and the server runs the same steps as the command line:
    save audio -> transcribe (EL_audio.py) -> speakers + medical terms (clean_transcript.py)
"""

import json
import os
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import soundfile as sf
from dotenv import find_dotenv, load_dotenv
from flask import Flask, abort, jsonify, request, send_from_directory

from EL_audio import RECORDINGS_DIR, SAMPLE_RATE, TRANSCRIPTS_DIR, WHISPER_MODEL, save_transcript, \
    transcribe_elevenlabs, transcribe_whisper
from clean_transcript import clean_transcript

HERE = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(HERE / "static"), static_url_path="/static")

jobs: dict[str, dict] = {}
pipeline_lock = threading.Lock()  # one recording at a time: the models are big


def safe_name(name: str, folder: Path) -> Path:
    """Only allow plain file names inside `folder` (no ../ tricks)."""
    path = (folder / Path(name).name).resolve()
    if path.parent != folder.resolve() or not path.exists():
        abort(404)
    return path


def load_result(clean_path: Path, audio_name: str) -> dict:
    result = json.loads(clean_path.read_text())
    result["audio_url"] = f"/audio/{audio_name}"
    result["downloads"] = {"txt": f"/files/{clean_path.stem}.txt", "json": f"/files/{clean_path.name}"}
    return result


def run_pipeline(job_id: str, audio_path: Path, options: dict) -> None:
    job = jobs[job_id]

    def stage(step: str, message: str) -> None:
        job.update(step=step, message=message)

    try:
        with pipeline_lock:
            keyterms = [k.strip() for k in options.get("keyterms", "").split(",") if k.strip()]
            if options["transcriber"] == "elevenlabs":
                stage("transcribe", "Transcribing with ElevenLabs...")
                segments = transcribe_elevenlabs(audio_path, keyterms)
            else:
                model = options.get("whisper_model") or WHISPER_MODEL
                stage("transcribe", f"Transcribing with Whisper ({model}, on this computer)...")
                segments = transcribe_whisper(audio_path, keyterms, model)
            if not segments:
                raise RuntimeError("No speech was found in the recording.")
            json_path, _ = save_transcript(audio_path, options["transcriber"], segments)

            def log(message: str) -> None:
                step = "terms" if ("medical" in message or "Checking" in message) else "speakers"
                if not message.startswith("Saved"):
                    stage(step, message)

            num = int(options["num_speakers"]) if options.get("num_speakers", "").isdigit() else None
            stage("speakers", "Separating speakers...")
            clean_path = clean_transcript(json_path, num, options.get("cleanup", "auto"), log=log)

        job.update(status="done", step="done", message="Done", result=load_result(clean_path, audio_path.name))
    except Exception as e:  # show the error in the page instead of failing silently
        traceback.print_exc()
        job.update(status="error", message=f"{e.__class__.__name__}: {e}")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def config():
    recordings = []
    for path in sorted(RECORDINGS_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            seconds = sf.info(path).duration
        except RuntimeError:
            continue
        recordings.append({"name": path.name, "seconds": round(seconds)})
    return jsonify({
        "has_anthropic": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")),
        "has_elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
        "recordings": recordings,
    })


@app.post("/api/jobs")
def create_job():
    """Start processing either an uploaded/recorded file or an existing recording."""
    options = {k: request.form.get(k, "") for k in ("transcriber", "whisper_model", "cleanup", "num_speakers", "keyterms")}
    options["transcriber"] = options["transcriber"] or "whisper"

    if "audio" in request.files:
        from faster_whisper import decode_audio  # handles the browser's webm/ogg/mp4 audio

        upload = request.files["audio"]
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp = RECORDINGS_DIR / f".upload_{stamp}{Path(upload.filename or 'audio.webm').suffix}"
        upload.save(tmp)
        audio_path = RECORDINGS_DIR / f"visit_{stamp}.wav"
        try:
            sf.write(audio_path, decode_audio(str(tmp), sampling_rate=SAMPLE_RATE), SAMPLE_RATE, subtype="PCM_16")
        finally:
            tmp.unlink(missing_ok=True)
    elif request.form.get("recording"):
        audio_path = safe_name(request.form["recording"], RECORDINGS_DIR)
    else:
        return jsonify({"error": "No audio provided."}), 400

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"status": "running", "step": "save", "message": "Audio saved", "recording": audio_path.name}
    threading.Thread(target=run_pipeline, args=(job_id, audio_path, options), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    if job_id not in jobs:
        abort(404)
    return jsonify(jobs[job_id])


@app.get("/api/results/<name>")
def saved_result(name: str):
    """A transcript processed earlier, e.g. /?open=sample_visit reopens it without re-running."""
    clean_path = safe_name(f"{Path(name).stem}.clean.json", TRANSCRIPTS_DIR)
    return jsonify(load_result(clean_path, f"{Path(name).stem}.wav"))


@app.get("/audio/<name>")
def audio(name: str):
    path = safe_name(name, RECORDINGS_DIR)
    return send_from_directory(path.parent, path.name)


@app.get("/files/<name>")
def files(name: str):
    path = safe_name(name, TRANSCRIPTS_DIR)
    return send_from_directory(path.parent, path.name, as_attachment=True)


if __name__ == "__main__":
    load_dotenv(find_dotenv())
    print("Open http://localhost:5050 in your browser (Chrome, Edge, Firefox or Safari).")
    app.run(host="127.0.0.1", port=5050, threaded=True, debug=False)
