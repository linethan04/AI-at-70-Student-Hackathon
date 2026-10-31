"""Turn each test conversation into a two-voice recording (macOS `say`), for testing audio upload.

    python Ethan/ai_at_70/test_kit/make_test_audio.py     # writes test_kit/audio/*.wav and demo/maria_visit.wav (git-ignored)

Synthetic voices reading fictional visits: no real patient audio (CLAUDE.md, Privacy).
"""

import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
SAMPLE_RATE = 16_000
VOICES = {"Clinician": "Daniel", "Patient": "Samantha"}
SPOKEN = [(r"(\d+) mg\b", r"\1 milligrams")]


def main() -> None:
    out_dir = HERE / "audio"
    out_dir.mkdir(exist_ok=True)
    pause = np.zeros(int(0.6 * SAMPLE_RATE), dtype=np.float32)
    demo = HERE.parent / "demo" / "maria_conversation.txt"
    for convo in sorted((HERE / "conversations").glob("*.txt")) + [demo]:
        pieces = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, line in enumerate(convo.read_text().splitlines()):
                m = re.match(r"\[[\d:]+\] (\w+): (.+)", line)
                if not m:
                    continue
                text = m.group(2)
                for pattern, new in SPOKEN:
                    text = re.sub(pattern, new, text)
                wav = Path(tmp) / f"{i}.wav"
                subprocess.run(["say", "-v", VOICES.get(m.group(1), "Daniel"), "-o", str(wav),
                                f"--data-format=LEI16@{SAMPLE_RATE}", text], check=True)
                audio, _ = sf.read(wav, dtype="float32")
                pieces += [audio, pause]
        path = convo.with_name("maria_visit.wav") if convo == demo else out_dir / f"{convo.stem}.wav"
        sf.write(path, np.concatenate(pieces), SAMPLE_RATE, subtype="PCM_16")
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
