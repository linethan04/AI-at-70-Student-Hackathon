"""Record or load an appointment recording and transcribe it with speaker labels.

Step 1 of the pipeline (see CLAUDE.md): audio -> transcript. The JSON output is
what the later Claude steps (fact extraction, plain-language rewrite) will read.

Usage:
    python Ethan/audio_workflow/EL_audio.py record                  # record mic until Enter, then transcribe
    python Ethan/audio_workflow/EL_audio.py transcribe visit.wav    # transcribe an existing file
    python Ethan/audio_workflow/EL_audio.py transcribe visit.wav --engine whisper --keyterms "metformin,lisinopril"
    python Ethan/audio_workflow/EL_audio.py transcribe visit.wav --clean   # + speaker separation and medical term check

Engines:
    elevenlabs  ElevenLabs Scribe (cloud). Speaker diarization + medical keyterm biasing.
                Needs ELEVENLABS_API_KEY. Default when the key is set.
    whisper     faster-whisper (local, offline, free). No speaker labels.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

HERE = Path(__file__).resolve().parent
RECORDINGS_DIR = HERE / "recordings"
TRANSCRIPTS_DIR = HERE / "transcripts"

SAMPLE_RATE = 16_000  # 16 kHz mono is plenty for speech and keeps files small
ELEVENLABS_MODEL = "scribe_v2"
WHISPER_MODEL = "base.en"  # try "small.en" or "medium.en" for better accuracy


# ---------- recording ----------

def record_until_enter(out_path: Path) -> Path:
    """Record from the default microphone until the user presses Enter."""
    import queue
    import threading

    import sounddevice as sd
    import soundfile as sf

    out_path.parent.mkdir(parents=True, exist_ok=True)
    chunks: queue.Queue = queue.Queue()
    stop = threading.Event()

    def callback(indata, _frames, _time, status):
        if status:
            print(status, file=sys.stderr)
        chunks.put(indata.copy())

    threading.Thread(target=lambda: (input(), stop.set()), daemon=True).start()

    # Write chunks to disk as they arrive so long appointments don't sit in memory.
    with sf.SoundFile(out_path, mode="w", samplerate=SAMPLE_RATE, channels=1, subtype="PCM_16") as f:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback):
            print("Recording... press Enter to stop.")
            while not stop.is_set():
                try:
                    f.write(chunks.get(timeout=0.2))
                except queue.Empty:
                    pass
        while not chunks.empty():
            f.write(chunks.get())

    print(f"Saved recording to {out_path}")
    return out_path


# ---------- transcription ----------
# Both engines return the same shape: a list of segments
#   {"speaker": str, "start": float, "end": float, "text": str}

def transcribe_elevenlabs(audio_path: Path, keyterms: list[str]) -> list[dict]:
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    kwargs = {}
    if keyterms:
        kwargs["keyterms"] = keyterms  # biases recognition toward drug names, conditions, etc.

    with open(audio_path, "rb") as f:
        result = client.speech_to_text.convert(
            file=f,
            model_id=ELEVENLABS_MODEL,
            language_code="eng",
            diarize=True,           # who said what
            tag_audio_events=True,  # (coughing), (laughter), ...
            **kwargs,
        )

    # Words come back one by one with a speaker_id; merge consecutive words into speaker turns.
    segments: list[dict] = []
    for word in result.words:
        if word.type == "spacing" and segments:
            segments[-1]["text"] += word.text
            continue
        speaker = word.speaker_id or "speaker_0"
        if segments and segments[-1]["speaker"] == speaker:
            segments[-1]["text"] += word.text
            segments[-1]["end"] = word.end
        else:
            segments.append({"speaker": speaker, "start": word.start, "end": word.end, "text": word.text})

    for seg in segments:
        seg["text"] = seg["text"].strip()
        # "speaker_0" -> "Speaker 1". Mapping speakers to Doctor/Patient is a later Claude step.
        seg["speaker"] = f"Speaker {int(seg['speaker'].rsplit('_', 1)[-1]) + 1}" if seg["speaker"].startswith("speaker_") else seg["speaker"]
    return [s for s in segments if s["text"]]


def transcribe_whisper(audio_path: Path, keyterms: list[str]) -> list[dict]:
    from faster_whisper import WhisperModel

    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    # Whisper has no keyterm API, but an initial prompt nudges spelling of uncommon words.
    prompt = ("Medical appointment. Terms: " + ", ".join(keyterms)) if keyterms else None
    segments, _info = model.transcribe(str(audio_path), initial_prompt=prompt, vad_filter=True, word_timestamps=True)
    return split_sentences(w for s in segments for w in s.words)


PAUSE_SPLIT_SECONDS = 0.8


def split_sentences(words) -> list[dict]:
    """Cut Whisper's words into sentences (and at long pauses). Whisper doesn't know who is
    talking, so its segments often span two speakers; sentence-sized pieces let
    clean_transcript.py assign each one to the right speaker."""
    out: list[dict] = []
    cur = None
    for w in words:
        if cur and w.start - cur["end"] > PAUSE_SPLIT_SECONDS:
            out.append(cur)
            cur = None
        if cur is None:
            cur = {"speaker": "Speaker", "start": w.start, "end": w.end, "text": ""}
        cur["text"] += w.word
        cur["end"] = w.end
        if w.word.rstrip().endswith((".", "?", "!")):
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    for seg in out:
        seg["text"] = seg["text"].strip()
    return [s for s in out if s["text"]]


ENGINES = {"elevenlabs": transcribe_elevenlabs, "whisper": transcribe_whisper}


# ---------- output ----------

def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds or 0), 60)
    return f"{m:02d}:{s:02d}"


def save_transcript(audio_path: Path, engine: str, segments: list[dict]) -> tuple[Path, Path]:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = audio_path.stem
    json_path = TRANSCRIPTS_DIR / f"{stem}.json"
    txt_path = TRANSCRIPTS_DIR / f"{stem}.txt"

    json_path.write_text(json.dumps({
        "source_audio": str(audio_path),
        "engine": engine,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "segments": segments,
    }, indent=2))
    txt_path.write_text("\n\n".join(
        f"[{fmt_time(s['start'])}] {s['speaker']}: {s['text']}" for s in segments
    ) + "\n")
    return json_path, txt_path


# ---------- CLI ----------

def main() -> None:
    load_dotenv(find_dotenv())  # searches upward for the project-root .env

    parser = argparse.ArgumentParser(description="Record and transcribe a clinical appointment.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record", help="record from the microphone, then transcribe")
    t = sub.add_parser("transcribe", help="transcribe an existing audio file")
    t.add_argument("audio", type=Path)
    for p in sub.choices.values():
        p.add_argument("--engine", choices=ENGINES,
                       default="elevenlabs" if os.getenv("ELEVENLABS_API_KEY") else "whisper")
        p.add_argument("--keyterms", default="", help="comma-separated medical terms to recognize, e.g. 'metformin,A1C'")
        p.add_argument("--clean", action="store_true",
                       help="then run clean_transcript.py (speaker separation + medical term check)")
        p.add_argument("--num-speakers", type=int, help="with --clean: how many people were in the room, if known")
    args = parser.parse_args()

    if args.command == "record":
        audio_path = record_until_enter(RECORDINGS_DIR / f"visit_{datetime.now():%Y%m%d_%H%M%S}.wav")
    else:
        audio_path = args.audio
        if not audio_path.exists():
            parser.error(f"file not found: {audio_path}")

    keyterms = [k.strip() for k in args.keyterms.split(",") if k.strip()]
    print(f"Transcribing {audio_path.name} with {args.engine}...")
    segments = ENGINES[args.engine](audio_path, keyterms)
    json_path, txt_path = save_transcript(audio_path, args.engine, segments)

    print("\n" + txt_path.read_text())
    print(f"Saved {txt_path}\nSaved {json_path}")

    if args.clean:
        from clean_transcript import clean_transcript
        clean_transcript(json_path, num_speakers=args.num_speakers)


if __name__ == "__main__":
    main()
