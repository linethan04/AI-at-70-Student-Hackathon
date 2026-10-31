"""The AI at 70 presentation: 4 slides in the app's colors and logo, with pictures from the demo video.

    python scripts/presentation/render_images.py       # once: logo + cartoon stills -> build/
    python scripts/presentation/make_presentation.py   # -> outputs/presentation/AI_at_70.pptx

Slide 1 is the title (project, authors). Slides 2-4 answer the three project questions, with the answers
from the README ("Why AI at 70").
"""

from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUILD = HERE / "build"
SCREENSHOTS = ROOT / "outputs" / "interface" / "screenshots"
OUT = ROOT / "outputs" / "presentation" / "AI_at_70.pptx"

AUTHORS = ["Ethan", "Jason", "Max", "Tanner"]  # edit to full names as needed
STATEMENT = "In our project, a person always stays in charge."

# the app's colors (outputs/interface/index.html)
BLUE, TEAL, GREEN, AMBER = "1C5D84", "38B6A9", "1D7A55", "F2B33D"
INK, MUTED, MINT, WHITE, CORAL = "12303D", "4F6877", "EEF6F4", "FFFFFF", "EE7B62"
HEAD, BODY = "Calibri", "Calibri"


def rgb(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_)


def shadow(shape, blur=18, dist=4, alpha=22) -> None:
    """A soft drop shadow (the app's cards)."""
    sp_pr = shape._element.spPr
    effects = etree.SubElement(sp_pr, qn("a:effectLst"))
    sh = etree.SubElement(effects, qn("a:outerShdw"), blurRad=str(Pt(blur)), dist=str(Pt(dist)), dir="5400000",
                          algn="t", rotWithShape="0")
    clr = etree.SubElement(sh, qn("a:srgbClr"), val=INK)
    etree.SubElement(clr, qn("a:alpha"), val=str(alpha * 1000))


def rounded(shape, radius=0.06) -> None:
    """Round a picture's corners (radius as a share of its shorter side)."""
    geom = shape._element.spPr.find(qn("a:prstGeom"))
    geom.set("prst", "roundRect")
    av = geom.find(qn("a:avLst"))
    if av is None:
        av = etree.SubElement(geom, qn("a:avLst"))
    etree.SubElement(av, qn("a:gd"), name="adj", fmla=f"val {int(radius * 100000)}")


def box(slide, x, y, w, h, fill, radius=None, line=None, name=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                                   Inches(x), Inches(y), Inches(w), Inches(h))
    if radius:
        shape.adjustments[0] = radius
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(1.25)
    else:
        shape.line.fill.background()
    if name:
        shape.name = name
    return shape


def text(slide, x, y, w, h, runs, size=16, color=INK, bold=False, font=BODY, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, italic=False, space_after=0, name=None):
    """runs: a string, or a list of paragraphs; each paragraph a string or a list of (text, {options})."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paragraphs = [runs] if isinstance(runs, str) else runs
    for i, para in enumerate(paragraphs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        for chunk, opts in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = chunk
            f = r.font
            f.name = opts.get("font", font)
            f.size = Pt(opts.get("size", size))
            f.bold = opts.get("bold", bold)
            f.italic = opts.get("italic", italic)
            f.color.rgb = rgb(opts.get("color", color))
    if name:
        tb.name = name
    return tb


def picture(slide, path, x, y, w, h, radius=0.05, crop=(0, 0, 0, 0), name=None):
    """A picture filling a w x h box without stretching: `crop` (left, top, right, bottom shares) is widened
    on the long side as needed so the visible part has the box's proportions."""
    iw, ih = Image.open(path).size
    left, top, right, bottom = crop
    fw, fh = 1 - left - right, 1 - top - bottom
    if (iw * fw) / (ih * fh) > w / h:   # too wide: trim the sides
        extra = (fw - (w / h) * ih * fh / iw) / 2
        left, right = left + extra, right + extra
    else:                               # too tall: trim top and bottom
        extra = (fh - iw * fw / ((w / h) * ih)) / 2
        top, bottom = top + extra, bottom + extra
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
    pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = left, top, right, bottom
    if radius:
        rounded(pic, radius)
    shadow(pic)
    if name:
        pic.name = name
    return pic


def question(slide, n: int, q: str) -> None:
    """The numbered question at the top of slides 2-4 (same place on each)."""
    c = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.6), Inches(0.55), Inches(0.62), Inches(0.62))
    c.fill.solid()
    c.fill.fore_color.rgb = rgb(TEAL)
    c.line.fill.background()
    c.name = "Question number"
    tf = c.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = str(n)
    r.font.size, r.font.bold, r.font.name = Pt(22), True, HEAD
    r.font.color.rgb = rgb(WHITE)
    text(slide, 1.45, 0.5, 11.3, 0.72, q, size=30, bold=True, color=INK, font=HEAD, anchor=MSO_ANCHOR.MIDDLE,
         name="Question")


def footer(slide, logo) -> None:
    slide.shapes.add_picture(str(logo), Inches(0.6), Inches(6.88), height=Inches(0.32)).name = "Logo"
    text(slide, 1.08, 6.9, 4, 0.3, [[("AI at 70", {"bold": True, "color": BLUE}), ("   Health for all ages", {"color": MUTED})]],
         size=11, anchor=MSO_ANCHOR.MIDDLE, name="Footer")


def background(slide, hex_: str) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = rgb(hex_)


def label(slide, x, y, words, fill=BLUE) -> None:
    """A small pill naming a picture."""
    w = 0.16 + 0.095 * len(words)
    pill = box(slide, x, y, w, 0.36, fill, radius=0.5, name=f"Label: {words}")
    tf = pill.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = words
    r.font.size, r.font.bold, r.font.name = Pt(12), True, BODY
    r.font.color.rgb = rgb(WHITE)


def point_rows(slide, x, y, w, rows, gap=0.95) -> None:
    """Numbered rows: a small teal circle, a bold lead, and a line under it."""
    for i, (lead, line) in enumerate(rows):
        yy = y + i * gap
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(yy + 0.04), Inches(0.36), Inches(0.36))
        dot.fill.solid()
        dot.fill.fore_color.rgb = rgb(MINT)
        dot.line.fill.background()
        dot.name = f"Point {i + 1} marker"
        tf = dot.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = "✓"
        r.font.size, r.font.bold = Pt(14), True
        r.font.color.rgb = rgb(GREEN)
        text(slide, x + 0.55, yy, w - 0.55, gap - 0.1, [[(lead, {"bold": True, "color": INK})], [(line, {"color": MUTED})]],
             size=15, space_after=2, name=f"Point {i + 1}")


def main() -> None:
    logo = BUILD / "logo.png"
    pres = Presentation()
    pres.slide_width, pres.slide_height = Inches(13.333), Inches(7.5)
    blank = pres.slide_layouts[6]
    pres.core_properties.title = "AI at 70"
    pres.core_properties.author = ", ".join(AUTHORS)

    # 1. Title
    s = pres.slides.add_slide(blank)
    background(s, BLUE)
    tile = box(s, 0.75, 0.9, 1.5, 1.5, WHITE, radius=0.22, name="Logo tile")
    shadow(tile, alpha=30)
    s.shapes.add_picture(str(logo), Inches(0.92), Inches(1.15), width=Inches(1.16)).name = "Logo"
    text(s, 0.75, 2.75, 6.4, 1.1, "AI at 70", size=66, bold=True, color=WHITE, font=HEAD, name="Title")
    text(s, 0.75, 3.85, 6.0, 0.9, "Visit summaries older patients and their families can understand",
         size=22, color="DCEFF6", name="Subtitle")
    text(s, 0.75, 4.95, 6.0, 0.5, STATEMENT, size=17, italic=True, color=AMBER, name="Project statement")
    text(s, 0.75, 6.05, 6.0, 0.4, [[("By  ", {"color": "B7D7E6"}), ("   ·   ".join(AUTHORS), {"bold": True, "color": WHITE})]],
         size=18, name="Authors")
    picture(s, BUILD / "together.png", 6.85, 2.05, w=5.9, h=3.32, radius=0.06,
            name="Maria and Sofia at home with every output")
    s.notes_slide.notes_text_frame.text = (
        "AI at 70 turns a primary-care visit into a short, plain-language summary for older patients and the family "
        "members they choose: a printout, an email and a phone call, in five languages. " + STATEMENT)

    # 2. Who and why
    s = pres.slides.add_slide(blank)
    background(s, WHITE)
    question(s, 1, "Who are we building this for, and why do they need it?")
    text(s, 0.6, 1.65, 5.9, 1.5, "Elderly patients who have difficulty retaining medical information and guidance.",
         size=26, bold=True, color=BLUE, font=HEAD, name="Answer")
    point_rows(s, 0.6, 3.35, 5.9, [
        ("Visits move fast", "And they're full of medical terms: \"bilateral edema\", \"titrate\", \"BID\"."),
        ("Details fade by the time they're home", "Medicine changes and warning signs are the easiest to lose."),
        ("Families are left guessing", "The people helping at home often weren't in the room."),
    ])
    picture(s, BUILD / "jargon.png", 6.95, 1.6, w=5.75, h=2.6, crop=(0.0, 0.04, 0.0, 0.18), name="At the visit")
    label(s, 7.15, 1.78, "At the visit")
    picture(s, BUILD / "confused.png", 6.95, 4.4, w=5.75, h=2.6, crop=(0.0, 0.05, 0.0, 0.17), name="At home")
    label(s, 7.15, 4.58, "At home", fill=CORAL)
    footer(s, logo)
    s.notes_slide.notes_text_frame.text = (
        "Our users are elderly patients who have difficulty retaining medical information and guidance, and the "
        "family members who help them. A visit is fast and full of jargon; by evening, the patient and family are "
        "unsure what changed.")

    # 3. What could go wrong
    s = pres.slides.add_slide(blank)
    background(s, MINT)
    question(s, 2, "What could go wrong, and what would we do about it?")
    picture(s, SCREENSHOTS / "5_review.png", 0.6, 1.95, w=6.4, h=3.58, crop=(0.05, 0.25, 0.05, 0.0),
            name="The physician's review screen")
    label(s, 0.6, 1.45, "The physician's review screen", fill=GREEN)
    text(s, 7.45, 1.65, 5.3, 1.5, "AI can make mistakes, so physicians always verify the final output.",
         size=26, bold=True, color=BLUE, font=HEAD, name="Answer")
    point_rows(s, 7.45, 3.35, 5.3, [
        ("Every item on a checklist", "Medicines, changes and changed words are ticked one by one (or Select all)."),
        ("Nothing goes out until they approve", "No printout, email or phone call before the physician signs off."),
        ("Doubts are flagged, not guessed", "Anything unclear, missing or translated is marked for review."),
    ])
    footer(s, logo)
    s.notes_slide.notes_text_frame.text = (
        "AI can make mistakes, so the physician always verifies the final output. The review screen puts the "
        "patient's page next to a checklist; nothing can be printed, emailed or called until every item is ticked and "
        "the physician approves. Editing or changing the language removes the approval.")

    # 4. Helping, not deciding
    s = pres.slides.add_slide(blank)
    background(s, WHITE)
    question(s, 3, "How does this help people rather than decide for them?")
    text(s, 0.6, 1.65, 6.0, 1.0, "There is no change in medical guidance, only simplification.",
         size=26, bold=True, color=BLUE, font=HEAD, name="Answer")
    rows = [("Decr. amlodipine to 5 mg daily", "Blood pressure medicine (Amlodipine): Take 1 pill (5 mg) each day."),
            ("Metformin 1000 mg BID with meals", "Blood sugar medicine (Metformin): Take 1 pill (1000 mg) twice a day, with meals."),
            ("Elevate legs when sitting", "Raise your legs when you sit.")]
    text(s, 0.6, 2.85, 2.5, 0.3, "THE PHYSICIAN'S NOTE", size=11, bold=True, color=MUTED, name="Note heading")
    text(s, 3.45, 2.85, 3.2, 0.3, "WHAT THE PATIENT READS", size=11, bold=True, color=GREEN, name="Summary heading")
    for i, (note, plain) in enumerate(rows):
        y = 3.2 + i * 1.08
        card = box(s, 0.6, y, 2.6, 0.9, MINT, radius=0.12, name=f"Note line {i + 1}")
        tf = card.text_frame
        tf.margin_left = tf.margin_right = Inches(0.15)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.word_wrap = True
        tf.paragraphs[0].alignment = PP_ALIGN.LEFT
        r = tf.paragraphs[0].add_run()
        r.text = note
        r.font.size, r.font.name = Pt(13), "Courier New"
        r.font.color.rgb = rgb(INK)
        text(s, 3.2, y, 0.25, 0.9, "→", size=20, bold=True, color=TEAL, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE, name=f"Arrow {i + 1}")
        card = box(s, 3.45, y, 3.15, 0.9, WHITE, radius=0.12, line="B9DCD5", name=f"Plain line {i + 1}")
        tf = card.text_frame
        tf.margin_left = tf.margin_right = Inches(0.15)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.word_wrap = True
        tf.paragraphs[0].alignment = PP_ALIGN.LEFT
        r = tf.paragraphs[0].add_run()
        r.text = plain
        r.font.size, r.font.name, r.font.bold = Pt(13), BODY, True
        r.font.color.rgb = rgb(INK)
    picture(s, BUILD / "recommend.png", 7.0, 1.7, w=5.75, h=2.85, crop=(0.0, 0.0, 0.0, 0.12),
            name="Dr. Lee explains what goes in and what comes out")
    callout = box(s, 7.0, 4.95, 5.75, 1.1, BLUE, radius=0.14, name="Statement")
    shadow(callout)
    tf = callout.text_frame
    tf.margin_left = tf.margin_right = Inches(0.3)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.word_wrap = True
    p = tf.paragraphs[0]
    for chunk, color, bold in [("A person always stays in charge. ", AMBER, True),
                               ("The physician decides; the patient and family understand.", WHITE, False)]:
        r = p.add_run()
        r.text = chunk
        r.font.size, r.font.name, r.font.bold = Pt(16), BODY, bold
        r.font.color.rgb = rgb(color)
    footer(s, logo)
    s.notes_slide.notes_text_frame.text = (
        "AI at 70 changes no medical guidance; it only simplifies it. Every diagnosis, medicine, dose and instruction "
        "comes from the physician's own note and keeps its meaning; the tool rewrites it in everyday words and adds no "
        "advice of its own. We reinforce patients' control over their own health by breaking down what the visit "
        "actually means and what to actually do.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pres.save(OUT)
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
