"""Voice Maria's made-up visit as a two-voice recording (macOS `say`): the audio the demo video's
recording step plays into the app through Chrome's fake microphone.

    python scripts/video/make_visit_audio.py     # reads maria_conversation.txt, writes maria_visit.wav (git-ignored)

Synthetic voices reading a fictional visit: no real patient audio (CLAUDE.md, Privacy).
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
    pause = np.zeros(int(0.6 * SAMPLE_RATE), dtype=np.float32)
    pieces = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, line in enumerate((HERE / "maria_conversation.txt").read_text().splitlines()):
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
    path = HERE / "maria_visit.wav"
    sf.write(path, np.concatenate(pieces), SAMPLE_RATE, subtype="PCM_16")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
