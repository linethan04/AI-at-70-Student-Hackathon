"""Download the neural voices voices.py uses for the phone call (~770 MB into data/voices/, git-ignored).

    python Ethan/conversion_library/build_voices.py

Kokoro v1.0 (Apache-2.0) for English, Spanish, Portuguese and Mandarin; Piper ar_JO-kareem for Arabic.
"""

import io
import tarfile
import urllib.request

from voices import KOKORO_ONNX, VOICES

KOKORO_FILES = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/{}"
SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{}.tar.bz2"


def main() -> None:
    KOKORO_ONNX.mkdir(parents=True, exist_ok=True)
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        if not (KOKORO_ONNX / name).exists():
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(KOKORO_FILES.format(name), KOKORO_ONNX / name)
    for name in ("kokoro-multi-lang-v1_0", "vits-piper-ar_JO-kareem-medium"):
        if not (VOICES / name).is_dir():
            print(f"downloading {name} ...")
            tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(SHERPA.format(name)).read()), mode="r:bz2").extractall(VOICES)
    print("voices ready")


if __name__ == "__main__":
    main()
