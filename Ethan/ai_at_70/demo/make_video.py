"""Build the ~60-second AI at 70 demo video: Maria Rodriguez's visit, today and with AI at 70.

    python Ethan/ai_at_70/test_kit/make_test_audio.py   # once: demo/maria_visit.wav
    python Ethan/ai_at_70/app.py &                      # the real page, for the screen recording
    python Ethan/ai_at_70/demo/capture_app.py           # records the page (demo/video/build/app.webm)
    python Ethan/ai_at_70/demo/make_video.py            # -> demo/video/ai_at_70_demo.mp4

Built like a short ad: hook (meet Maria), problem (a visit full of jargon, a confused home), the turn ("the same
visit, with AI at 70"), how it works (simple check-in, Dr. Lee's typed notes, AI at 70 in and out, the recording as a helpful extra, uploading
the typed notes, approval, translation as an option, the printout),
the payoff at home (email and phone call for her daughter Sofia), and the line that answers the problem
("nobody's guessing"). About 175 spoken words (~75 s): one continuous voiceover with real pauses, scenes crossfade.

Cartoon scenes come from cartoon.html (modern flat style), rendered frame by frame; the app scenes are cut from the
screen recording of the real page and shown in a browser window. Narration and the phone-call voice are Kokoro (the
same neural voices the app uses). All people and notes are made up.
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

HERE = Path(__file__).resolve().parent
BUILD = HERE / "video" / "build"
OUT = HERE / "video" / "ai_at_70_demo.mp4"
sys.path.insert(0, str(HERE.parents[1] / "conversion_library"))
from voices import kokoro  # noqa: E402

FF = imageio_ffmpeg.get_ffmpeg_exe()
FPS, W, H, RATE = 30, 1280, 720, 24000
LEAD = 0.25          # a beat of picture before each line starts
XF = 0.35            # crossfade between pieces
SCREEN = (142, 42, 996, 560)  # where the screen recording sits on its backdrop (x, y, w, h)
NARRATOR, NARRATOR_SPEED = "af_bella", 1.06        # Kokoro's most natural voices: af_heart (the app's phone voice), af_bella
PHONE_VOICE = "af_heart"
PHONE_LINES = ["Blood pressure medicine, called Amlodipine.", "Take 1 pill, 5 milligrams, each day."]

# (scene, narration, pause after the line). Narration is written to be heard: "AI" (said "ay-eye"; "A I" comes out
# "uh-eye"), "Doctor Lee" (not "Dr. Lee", read with a stop). A line ending in a comma runs on into the next scene
# with a short pause. A scene is a cartoon scene name, "name@seconds", or "app:<from mark>:<to mark or +seconds>|caption"
# cut from the screen recording; " + " joins pieces that share one line.
STORY = [
    # the problem: today
    ("maria", "This is Maria. She's seventy-eight, with diabetes and high blood pressure.", 0.5),
    ("doctor", "Her check-ups move fast. Bilateral edema. Titrate. B M P.", 0.6),
    ("home", "By the time she's home, it's all a blur. And her daughter, Sofia, is left guessing.", 0.7),
    # the turn
    ("turn", "Now, the same visit, with AI at 70.", 0.5),
    # how it works
    ("arrive@1.6 + app:checkin:checkin_done|Maria checks in with a few simple questions", "Maria checks in with a few simple questions.", 0.7),
    ("visit", "Doctor Lee types up notes, in the usual shorthand.", 0.6),
    ("recommend", "Then Doctor Lee turns to AI at 70, which takes those notes and turns them into a summary in plain, everyday language.", 0.9),
    ("app:record:recording+2.5|Recording the conversation adds helpful detail + app:transcribed:+2.0|Recording the conversation adds helpful detail",
     "Recording the conversation can add helpful detail, and it's written out right away.", 0.6),
    ("app:note:note_read+1.2|Doctor Lee uploads the typed notes", "Then Doctor Lee uploads the typed notes.", 0.5),
    ("app:summary:approved+0.8|Doctor Lee reads it over and approves it", "In seconds, there's a summary. Doctor Lee reads it over, and approves it.", 0.5),
    ("app:spanish:spanish_done+1.2|Spanish, Mandarin, Portuguese or Arabic",
     "For patients who prefer another language, it can be translated into Spanish, Mandarin, Portuguese, or Arabic.", 0.5),
    ("spanish", "Here it is in Spanish, still in plain, everyday words.", 0.7),
    ("handoff", "Maria leaves with her summary, right in her hand.", 0.7),
    # the payoff: at home
    ("email", "That evening, Sofia gets it by email,", 0.15),
    ("phone", "and a friendly call goes over what matters most.", 0.4),   # + the phone voice
    ("together", "This time, nobody's guessing.", 0.6),
    ("end", "AI at 70. Quick. Reliable. Understandable.", 1.0),
]


def ffmpeg(*args: str) -> None:
    subprocess.run([FF, "-loglevel", "error", "-y", *args], check=True)


def voice(text: str, name: str, speed: float = 1.0) -> np.ndarray:
    samples, rate = kokoro().create(text, voice=name, speed=speed, lang="en-us")
    assert rate == RATE
    return np.asarray(samples, dtype=np.float32)


def caption_png(page, text: str, path: Path) -> None:
    """The same caption the cartoon scenes use, on a transparent page, for the app scenes."""
    page.goto(f"file://{HERE / 'cartoon.html'}?scene=caption&text={urllib.parse.quote(text)}")
    page.wait_for_function("window.ready")
    page.screenshot(path=str(path), omit_background=True)


def cartoon_data(phone_at=(3.0, 5.6)) -> str:
    fam = json.loads((BUILD / "family_email.json").read_text())["body"].split("\n")
    data = {"logo": "video/build/logo.png", "printout": "video/build/printout.png", "printoutEs": "video/build/printout_es.png",
            "familyEmail": "\n".join(fam[:15]), "phone": PHONE_LINES, "phoneAt": list(phone_at)}
    return urllib.parse.quote(json.dumps(data))


def render_cartoon(page, scene: str, seconds: float, out: Path, data: str) -> None:
    frames = BUILD / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir()
    page.goto(f"file://{HERE / 'cartoon.html'}?scene={scene}&data={data}")
    page.wait_for_function("window.ready")
    page.wait_for_timeout(300)
    for i in range(round(seconds * FPS)):
        page.evaluate(f"window.seek({i / FPS})")
        page.screenshot(path=str(frames / f"{i:05d}.jpg"), type="jpeg", quality=92)
    ffmpeg("-framerate", str(FPS), "-i", str(frames / "%05d.jpg"), "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p",
           "-c:v", "libx264", "-r", str(FPS), str(out))


def cut_app(page, marks: dict, spec: str, seconds: float, out: Path, n: int) -> None:
    """'app:summary:approved+0.8|caption': the recording from one mark to another, fitted to `seconds`."""
    _, start, rest = spec.split(":", 2)
    end, _, text = rest.partition("|")
    t0 = marks[start]
    t1 = t0 + float(end[1:]) if end.startswith("+") else marks[end.split("+")[0]] + float(end.split("+")[1] if "+" in end else 0)
    speed = (t1 - t0) / seconds
    cap = BUILD / f"cap{n}.png"
    caption_png(page, text, cap)
    x, y, w, h = SCREEN
    ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", str(BUILD / "frame.png"), "-ss", f"{t0:.2f}", "-t", f"{t1 - t0:.2f}",
           "-i", str(BUILD / "app.webm"), "-i", str(cap), "-filter_complex",
           f"[1:v]setpts=PTS/{speed:.4f},fps={FPS},scale={w}:{h},tpad=stop_mode=clone:stop_duration=2[v];"
           f"[0:v][v]overlay={x}:{y}[s];[s][2:v]overlay=0:0,trim=duration={seconds:.3f},format=yuv420p", "-r", str(FPS),
           "-c:v", "libx264", "-an", str(out))


def music(length: float, split: float) -> np.ndarray:
    """A soft pad under the narration: a low, unsettled chord for 'today', a warm bright one from the turn on."""
    t = np.arange(int(length * RATE)) / RATE
    chords = [(split, [220.0, 261.63, 329.63]), (length, [261.63, 329.63, 392.0, 523.25])]  # A minor, then C major
    out, start = np.zeros_like(t), 0.0
    for end, notes in chords:
        m = (t >= start) & (t < end)
        env = np.clip(np.minimum((t[m] - start) / 1.2, (end - t[m]) / 1.2), 0, 1)
        out[m] += env * sum(np.sin(2 * np.pi * f * t[m]) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.2 * t[m] + f)) for f in notes) / len(notes)
        start = end - 0.6  # the chords overlap a little instead of stopping dead
    return (out * 0.055).astype(np.float32)


def phone_eq(x: np.ndarray) -> np.ndarray:
    """A light telephone sound: cut the deep lows and the airy highs."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    spec *= ((f > 300) & (f < 3800)) * 1.0 + 0.15
    return np.fft.irfft(spec, len(x)).astype(np.float32)


def main() -> None:
    from playwright.sync_api import sync_playwright
    marks = json.loads((BUILD / "marks.json").read_text())
    lines = [voice(text, NARRATOR, NARRATOR_SPEED) for _, text, _ in STORY]
    halves = [phone_eq(voice(t, PHONE_VOICE, 0.95)) for t in PHONE_LINES]
    breath = np.zeros(int(0.3 * RATE), dtype=np.float32)
    phone = np.concatenate([halves[0], breath, halves[1]])

    # the timeline: each scene is a beat of picture, its line, then a pause
    plan, t = [], 0.0
    for n, ((spec, _, pause), line) in enumerate(zip(STORY, lines)):
        seconds = LEAD + len(line) / RATE + pause
        if spec == "phone":
            phone_start = LEAD + len(line) / RATE + 0.35
            seconds = phone_start + len(phone) / RATE + pause
            phone_at = (phone_start, phone_start + (len(halves[0]) + len(breath)) / RATE)
        plan.append((n, spec, t, seconds))
        t += seconds
    total = t

    pieces = []  # (spec piece, start on the timeline, length)
    for n, spec, start, seconds in plan:
        parts = [x.strip() for x in spec.split(" + ")]
        fixed = sum(float(x.split("@")[1]) for x in parts if "@" in x)
        flexible = [x for x in parts if "@" not in x]
        for part in parts:
            length = float(part.split("@")[1]) if "@" in part else (seconds - fixed) / len(flexible)
            pieces.append((n, part, start, length))
            start += length

    data = cartoon_data(phone_at)
    segments = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": W, "height": H})
        page.goto(f"file://{HERE / 'cartoon.html'}?scene=frame&data={data}")  # the backdrop for the app scenes
        page.wait_for_function("window.ready")
        page.screenshot(path=str(BUILD / "frame.png"))
        for k, (n, part, start, length) in enumerate(pieces):
            render_len = length + (XF if k < len(pieces) - 1 else 0)  # runs on under the next crossfade
            out = BUILD / f"seg{k:02d}.mp4"
            if part.startswith("app:"):
                cut_app(page, marks, part, render_len, out, k)
            else:
                render_cartoon(page, part.split("@")[0], render_len, out, data)
            segments.append((out, start))
            print(f"{n + 1:2d}. {part.split('|')[0][:44]:44s} {start:5.1f}s +{length:.1f}s")
        browser.close()

    # video: crossfade each piece into the next, exactly at its start on the timeline
    inputs = sum((["-i", str(s)] for s, _ in segments), [])
    chain, prev = [], "[0:v]"
    for k, (_, start) in enumerate(segments[1:], 1):
        label = f"[v{k}]"
        chain.append(f"{prev}[{k}:v]xfade=transition=fade:duration={XF}:offset={start - XF:.3f}{label}")
        prev = label
    ffmpeg(*inputs, "-filter_complex", ";".join(chain), "-map", prev, "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-r", str(FPS), str(BUILD / "video.mp4"))

    # audio: the voiceover and the phone voice over the pad, faded in and out
    split = plan[3][2]  # the turn
    track = music(total, split)
    fade = int(1.2 * RATE)                       # the music fades; the voice is never faded or cut
    track[:int(0.3 * RATE)] *= np.linspace(0, 1, int(0.3 * RATE))
    track[-fade:] *= np.linspace(1, 0, fade) ** 2
    for (n, spec, start, _), line in zip(plan, lines):
        i = int((start + LEAD) * RATE)
        track[i:i + len(line)] += line[: len(track) - i] * 0.95
        if spec == "phone":
            j = int((start + phone_at[0]) * RATE)
            track[j:j + len(phone)] += phone[: len(track) - j] * 0.85
    sf.write(BUILD / "audio.wav", np.clip(track, -1, 1), RATE)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(BUILD / "video.mp4"), "-i", str(BUILD / "audio.wav"), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
           "-shortest", str(OUT))
    print(f"{total:.1f} seconds -> {OUT}")


if __name__ == "__main__":
    main()
