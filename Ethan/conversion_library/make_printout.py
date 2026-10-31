"""Offline layer 2: turn a clinician note into a one-page, large-print printout. No API key needed.

Works on top of convert_note.py's word swaps, with fixed rules instead of a language model:
    1. Split the note by its headings and regroup them into patient sections, most important
       first (CLAUDE.md): what we found, what to do next, your medicines, when to come back,
       tests, why you came in, your hospital stay, your health history. The physical exam and
       review of systems are left off the printout (listed for the clinician, not dropped silently).
    2. Break each section into short bullet points: one sentence or list item per bullet.
    3. Apply plain phrasing rules: "the patient" -> "you", "denies fever" -> "no fever",
       "presents with" -> "came in with", "secondary to" -> "caused by", "nausea/vomiting" ->
       "nausea or vomiting", ">14" -> "more than 14".
    4. Measure the result with SMOG (target 5th-7th grade).
Nothing is added: every bullet comes from a line of the note. Flagged words stay highlighted on
screen for the clinician (not in print).

    python Ethan/conversion_library/make_printout.py note.txt [--name "Mary Smith"]

Writes output/<name>.printout.html (open it and print).
"""

import argparse
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import textstat
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from convert_note import MAX_GRADE, OUTPUT, TARGET_GRADE, Finding, convert, lay_dictionary, match_case

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
FLAG_ON, FLAG_OFF, WORD_ON, WORD_OFF = "\x01", "\x02", "\x03", "\x04"  # markers around flagged / explained words
MARKERS = FLAG_ON + FLAG_OFF + WORD_ON + WORD_OFF
INDEX = "\x05"  # "\x01plain\x0512\x02": marked word that came from finding 12
ONE_PAGE_WORDS = 380  # about what fits on one page at 16pt with headings

# Patient sections, in the order the printout shows them (CLAUDE.md: lead with what matters most).
SECTIONS = {
    "found": "What we found",
    "found_plan": "What we found and what to do next",
    "plan": "What to do next",
    "meds": "Your medicines",
    "followup": "When to come back or get help",
    "tests": "Your test results",
    "reason": "Why you came in",
    "course": "Your hospital stay",
    "history": "Your health history",
    "other": "Other notes from your visit",
}
LEFT_OFF = "left_off"  # exam findings: for the clinician, not the patient

HEADINGS = {
    "reason": ["presenting complaint", "pc", "chief complaint", "cc", "reason for visit", "reason for consultation",
               "reason for admission", "reason for referral", "history of present illness", "hpi",
               "history of presenting complaint", "hpc", "history", "hx", "subjective"],
    "found": ["impression", "imp", "clinical impression", "assessment", "diagnosis", "diagnoses", "discharge diagnosis",
              "discharge diagnoses", "admission diagnosis", "admission diagnoses", "admitting diagnosis",
              "final diagnosis", "final diagnoses", "principal diagnosis", "problem list", "postoperative diagnosis",
              "preoperative diagnosis"],
    "found_plan": ["assessment and plan", "a/p", "a&p", "impression and plan"],
    "plan": ["plan", "discharge plan", "treatment plan", "recommendations", "recommendation", "treatment",
             "management", "mx", "disposition", "instructions", "discharge instructions"],
    "meds": ["medications", "medication", "current medications", "discharge medications", "medications on discharge",
             "home medications", "meds", "dh", "drug history", "medicines"],
    "followup": ["follow up", "follow-up", "followup", "f/u", "return", "return visit"],
    "tests": ["laboratory data", "laboratory studies", "laboratory", "labs", "lab", "investigations", "studies",
              "diagnostic studies", "imaging", "radiology", "results", "data", "laboratory values", "tests"],
    "course": ["hospital course", "emergency department course", "course", "procedure", "procedures",
               "procedure performed", "discharge condition", "condition on discharge", "complications"],
    "history": ["past medical history", "pmh", "pmhx", "past surgical history", "psh", "surgical history",
                "social history", "sh", "family history", "fh", "allergies", "past history", "medical history",
                "immunizations", "habits"],
    LEFT_OFF: ["physical examination", "physical exam", "examination", "exam", "ex", "o/e", "on examination",
               "review of systems", "ros", "vital signs", "vitals", "objective", "general appearance", "keywords"],
}
NARRATIVE = {"hospital course", "course", "emergency department course"}  # no "Heading:" prefix needed
HEADING_KIND = {h: kind for kind, names in HEADINGS.items() for h in names}
INLINE_HEADING = re.compile(r"(?<=[.!?])[ \t]+(" + "|".join(sorted(map(re.escape, HEADING_KIND), key=len, reverse=True))
                            + r")[ \t]*:", re.I)
HEADING_LINE = re.compile(r"^[ \t]*([A-Za-z][A-Za-z /&()'-]{0,45}?)[ \t]*:[ \t]*(.*)$")

# Bullets from the plan that say when to come back or get help sooner.
FOLLOWUP_WORDS = re.compile(r"\b(review|follow[- ]?up|come back|return|appointment|recheck|see (?:you|your)|911|"
                            r"emergency|A&E|urgent(?:ly)?|earlier if|sooner if|worse|worsening|call)\b", re.I)
WHEN_TO_CALL = re.compile(r"\b(911|999|emergency|A&E|urgent(?:ly)?|earlier if|sooner if|worse|worsening|call)\b", re.I)

# Plain phrasing rules (model knowledge; listed for the clinician as "sentence changes").
# The "you" rules only apply outside the history section, where "his mother" etc. would be wrong.
SUBJECT_VERBS = (r"is|was|has|had|will|denies|denied|reports|reported|presents|presented|complains|complained|states|"
                 r"stated|says|said|lives|works|smokes|drinks|takes|feels|felt|went|came|underwent|returned|"
                 r"tolerated|did|does|should|can|could|would|may|might|must|needs|wants|continues|agrees|understands")
YOU_RULES = [
    (r"\b(?:the )?patient's\b", "your"),
    (r"\b(?:the )?patient\b", "you"),
    (rf"\b(?:he|she)\b(?= (?:{SUBJECT_VERBS})\b)", "you"),
    (r"\bhis\b", "your"),
    (r"\bhim\b", "you"),
    (r"\byou (?:denies|denied|denies having)\b", "you said you had no"),
    (r"\byou (?:reports|states)\b", "you report"),
    (r"\byou (?:reported|stated|says)\b", "you said"),
    (r"\byou (?:complains|complained) of\b", "you had"),
    (r"\byou (?:presents|presented) with\b", "you came in with"),
    (r"\byou is\b", "you are"), (r"\byou was\b", "you were"), (r"\byou has\b", "you have"),
    (r"\byou does\b", "you do"), (r"\byou underwent\b", "you had"),
    (r"\byou (live|work|smoke|drink|take|feel|need|want|continue|agree|understand)s\b", r"you \1"),
]
# After the phrase rules, which can leave "you also has" ("Patient also c/o ...")
AGREEMENT_RULES = [
    (r"\byou((?:\x05\d+)?[\x02\x04]?) ((?:also|still|now|only) )?([\x01\x03]?)has\b", r"you\1 \2\3have"),
    (r"\byou((?:\x05\d+)?[\x02\x04]?) ((?:also|still|now|only) )?([\x01\x03]?)is\b", r"you\1 \2\3are"),
    (r"\byou((?:\x05\d+)?[\x02\x04]?) ((?:also|still|now|only) )?([\x01\x03]?)was\b", r"you\1 \2\3were"),
    (r"\byou((?:\x05\d+)?[\x02\x04]?) ((?:also|still|now|only) )?([\x01\x03]?)(report|state)s\b", r"you\1 \2\3\4"),
]
NOT_A_NOUN = r"(?:to|and|or|with|at|in|on|for|from|about|today|again|home|back|up|that|this|\.|,|$)"
PHRASE_RULES = [
    (r"^(?:denies|denied)\b", "no"),
    (r"\b(?:denies|denied)\b", "no"),
    (r"\b(?:complains|complaining|complained) of\b", "has"),
    (r"\b(?:presents|presented|presenting) with\b", "came in with"),
    (r"\bsecondary to\b", "caused by"),
    (r"\bstatus post\b", "after"),
    (r"\bprior to\b", "before"),
    (r"\bin order to\b", "to"),
    (r"\bapproximately\b", "about"),
    (r"\bsubsequently\b", "then"),
    (r"\butiliz(e|es|ed)\b", lambda m: {"e": "use", "es": "uses", "ed": "used"}[m.group(1)]),
    (r"\bdiscontinu(e|ed)\b", lambda m: {"e": "stop", "ed": "stopped"}[m.group(1)]),
    (r"\binitiat(e|ed)\b", lambda m: {"e": "start", "ed": "started"}[m.group(1)]),
    (r"\bcommenc(e|ed)\b", lambda m: {"e": "start", "ed": "started"}[m.group(1)]),
    (r"\bobtain(ed)?\b", lambda m: "got" if m.group(1) else "get"),
    (r"\bdemonstrat(e|es|ed)\b", lambda m: {"e": "show", "es": "shows", "ed": "showed"}[m.group(1)]),
    (r"\bsufficient\b", "enough"),
    (r"\badditional\b", "more"),
    (r"\bnegative for\b", "no sign of"),
    (r"\bmedications\b", "medicines"),
    (r"\bmeds\b", "medicines"),
    (r"^elevate\b", "raise"),
    (r"^decrease\b", "lower"),
    (r"^review in\b", "check-up in"),
    (r"\b(?:delayed )?script\b", lambda m: "delayed prescription" if m.group(0).lower().startswith("delayed") else "prescription"),
    (r"\bx\s?(?=\d+ (?:days?|weeks?|months?|years?)\b)", "for "),
    (r"(?<=\d)\s?x\b", " times"),
    (r"\bmedication\b", "medicine"),
    (r"\bregimen\b", "treatment plan"),
    (r"/(day|week|month|hour|night)\b", r" a \1"),                   # 14 units/week
    (r"\b(\w+) and/or (\w+)", r"\1 or \2 or both"),
    (r"(?<=[A-Za-z0-9][\x02\x04])/(?=[\x01\x03]?[A-Za-z]{2})|(?<=[A-Za-z]{2}[\x02\x04])/(?=[\x01\x03]?[A-Za-z]{2})|(?<=[A-Za-z]{2})/(?=[\x01\x03]?[A-Za-z]{2})", " or "),  # nausea/vomiting
    (r"(?<=[\w\x02\x04)]) - (?=\S)", ": "),                          # "joint pain - mainly stiffness"
    (r"\s*>=?\s*(?=\d)", " more than "), (r"\s*<=?\s*(?=\d)", " less than "),
    (r"\s*≥\s*(?=\d)", " at least "), (r"\s*≤\s*(?=\d)", " at most "),
    (r"\s+&\s+", " and "),
]


@dataclass
class Section:
    key: str
    title: str
    items: list[str] = field(default_factory=list)  # with marker characters


@dataclass
class Printout:
    sections: list[Section]
    words: list[Finding]                 # kept terms explained in "Words to know"
    flags: list[Finding]                 # words the clinician should check
    left_off: list[tuple[str, str]]      # (heading, text) not shown to the patient
    changes: dict[str, int]              # sentence rule -> times used
    findings: list[Finding]
    readability: dict
    word_count: int
    missing: list[str] = field(default_factory=list)  # numbers / medicines in the note but not the printout


# ---------- 1. sections ----------

def normalize_heading(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower())


def split_sections(note: str) -> list[tuple[str, str, str]]:
    """[(kind, heading as written, body)]. Unknown "Neck: supple" lines stay in the current section."""
    note = note.replace("(Medical Transcription Sample Report)", "")
    note = INLINE_HEADING.sub(r"\n\1:", note)  # "...HTN. Plan: start..." -> heading on its own line
    parts, kind, heading, body = [], "other", "", []
    for line in note.splitlines():
        m = HEADING_LINE.match(line)
        k = HEADING_KIND.get(normalize_heading(m.group(1))) if m else None
        if k:
            if any(b.strip() for b in body):
                parts.append((kind, heading, "\n".join(body)))
            kind, heading, body = k, m.group(1).strip(), [m.group(2)]
        else:
            body.append(line)
    if any(b.strip() for b in body):
        parts.append((kind, heading, "\n".join(body)))
    return parts


# ---------- 2. plain text with markers ----------

def marked_text(text: str, offset: int = 0) -> tuple[str, list[Finding]]:
    """convert_note's word swaps, with every changed, explained or flagged word wrapped in markers
    that also carry the finding's number (offset + its index), so the original can be shown later."""
    c = convert(text)
    out, pos = [], 0
    for i, f in enumerate(c.findings):
        out.append(text[pos:f.start])
        word = match_case(text, f.start, f.text, f.replace_with, f.kind) if f.replace_with else f.text
        if f.flag:
            word = f"{FLAG_ON}{word}{INDEX}{offset + i}{FLAG_OFF}"
        elif f.explain or f.replace_with:
            word = f"{WORD_ON}{word}{INDEX}{offset + i}{WORD_OFF}"
        out.append(word)
        pos = f.end
    out.append(text[pos:])
    return "".join(out), c.findings


def strip_markers(text: str) -> str:
    return re.sub(f"{INDEX}\\d+|[{MARKERS}]", "", text)


# ---------- 3. short bullets with plain phrasing ----------

NOT_A_SENTENCE_END = re.compile(r"\b(?:Dr|Mr|Mrs|Ms|St|vs|approx|e\.g|i\.e|[A-Za-z])\.[\x02\x04]?$")


def to_items(text: str) -> list[str]:
    """One bullet per list item or sentence; long run-on sentences split where a new clause starts."""
    items = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:\d+[.)]|[-•*])\s+", "", line).strip(" \t,")
        if not strip_markers(line).strip(" .-"):
            continue
        pieces = []
        for piece in re.split(r"(?:(?<=[.!?])|(?<=[.!?][\x02\x04]))\s+(?=[\x01\x03]?[A-Z0-9])|;\s*", line):
            if pieces and NOT_A_SENTENCE_END.search(pieces[-1]):
                pieces[-1] += " " + piece  # "Dr. X", "b.i.d. Then"
            else:
                pieces.append(piece)
        for piece in pieces:
            # ", and he was admitted" -> new sentence (only before a new subject, so lists stay intact)
            items += re.split(r",? (?:and|but) (?=(?:he|she|you|the patient|we|they|it|this)\b)", piece)
    return [i for i in items if strip_markers(i).strip(" .")]


def apply_rules(item: str, rules: list, changes: dict) -> str:
    for pattern, replacement in rules:
        def swap(m, replacement=replacement, pattern=pattern):
            new = replacement(m) if callable(replacement) else m.expand(replacement)
            if new.lower() != m.group(0).lower():
                key = f"{strip_markers(m.group(0)).strip()} → {new.strip()}"
                changes[key] = changes.get(key, 0) + 1
            return new
        item = re.sub(pattern, swap, item, flags=re.I)
    return item


def tidy_item(item: str) -> str:
    item = re.sub(r"\s+([,.;:])", r"\1", re.sub(r"[ \t]+", " ", item)).strip(" ,;:-")
    item = re.sub(r",\s*$", "", item)
    first = re.search(r"[^\x01\x02\x03\x04\s(\"']", item)
    if first and first.group(0).isalpha():
        item = item[:first.start()] + item[first.start()].upper() + item[first.start() + 1:]
    if not re.search(r"[.!?:][\x02\x04]?$", item):
        item += "."
    return item


def simplify(text: str, kind: str, changes: dict) -> list[str]:
    if kind == "history":
        return [tidy_item(apply_rules(i, PHRASE_RULES, changes)) for i in to_items(text)]
    items = []
    for item in to_items(text):
        she = re.search(rf"\bshe\b(?= (?:{SUBJECT_VERBS})\b)", item, re.I)
        item = apply_rules(item, YOU_RULES + PHRASE_RULES + AGREEMENT_RULES, changes)
        if she:  # the patient is "she": "her blood sugar" -> "your blood sugar", "gave her" -> "gave you"
            item = apply_rules(item, [(rf"\bher\b(?! {NOT_A_NOUN})(?=\s+[A-Za-z\x01\x03])", "your"), (r"\bher\b", "you")], changes)
        items.append(tidy_item(item))
    return items


# ---------- 4. the printout ----------

def plain_heading(heading: str) -> str:
    if heading.isupper() and len(heading) > 4:
        heading = heading.capitalize()  # "PAST MEDICAL HISTORY" -> "Past medical history"; keep "PMH"
    text, _ = marked_text(heading + ":")  # the colon tells the converter it's a heading ("PMH:")
    text = strip_markers(text).strip().rstrip(":")
    return text[:1].upper() + text[1:]


def reading_level(items: list[str]) -> dict:
    text = "\n".join(strip_markers(i) for i in items)
    sentences = textstat.sentence_count(text)
    smog = round(textstat.smog_index(text), 1) if sentences >= 3 else None  # SMOG needs a few sentences
    return {"smog": smog, "flesch_kincaid": round(textstat.flesch_kincaid_grade(text), 1), "sentences": sentences}


def make_printout(note: str) -> Printout:
    sections = {k: Section(k, t) for k, t in SECTIONS.items()}
    left_off, findings, changes, shown_source = [], [], {}, []
    for kind, heading, body in split_sections(note):
        if kind == LEFT_OFF:
            left_off.append((heading, body.strip()))
            continue
        text, found = marked_text(body, offset=len(findings))
        findings += found
        items = simplify(text, kind, changes)
        if kind in ("history", "course") and heading and items and normalize_heading(heading) not in NARRATIVE:
            # several sub-headings share these sections: "Allergies: none", "Discharge condition: guarded"
            first = items[0]
            i = len(first) - len(first.lstrip(MARKERS))
            if first[i:i + 1].isupper() and not first[i + 1:i + 2].isupper():  # "Widowed" -> "widowed", keep "COPD"
                first = first[:i] + first[i].lower() + first[i + 1:]
            items[0] = f"{plain_heading(heading)}: {first}"
        shown_source.append(re.sub(r"(?m)^\s*\d+[.)]\s", "", strip_markers(text)))  # minus list numbers
        if kind in ("plan", "found_plan"):  # "Review in 1 week, or earlier if worse" -> when to come back
            # "Start furosemide 20mg BD, f/u 1/52" -> the medicine stays in the plan, the follow-up moves
            items = [tidy_item(part) for i in items for part in
                     re.split(r",\s*(?=[\x01\x03]?(?:follow[- ]?up|check-up|review|return|come back)\b)", i, flags=re.I)]
            sections["followup"].items += [i for i in items if FOLLOWUP_WORDS.search(strip_markers(i))]
            items = [i for i in items if not FOLLOWUP_WORDS.search(strip_markers(i))]
        sections[kind].items += items
    shown = [s for s in sections.values() if s.items]
    all_items = [i for s in shown for i in s.items]
    shown_text = " ".join(strip_markers(i).lower() for i in all_items)
    words, flags, seen = [], [], set()
    for f in findings:
        key = (f.text.lower(), f.flag)
        if key in seen:
            continue
        seen.add(key)
        if f.explain and not f.replace_with:
            words.append(f)
        if f.flag:
            flags.append(f)
    readability = {"original": reading_level(note.splitlines()), "printout": reading_level(all_items)}
    # Safety check: the sentence rules must not lose a number or a medicine name.
    printed = " ".join(strip_markers(i) for i in all_items)
    source = " ".join(shown_source)
    missing = sorted(set(re.findall(r"\d+(?:\.\d+)?", source)) - set(re.findall(r"\d+(?:\.\d+)?", printed)), key=float)
    missing += sorted({f.text for f in findings if f.kind == "medication" and f.text.lower() not in printed.lower()})
    return Printout(shown, words, flags, left_off, changes, findings, readability, len(shown_text.split()), missing)


# ---------- HTML ----------

def marked_html(text: str) -> Markup:
    html = str(escape(text))
    for marker, tag in ((FLAG_ON, '<mark class="flag">'), (FLAG_OFF, "</mark>"),
                        (WORD_ON, '<span class="word">'), (WORD_OFF, "</span>")):
        html = html.replace(marker, tag)
    return Markup(html)


def jinja() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape())
    env.filters["marked"] = marked_html
    return env


def template_context(p: Printout, name: str = "", visit_date: str = "", clinician: str = "", phone: str = "") -> dict:
    return {"p": p, "name": name, "visit_date": visit_date or date.today().strftime("%B %-d, %Y"),
            "clinician": clinician, "phone": phone, "target": TARGET_GRADE, "max_grade": MAX_GRADE,
            "one_page_words": ONE_PAGE_WORDS, "when_to_call": WHEN_TO_CALL,
            "sources": lay_dictionary()[2], "strip": strip_markers}


def render_page(p: Printout, **details) -> str:
    """Standalone printable page (the CLI's output)."""
    return jinja().get_template("standalone.html").render(**template_context(p, **details))


def main() -> None:
    parser = argparse.ArgumentParser(description="Make a large-print plain-language printout from a clinician note.")
    parser.add_argument("notes", type=Path, nargs="+")
    parser.add_argument("--name", default="", help="patient name for the header")
    args = parser.parse_args()
    OUTPUT.mkdir(exist_ok=True)
    for path in args.notes:
        p = make_printout(path.read_text())
        out = OUTPUT / f"{path.stem}.printout.html"
        out.write_text(render_page(p, name=args.name))
        r = p.readability
        print(f"{path.name}: SMOG {r['original']['smog']} -> {r['printout']['smog']} (target {TARGET_GRADE}-{MAX_GRADE}), "
              f"{p.word_count} words, {len(p.flags)} to check  ->  {out}")


if __name__ == "__main__":
    main()
