"""Web interface for the audio pipeline: record in the browser, get a cleaned transcript.

    python Ethan/audio_workflow/app.py            # then open http://localhost:5050
    python Ethan/audio_workflow/app.py --public   # safe to put behind a public URL

Pages:
    /          simple page (static/site/): record or upload, then read the transcript.
               Uses the fast defaults; works on phones.
    /advanced  full page (static/index.html): settings, saved recordings, test visits.
               Turned off with --public.

The browser records with the device's microphone, uploads the audio to this server, and the
server runs the same steps as the command line:
    save audio -> transcribe (EL_audio.py) -> speakers + medical terms (clean_transcript.py)

--public: visitors can only reach the results of their own upload, through a random
job link; listing or opening other recordings by name is disabled.
"""

import argparse
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

app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # ~3 hours of compressed audio
PUBLIC = False  # set by --public

jobs: dict[str, dict] = {}
pipeline_lock = threading.Lock()  # one recording at a time: the models are big


def local_only() -> None:
    """Routes that browse saved recordings are for the person running the server, not visitors."""
    if PUBLIC:
        abort(404)


def safe_name(name: str, folder: Path) -> Path:
    """Only allow plain file names inside `folder` (no ../ tricks)."""
    path = (folder / Path(name).name).resolve()
    if path.parent != folder.resolve() or not path.exists():
        abort(404)
    return path


def load_result(clean_path: Path, audio_name: str, job_id: str | None = None) -> dict:
    """The cleaned transcript plus links to its audio and downloads. Job results use links
    that only work with the job's random id; saved results (local only) use file names."""
    result = json.loads(clean_path.read_text())
    if job_id:
        result["audio_url"] = f"/api/jobs/{job_id}/audio"
        result["downloads"] = {"txt": f"/api/jobs/{job_id}/download/txt", "json": f"/api/jobs/{job_id}/download/json"}
    else:
        result["audio_url"] = f"/audio/{audio_name}"
        result["downloads"] = {"txt": f"/files/{clean_path.stem}.txt", "json": f"/files/{clean_path.name}"}
    return result


def run_pipeline(job_id: str, audio_path: Path, options: dict) -> None:
    job = jobs[job_id]

    def stage(step: str, message: str) -> None:
        job.update(step=step, message=message)

    try:
        if pipeline_lock.locked():
            stage("save", "Waiting for another recording to finish...")
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

        job.update(status="done", step="done", message="Done", clean_path=str(clean_path),
                   result=load_result(clean_path, audio_path.name, job_id))
    except Exception as e:  # show the error in the page instead of failing silently
        traceback.print_exc()
        job.update(status="error", message=f"{e.__class__.__name__}: {e}")


@app.get("/")
def index():
    return send_from_directory(HERE / "static" / "site", "index.html")


@app.get("/site/<path:name>")
def site_assets(name: str):
    return send_from_directory(HERE / "static" / "site", name)


@app.get("/advanced")
def advanced():
    local_only()
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def config():
    local_only()
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
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        tmp = RECORDINGS_DIR / f".upload_{stamp}{Path(upload.filename or 'audio.webm').suffix}"
        upload.save(tmp)
        audio_path = RECORDINGS_DIR / f"visit_{stamp}.wav"
        try:
            samples = decode_audio(str(tmp), sampling_rate=SAMPLE_RATE)
        except Exception:
            return jsonify({"error": "That file couldn't be read as audio. Try a different file."}), 400
        finally:
            tmp.unlink(missing_ok=True)
        if len(samples) < SAMPLE_RATE:  # under a second
            return jsonify({"error": "The recording is too short. Record at least a few seconds."}), 400
        sf.write(audio_path, samples, SAMPLE_RATE, subtype="PCM_16")
    elif request.form.get("recording"):
        local_only()
        audio_path = safe_name(request.form["recording"], RECORDINGS_DIR)
    else:
        return jsonify({"error": "No audio provided."}), 400

    job_id = uuid.uuid4().hex  # unguessable: the job id is the only key to this result
    jobs[job_id] = {"status": "running", "step": "save", "message": "Audio saved", "audio_path": str(audio_path)}
    threading.Thread(target=run_pipeline, args=(job_id, audio_path, options), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    if job_id not in jobs:
        abort(404)
    job = jobs[job_id]
    return jsonify({k: job[k] for k in ("status", "step", "message", "result") if k in job})


@app.get("/api/jobs/<job_id>/audio")
def job_audio(job_id: str):
    if job_id not in jobs:
        abort(404)
    path = Path(jobs[job_id]["audio_path"])
    return send_from_directory(path.parent, path.name)


@app.get("/api/jobs/<job_id>/download/<kind>")
def job_download(job_id: str, kind: str):
    if job_id not in jobs or "clean_path" not in jobs[job_id] or kind not in ("txt", "json"):
        abort(404)
    clean = Path(jobs[job_id]["clean_path"])
    path = clean if kind == "json" else clean.with_suffix(".txt")
    return send_from_directory(path.parent, path.name, as_attachment=True, download_name=f"transcript.{kind}")


@app.get("/api/results/<name>")
def saved_result(name: str):
    """A transcript processed earlier, e.g. /advanced?open=sample_visit reopens it without re-running."""
    local_only()
    clean_path = safe_name(f"{Path(name).stem}.clean.json", TRANSCRIPTS_DIR)
    return jsonify(load_result(clean_path, f"{Path(name).stem}.wav"))


@app.get("/audio/<name>")
def audio(name: str):
    local_only()
    path = safe_name(name, RECORDINGS_DIR)
    return send_from_directory(path.parent, path.name)


@app.get("/files/<name>")
def files(name: str):
    local_only()
    path = safe_name(name, TRANSCRIPTS_DIR)
    return send_from_directory(path.parent, path.name, as_attachment=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Visit Recorder web app.")
    parser.add_argument("--public", action="store_true", help="hide /advanced and saved recordings from visitors")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()
    PUBLIC = args.public
    load_dotenv(find_dotenv())
    print(f"Open http://localhost:{args.port} in your browser" + (" (public mode)" if PUBLIC else
          f"; full settings at http://localhost:{args.port}/advanced"))
    app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False)
