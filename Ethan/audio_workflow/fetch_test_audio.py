"""Download a real mock primary-care visit to test the pipeline with.

Source: PriMock57 (Babylon Health, CC BY 4.0): 57 mock GP consultations between 7
clinicians and actors playing patients, with hand-made, timed transcripts.
https://github.com/babylonhealth/primock57  (paper: https://arxiv.org/abs/2204.00333)

The doctor and patient were recorded on separate channels. This script mixes them into
one mono file (like a single microphone in the room) and saves the human transcript,
with who-said-what, as the answer key for evaluate.py.

    python Ethan/audio_workflow/fetch_test_audio.py                  # day1_consultation01
    python Ethan/audio_workflow/fetch_test_audio.py day2_consultation03 --seconds 180

Writes recordings/primock_<id>.wav and test_data/primock_<id>.reference.json/.txt
"""

import argparse
import json
import re
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

from EL_audio import RECORDINGS_DIR, fmt_time

HERE = Path(__file__).resolve().parent
TEST_DATA_DIR = HERE / "test_data"
AUDIO_URL = "https://media.githubusercontent.com/media/babylonhealth/primock57/main/audio/{id}_{who}.wav"
TRANSCRIPT_URL = "https://raw.githubusercontent.com/babylonhealth/primock57/main/transcripts/{id}_{who}.TextGrid"
SPEAKERS = {"doctor": "Doctor", "patient": "Patient"}


def download(url: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {url.rsplit('/', 1)[-1]}...")
        urllib.request.urlretrieve(url, dest)
    return dest


def clean_text(text: str) -> str:
    """Drop PriMock57's transcriber tags: <UNSURE>..</UNSURE> keeps its words, <UNIN/> is removed."""
    text = re.sub(r"<UNIN/>", "", text)
    text = re.sub(r"</?[A-Z]+/?>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def read_textgrid(path: Path, speaker: str) -> list[dict]:
    """Minimal Praat TextGrid reader: every non-empty interval becomes an utterance."""
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(r'xmin = ([\d.]+)\s*\n\s*xmax = ([\d.]+)\s*\n\s*text = "((?:[^"]|"")*)"')
    out = []
    for start, end, text in pattern.findall(content):
        text = clean_text(text.replace('""', '"'))
        if text:
            out.append({"speaker": speaker, "start": float(start), "end": float(end), "text": text})
    return out


def fetch(consultation: str, seconds: float | None) -> tuple[Path, Path]:
    raw_dir = TEST_DATA_DIR / "primock57"
    channels, utterances = [], []
    for who, label in SPEAKERS.items():
        wav = download(AUDIO_URL.format(id=consultation, who=who), raw_dir / f"{consultation}_{who}.wav")
        grid = download(TRANSCRIPT_URL.format(id=consultation, who=who), raw_dir / f"{consultation}_{who}.TextGrid")
        audio, sr = sf.read(wav, dtype="float32")
        channels.append(audio if audio.ndim == 1 else audio.mean(axis=1))
        utterances += read_textgrid(grid, label)

    # Mix the two channels into one "room" recording, normalized to avoid clipping.
    length = max(len(c) for c in channels)
    mixed = sum(np.pad(c, (0, length - len(c))) for c in channels)
    if seconds:
        mixed = mixed[: int(seconds * sr)]
        utterances = [u for u in utterances if u["start"] < seconds]
    mixed = mixed / max(1e-9, np.abs(mixed).max()) * 0.9

    name = f"primock_{consultation}" + (f"_{int(seconds)}s" if seconds else "")
    audio_path = RECORDINGS_DIR / f"{name}.wav"
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    sf.write(audio_path, mixed, sr, subtype="PCM_16")

    utterances.sort(key=lambda u: u["start"])
    ref_json = TEST_DATA_DIR / f"{name}.reference.json"
    ref_json.write_text(json.dumps({"source": "PriMock57 (CC BY 4.0)", "consultation": consultation,
                                    "seconds": seconds, "audio": str(audio_path), "utterances": utterances}, indent=2))
    ref_json.with_suffix("").with_suffix(".reference.txt").write_text("\n\n".join(
        f"[{fmt_time(u['start'])}] {u['speaker']}: {u['text']}" for u in utterances) + "\n")
    print(f"Wrote {audio_path} ({len(mixed) / sr / 60:.1f} min)\nWrote {ref_json}")
    return audio_path, ref_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a PriMock57 mock consultation for testing.")
    parser.add_argument("consultation", nargs="?", default="day1_consultation01",
                        help="e.g. day1_consultation01 ... day5_consultation15")
    parser.add_argument("--seconds", type=float, help="keep only the first N seconds (faster tests)")
    args = parser.parse_args()
    fetch(args.consultation, args.seconds)


if __name__ == "__main__":
    main()
