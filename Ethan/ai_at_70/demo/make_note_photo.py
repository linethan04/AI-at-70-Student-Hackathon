"""A 'photo' of Dr. Lee's handwritten-style note for Maria Rodriguez's visit (made-up), to test photo upload.

    python Ethan/ai_at_70/demo/make_note_photo.py      # writes demo/maria_note_photo.jpg
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
NOTE = """Maria Rodriguez  78F   Oct 31
CC: Follow-up of type 2 diabetes and hypertension.
Bilateral leg swelling x 2 weeks.
Meds: Metformin 1000 mg daily, amlodipine 10 mg daily,
atorvastatin 40 mg qhs, acetaminophen 500 mg PRN knee pain.
Allergies: NKDA
A: 1. Type 2 diabetes, not at goal.
2. Hypertension, not at goal.
3. Bilateral leg edema, likely secondary to amlodipine.
P: 1. Decrease amlodipine to 5 mg daily.
2. Increase metformin to 1000 mg BID with meals.
3. Check BMP and urine microalbumin today.
4. Elevate legs when sitting.
5. Follow up in 4 weeks with Dr. Lee.
6. Go to the ER or call 911 if chest pain or trouble breathing.
                                        - Dr. Lee"""


def main() -> None:
    font = ImageFont.truetype("/System/Library/Fonts/Noteworthy.ttc", 34)
    w, h, line = 1500, 1240, 64
    page = Image.new("RGB", (w, h), "#fffdf4")
    d = ImageDraw.Draw(page)
    for y in range(150, h, line):  # ruled notepad lines
        d.line([(60, y + 2), (w - 60, y + 2)], fill="#c9dcf0", width=2)
    d.line([(120, 0), (120, h)], fill="#f0b4b4", width=3)
    d.text((150, 40), "Riverside Primary Care  ·  Progress note", font=ImageFont.truetype("/System/Library/Fonts/Noteworthy.ttc", 30), fill="#7a8794")
    for i, text in enumerate(NOTE.splitlines()):
        d.text((150, 108 + i * line), text, font=font, fill="#1b2a6b")
    photo = Image.new("RGB", (w + 140, h + 140), "#6b5a48")  # the desk under the page
    photo.paste(page.rotate(-1.2, expand=False, fillcolor="#6b5a48"), (70, 70))
    photo = photo.filter(ImageFilter.GaussianBlur(0.6))
    photo.save(HERE / "maria_note_photo.jpg", quality=88)
    print("Wrote", HERE / "maria_note_photo.jpg")


if __name__ == "__main__":
    main()
