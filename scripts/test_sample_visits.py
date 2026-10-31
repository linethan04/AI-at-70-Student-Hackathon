"""Run every made-up visit in outputs/interface/sample_visits/ through the real AI at 70 page, start to finish, and save
what the patient and family would get.

For each visit the browser:
  1. uploads the check-in (checkin.json), which sets the language and who may get the summary;
  2. uploads the conversation audio (conversation.m4a) and waits for the transcript, or presses Skip if there is none;
  3. uploads the typed note (note.txt) and writes the summary;
  4. ticks every checklist item and approves, in the patient's language and again in English;
  5. saves the printout (PDF), every email the consent allows, the phone script and the phone call audio.

Results go to each visit's results/ folder, with a summary in sample_visits/RESULTS.md.

    python scripts/run_ai_at_70.py                    # in another terminal
    python scripts/test_sample_visits.py              # all visits
    python scripts/test_sample_visits.py 2_wei_chen_mandarin --audio   # one visit; --audio re-voices its conversation

Synthetic voices reading fictional visits (macOS `say`, Chrome): no real patient data (CLAUDE.md, Privacy).
"""

import argparse
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "outputs" / "interface" / "sample_visits"
URL = "http://127.0.0.1:5070"
SAMPLE_RATE = 16_000
CLINICIAN_VOICE = "Daniel"
PATIENT_VOICES = {"1_maria_rodriguez_english": "Samantha", "2_wei_chen_mandarin": "Grandpa (English (US))",
                  "3_joao_silva_portuguese": "Eddy (English (US))", "4_fatima_haddad_arabic": "Grandma (English (US))"}
SPOKEN = [(r"(\d+) mg\b", r"\1 milligrams")]
NAMES = {"en": "English", "zh": "Mandarin", "es": "Spanish", "pt": "Portuguese", "ar": "Arabic"}


def to_m4a(audio: np.ndarray, rate: int, path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        sf.write(wav, audio, rate, subtype="PCM_16")
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(wav), str(path)], check=True)


def make_audio(visit: Path) -> None:
    """conversation.txt -> conversation.m4a, two synthetic voices."""
    pause = np.zeros(int(0.6 * SAMPLE_RATE), dtype=np.float32)
    pieces = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, line in enumerate((visit / "conversation.txt").read_text().splitlines()):
            m = re.match(r"\[[\d:]+\] (\w+): (.+)", line)
            if not m:
                continue
            text = m.group(2)
            for pattern, new in SPOKEN:
                text = re.sub(pattern, new, text)
            wav = Path(tmp) / f"{i}.wav"
            voice = CLINICIAN_VOICE if m.group(1) == "Clinician" else PATIENT_VOICES.get(visit.name, "Samantha")
            subprocess.run(["say", "-v", voice, "-o", str(wav), f"--data-format=LEI16@{SAMPLE_RATE}", text], check=True)
            audio, _ = sf.read(wav, dtype="float32")
            pieces += [audio, pause]
    to_m4a(np.concatenate(pieces), SAMPLE_RATE, visit / "conversation.m4a")
    print("  wrote", (visit / "conversation.m4a").relative_to(ROOT))


def phone_audio(lines: list[str], lang: str, path: Path) -> None:
    """The phone call as the page plays it: each line in the neural voice for the language (/api/speak)."""
    pieces, rate = [], 24_000
    for line in lines:
        req = urllib.request.Request(URL + "/api/speak", json.dumps({"text": line, "lang": lang}).encode(),
                                     {"content-type": "application/json"})
        audio, rate = sf.read(io.BytesIO(urllib.request.urlopen(req, timeout=300).read()), dtype="float32")
        pieces += [audio, np.zeros(int(0.35 * rate), dtype=np.float32)]
    to_m4a(np.concatenate(pieces), rate, path)


def save_outputs(page, out: Path, lang: str, report: dict) -> None:
    """Everything the approved summary can become, in the language on screen."""
    page.emulate_media(media="print")
    page.pdf(path=str(out / f"printout_{lang}.pdf"), format="Letter", print_background=True)
    page.emulate_media(media="screen")
    page.evaluate("document.getElementById('toast').hidden = true")
    page.screenshot(path=str(out / f"review_{lang}.png"), full_page=True)
    people = page.evaluate("people()")
    report["outputs"][lang] = []
    for p in people:
        o = page.evaluate("async (k) => await loadOutputs(k)", p["key"])
        who = "patient" if p["key"] == "patient" else "family"
        approved = page.evaluate("`${approval.by} · ${approval.date}`")
        mail = (f"To: {p['email'] or '(no email address with consent: not sent)'}\nSubject: {o['email']['subject']}\n\n"
                f"{o['email']['body']}\n\n{o['labels']['reviewed']}: {approved}\n")
        (out / f"email_{who}_{lang}.txt").write_text(mail)
        (out / f"phone_{who}_{lang}.txt").write_text("\n".join(o["phone"]) + "\n")
        report["outputs"][lang] += [f"email_{who}_{lang}.txt", f"phone_{who}_{lang}.txt"]
    # the call goes to family when the patient agreed to share, else to the patient (the page's default)
    o = page.evaluate("async (k) => await loadOutputs(k)", "family" if len(people) > 1 else "patient")
    phone_audio(o["phone"], lang, out / f"phone_call_{lang}.m4a")
    report["outputs"][lang] += [f"printout_{lang}.pdf", f"review_{lang}.png", f"phone_call_{lang}.m4a"]
    report["translation_flags"][lang] = len(o.get("flags", []))


def approve(page) -> None:
    page.click("#selectAll")
    page.click("#approveBtn")  # the confirm dialog is accepted by the handler
    page.wait_for_function("document.body.classList.contains('approved')", timeout=30000)


def run_visit(browser, visit: Path) -> dict:
    q = json.loads((visit / "checkin.json").read_text())
    lang = q.get("summary_language") or q["language"]
    out = visit / "results"
    out.mkdir(exist_ok=True)
    report = {"visit": visit.name, "patient": q["answers"]["patient_full_name"], "language": NAMES[lang],
              "errors": [], "outputs": {}, "translation_flags": {}}
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.on("dialog", lambda d: d.accept())
    page.on("pageerror", lambda e: report["errors"].append(str(e)))
    page.on("console", lambda m: m.type == "error" and report["errors"].append(m.text))
    t0 = time.time()

    page.goto(URL)
    page.click("text=Start a visit")
    page.set_input_files("#qFile", str(visit / "checkin.json"))
    page.wait_for_selector("#s3:not([hidden])")

    audio = visit / "conversation.m4a"
    if audio.exists():
        page.set_input_files("#aFile", str(audio))
        page.wait_for_function("/^(✓|Couldn't)/.test(document.getElementById('aStatus').textContent)", timeout=600000)
        status = page.text_content("#aStatus")
        if not status.startswith("✓"):
            report["errors"].append(status)
        (out / "transcript.txt").write_text(page.input_value("#convo") + "\n")
        report["conversation"] = "audio, transcribed"
        page.click("#next3")
    else:
        report["conversation"] = "skipped"
        page.click("#skip3")

    page.set_input_files("#nFile", str(visit / "note.txt"))
    page.wait_for_function("document.getElementById('nStatus').textContent.startsWith('✓')", timeout=60000)
    page.fill("#clinName", "Dr. Lee")
    page.fill("#office", "555-0100")
    page.click("#go")
    page.wait_for_selector("#review:not([hidden]), #error:not([hidden])", timeout=300000)
    if page.is_visible("#error"):
        report["errors"].append(page.text_content("#errorText"))
        page.close()
        return report
    page.wait_for_function(f"document.getElementById('sheet').lang === '{lang}'", timeout=300000)
    res = page.evaluate("res")
    report.update(ready=res["ready"], reader=res["reader"], failed_checks=[f"{c['name']}: {c['detail']}" for c in res["checks"] if not c["ok"]],
                  inputs_disagree=res["cross_checks"], checklist_items=len(res["checklist"]))

    approve(page)
    save_outputs(page, out, lang, report)
    if lang != "en":  # the clinician's own language too
        page.click("#langs button:has-text('English')")
        page.wait_for_function("document.getElementById('sheet').lang === 'en' && !document.querySelector('#langs button').disabled",
                               timeout=300000)
        approve(page)
        save_outputs(page, out, "en", report)
    report["seconds"] = round(time.time() - t0)
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    page.close()
    return report


def write_summary(reports: list[dict]) -> None:
    rows = ["| Visit | Language | Conversation | Checks | Inputs disagree | Translation flags | Errors |", "|---|---|---|---|---|---|---|"]
    for r in reports:
        checks = "all pass" if r.get("ready") else "; ".join(r.get("failed_checks", [])) or "not run"
        flags = ", ".join(f"{NAMES[k]}: {v}" for k, v in r["translation_flags"].items() if k != "en") or "none (English)"
        rows.append(f"| [{r['patient']}]({r['visit']}/) | {r['language']} | {r.get('conversation', '')} | {checks} | "
                    f"{'<br>'.join(r.get('inputs_disagree', [])) or 'none'} | {flags} | {'<br>'.join(r['errors']) or 'none'} |")
    (SAMPLES / "RESULTS.md").write_text(
        "# Test results\n\nWritten by `python scripts/test_sample_visits.py` (offline summary and translation, no API keys). "
        "Each visit's files are in its `results/` folder.\n\n" + "\n".join(rows) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("visits", nargs="*", help="folder names in sample_visits/ (default: all)")
    parser.add_argument("--audio", action="store_true", help="re-voice the conversations even if conversation.m4a exists")
    args = parser.parse_args()
    try:
        urllib.request.urlopen(URL + "/api/config", timeout=5)
    except OSError:
        sys.exit("Start the app first: python scripts/run_ai_at_70.py")
    visits = [SAMPLES / v for v in args.visits] or sorted(p for p in SAMPLES.iterdir() if p.is_dir())
    for v in visits:
        if (v / "conversation.txt").exists() and (args.audio or not (v / "conversation.m4a").exists()):
            make_audio(v)
    reports = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for v in visits:
            print(v.name, "...", flush=True)
            r = run_visit(browser, v)
            print("  ready" if r.get("ready") else "  NOT READY", r.get("failed_checks", ""), "errors:", r["errors"] or "none",
                  f"({r.get('seconds', '?')} s)")
            reports.append(r)
        browser.close()
    if not args.visits:
        write_summary(reports)
        print("Wrote", (SAMPLES / "RESULTS.md").relative_to(ROOT))


if __name__ == "__main__":
    main()
