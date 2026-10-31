"""Build the ~60-second AI at 70 demo video: Maria Rodriguez's visit, today and with AI at 70.

    python Ethan/ai_at_70/test_kit/make_test_audio.py   # once: demo/maria_visit.wav
    python Ethan/ai_at_70/demo/make_note_photo.py       # once: demo/maria_note_photo.jpg
    python Ethan/ai_at_70/app.py &                      # the real page, for the screen recording
    python Ethan/ai_at_70/demo/capture_app.py           # records the page (demo/video/build/app.webm)
    python Ethan/ai_at_70/demo/make_video.py            # -> demo/video/ai_at_70_demo.mp4

Cartoon scenes come from cartoon.html, rendered frame by frame; the app scenes are cut from the screen
recording of the real page. Narration and the phone-call voice are Kokoro (the same neural voices the app uses).
One story throughout: Maria Rodriguez (78), her daughter Sofia, Dr. Lee. All made up.
"""

import json
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
BUILD = HERE / "video" / "build"
OUT = HERE / "video" / "ai_at_70_demo.mp4"
sys.path.insert(0, str(HERE.parents[1] / "conversion_library"))
from voices import kokoro  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
FPS, W, H, RATE = 30, 1280, 720, 24000
GAP = 0.18           # pause after each narration line
NARRATOR = "am_michael"
PHONE_LINE = "Blood pressure medicine, called Amlodipine. Take 1 pill, 5 milligrams, each day."

# (scene, narration). A scene is a cartoon scene name, or "app:<from mark>:<to mark or +seconds>" cut from the
# screen recording; "+" joins pieces that share one narration line.
STORY = [
    ("maria", "Meet Maria. She's seventy-eight, with diabetes and high blood pressure."),
    ("doctor", "At the doctor, she hears words like bilateral edema, B I D, and B M P."),
    ("home", "By the time she's home, it's all a blur. And her daughter, Sofia, is just as confused."),
    ("intro", "There's a better way. Sofia sets Maria up with A I at 70."),
    ("app:checkin:checkin_done|Maria's check-in, in her own words", "Before the visit, Maria fills out a short check-in, in her own words."),
    ("app:record:+3.2|Record the visit + app:transcribed:+2.4|Written out right away", "At the visit, the conversation is recorded, and written out right away."),
    ("photo@2.0 + app:note:+2.2|Read from the photo", "Then Dr. Lee snaps a photo of the visit notes."),
    ("app:summary:approved+0.8|Plain words, checked by Dr. Lee + printer@3.0", "In seconds: a one-page summary, in plain, simple words. Dr. Lee checks it, approves it, and prints it."),
    ("email", "At home, the same summary arrives by email, in case the paper gets lost."),
    ("phone", "And a phone call walks her through what to do."),
    ("family", "Sofia gets every update too, so the whole family stays in the loop."),
    ("end", "A I at 70. Quick. Reliable. Understandable."),
]


def ffmpeg(*args: str) -> None:
    subprocess.run([FF, "-loglevel", "error", "-y", *args], check=True)


def voice(text: str, name: str, speed: float = 1.0) -> np.ndarray:
    samples, rate = kokoro().create(text, voice=name, speed=speed, lang="en-us")
    assert rate == RATE
    return np.asarray(samples, dtype=np.float32)


def caption_png(text: str, path: Path) -> None:
    """The same caption pill the cartoon scenes use, for the app scenes."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 30)
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    x0, y0 = (W - tw) // 2 - 26, H - 34 - th - 26
    d.rounded_rectangle((x0, y0, x0 + tw + 52, y0 + th + 26), 12, fill=(18, 48, 61, 225))
    d.text((x0 + 26, y0 + 13 - box[1]), text, font=font, fill="white")
    img.save(path)


def cartoon_data() -> str:
    fam = json.loads((BUILD / "family_email.json").read_text())["body"].split("\n")
    data = {"logo": "video/build/logo.png", "note": "maria_note_photo.jpg", "printout": "video/build/printout.png",
            "email": "\n".join(["Dear Maria Rodriguez,", "Here is the summary of your visit today."] + fam[2:12]),
            "familyEmail": "\n".join(fam[:9]),
            "phone": ["Blood pressure medicine, called Amlodipine.", "Take 1 pill, 5 milligrams, each day."], "phoneAt": [2.8, 5.0]}
    return urllib.parse.quote(json.dumps(data))


def render_cartoon(page, scene: str, seconds: float, out: Path) -> None:
    frames = BUILD / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir()
    page.goto(f"file://{HERE / 'cartoon.html'}?scene={scene}&data={cartoon_data()}")
    page.wait_for_function("window.ready")
    page.wait_for_timeout(400)  # fonts and images
    for i in range(round(seconds * FPS)):
        page.evaluate(f"window.seek({i / FPS})")
        page.screenshot(path=str(frames / f"{i:05d}.jpg"), type="jpeg", quality=92)
    ffmpeg("-framerate", str(FPS), "-i", str(frames / "%05d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(out))


def cut_app(marks: dict, spec: str, seconds: float, out: Path, n: int) -> None:
    """'app:summary:approved+0.8|caption': the recording from one mark to another, fitted to `seconds`."""
    _, start, rest = spec.split(":", 2)
    end, _, text = rest.partition("|")
    t0 = marks[start]
    t1 = t0 + float(end[1:]) if end.startswith("+") else marks[end.split("+")[0]] + float(end.split("+")[1] if "+" in end else 0)
    speed = (t1 - t0) / seconds
    cap = BUILD / f"cap{n}.png"
    caption_png(text, cap)
    ffmpeg("-ss", f"{t0:.2f}", "-t", f"{t1 - t0:.2f}", "-i", str(BUILD / "app.webm"), "-i", str(cap), "-filter_complex",
           f"[0:v]setpts=PTS/{speed:.4f},fps={FPS},scale={W}:{H}[v];[v][1:v]overlay=0:0,trim=duration={seconds:.3f}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out))


def music(length: float, split: float) -> np.ndarray:
    """A soft pad under the narration: minor for 'today', major for 'with AI at 70'."""
    t = np.arange(int(length * RATE)) / RATE
    chords = [(split, [220.0, 261.63, 329.63]), (length, [261.63, 329.63, 392.0, 523.25])]  # A minor, then C major
    out, start = np.zeros_like(t), 0.0
    for end, notes in chords:
        m = (t >= start) & (t < end)
        env = np.clip(np.minimum((t[m] - start) / 1.5, (end - t[m]) / 1.5), 0, 1)
        out[m] = env * sum(np.sin(2 * np.pi * f * t[m]) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.2 * t[m] + f)) for f in notes) / len(notes)
        start = end
    return (out * 0.05).astype(np.float32)


def phone_eq(x: np.ndarray) -> np.ndarray:
    """A light telephone sound: cut the deep lows and the airy highs."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    spec *= ((f > 300) & (f < 3800)) * 1.0 + 0.15
    return np.fft.irfft(spec, len(x)).astype(np.float32)


def main() -> None:
    from playwright.sync_api import sync_playwright
    marks = json.loads((BUILD / "marks.json").read_text())
    lines = [voice(text, NARRATOR, 1.08) for _, text in STORY]
    phone = phone_eq(voice(PHONE_LINE, "af_heart", 0.95))
    segments, audio_at, t = [], [], 0.0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": W, "height": H})
        for n, ((spec, _), line) in enumerate(zip(STORY, lines)):
            seconds = len(line) / RATE + GAP + 0.15
            if spec == "phone":
                seconds += len(phone) / RATE + 0.2
            if spec == "end":
                seconds += 0.8
            pieces = [x.strip() for x in spec.split(" + ")]
            fixed = sum(float(x.split("@")[1]) for x in pieces if "@" in x)
            flexible = [x for x in pieces if "@" not in x]
            for k, piece in enumerate(pieces):
                length = float(piece.split("@")[1]) if "@" in piece else (seconds - fixed) / len(flexible)
                out = BUILD / f"seg{n:02d}_{k}.mp4"
                if piece.startswith("app:"):
                    cut_app(marks, piece, length, out, n * 10 + k)
                else:
                    render_cartoon(page, piece.split("@")[0], length, out)
                segments.append(out)
            audio_at.append((t + 0.15, line))
            if spec == "phone":
                audio_at.append((t + 0.15 + len(line) / RATE + 0.3, phone))
            print(f"{n + 1:2d}. {spec.split('|')[0][:40]:40s} {t:5.1f}s +{seconds:.1f}s")
            t += seconds
        browser.close()
    # video: the segments in order
    (BUILD / "list.txt").write_text("".join(f"file '{s}'\n" for s in segments))
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(BUILD / "list.txt"), "-c", "copy", str(BUILD / "video.mp4"))
    # audio: narration + phone voice over a soft pad
    track = music(t, split=sum(len(l) / RATE + GAP + 0.15 for l in lines[:3]))
    for start, clip in audio_at:
        i = int(start * RATE)
        track[i:i + len(clip)] += clip[: len(track) - i] * 0.9
    sf.write(BUILD / "audio.wav", np.clip(track, -1, 1), RATE)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(BUILD / "video.mp4"), "-i", str(BUILD / "audio.wav"), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
           "-shortest", str(OUT))
    print(f"{t:.1f} seconds -> {OUT}")


if __name__ == "__main__":
    main()
