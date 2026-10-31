"""Record the real AI at 70 page for the demo video: Maria Rodriguez's visit, start to finish.

Needs the server running (python scripts/run_ai_at_70.py) and the demo audio (scripts/video/make_visit_audio.py).
Chrome's fake microphone plays maria_visit.wav into the Record button, so the recording step is real.
Writes build/app.webm (git-ignored) plus marks.json (when each moment happens), pictures of the printout (English and
Spanish), and the email and phone text the video shows.

    python scripts/video/capture_app.py
"""

import base64
import json
import shutil
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
URL = "http://127.0.0.1:5070"
SIZE = {"width": 1280, "height": 720}


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    marks: dict[str, float] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={HERE / 'maria_visit.wav'}"])
        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(BUILD / "raw"), record_video_size=SIZE)
        ctx.grant_permissions(["microphone"])
        page = ctx.new_page()
        t0 = time.time()
        mark = lambda name: marks.__setitem__(name, round(time.time() - t0, 2))
        page.on("dialog", lambda d: d.accept())

        # landing
        page.goto(URL)
        page.wait_for_timeout(1200)
        mark("landing")
        logo = page.evaluate("LOGO").split(",", 1)[1]  # the app's logo, for the cartoon scenes
        (BUILD / "logo.png").write_bytes(base64.b64decode(logo))
        page.wait_for_timeout(2500)

        # the patient's check-in at the front desk: a few simple taps on the questionnaire
        page.goto(URL + "/questionnaire")
        page.wait_for_timeout(600)
        mark("checkin")
        page.click("#patient_full_name")
        page.keyboard.type("Maria Rodriguez", delay=60)
        page.fill("#patient_date_of_birth", "1948-03-14")
        for step in (lambda: page.select_option("#visit_type", "Follow-up visit"),
                     lambda: page.check('input[name=barriers][value="Remembering medications or appointments"]'),
                     lambda: page.select_option("#learning_style", "Very simple, short instructions"),
                     lambda: page.check('input[name=caregiver_share_consent][value="Yes"]')):
            step()
            page.wait_for_timeout(700)
        mark("checkin_done")

        # the clinician's page: load her check-in
        page.goto(URL)
        page.click("text=Start a visit")
        page.set_input_files("#qFile", str(HERE / "maria_checkin.json"))
        page.wait_for_selector("#s3:not([hidden])")
        page.wait_for_timeout(1000)
        mark("record")
        page.click("#recBtn")
        page.wait_for_timeout(3500)
        mark("recording")
        page.wait_for_timeout(33500)
        page.click("#recBtn")
        page.wait_for_function("document.getElementById('aStatus').textContent.startsWith('✓')", timeout=600000)
        page.wait_for_timeout(300)
        mark("transcribed")
        page.wait_for_timeout(2500)

        # Dr. Lee's typed note, uploaded as a file
        page.click("#next3")
        page.wait_for_timeout(800)
        mark("note")
        page.wait_for_timeout(700)
        page.set_input_files("#nFile", str(HERE / "maria_note.txt"))
        page.wait_for_function("document.getElementById('nStatus').textContent.startsWith('✓')", timeout=120000)
        mark("note_read")
        page.wait_for_timeout(1500)
        page.click("#clinName")
        page.keyboard.type("Dr. Lee", delay=60)
        page.click("#office")
        page.keyboard.type("555-0100", delay=60)
        page.wait_for_timeout(800)

        # the summary, checked and approved
        page.click("#go")
        page.wait_for_selector("#review:not([hidden])", timeout=180000)
        page.wait_for_timeout(400)
        mark("summary")
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, 260)
        page.wait_for_timeout(1200)
        page.click("#selectAll")
        page.wait_for_timeout(700)
        page.locator("#approveBtn").scroll_into_view_if_needed()
        page.click("#approveBtn")
        page.wait_for_timeout(500)
        mark("approved")
        page.locator("#send").scroll_into_view_if_needed()
        page.wait_for_timeout(1500)

        # email
        page.click("[data-tab=email]")
        page.select_option("#emailTo", "patient")
        page.wait_for_timeout(600)
        page.locator("#pane-email").scroll_into_view_if_needed()
        mark("email")
        page.wait_for_timeout(3500)

        # phone call
        page.click("[data-tab=phone]")
        page.locator("#pane-phone").scroll_into_view_if_needed()
        mark("phone")
        page.wait_for_timeout(2500)

        # what the video shows outside the page: the printout, and the text family members get
        page.locator("#sheet").screenshot(path=str(BUILD / "printout.png"))
        family_email = page.evaluate("""async () => (await (await fetch('/api/outputs', {method: 'POST', headers: {'content-type': 'application/json'},
            body: JSON.stringify({doc, lang: 'en', patient: 'Maria Rodriguez', recipient: 'Sofia Rodriguez', relationship: 'Daughter',
                                  clinician: 'Dr. Lee', office_phone: '555-0100'})})).json()).email""")
        phone_lines = page.evaluate("[...document.querySelectorAll('#script li')].map(li => li.textContent)")

        # the same summary in Spanish (the language buttons above the patient's page)
        page.locator("#langs").scroll_into_view_if_needed()
        page.mouse.wheel(0, -120)
        page.wait_for_timeout(800)
        mark("spanish")
        page.click("#langs button:has-text('Español')")
        page.wait_for_function("document.getElementById('sheet').lang === 'es' && !document.querySelector('#langs button').disabled", timeout=180000)
        page.wait_for_timeout(500)
        mark("spanish_done")
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(2500)
        page.locator("#sheet").screenshot(path=str(BUILD / "printout_es.png"))
        ctx.close()
        video = Path(page.video.path())
        browser.close()
    shutil.move(video, BUILD / "app.webm")
    (BUILD / "marks.json").write_text(json.dumps(marks, indent=1))
    (BUILD / "family_email.json").write_text(json.dumps(family_email, indent=1))
    (BUILD / "phone_lines.json").write_text(json.dumps(phone_lines, indent=1))
    print(json.dumps(marks))


if __name__ == "__main__":
    urllib.request.urlopen(URL + "/api/config", timeout=5)  # fail early if the server isn't running
    main()
