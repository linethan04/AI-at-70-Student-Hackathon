"""A natural voice for the phone call, made on this computer (no API key, nothing leaves the machine).

Neural text-to-speech, the most human-sounding open voices available offline:
    English, Spanish, Portuguese   Kokoro v1.0 (kokoro-onnx): af_heart, ef_dora, pf_dora
    Mandarin                       Kokoro v1.0 through sherpa-onnx, with its Chinese lexicon: zf_xiaoxiao
    Arabic                         Piper ar_JO "kareem" (piper-tts)
Models are in tools/voice/models/ (~770 MB, git-ignored); build_voices.py downloads them.

    python tools/voice/voices.py en "Take 1 pill, 5 milligrams, each day." out.wav
"""

import io
import sys
import threading
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
VOICES = HERE / "models"  # downloaded by scripts/setup/build_voices.py (git-ignored)
KOKORO_ONNX = VOICES / "kokoro-onnx"
KOKORO_ZH = VOICES / "kokoro-multi-lang-v1_0"
PIPER_AR = VOICES / "vits-piper-ar_JO-kareem-medium" / "ar_JO-kareem-medium.onnx"
KOKORO_VOICE = {"en": ("af_heart", "en-us"), "es": ("ef_dora", "es"), "pt": ("pf_dora", "pt-br")}
ZH_SPEAKER = 47        # zf_xiaoxiao in Kokoro v1.0's speaker list
SPEED = 0.92           # a little slower than everyday speech, for older listeners
lock = threading.Lock()  # one line at a time: each model uses every core


def available(lang: str) -> bool:
    if lang in KOKORO_VOICE:
        return (KOKORO_ONNX / "kokoro-v1.0.onnx").exists()
    return KOKORO_ZH.is_dir() if lang == "zh" else PIPER_AR.exists() if lang == "ar" else False


@lru_cache(maxsize=1)
def kokoro():
    from kokoro_onnx import Kokoro
    return Kokoro(str(KOKORO_ONNX / "kokoro-v1.0.onnx"), str(KOKORO_ONNX / "voices-v1.0.bin"))


@lru_cache(maxsize=1)
def kokoro_zh():
    import sherpa_onnx
    d = KOKORO_ZH
    model = sherpa_onnx.OfflineTtsModelConfig(kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
        model=str(d / "model.onnx"), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
        data_dir=str(d / "espeak-ng-data"), dict_dir=str(d / "dict"), lang="zh",
        lexicon=f"{d / 'lexicon-zh.txt'},{d / 'lexicon-us-en.txt'}"), num_threads=4)
    rules = ",".join(str(d / f) for f in ("date-zh.fst", "number-zh.fst", "phone-zh.fst"))
    return sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=model, rule_fsts=rules))


@lru_cache(maxsize=1)
def piper_ar():
    from piper import PiperVoice
    return PiperVoice.load(str(PIPER_AR))


def wav(samples, rate: int) -> bytes:
    pad = np.zeros(int(0.3 * rate), dtype=np.float32)  # a breath between lines
    out = io.BytesIO()
    sf.write(out, np.concatenate([np.asarray(samples, dtype=np.float32), pad]), rate, format="WAV", subtype="PCM_16")
    return out.getvalue()


def speak(text: str, lang: str = "en") -> bytes:
    """WAV audio of one line, read in the language's voice."""
    with lock:
        if lang in KOKORO_VOICE:
            voice, code = KOKORO_VOICE[lang]
            samples, rate = kokoro().create(text, voice=voice, speed=SPEED, lang=code)
            return wav(samples, rate)
        if lang == "zh":
            audio = kokoro_zh().generate(text, sid=ZH_SPEAKER, speed=SPEED)
            return wav(audio.samples, audio.sample_rate)
        if lang == "ar":
            out = io.BytesIO()
            with wave.open(out, "wb") as w:
                piper_ar().synthesize_wav(text, w)
            samples, rate = sf.read(io.BytesIO(out.getvalue()), dtype="float32")
            return wav(samples, rate)
    raise ValueError(f"no voice for {lang}")


if __name__ == "__main__":
    Path(sys.argv[3] if len(sys.argv) > 3 else "voice.wav").write_bytes(speak(sys.argv[2], sys.argv[1]))
