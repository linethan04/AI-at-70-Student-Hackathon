"""Pictures for the presentation, taken from the same sources as the demo video so everything matches:
the app's logo, and stills of the video's cartoon scenes (scripts/video/cartoon.html) without captions.

    python scripts/presentation/render_images.py     # -> scripts/presentation/build/ (git-ignored)

Needs the video's capture files (scripts/video/build/, from scripts/video/capture_app.py) for the printouts and
the family email shown in some scenes.
"""

import base64
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VIDEO = ROOT / "scripts" / "video"
BUILD = HERE / "build"
sys.path.insert(0, str(VIDEO))
from make_video import cartoon_data  # noqa: E402

# (scene in cartoon.html, moment in seconds, output name)
STILLS = [("maria", 3.0, "maria"), ("doctor", 3.6, "jargon"), ("home", 3.0, "confused"),
          ("recommend", 6.5, "recommend"), ("spanish", 3.0, "spanish"), ("together", 3.0, "together")]


def main() -> None:
    BUILD.mkdir(exist_ok=True)
    page_html = (ROOT / "outputs" / "interface" / "index.html").read_text()
    logo = re.search(r'const LOGO = "data:image/png;base64,([^"]+)"', page_html).group(1)
    (BUILD / "logo.png").write_bytes(base64.b64decode(logo))
    data = cartoon_data()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=2)
        for scene, t, name in STILLS:
            page.goto(f"file://{VIDEO / 'cartoon.html'}?scene={scene}&data={data}")
            page.wait_for_function("window.ready")
            page.add_style_tag(content=".cap,.chip{display:none!important}")
            page.evaluate(f"window.seek({t})")
            page.screenshot(path=str(BUILD / f"{name}.png"))
            print("Wrote", BUILD / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main()
