"""Generate a synthetic doctor/patient visit recording for testing (macOS only).

Uses the built-in `say` voices so we never need real patient audio (see CLAUDE.md, Privacy).

    python Ethan/make_sample_audio.py
    python Ethan/EL_audio.py transcribe Ethan/recordings/sample_visit.wav
"""

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

OUT = Path(__file__).resolve().parent / "recordings" / "sample_visit.wav"
SAMPLE_RATE = 16_000

# Fictional patient, fictional visit.
SCRIPT = [
    ("Daniel", "Good morning, Mrs. Alvarez. How have you been feeling since your last visit?"),
    ("Samantha", "Pretty good, doctor. I get a little dizzy when I stand up too fast, though."),
    ("Daniel", "Okay. Your blood pressure today is one hundred and two over sixty-four, which is on the low side. "
               "I think the lisinopril dose is a bit too strong for you."),
    ("Daniel", "Let's lower the lisinopril from twenty milligrams to ten milligrams, once a day in the morning."),
    ("Samantha", "Okay. Should I keep taking the metformin?"),
    ("Daniel", "Yes, keep the metformin at five hundred milligrams twice a day with meals. Your A1C was seven point one, which is close to our goal."),
    ("Daniel", "Stand up slowly, and drink plenty of water. If you faint or have chest pain, call nine one one."),
    ("Daniel", "I'd like to see you back in four weeks to recheck your blood pressure."),
    ("Samantha", "Thank you, doctor. My daughter will drive me."),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pause = np.zeros(int(0.6 * SAMPLE_RATE), dtype=np.float32)
    pieces = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (voice, line) in enumerate(SCRIPT):
            wav = Path(tmp) / f"{i}.wav"
            subprocess.run(["say", "-v", voice, "-o", str(wav),
                            f"--data-format=LEI16@{SAMPLE_RATE}", line], check=True)
            audio, _ = sf.read(wav, dtype="float32")
            pieces += [audio, pause]
    sf.write(OUT, np.concatenate(pieces), SAMPLE_RATE, subtype="PCM_16")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
