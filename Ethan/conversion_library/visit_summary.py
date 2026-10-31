"""The patient visit summary: short, in plain words, for an older adult after a primary care visit.

Three parts:
    Your visit       2-4 sentences: why you came in and what the doctor found
    Your medicines   each medicine exactly as named in the note (what it does, in plain words, from its
                     MedlinePlus drug page), with a clear instruction under it: "Take 1000 mg twice a day,
                     with meals." taken from the note
    What to do next  bullets: changes, tests, follow-up visits, and when to get help sooner (bold)
Medical terms stay highlighted: on screen the original is struck through next to its plain meaning
(medical = red -> green, hard everyday words = purple -> blue); the printed copy shows the plain words.

Readability is judged by a model of the reader (reader.py), not a formula: a reader at the target
grade (CLAUDE.md: 5th-7th) should know at least 98% of the words, and sentences stay short. The
summary is rewritten until it passes; each try fixes what the reader wouldn't follow (split long
sentences, swap words the reader wouldn't know for ones they would, shorter medicine descriptions,
fewer bullets). The best try is always shown. SMOG is still reported for reference.
    offline (default): rules + dictionaries + the reader's word list
    --claude: Claude writes it and is told what the reader wouldn't follow, until it passes

Other checks: every medicine in the note is listed, every number is in the summary or in the
"left out" list the clinician sees, and no medical jargon is left in the patient's text.

    python Ethan/conversion_library/visit_summary.py <note.txt> [--name "Mary Smith"] [--grade 7] [--claude]
"""

import argparse
import re
import sys
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import textstat
from wordfreq import zipf_frequency

from convert_note import DOSING_WORDS, OUTPUT, analyze, convert, drug_names, lay_dictionary, medical_vocab
from drug_info import UK_NAMES, lookup
from make_printout import (FLAG_OFF, FLAG_ON, INDEX, WHEN_TO_CALL, WORD_OFF, WORD_ON, jinja, make_printout,
                           marked_text, strip_markers, split_sections, tidy_item)
from reader import DOCTOR_TALK, READER_GRADE, WORD, assess, describe, doctor_talk, gloss, is_known

HERE = Path(__file__).resolve().parent
KINDS = ("med", "word", "keep", "drug")
EVERYDAY_ZIPF = 3.5   # single words at least this common aren't counted as leftover jargon ("hypertension" is 3.4)
MAX_TRIES = 6
MARKUP = re.compile(r"\[\[([^\]|]*)\|([^\]|]*)\|([^\]|]*)\|([^\]|]*)\]\]")
NAME_SUFFIXES = ("acid", "sodium", "potassium", "succinate", "tartrate", "hydrochloride", "hcl", "inhaler", "cream", "patch",
                 "spray", "drops", "gel", "xl", "sr", "er", "la", "cr")
SALTS = {"succinate", "tartrate", "hydrochloride", "hcl", "sodium", "potassium", "calcium", "magnesium", "iron", "zinc",
         "chloride", "carbonate", "citrate", "sulfate", "oxygen", "alcohol", "nicotine", "caffeine", "glucose"}  # only a
# medicine when the note gives it a dose ("calcium 600 mg"), not in "low sodium diet" or "metoprolol succinate"
UNDECIDED = re.compile(r"\b(?:discuss|consider|may|might|could|possible|possibly|think about)\b[^.\n]*$", re.I)
FORM_VERBS = [(r"inhaler|puff|spray|nebuli", "Use"), (r"cream|ointment|gel|emollient|patch|lotion", "Put on"),
              (r"drops?\b", "Use")]
MED_LINE_START = re.compile(r"^(?:start|stop|increase|decrease|reduce|lower|raise|restart|continue|keep taking|take|"
                            r"delayed|prescribed|advised|told|switch|change|hold)\b", re.I)
VERBS = ("treat", "prevent", "relieve", "reduce", "lower", "control", "decrease", "help", "slow", "improve",
         "eliminate", "stop", "increase", "manage", "ease")
USE_STOPWORDS = {"certain", "types", "type", "people", "adults", "children", "mild", "moderate", "severe", "other",
                 "conditions", "condition", "symptoms", "risk", "such", "with", "that", "from", "have", "been",
                 "caused", "used", "also", "your", "body", "some", "medications", "medication", "treatment"}
CLASSES = [  # MedlinePlus "is in a class of medications called ..." -> what a patient would call it
    (r"diuretic|water pill", "Water pill"), (r"antibiotic", "Infection medicine"), (r"anticoagulant", "Blood thinner"),
    (r"statin|HMG-CoA", "Cholesterol medicine"), (r"proton[- ]pump inhibitor", "Stomach medicine"),
    (r"antidepressant|serotonin|SSRI", "Mood medicine"), (r"bisphosphonate", "Bone medicine"),
    (r"corticosteroid", "Steroid medicine"), (r"NSAID|nonsteroidal anti-inflammatory", "Pain medicine"),
    (r"cholinesterase inhibitor", "Memory medicine"), (r"bronchodilator", "Breathing medicine"),
    (r"analgesic", "Pain medicine"), (r"antiviral", "Virus medicine"),
]
CATEGORIES = [  # the earliest match in the text wins: the reason in the note, then the use that fits the note, then MedlinePlus
    (r"rate control|heart rate|rhythm", "Heart rate medicine"),
    (r"blood clots?|anticoagul|blood thinner|stroke prevention|prevent(?:ing)? (?:a )?stroke", "Blood thinner"),
    (r"high blood pressure|hypertension", "Blood pressure medicine"),
    (r"diabetes|blood sugar|glucose", "Blood sugar medicine"),
    (r"cholesterol", "Cholesterol medicine"),
    (r"bacteria", "Infection medicine"),
    (r"virus|viral", "Virus medicine"),
    (r"air passages|asthma|wheez|copd|breath|lung", "Breathing medicine"),
    (r"osteoporosis|bones?\b", "Bone medicine"),
    (r"thyroid", "Thyroid medicine"),
    (r"stomach acid|heartburn|ulcer|reflux|gerd", "Stomach medicine"),
    (r"depress|anxiety|mood", "Mood medicine"),
    (r"sleep|insomnia", "Sleep medicine"),
    (r"allerg|hay fever|itch|hives", "Allergy medicine"),
    (r"seizure|epilep", "Seizure medicine"),
    (r"swelling and redness|corticosteroid|steroid", "Steroid medicine"),
    (r"pain|fever|arthritis|aches", "Pain medicine"),
    (r"diuretic|water pill|edema|excess fluid", "Water pill"),
    (r"prostat", "Prostate medicine"),
    (r"alzheimer|dementia|memory", "Memory medicine"),
    (r"heart|angina", "Heart medicine"),
    (r"vitamin|supplement|calcium", "Supplement"),
    (r"nausea|vomit", "Nausea medicine"),
    (r"constipation|bowel", "Bowel medicine"),
]
STATUS = re.compile(r"\b(not at goal|not (?:well )?controlled|uncontrolled|poorly controlled|above (?:goal|target)|"
                    r"not at target|elevated|still high|remains high)\b", re.I)
MEASURES = [(r"diabetes|blood sugar|glucose|a1c", "blood sugar"), (r"high blood pressure|hypertension|blood pressure", "blood pressure"),
            (r"cholesterol|lipid", "cholesterol"), (r"weight|obesity", "weight")]
CAUSED_BY = re.compile(r"^(.*?),?\s*(?:most |very )?(?:likely |probably |possibly |may be )?(?:secondary to|caused by|due to|"
                       r"related to|from)\s+([A-Za-z-]+)\.?$", re.I)
ORAL_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s?(mg|mcg|micrograms?|g)\b", re.I)
MODEL = "model"
LWV = "Living Word Vocabulary"

# Everyday words a reader may not know -> words they would (model knowledge, flagged for the clinician).
EASIER = {
    "improving": "getting better", "worsening": "getting worse", "medication": "medicine", "medications": "medicines",
    "regularly": "on a set schedule", "immediately": "right away", "additional": "more", "approximately": "about",
    "physician": "doctor", "evaluation": "check", "evaluate": "check", "appointment": "visit", "currently": "now",
    "difficulty": "trouble", "generally": "mostly", "possibly": "maybe", "management": "care", "monitoring": "watching",
    "recurring": "coming back", "episodes": "bouts", "assessment": "check", "alongside": "with", "settling": "going away",
    "conservative": "simple", "productive": "wet", "persistent": "lasting", "onset": "start", "fluids": "drinks",
    "viral": "virus", "intermittent": "on and off", "moderate": "medium", "severe": "very bad", "acute": "sudden",
    "chronic": "long-lasting", "bilateral": "on both sides", "recheck": "check again", "consider": "think about",
    "symptoms": "signs", "symptom": "sign", "analgesia": "pain relief", "prophylactic": "to prevent it",
    "supportive": "helpful", "urgently": "right away", "thereafter": "after that", "infective": "infection",
    "elevated": "high", "increased": "more", "decreased": "less", "nightly": "each night", "renal": "kidney",
    "cardiac": "heart", "pulmonary": "lung", "hepatic": "liver", "oral": "by mouth", "monitor": "check",
    "indicated": "needed", "recommended": "suggested", "advised": "told", "mild": "a little", "mildly": "a little",
    "resolved": "gone", "seek": "get", "annual": "yearly", "significant": "large", "significantly": "a lot",
    "abdominal": "belly", "therapy": "treatment", "respiratory": "breathing", "complaint": "problem", "episode": "bout",
    "noted": "seen", "intake": "amount",
}
def split_list(m: re.Match) -> str:
    """'Call 911 if you have A, B, C, or D (x, y, z).' (too long) -> 'Call 911 if you have A, B or C. Also call 911 for D (x, y, z).'"""
    head, items = m.group(1), m.group(2).rstrip(". ")
    parts = [p for p in re.split(r",\s*(?:or\s+|and\s+)?(?![^()]*\))", items) if p]
    if len((head + items).split()) <= 18 or len(parts) < 3:
        return m.group(0)
    first, rest = parts[:-1] if len(parts) <= 4 else parts[:3], parts[-1:] if len(parts) <= 4 else parts[3:]
    verb = head[: -len(" if you have ")]
    join = lambda xs: xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " or " + xs[-1]
    return f"{head}{join(first)}. Also {verb[0].lower() + verb[1:]} for {join(rest)}."


def follow_up(m: re.Match) -> str:
    """'follow-up with Dr. Patel, heart doctor, in 2 weeks' -> 'Go to your follow-up visit in 2 weeks with Dr. Patel
    (heart doctor)'"""
    who, dept, when = m.group(1), m.group(2), m.group(3)
    return f"Go to your follow-up visit {when} with {who}" + (f" ({dept.strip()})" if dept else "")


# Note shorthand in the next-steps bullets -> how a person would say it (model knowledge).
STEP_RULES = [
    (r"^safety[- ]?net(?:ting)?(?: advice)?:\s*", ""),
    (r"^lifestyle (?:a partial change|modifications?|changes?):\s*", ""),
    (r"^(?:follow[- ]?up|come back|return|review) with ((?-i:Dr)\.? [A-Za-z-]+)(?:,\s*([^,]+?))?,? (in \d+ \w+)(?=\.|$)", follow_up),
    (r"^come back (\d+ (?:days?|weeks?|months?|years?))\b,?", r"Go to your next visit in \1."),
    (r"^(Go to your next visit in [^.]+\.) ?sooner\b", r"\1 Come back sooner"),
    (r"^(?:advised|told|recommended|suggested)(?: to)?\s+", ""),
    (r"^to\s+", ""),
    (r"^can\s+", "You can "),
    (r"^(if .+?),?\s+to\s+(contact|see|call|speak|have|book|return|come|go|ring|attend|seek)\b", r"\1, \2"),
    (r"(?-i:\bdr\b)\.?", "doctor"),
    (r"\basap\b", "as soon as you can"),
    (r"^(?:review|check-up|check up|follow[- ]?up|f/u)(?: in| after)\b", "Come back in"),
    (r"\bor earlier if\b", "or sooner if"),
    (r"\bif (?:getting worse|worsening) (?:symptoms|signs)\b", "if you feel worse"),
    (r"\bif (?:symptoms|signs) (?:are )?not (?:getting better|improving)\b", "if you are not getting better"),
    (r"\bif not better\b", "if you are not better"),
    (r"\bnot settling\b", "not going away"),
    (r"\bfurther assessment\b", "another check"),
    (r"\b(?:if )?recurring episodes of (?:the )?same\b", "if it keeps coming back"),
    (r"\bnew onset\b", "new"),
    (r"\b(?:to )?recheck (.+?)(\.|$)", r"to check \1 again\2"),
    (r"^conservative (?:treatment|management|care|mx)\s*[:\-–]?\s*", "Care at home: "),
    (r"\bas needed (?!for\b)(?=[a-z])", "as needed for "),
    (r"\binfective (?:exacerbation|flare-up) of ([^.,]+)", r"a flare-up of \1 caused by an infection"),
    (r",? not at goal\b", ". It is not yet at your goal"),
    (r"^(Come back in [^,]+?),? (?:or )?sooner if (.+)$", r"\1. Come back sooner if \2"),
    (r"^Or sooner if\b", "Come back sooner if"),
    (r"\bif worse\b", "if you feel worse"),
    (r"\bif you feel worse \(([^)]+)\)", r"if you feel worse, such as \1"),
    (r"^((?:call|ring) (?:999|911|111)|go to [^.]+?) if (?!you\b)", r"\1 if you have "),
    (r"\bthinks you have (?!a |an |the )(viral|bacterial|new|possible)\b", r"thinks you have a \1"),
    (r"\bor possible\b", "or maybe a"),
    (r"(\d+ ?(?:mg|mcg|ml)) day (\d+),? then\b", r"\1 on day \2, then"),
    (r"\b(contact|see|call|with|ask|tell) (doctor|family doctor|nurse)\b", r"\1 your \2"),
    # follow-up: say when and with whom, not why
    (r"^(?:come back|follow[- ]?up|return|review)( (?:in|after) \d+ (?:days?|weeks?|months?))"
     r"(?: (?:with|to see) ((?-i:Dr)\.? [A-Za-z-]+|(?:your )?[a-z ]+?doctor))?(?:,\s*((?-i:[A-Z][A-Za-z ]+?)),?)?"
     r"(?:,? (?:to (?:check|recheck|review|discuss|see how|assess|reassess|monitor|look at|go over|follow up on)\b|for (?:a |an |your )?"
     r"[\w ]*?(?:check|review)\b)[^.]*)?"
     r"(?=\.|$)",
     lambda m: f"Go to your follow-up visit{m.group(1)}" + (f" with {m.group(2)}" if m.group(2) else "")
               + (f" ({m.group(3)})" if m.group(3) else "")),
    (r"\b(?:bilateral|two-sided) (leg|arm|ankle|foot|feet)s? swelling\b", lambda m: f"swelling in both {m.group(1).replace('foot', 'feet')}s"
     if m.group(1) != "feet" else "swelling in both feet"),
    (r"^(raise|rest|elevate|ice|move|stretch|lift) (legs?|feet|foot|arms?|knees?|back)\b", r"\1 your \2"),
    (r"\bwhen sitting\b", "when you sit"),
    (r"\bdaily\b", "each day"),
    (r"\bif (\w+) not going away\b", r"if the \1 does not go away"),
    (r"\bdoes not go away or worse\b", "does not go away, gets worse,"),
    (r"\bor new symptoms\b", "or you have new symptoms"),
    # when to get help: who to call, then "if you have ..."
    (r"^(911|999|111|988)\b", r"Call \1"),
    (r"^((?:call|ring) (?:911|999|988|111)) for\b", r"\1 if you have"),
    (r"^if (?!you\b)(.+?), ((?:call|ring|go|get|come|return)\b.+?)\.?$", lambda m: f"{m.group(2)[0].upper() + m.group(2)[1:]} if "
     + ("" if re.match(r"(?:you|your|there|it|the|symptoms?|not|we)\b", m.group(1), re.I) else "you have ") + f"{m.group(1)}."),
    (r"^(?:return|come back)(?: or call)? if\b", "Call us or come back if"),
    (r"^call if\b", "Call us if"),
    (r"\bif gain\b", "if you gain"),
    (r"\bif not improving\b", "if you are not better"),
    (r"^((?:call|ring)(?: us| \d{3})?(?: or come back| or go to the emergency room)?|come back|go to the emergency room(?: or call \d{3})?|"
     r"get [^,]*?|Call us or come back) if (?!you\b|your\b|it\b|the\b|not\b|needed\b|there\b|we\b)", r"\1 if you have "),
    (r"\bif you have (fever|high fever)\b", r"if you have a \1"),
    (r"\bsymptoms? (?:>|more than) ?(\d+ \w+)", r"symptoms that last more than \1"),
    (r"^(.+? if you have )(.+)$", split_list),
    # tests and scans: what will happen
    (r"^(an? [^.]*?(?:scan|ultrasound|x-ray|mammogram)\b(?: \([^)]*\))?)(?: (?:is )?(?:ordered|due|today|booked))?\.?$",
     lambda m: f"You will get {m.group(1)[0].lower() + m.group(1)[1:]}."),
    # everyday wording
    (r"(\d+) minutes? walking\b", r"walk \1 minutes"),
    (r"\bat pharmacy\b", "at the pharmacy"),
    (r"\b(at|to) next visit\b", r"\1 your next visit"),
    (r", (bring the numbers)\b", r". Bring the numbers"),
    (r"^eat less salt, less than\b", "Eat less salt: less than"),
    (r"(\d(?:\.\d+)?) ?L\b", r"\1 liters"),
    (r"(\d+(?:\.\d+)?) g\b(?= a day| each day| per day)", r"\1 grams"),
    (r"\bhigh cholesterol and other blood fats\b", "high cholesterol"),
    (r",?\s*(?:hemodynamically|haemodynamically) stable\b", ""),
    (r", new\b(?= and|\.|$)", ""),
    (r", no signs of anything serious\b", ". There are no signs of anything serious"),
    (r", ((?-i:[A-Za-z]+)) for (fever or pain|fever|pain)\b", r", and take \1 for \2"),
    (r"\bstage \d+,?\s*", ""),
    (r"\bhave (very bad|sudden|bad) headache\b", r"have a \1 headache"),
    (r"\bdue to\b", "because of"),
]
PURPOSE_RULES = [(r"\bmild to moderate\s+", ""), (r"\bcertain\s+", "")]


# ---------- model ----------

@dataclass
class Segment:
    text: str                      # plain text, or the original term for a term segment
    kind: str = "text"             # text | med | word | keep | drug
    plain: str = ""                # plain words for the patient
    source: str = ""
    flag: str = ""
    defined: bool = False          # plain is an explanation of the term, not a swap ("a disease in which...")


@dataclass
class Medicine:
    name: str                      # exactly as in the note
    purpose: list[Segment]         # what it does, plain words (MedlinePlus)
    instruction: list[Segment]     # "Take 1000 mg twice a day, with meals." from the note ([] = not in the note)
    source: str = ""               # MedlinePlus drug page
    change: str = ""               # "New", "Higher dose", "Lower dose", "New dose", "Stopped" or ""
    flags: list[str] = field(default_factory=list)
    category: str = ""             # "Blood pressure medicine": what the patient calls it (from MedlinePlus)
    note: list[Segment] = field(default_factory=list)  # "This may be causing the swelling in both legs."


@dataclass
class Summary:
    overview: list[list[Segment]]
    medicines: list[Medicine]
    steps: list[list[Segment]]
    origin: str
    urgent: set = field(default_factory=set)                    # step indices: when to get help sooner
    left_out: list[dict] = field(default_factory=list)          # {"text", "reason"} not in the summary
    clinician_flags: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    readability: dict = field(default_factory=dict)
    tries: list[dict] = field(default_factory=list)
    grade: int = READER_GRADE

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    @property
    def reading_ok(self) -> bool:
        return all(c["ok"] for c in self.checks if c["name"].startswith("Reader"))

    def segments(self) -> list[Segment]:
        out = [s for item in self.overview + self.steps for s in item]
        for m in self.medicines:
            out += [Segment(m.name, "drug", "", m.source)] + m.instruction + m.note
        return out

    def terms(self) -> list[Segment]:
        return [s for s in self.segments() if s.kind != "text"]


def clean(item: list[Segment]) -> str:
    """What the patient reads: plain words only; kept names with their explanation after them."""
    out = []
    for s in item:
        if s.kind in ("med", "word"):
            out.append(s.plain)
        elif s.kind in ("keep", "drug"):
            out.append(f"{s.text} ({s.plain})" if s.plain else s.text)
        else:
            out.append(s.text)
    return "".join(out)


def medicine_lines(m: Medicine) -> list[str]:
    head = f"{m.category} ({m.name})." if m.category else f"{m.name}."
    return [head] + ([clean(m.instruction)] if m.instruction else []) + ([clean(m.note)] if m.note else [])


def patient_text(s: Summary) -> str:
    lines = [clean(i) for i in s.overview] + [l for m in s.medicines for l in medicine_lines(m)] + [clean(i) for i in s.steps]
    return "\n".join(lines)


# ---------- text -> segments ----------

def to_segments(item: str, findings: list) -> list[Segment]:
    """A make_printout item (with markers that carry finding numbers) as segments."""
    marked = re.compile(f"([{FLAG_ON}{WORD_ON}])(.*?){INDEX}(\\d+)([{FLAG_OFF}{WORD_OFF}])")
    segments, pos = [], 0
    for m in marked.finditer(item):
        if m.start() > pos:
            segments.append(Segment(strip_markers(item[pos:m.start()])))
        f, shown = findings[int(m.group(3))], m.group(2)
        if f.kind == "medication":
            seg = Segment(shown, "drug", "", "note")
        elif f.kind == "abbreviation" and lay_dictionary()[0].get(f.text, {}).get("kind") == "lab_test" and not f.replace_with:
            seg = Segment(shown, "keep", f.explain or "", f.source)  # "TSH": a lab name stays as on the report
        elif not f.replace_with and f.explain and " " not in f.text and is_known(f.text):
            seg = Segment(shown)  # an everyday word a source happens to define ("fainting"): keep the word
        elif f.source == "MedlinePlus Lab Tests" and not f.replace_with:
            seg = Segment(shown, "keep", f.explain or "", f.source)
        elif not (f.replace_with or f.explain):
            seg = Segment(shown)  # no plain wording found: leave the word (the jargon check reports it)
        else:
            seg = Segment(f.text, "word" if f.kind == "wording" else "med",
                          shown if f.replace_with else (f.explain or ""),
                          MODEL if f.source and "model knowledge" in f.source else (f.source or ""),
                          defined=not f.replace_with)
        seg.flag = f.flag or ""
        segments.append(seg)
        pos = m.end()
    if pos < len(item):
        segments.append(Segment(strip_markers(item[pos:])))
    return segments


def plain_segments(text: str) -> list[Segment]:
    marked, found = marked_text(text)
    return to_segments(marked, found)


def parse_markup(sentence: str) -> list[Segment]:
    """[[original|plain|kind|source]] markup (Claude's output) as segments."""
    segments, pos = [], 0
    for m in MARKUP.finditer(sentence):
        if m.start() > pos:
            segments.append(Segment(sentence[pos:m.start()]))
        original, plain, kind, source = (g.strip() for g in m.groups())
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r} in {m.group(0)}")
        segments.append(Segment(original, kind, plain, source,
                                "no standard source (model knowledge, verify)" if source == MODEL else ""))
        pos = m.end()
    if pos < len(sentence):
        segments.append(Segment(sentence[pos:]))
    return segments


def rewrite(item: list[Segment], rules: list) -> list[Segment]:
    """Apply phrasing rules to what the patient reads, keeping the highlighted terms."""
    terms = [s for s in item if s.kind != "text"]
    text = clean(item)
    for pattern, new in rules:
        text = re.sub(pattern, new, text, flags=re.I)
    if not terms:
        return [Segment(text)]
    shown = {(f"{t.text} ({t.plain})" if t.kind in ("keep", "drug") and t.plain else
              t.text if t.kind in ("keep", "drug") else t.plain): t for t in terms}
    pattern = "|".join(re.escape(k) for k in sorted(shown, key=len, reverse=True) if k)
    if not pattern:
        return [Segment(text)]
    out, pos = [], 0
    for m in re.finditer(pattern, text, re.I):
        if m.start() > pos:
            out.append(Segment(text[pos:m.start()]))
        t = shown.get(m.group(0)) or next(v for k, v in shown.items() if k.lower() == m.group(0).lower())
        out.append(replace(t, plain=m.group(0) if t.kind in ("med", "word") else t.plain))
        pos = m.end()
    if pos < len(text):
        out.append(Segment(text[pos:]))
    return out


def capitalize(item: list[Segment]) -> list[Segment]:
    for s in item:
        visible = s.plain if s.kind in ("med", "word") else s.text
        if not visible.strip():
            continue
        if s.kind in ("med", "word"):
            s.plain = s.plain[:1].upper() + s.plain[1:]
        elif s.kind == "text":
            i = len(s.text) - len(s.text.lstrip())
            s.text = s.text[:i] + s.text[i:i + 1].upper() + s.text[i + 1:]
        break
    return item


# ---------- words the reader would know ----------

def easier_word(word: str, grade: int) -> tuple[str, str] | None:
    """(easier wording, source) for a word the reader may not know, or None."""
    w = word.lower()
    entry = lay_dictionary()[1].get(w)
    if entry and entry.get("standard") and entry.get("plain") and all(is_known(x, grade) for x in WORD.findall(entry["plain"])):
        return entry["plain"], entry["source"]
    if w in EASIER and all(is_known(x, grade) for x in WORD.findall(EASIER[w])):
        return EASIER[w], MODEL
    medical = w in lay_dictionary()[1] or w in medical_vocab() or w.rstrip("s") in medical_vocab()
    g = None if medical else gloss(w, grade)
    if g:
        return g, LWV
    return None


def familiar(item: list[Segment], grade: int, skip: set[str], unknown: bool = True) -> list[Segment]:
    """Swap doctor words ("severe" -> "very bad") and, if unknown is set, words the reader may not know, for words
    they would say; marked as 'hard word -> simpler word'."""
    out = []
    for s in item:
        if s.kind == "text":
            pos = 0
            for m in WORD.finditer(s.text):
                w = m.group(0)
                talk = w.lower() in EASIER and DOCTOR_TALK.fullmatch(w)
                if w.lower() in skip or not talk and (not unknown or is_known(w, grade)) \
                        or w[:1].isupper() and m.start() > 0 and s.text[m.start() - 2:m.start()] != ". ":
                    continue
                easier = (EASIER[w.lower()], MODEL) if talk else easier_word(w, grade)
                if not easier:
                    continue
                plain, source = easier
                if w[:1].isupper():
                    plain = plain[:1].upper() + plain[1:]
                out.append(Segment(s.text[pos:m.start()]))
                out.append(Segment(w, "word", plain, source, "no standard source (model knowledge, verify)" if source == MODEL else ""))
                pos = m.end()
            out.append(Segment(s.text[pos:]))
        elif s.kind == "med" and s.plain:
            for w in WORD.findall(s.plain):  # "an acute infection" -> "a sudden infection"
                if w.lower() in EASIER and DOCTOR_TALK.fullmatch(w):
                    s = replace(s, plain=re.sub(rf"\b{re.escape(w)}\b", EASIER[w.lower()], s.plain),
                                flag=s.flag or "no standard source (model knowledge, verify)")
            words = WORD.findall(s.plain)
            hard = [w for w in words if not is_known(w, grade) and w.lower() not in skip]
            for w in hard:  # a definition that itself has a hard word (not a word-list gloss inside MedlinePlus text)
                easier = easier_word(w, grade)
                if easier and easier[1] != LWV:
                    s = Segment(s.text, s.kind, re.sub(rf"\b{re.escape(w)}\b", easier[0], s.plain), s.source,
                                s.flag or ("" if easier[1] != MODEL else "no standard source (model knowledge, verify)"))
            out.append(s)
        else:
            out.append(s)
    return [s for s in out if s.kind != "text" or s.text]


# ---------- medicines ----------

def third_person(gerund: str) -> str:
    """'relaxing' -> 'relaxes', 'stopping' -> 'stops', 'reducing' -> 'reduces'."""
    base = gerund[:-3]
    if len(base) > 2 and base[-1] == base[-2] and base[-1] not in "lsz":
        base = base[:-1]
    if zipf_frequency(base + "e", "en") > zipf_frequency(base, "en"):
        base += "e"
    return base + ("es" if base.endswith(("s", "x", "sh", "ch", "z")) else "s")


def verb3(verb: str) -> str:
    return verb + ("es" if verb.endswith(("s", "x", "sh", "ch")) else "s")


def purpose_options(why: str) -> list[tuple[str, str]]:
    """[(kind, phrase)] from MedlinePlus 'Why is this medication prescribed?': uses and how it works."""
    why = re.sub(r"\s*\([^)]*\)", "", why)
    options = []
    first = re.split(r"(?<=\.)\s+", why)[0]
    used = re.search(r"\bis used\b(.*?)(?:\.|$)", first)
    if used:
        clause = re.sub(r"^\s*(?:alone or (?:in combination )?with other medications.*?(?=\bto\b))?(?:to:?)?\s*", "",
                        used.group(1))
        for use in re.split(r"[,;]?\s+(?:and\s+)?(?:to\s+)?(?=(?:%s)\b)" % "|".join(VERBS), clause):
            m = re.match(r"(%s)\s+(.+)" % "|".join(VERBS), use.strip())
            if m:
                obj = re.split(r",? such as\b|,? including\b| in (?:people|adults|patients|children)\b", m.group(2))[0]
                options.append(("use", f"{verb3(m.group(1))} {re.sub(r'^certain ', '', obj.strip(' ,'))}"))
    # Only when the medicine (or "It") is the subject: "...blocks a substance that helps blood clots to form"
    # must not become "helps blood clots to form".
    helps = re.search(r"(?:^|\.\s+)(?:It|[A-Z][\w-]+(?: [\w-]+)?) helps? (?:to )?([^.:;]+)", why)
    if helps:
        options.append(("does", "helps " + helps.group(1).strip()))
    works = re.search(r"(?:^|\.\s+)(?:It|[A-Z][\w-]+(?: [\w-]+)?) works by (\w+ing)\b([^.]*)", why)
    if works:
        rest = re.sub(r"\b(and|or) (\w+ing)\b", lambda m: f"{m.group(1)} {third_person(m.group(2))}", works.group(2))
        options.append(("does", third_person(works.group(1)) + rest.rstrip()))
    return options


def pick_purpose(options: list[tuple[str, str]], note_words: set[str], grade: int, plainest: bool) -> str:
    """The use that matches the patient's note ('treats high blood pressure'), else what it does.
    plainest: among the candidates, prefer the one with the most words the reader knows."""
    def score(phrase: str) -> float:
        words = {w for w in re.findall(r"[a-z0-9]+", phrase.lower()) if len(w) > 3 and w not in USE_STOPWORDS}
        words.discard(phrase.split()[0])
        return len(words & note_words) / len(words) if words else 0
    uses = sorted((o for o in options if o[0] == "use"), key=lambda o: -score(o[1]))
    if uses and score(uses[0][1]) >= 0.6:
        return uses[0][1]
    helps = [o for o in options if o[1].startswith("helps ")]
    works = [o for o in options if o[0] == "does" and not o[1].startswith("helps ")]
    candidates = [o[1] for o in helps + works + uses]  # what it does in the body, else its first listed use
    if plainest and candidates:  # the plainest, keeping the order (uses before how it works)
        return max(enumerate(candidates), key=lambda ic: (assess(ic[1], grade=grade)["coverage"], -ic[0]))[1]
    return candidates[0] if candidates else ""


def shorten(phrase: str, words: int) -> str:
    """Cut a description at a natural break, keeping at least a few words."""
    out = phrase
    for m in re.finditer(r",\s+| so that | so | and ", phrase):
        if len(phrase[:m.start()].split()) >= 2 and not (m.group(0).strip() == "and" and len(phrase[:m.start()].split()) < 3):
            out = phrase[:m.start()]  # never cut to one word ("relaxes")
            break
    if len(out.split()) > words:
        cut = " ".join(out.split()[:words])
        to = cut.rfind(" to ")  # end at a natural point: "...the air passages to the lungs"
        out = cut[:cut.rfind(" to ", 0, to)] if to > 0 and " to " in cut[:to] and len(cut[:to].split()) >= 4 else cut
    out = re.sub(r"(?:\s+(?:to|the|of|a|an|and|or|in|for|with|by|from|your))+$", "", out)  # no dangling "to the"
    return out.strip(" ,")


def dose_after(text: str, start: int) -> str:
    """'1000 mg BID with meals (currently ...)' -> '1000 mg BID with meals': up to the next break."""
    rest = text[start:]
    end = len(rest)
    for pattern in (r"[;\n(]|,(?!\s*then\b)", r"\s-\s", r"\.\s", r"\.$", r"\s(?:and|then stop|if)\s"):
        m = re.search(pattern, rest)
        if m:
            end = min(end, m.start())
    return re.sub(r"^(?:to|at|of)\s+", "", rest[:end].strip(" .:-"), flags=re.I)


def instruction_for(name: str, dose: str, change: str, keep_taking: bool, when: str) -> tuple[list[Segment], bool]:
    """('Take 1 pill (1000 mg) twice a day, with meals.', pill count assumed?) from the note's dose;
    [] if the note has none."""
    if change == "Stopped":
        return [Segment("Stop taking this.")], False
    if when:  # "to start in 24-48 hours if symptoms not improving" (delayed prescription)
        segs = rewrite(plain_segments(when), STEP_RULES)
        return capitalize(segs + [Segment(".")]), False
    if not dose:
        return [], False
    verb = next((v for p, v in FORM_VERBS if re.search(p, name + " " + dose, re.I)), "Take")
    if keep_taking:
        verb = "Keep using" if verb == "Use" else "Keep taking"
    dose = re.sub(r"\bx\s?(\d+)\s*(days?|weeks?|months?)\b", r"for \1 \2", dose)  # "BID x 5 days"
    dose = re.sub(r"(\d)\s?x\b", r"\1 times", dose)
    dose = re.sub(r"\bthen back to\b", "then go back to", dose)
    dose = re.sub(r"\bnightly\b", "each night", dose)
    dose = re.sub(r"^(\d+(?:\.\d+)?\s?(?:mg|mcg|micrograms?))\s+(\d+ puffs?)\b", r"\2 (\1)", dose)  # "100mcg 2 puffs"
    dose = re.sub(r"\s*/\s*(day|week|month|hour|night)\b", r" a \1", dose)
    dose = ORAL_AMOUNT.sub(lambda m: f"{m.group(1)} {m.group(2).lower()}", dose)  # "5mg" -> "5 mg"
    # "5 mg" -> "1 pill (5 mg)"; not for grams (1 g of paracetamol is 2 tablets) or combinations ("49/51 mg")
    amounts = ORAL_AMOUNT.findall(dose)
    one_pill = (verb in ("Take", "Keep taking") and len(amounts) == 1 and amounts[0][1].lower().startswith("m")
                and not re.search(r"\d\s*/\s*\d+(?:\.\d+)?\s*(?:mg|mcg|g|IU|units)\b|(?:mg|mcg|g)\s*/\s*\d|\+", dose, re.I))
    if one_pill:
        dose = ORAL_AMOUNT.sub(lambda m: f"1 pill ({m.group(1)} {m.group(2).lower()})", dose)
    segs = rewrite(plain_segments(dose), STEP_RULES + [(r"\bdaily\b", "each day"), (r"\bweekly\b", "once a week")])
    first = clean(segs).lstrip().lower()
    if re.match(r"(take|use|put|apply|start|stop|keep)\b", first):
        return capitalize(segs + [Segment(".")]), one_pill
    with_meals = re.compile(r"\s+(with (?:meals|food)|at bedtime|in the morning)\b", re.I)
    for s in segs[:1]:  # "Take" + "As needed" -> "Take as needed"
        if s.kind in ("med", "word") and s.plain[:2].istitle():
            s.plain = s.plain[0].lower() + s.plain[1:]
        elif s.kind == "text" and s.text[:2].istitle():
            s.text = s.text[0].lower() + s.text[1:]
    segs = [Segment(re.sub(r"(?<=\)), (?=at bedtime|in the morning)", " ", with_meals.sub(r", \1", s.text))) if s.kind == "text"
            else s for s in segs]  # "twice a day, with meals"; "1 pill (0.4 mg) at bedtime"
    return [Segment(f"{verb} ")] + segs + [Segment(".")], one_pill


def category_for(purpose: str, why: str, reason: str = "", form: str = "") -> str:
    """What a patient would call it. The reason the note gives ("for rate control") wins, then the drug class
    MedlinePlus names ("diuretics"), then the use that fits the note, then the first use MedlinePlus lists."""
    if re.search(r"inhaler|puff|inhal", form, re.I):
        return "Breathing medicine"  # an inhaler's MedlinePlus page may be the nasal spray (beclomethasone)

    def earliest(text: str) -> str:
        hits = [(m.start(), name) for pattern, name in CATEGORIES for m in [re.search(pattern, text or "", re.I)] if m]
        return min(hits)[1] if hits else ""

    if earliest(reason):
        return earliest(reason)
    drug_class = re.search(r"class of medications called ([^.]+)", why or "")
    for pattern, name in CLASSES if drug_class else []:
        if re.search(pattern, drug_class.group(1), re.I):
            return name
    return earliest(purpose) or earliest(why) or "Medicine"


def find_medicines(note: str, level: int, grade: int) -> tuple[list[Medicine], set[str]]:
    """Every medicine in the note, with what it does and how to take it."""
    names = note_medicines(note)
    note_words = set(re.findall(r"[a-z0-9]+", (note + " " + convert(note).plain_text).lower()))
    parts = split_sections(note)
    medicines = []
    for key in sorted(names, key=lambda n: note.lower().find(n)):
        shown_name, dose, change, keep_taking, when, in_plan, dose_from_meds = None, "", "", False, "", False, False
        reason, undecided = "", ""
        for kind, _, body in parts:
            for m in re.finditer(rf"\b{re.escape(key)}\b", body, re.I):
                suffix = re.match(r"\s+(%s)\b" % "|".join(NAME_SUFFIXES), body[m.end():], re.I)
                end = m.end() + (suffix.end() if suffix else 0)
                name = body[m.start():end]
                shown_name = shown_name or name[0].upper() + name[1:]
                found = dose_after(body, end)
                plain = convert(found).plain_text if found else ""
                has_dose = bool(found) and bool(re.search(r"\d", found) or DOSING_WORDS.search(plain))
                line_start = body.rfind("\n", 0, m.start()) + 1
                before = body[line_start:m.start()]
                if kind in ("plan", "found_plan") and UNDECIDED.search(before):
                    # "discuss trial taper of omeprazole to 20 mg": not a decision; keep the current dose, ask
                    undecided = body[line_start:body.find("\n", end) if "\n" in body[end:] else len(body)].strip()
                    continue
                if kind in ("plan", "found_plan"):
                    in_plan = True
                    for_what = re.search(r"\bfor ([a-z][a-z ]+?)\s*(?:[.,;(]|$)", body[end:body.find("\n", end) if "\n" in body[end:]
                                                                                    else len(body)])
                    reason = for_what.group(1) if for_what else reason
                    if re.search(r"\b(?:instead of|stop|discontinue)\s*$", before, re.I):
                        change = "Stopped"
                    elif re.search(r"\b(?:decrease|reduce|lower)\b", before, re.I) and change != "Stopped":
                        change = "Lower dose"
                    elif re.search(r"\b(?:increase|raise)\b", before, re.I) and change != "Stopped":
                        change = "Higher dose"
                    elif re.search(r"\bchange\b", before, re.I) and change != "Stopped":
                        change = "New dose"
                    elif re.search(r"\b(?:start|script|prescribed|advised|commence)\b", before, re.I) and change != "Stopped":
                        change = "New"
                    if re.search(r"\bcontinue\b", before, re.I):
                        keep_taking = True
                    line = body[end:body.find("\n", end) if "\n" in body[end:] else len(body)]
                    start_when = re.search(r"\bto ((?:start|take|begin|use)\b[^.]*)", line, re.I)
                    if start_when and not has_dose:
                        when = start_when.group(1).strip(" .")
                    if has_dose:
                        dose = found  # the plan's (new) dose wins over the medicine list
                elif has_dose and (kind == "meds" or not dose) and not (in_plan and dose):
                    if kind == "meds" or not dose_from_meds:
                        dose = found
                        dose_from_meds = kind == "meds"
        info = lookup(key, online=True, tries=1)
        purpose_text, flags = "", []
        if info.get("found"):
            purpose_text = shorten(pick_purpose(purpose_options(info["why"]), note_words, grade, plainest=level >= 2), 12)
            if level >= 2:
                purpose_text = shorten(purpose_text, 8)
            if level >= 5:
                purpose_text = shorten(purpose_text, 5)
        else:
            flags.append("no MedlinePlus drug page found: add what it is for, or leave the name only")
        instruction, one_pill = instruction_for(shown_name or key, dose, change if in_plan else "", keep_taking, when)
        if one_pill:
            flags.append("\"1 pill\" assumed from the dose in the note: confirm the tablet strength")
        if not instruction:
            flags.append("how to take it is not in the note: fill in the blank line or add it to the note")
        if undecided:
            flags.append(f"the plan says \"{undecided}\": not shown as a change; edit it if this was decided")
        purpose = rewrite(plain_segments(purpose_text), PURPOSE_RULES) if purpose_text else []
        if level >= 2:  # a condition MedlinePlus only defines at length stays as its name here
            purpose = [Segment(x.text) if x.kind == "med" and x.plain and len(x.plain.split()) > 4 else x for x in purpose]
        category = category_for(purpose_text, info.get("why", ""), reason, f"{shown_name} {dose}")
        category = "" if category == "Medicine" else category
        if category:
            flags.append(f"called \"{category}\" from " + ("the note" if reason and category_for("", "", reason) != "Medicine"
                         else "its MedlinePlus page") + ": check that is why this patient takes it")
        medicines.append(Medicine(shown_name or key, purpose, instruction, info.get("url", ""),
                                  change if in_plan else "", flags, category))
    return medicines, names


def note_medicines(note: str) -> set[str]:
    """Medicine names in the note: RxNorm names that aren't everyday words ("aspirin" counts, "water" doesn't)."""
    found = {f.text.lower() for f in analyze(note) if f.kind == "medication"}
    lab_tests = {t for t, e in lay_dictionary()[1].items() if e.get("kind") == "lab_test"}
    for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", note):
        if w.lower() in drug_names() and zipf_frequency(w.lower(), "en") < 4.5 and w.lower() not in lab_tests:
            found.add(w.lower())
    for uk in sorted(UK_NAMES, key=len, reverse=True):  # "alendronic acid", "Clenil"
        if re.search(rf"\b{re.escape(uk)}\b", note, re.I) and not any(uk in f.split() for f in found if f != uk):
            found = {f for f in found if f not in uk.split()} | {uk}
    found |= {m.group(1).lower() for m in re.finditer(r"\b(vitamin [A-Z]\d{0,2})\s+\d", note, re.I)}  # "vitamin D 1000 IU"
    # A substance is a medicine only with a dose ("calcium 600 mg"), not in "low sodium diet" or "metoprolol succinate".
    found = {f for f in found if f not in SALTS or re.search(rf"\b{f}\b[^.\n]{{0,20}}?\d", note, re.I)
             and not re.search(rf"\w+ {f}\b", note, re.I) or re.search(rf"^\s*(?:meds|medications)\s*:.*\b{f}\b", note, re.I | re.M)}
    # Vaccines are given in the clinic or listed as next steps, not taken at home.
    found = {f for f in found if not lookup(f, online=False).get("why", "").startswith("Why get vaccinated")}
    # Combinations stay together: "sacubitril/valsartan", "calcium + vitamin D".
    for f in sorted(found):
        combo = re.search(rf"\b{re.escape(f)}\s*[/+]\s*([A-Za-z][A-Za-z -]*?)(?=\s+\d|\s*[,.;\n]|$)", note, re.I | re.M)
        second = combo.group(1).lower().split()[0] if combo else ""
        if combo and f in found and (second in drug_names() or second == "vitamin" or second in UK_NAMES):
            words = set(re.findall(r"[a-z0-9-]+", combo.group(0).lower()))
            found = {g for g in found if not set(g.split()) <= words} | {combo.group(0).lower()}
    # Only mentioned as an allergy ("Allergies: latex", "allergic to penicillin"): not a medicine they take.
    lines = note.lower().splitlines()
    return {m for m in found if not all(re.search(r"allerg|nkda|intoleran|reaction to", l)
                                        for l in lines if re.search(rf"\b{re.escape(m)}\b", l))}


# ---------- the offline writer ----------

def first_to_second(text: str) -> str:
    """The patient's own words in the note ("I have a cough") -> "you have a cough"."""
    for pattern, new in ((r"\bI'm\b", "you're"), (r"\bI am\b", "you are"), (r"\bI've\b", "you've"),
                         (r"\bI\b", "you"), (r"\bmy\b", "your"), (r"\bme\b", "you"), (r"\bmyself\b", "yourself")):
        text = re.sub(pattern, new, text)
    return text


def lower_first(text: str) -> str:
    i = len(text) - len(text.lstrip(f" {FLAG_ON}{WORD_ON}"))
    word = re.match(r"\w+", text[i:])
    if word and (word.group(0) == "A" or not word.group(0).isupper()) and not re.match(r"[A-Z]\w*[A-Z0-9]", word.group(0)):
        return text[:i] + text[i].lower() + text[i + 1:]
    return text


PRESENTS = re.compile(r"^.*?\b(?:presents?|presented|presenting|came in|comes in|here|seen|complains|c/o)"
                      r"(?: today)?(?: with| for| of)\s+", re.I)
AGE_SEX = re.compile(r"^\s*\d+[- ]?(?:(?:y/?o|yo|years?[- ]old|year old)[- ]?(?:M|F|male|female|man|woman)?|"
                     r"(?-i:M|F)|male|female|man|woman)\b[,:.]?\s*", re.I)


def came_in_for(pc: str) -> str:
    """'Headache' -> 'You came in because of a headache.'; 'I have a cough' -> 'You came in because you have a cough.';
    '82F presents with 3 days of dysuria' -> 'You came in because of 3 days of pain when you pass urine.'"""
    pc = first_to_second(pc).rstrip(". ")
    plain = strip_markers(pc)
    if PRESENTS.match(plain):  # history sentence: keep only what they came in with
        cut = PRESENTS.match(plain).end()
        pos = next(i for i in range(len(pc) + 1) if len(strip_markers(pc[:i])) >= cut)
        pc = pc[pos:]
    elif AGE_SEX.match(plain) and AGE_SEX.match(plain).end():
        pc = pc[AGE_SEX.match(plain).end():]
    pc = re.sub(r"^\s*\d+[- ](?:week|month|day|year)\s+(?=follow)", "", pc, flags=re.I)  # "6-week follow-up"
    start = strip_markers(pc).strip().lower()
    if re.search(r"\b(?:visit|check-?up|physical)\b", start) and not start.startswith(("follow", "you ")):
        return f"You came in for {'' if start.startswith(('a ', 'an ', 'your ', 'the ')) else 'your '}{lower_first(pc)}."
    if start.startswith(("you ", "your ", "you've ", "you're ", "you'd ")):
        return f"You came in because {lower_first(pc)}."
    if start.startswith(("follow", "review", "check")):
        return f"You came in for a {lower_first(pc)}."
    words = start.split()
    article = "a " if len(words) == 1 and not start.endswith("s") else ""
    return f"You came in because of {article}{lower_first(pc)}."


def split_more(item: str) -> list[str]:
    """'Conservative treatment: rest, fluids, regular paracetamol.' -> two sentences."""
    parts = re.split(r"(?<=[\w\x02\x04)])\s*[:;]\s+(?=\S)|\s+-\s+", item)
    if len(parts) == 2 and len(strip_markers(parts[0]).split()) <= 3:
        return [item]  # a label and its list stay together
    return [tidy_item(p) for p in parts if strip_markers(p).strip(" .")]


def split_long(item: str, limit: int = 18) -> list[str]:
    """Break a long sentence at ', or' / ', and' / ', but' when both halves can stand alone."""
    if len(strip_markers(item).split()) <= limit:
        return [item]
    parts = re.split(r",\s+(?=(?:and|but|then)\s)", item, maxsplit=1)
    return [tidy_item(p[0].upper() + p[1:] if p[:1].islower() else p) for p in parts] if len(parts) > 1 else [item]


def is_medicine_line(item: str, names: set[str]) -> bool:
    words = re.findall(r"[a-z]+", strip_markers(item).lower())[:5]
    return bool(MED_LINE_START.match(strip_markers(item).strip())) and any(w in names for w in words) \
        or any(w in names for w in words[:2])


def offline_summary(note: str, level: int, grade: int) -> Summary:
    p = make_printout(note)
    by_key = {s.key: s.items for s in p.sections}
    left_out = [{"text": f"{h}: {t}", "reason": "exam findings are for the clinician"} for h, t in p.left_off]
    used = set()

    medicines, names = find_medicines(note, level, grade)

    # Your visit: why you came in, then what the doctor found, said once (2-3 sentences)
    overview = []
    reason = by_key.get("reason", [])
    if reason:
        overview.append(came_in_for(reason[0]))
        used.add(id(reason[0]))
        left_out.append({"text": strip_markers(reason[0]), "reason": "the note's wording (said more simply in Your visit)"})
    # "Fall risk: refer to PT..." (assessment and plan by problem): the problem is a finding, the rest a step.
    labels, actions = [], []
    for item in by_key.get("found_plan", []):
        label, sep, rest = item.partition(": ")
        if sep and len(strip_markers(label).split()) <= 6 and strip_markers(rest).strip():
            labels.append(label)
            actions.append(rest)
            if not re.search(r"vaccin|immuni|screening|medications?|meds\b|labs?\b|health maintenance|prevent|counsel|"
                             r"use\b|follow", strip_markers(label), re.I):
                labels[-1] = label
            else:
                labels.pop()
        else:
            actions.append(item)
    if labels:
        found_plan_found, found_plan_rest = labels, actions
    else:
        found_plan_found, found_plan_rest = by_key.get("found_plan", [])[:2], by_key.get("found_plan", [])[2:]
    found = by_key.get("found", []) + found_plan_found
    overview += findings_sentences(found, overview[0] if overview else "", medicines, names, p.findings)
    for item in found:
        used.add(id(item))
    left_out += [{"text": strip_markers(i), "reason": "the note's wording (said more simply in Your visit)"}
                 for i in by_key.get("found", []) + by_key.get("found_plan", [])]
    if len(overview) < 2 and len(reason) > 1:
        overview.append(reason[1])
        used.add(id(reason[1]))

    # What to do next: plan (medicine lines are in "Your medicines"), follow-up, when to get help (last)
    plan = by_key.get("plan", []) + found_plan_rest
    follow = by_key.get("followup", [])
    for i in plan + follow + by_key.get("found_plan", []):
        used.add(id(i))
    med_lines = [i for i in plan if is_medicine_line(i, names)]
    # The clinician documenting consent or advice given isn't a step for the patient.
    record = [i for i in plan + follow if CLINICIAN_RECORD.search(strip_markers(i))]
    left_out += [{"text": strip_markers(i), "reason": "clinician's record, not a step for the patient"} for i in record]
    plan = [i for i in plan if i not in record]
    undecided = [i for i in plan if re.match(r"\W*(?:discuss|consider|think about)\b", strip_markers(i), re.I)]
    left_out += [{"text": strip_markers(i), "reason": "not decided yet (the plan says to discuss or consider it)"} for i in undecided]
    plan = [i for i in plan if i not in undecided]
    follow = [i for i in follow if i not in record]
    left_out += [{"text": strip_markers(i), "reason": "covered in Your medicines"} for i in med_lines]
    urgent_items = [i for i in follow if WHEN_TO_CALL.search(strip_markers(i))]
    steps = [i for i in plan if i not in med_lines] + [i for i in follow if i not in urgent_items]
    if level >= 1:
        steps = [q for i in steps for part in split_more(i) for q in split_long(part)]
        urgent_items = [q for i in urgent_items for q in split_long(i)]
        overview = [q for i in overview for part in split_more(i) for q in split_long(part)]
    max_steps = 10 if level < 4 else 6
    if len(steps) > max_steps:
        left_out += [{"text": strip_markers(i), "reason": "cut to keep the summary short"} for i in steps[max_steps:]]
        steps = steps[:max_steps]
    steps += urgent_items

    # Everything else in the note is listed for the clinician, not dropped silently.
    for section in p.sections:
        for item in section.items:
            if id(item) not in used:
                left_out.append({"text": strip_markers(item), "reason": f"not needed for a short summary ({section.title.lower()})"})

    overview_segs = define_once([capitalize(rewrite(to_segments(tidy_item(i), p.findings), STEP_RULES)) for i in overview])[:4]
    if level >= 1:
        overview_segs = definitions_apart(overview_segs)
    step_segs = [direct_step(capitalize(rewrite(to_segments(tidy_item(i), p.findings), STEP_RULES))) for i in steps]
    if level >= 1:
        step_segs = definitions_apart(step_segs, same_item=True)
    # Doctor words ("severe", "elevated") always; other words the reader may not know from try 4.
    skip = {w.lower() for m in medicines for w in WORD.findall(m.name)}
    overview_segs = [capitalize(familiar(i, grade, skip, unknown=level >= 3)) for i in overview_segs]
    step_segs = [capitalize(familiar(i, grade, skip, unknown=level >= 3)) for i in step_segs]
    for m in medicines:
        m.purpose = familiar(m.purpose, grade, skip, unknown=level >= 3)
        m.instruction = familiar(m.instruction, grade, skip, unknown=level >= 3)
    urgent = {len(step_segs) - len(urgent_items) + k for k in range(len(urgent_items))}
    return Summary(overview_segs, medicines, step_segs, "Offline rewriter (rules + dictionaries + reader word list)",
                   urgent, left_out, grade=grade)


CLINICIAN_RECORD = re.compile(r"\b(understands?|happy with (?:the )?(?:plan|management)|agrees? with|agreeable|"
                             r"consent(?:ed)?|safety[- ]?net(?:ting)?(?: advice)? (?:given|discussed|provided)|advice given|"
                             r"questions answered)\b|^(?:repeat|recheck|review|discuss|reassess)\b.*\bat (?:the |your )?next visit",
                             re.I)
LAB_VERBS = re.compile(r"^(?:check|order|obtain|get|draw|repeat|do|send|arrange)\b", re.I)
WHEN = re.compile(r"\b(today|tomorrow|this week|next week|before (?:your|the) next visit|in \d+ (?:days?|weeks?|months?))\b", re.I)


def is_lab(s: Segment) -> bool:
    """A lab test named in the note: 'BMP', 'TSH', 'CBC' (-> 'blood count tests'), 'urine microalbumin'."""
    entry = lay_dictionary()[1].get(s.text.lower()) or lay_dictionary()[0].get(s.text) or {}
    return s.kind == "keep" and "Lab Tests" in (s.source or "") or s.kind in ("med", "keep") and (
        entry.get("kind") == "lab_test" or bool(re.search(r"\btests?\b", s.plain)) and s.text.isupper())


def direct_step(item: list[Segment]) -> list[Segment]:
    """Lab steps -> 'Go to the lab today for a blood test (BMP) and a urine test (microalbumin).';
    'TSH, CBC, BMP today' -> 'Go to the lab today for blood tests (TSH, CBC and BMP).' Not why (CLAUDE.md)."""
    labs = {k for k, e in lay_dictionary()[0].items() if e.get("kind") == "lab_test"}
    split = []
    for s in item:  # lab names the converter left as plain text ("TSH" has nothing to explain)
        if s.kind != "text":
            split.append(s)
            continue
        pos = 0
        for m in re.finditer(r"\b[A-Z][A-Za-z0-9]{1,5}\b", s.text):
            if m.group(0) in labs:
                split += [Segment(s.text[pos:m.start()]), Segment(m.group(0), "keep", "", "MedlinePlus Lab Tests")]
                pos = m.end()
        split.append(Segment(s.text[pos:]))
    item = [s for s in split if s.kind != "text" or s.text]
    text = clean(item)
    tests = [s for s in item if is_lab(s)]
    first = next((i for i, s in enumerate(item) if is_lab(s)), 0)
    starts_with_test = tests and not re.sub(r"[\W\d]", "", clean(item[:first]))
    if tests and (LAB_VERBS.match(text.strip()) or starts_with_test or re.match(r"^to check\b", text.strip(), re.I)):
        when = WHEN.search(text)
        kinds = {}
        for t in tests:
            kind = "urine test" if re.search(r"urine|\bUA\b", t.plain + t.text, re.I) else "blood test"
            kinds.setdefault(kind, []).append(re.sub(r"^(urine|blood)\s+", "", t.text, flags=re.I))
        out = [Segment("Go to the lab" + (f" {when.group(1)}" if when else "") + " for ")]
        for i, (kind, tnames) in enumerate(kinds.items()):
            out.append(Segment(("" if i == 0 else " and ") + (f"a {kind} (" if len(tnames) == 1 else f"{kind}s (")))
            for j, name in enumerate(tnames):
                src = next(t for t in tests if t.text.endswith(name))
                out += [Segment("" if j == 0 else (" and " if j == len(tnames) - 1 else ", ")),
                        Segment(name, "keep", "", src.source, src.flag)]
            out.append(Segment(")"))
        return out + [Segment(".")]
    return item


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", strip_markers(text).lower()) if len(w) > 2 and w not in
            {"the", "and", "not", "with", "your", "you", "for", "type", "goal", "likely", "also", "have"}}


def findings_sentences(found: list[str], reason: str, medicines: list[Medicine], names: set[str],
                       findings: list | None = None) -> list[str]:
    """'Type 2 diabetes, not at goal' + 'Hypertension, not at goal' -> 'Your blood sugar and blood pressure are still
    too high.'; 'Leg swelling, likely caused by amlodipine' -> a note on amlodipine; anything already said in the
    reason sentence isn't repeated."""
    measures, other = [], []
    for item in found:
        text = strip_markers(item)
        caused = CAUSED_BY.match(clean(rewrite(to_segments(item, findings), STEP_RULES)).strip() if findings else text.strip())
        if caused and caused.group(2).lower() in names:
            condition = lower_first(caused.group(1).strip(" ,."))
            for m in medicines:
                if m.name.lower().startswith(caused.group(2).lower()):
                    article = "" if re.match(r"(the|your|a|an)\b", condition) else "the "
                    m.note = [Segment(f"This medicine may be causing {article}{condition}.")]
            continue
        if STATUS.search(text):
            for pattern, measure in MEASURES:
                if re.search(pattern, text, re.I) and measure not in measures:
                    measures.append(measure)
                    break
            else:
                other.append(item)
            continue
        if content_words(item) <= content_words(reason):
            continue  # already said: "You came in for a follow-up of type 2 diabetes"
        other.append(item)
    sentences = []
    if measures:
        joined = " and ".join(measures) if len(measures) <= 2 else ", ".join(measures[:-1]) + " and " + measures[-1]
        sentences.append(f"Your {joined} {'is' if len(measures) == 1 else 'are'} still too high.")
    if other:
        lead = "The doctor also found " if sentences else "The doctor thinks you have "
        parts = [lower_first(strip_markers(i) if False else i).rstrip(". ") for i in other[:2]]
        sentences.append(lead + " and ".join(parts) + ".")
    return sentences


def tidy_definition(text: str, grade: int = READER_GRADE) -> str:
    """'your blood glucose, or blood sugar, levels' -> 'your blood sugar levels' (the words the reader knows;
    if both are known, the first: 'urine, or pee' -> 'urine')."""
    def pick(m):
        first, second = m.group(1), m.group(2)
        known = lambda t: all(is_known(w, grade) for w in WORD.findall(t))
        jargon = lambda t: bool(lay_dictionary()[1].get(t.lower(), {}).get("plain"))  # "blood glucose" -> "blood sugar"
        return first if known(first) and not jargon(first) or not known(second) else second
    return re.sub(r"\b([\w-]+(?: [\w-]+)?), or ([\w-]+(?: [\w-]+)?),?", pick, text)


def definitions_apart(items: list[list[Segment]], same_item: bool = False) -> list[list[Segment]]:
    """'You have [a group of lung diseases that make it hard to breathe...]' ->
    'You have a flare-up of COPD.' + 'COPD is a group of lung diseases that make it hard to breathe...'"""
    out = []
    for item in items:
        extra = []
        new_item = []
        for x in item:
            plain = tidy_definition(re.sub(r"\s*\(([^)]*)\)", r", or \1,", x.plain) if x.kind == "keep" else x.plain) \
                if x.kind in ("med", "keep") else ""
            known = all(is_known(w) for w in WORD.findall(x.text)) and not re.fullmatch(r"[A-Z0-9]{2,6}", x.text.strip())
            is_definition = x.kind == "keep" or x.defined
            if is_definition:
                plain = essence(plain)
            if is_definition and len(plain.split()) > 5 and re.match(r"(a|an|the)\b", plain, re.I) and known:
                new_item.append(Segment(x.text if not x.text[:1].isupper() or x.text.isupper() else x.text[0].lower() + x.text[1:]))
            elif is_definition and len(plain.split()) > 5 and re.match(r"(a|an|the)\b", plain, re.I):
                name = x.text if not x.text.isupper() or len(x.text) <= 5 else x.text.lower()
                new_item.append(Segment(name, "keep", "", x.source, x.flag))
                extra.append([Segment(f"{name[0].upper() + name[1:]} is "), Segment("", "med", plain.strip(" ,"), x.source,
                                                                                  x.flag), Segment(".")])
            else:
                new_item.append(x)
        if same_item:
            out.append(new_item + [seg for e in extra for seg in [Segment(" ")] + e])
        else:
            out.append(new_item)
            out += extra
    return out if same_item else out[:5]


DEFINITION_RULES = [  # the essence of a definition: "a group of lung diseases that make..." -> "a lung disease that makes..."
    (r"^(a|an) (?:group|type|kind|set) of (\w+) (disease|condition|problem)s that (\w+)\b",
     lambda m: f"{m.group(1)} {m.group(2)} {m.group(3)} that {m.group(4) if m.group(4).endswith('s') else verb3(m.group(4))}"),
    (r"^(a|an) (?:group|type|kind) of (\w+ )?(diseases|conditions|problems)\b", lambda m: f"{m.group(1)} {m.group(2) or ''}{m.group(3)[:-1]}"),
]


def essence(definition: str) -> str:
    """A definition cut to its main idea, one short phrase."""
    text = definition.strip(" ,.")
    for pattern, new in DEFINITION_RULES:
        text = re.sub(pattern, new, text, flags=re.I)
    return shorten(text, 12) if len(text.split()) > 8 else text


def define_once(items: list[list[Segment]]) -> list[list[Segment]]:
    """Explain a term the first time; after that use its name ("type 2 diabetes")."""
    seen, out = set(), []
    for item in items:
        new = []
        for x in item:
            if x.kind == "med" and x.defined and x.text.lower() in seen and len(x.plain.split()) > 4:
                x = Segment(x.text if x.text.isupper() else x.text[0].lower() + x.text[1:])
            elif x.kind == "med":
                seen.add(x.text.lower())
            new.append(x)
        out.append(new)
    return out


TRY_CHANGES = ["first draft", "split long sentences", "plainer medicine descriptions",
               "swap words the reader may not know", "fewer bullets and sentences", "shortest medicine descriptions"]


def best_of_tries(note: str, make, grade: int) -> Summary:
    """Rewrite until the reader check passes; keep the best try if none does."""
    tries, best = [], None

    def score(s: Summary) -> tuple:
        r = s.readability["reader"]
        return (s.ready, s.reading_ok, sum(c["ok"] for c in s.checks), r["coverage"], -r["max_sentence"])

    for level in range(MAX_TRIES):
        summary = check(make(level), note, grade)
        r = summary.readability["reader"]
        tries.append({"try": level + 1, "change": TRY_CHANGES[level] if level < len(TRY_CHANGES) else "retry",
                      "known": r["known_per_100"], "max_sentence": r["max_sentence"], "ok": summary.reading_ok,
                      "smog": summary.readability["smog"]})
        if best is None or score(summary) > score(best):
            best = summary
        if summary.ready:
            break
    best.tries = tries
    return best


# ---------- checks ----------

def numbers_in(text: str) -> set[str]:
    text = re.sub(r"(?m)^\s*\d+[.)]\s", "", text)  # list numbering "1." isn't content
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def leftover_jargon(summary: Summary) -> list[str]:
    """Medical words or abbreviations still in the patient's text (outside medicine names)."""
    kept = {s.text.lower() for s in summary.terms() if s.kind in ("keep", "drug")}
    left = set()
    for f in analyze(re.sub(r"\([^)]*\)", "", patient_text(summary))):  # names in parentheses are kept on purpose
        word = f.text.lower()
        if f.kind == "phrase" and f.text.lower() in (f.replace_with or "").lower():
            continue  # already the everyday phrase ("heat packs")
        if f.kind == "medication" or word in kept or any(word in k for k in kept):
            continue
        if f.kind == "wording" or (f.kind == "term" and not f.replace_with and f.explain):
            continue  # a long everyday word, or a plain term MedlinePlus names (e.g. "heart failure")
        if f.kind == "term" and " " not in word and zipf_frequency(word, "en") >= EVERYDAY_ZIPF:
            continue  # "medicines", "arthritis": MedlinePlus topic names that are everyday words
        left.add(f.text)
    return sorted(left)


def reader_skip(summary: Summary) -> set[str]:
    """Words that don't count against the reader: medicine names, and names kept with an explanation."""
    skip = set()
    for s in summary.terms():
        if s.kind in ("keep", "drug"):
            skip |= {w.lower() for w in WORD.findall(s.text)}
    for m in summary.medicines:
        skip |= {w.lower() for w in WORD.findall(m.name)}
    text = patient_text(summary)
    skip |= {m.group(1).lower() for m in re.finditer(r"\bDr\.? ([A-Z][a-z]+)", text)}  # "Dr. Lee"
    for names in re.findall(r"\(([^)]*)\)", text):  # names kept for reference after the plain words: "(echocardiogram)"
        skip |= {w.lower() for w in WORD.findall(names) if not is_known(w)}
    return skip


def check(summary: Summary, note: str, grade: int) -> Summary:
    text = patient_text(summary)
    reader = assess(text, reader_skip(summary), grade)
    sentences = textstat.sentence_count(text)
    summary.readability = {"reader": reader, "describe": describe(reader),
                           "smog": round(textstat.smog_index(text), 1) if sentences >= 3 else None,
                           "smog_note": round(textstat.smog_index(note), 1)}
    accounted = text + " " + " ".join(x["text"] for x in summary.left_out)
    missing_numbers = sorted(numbers_in(convert(note).plain_text) - numbers_in(convert(accounted).plain_text + accounted), key=float)
    listed = " ".join(m.name.lower() for m in summary.medicines)
    missing_meds = sorted(m for m in note_medicines(note) if m not in listed and m not in text.lower())
    jargon = leftover_jargon(summary)
    talk = doctor_talk(text)
    summary.readability["doctor_talk"] = talk
    summary.checks = [
        {"name": "Reader knows the words", "ok": reader["ok_words"],
         "detail": f"{reader['known_per_100']} of every 100 words (target 98)"
                   + (f"; might not know: {', '.join(reader['unknown'][:6])}" if reader["unknown"] else "")},
        {"name": "Reader can follow the sentences", "ok": reader["ok_sentences"],
         "detail": f"{reader['avg_sentence']} words on average, longest {reader['max_sentence']} (limits 13 and 20)"},
        {"name": "Reader hears everyday talk, not doctor talk", "ok": not talk,
         "detail": "sounds like a person talking" if not talk else "still sounds like a note: " + ", ".join(talk)},
        {"name": "Medicines listed", "ok": not missing_meds,
         "detail": "every medicine in the note is listed" if not missing_meds else "missing: " + ", ".join(missing_meds)},
        {"name": "Numbers kept", "ok": not missing_numbers,
         "detail": "every number is in the summary or the left-out list" if not missing_numbers
         else "missing: " + ", ".join(missing_numbers)},
        {"name": "No medical jargon left", "ok": not jargon,
         "detail": "none found" if not jargon else "still in the text: " + ", ".join(jargon)},
    ]
    summary.grade = grade
    return summary


# ---------- Claude (when ANTHROPIC_API_KEY is set) ----------

CLAUDE_MODEL = "claude-opus-5-5"
SUMMARY_PROMPT = """\
You write a short visit summary for an older adult after a primary care visit, from the clinician's \
note only. The patient and their family read it. Write to the patient as "you", the way a kind, \
clear nurse would explain it in person.

Say each thing once, in its most basic form. Example of the style:
  overview: "You came in for a follow-up of type 2 diabetes and high blood pressure." "Your blood sugar and \
blood pressure are still too high."
  medicine: category "Blood pressure medicine", name "Amlodipine", how_to_take "Take 1 pill (5 mg) each day."
  next_steps: "Go to the lab today for a blood test (BMP) and a urine test (microalbumin)." "Go to your \
follow-up visit in 4 weeks with Dr. Lee (Internal Medicine)."

- overview: 2 sentences (3 at most): why you came in, then what the doctor found, without repeating it.
- medicines: every medicine in the note. category: what a patient would call it, from <medicine_info> \
or the reason the note gives ("Blood pressure medicine", "Blood thinner", "Heart rate medicine"). name: exactly as written in the note. how_to_take: one direct \
instruction from the note, starting with a verb, with the amount in parentheses: "Take 1 pill (5 mg) each \
day." Only say "1 pill" for tablets with a single amount, and list it in clinician_flags to confirm. Empty \
if the note doesn't say. note: only if the note links a problem to this medicine.
- next_steps: direct commands. Say what to do, when, and with whom; not why. Start a bullet with "!" if it \
says when to get help sooner or call 911/999.
- The reader reads at about a grade {grade} level: use words most children know by grade {grade}, \
explain any other word, one idea per sentence, sentences under 15 words. Respectful, never childish.
- Say it the way you would say it out loud to the patient, not the way the note says it. Knowing every \
word isn't enough: "worsening breathlessness" uses common words but is doctor talk; say "your breathing \
has gotten worse". Use everyday verbs, not clinical nouns or qualifiers: "trouble breathing" (not \
"shortness of breath"), "very bad" (not "severe"), "a bladder infection" (not "acute cystitis"), "You will \
be sent to a heart doctor." (not "referral to cardiology"). Drop qualifiers that don't change what the \
patient does ("stage 2", "hemodynamically stable"; list them in left_out). Lead with plain words; a name the patient will hear \
again goes in parentheses after: "a heart scan (echocardiogram)", "blood tests (TSH, CBC and BMP)". \
Definitions: only the main idea, one short phrase.
- Every medical term or abbreviation is written [[original|plain words|med|source]], where the plain \
words say what it means. Hard everyday words: [[original|simpler words|word|source]]. source: the \
source given in <approved_words>, or "model" if none (it will be flagged).
- Never add, drop or soften a diagnosis, instruction, warning or follow-up. No advice or side effects \
the note doesn't contain. Numbers, doses and times stay exactly as written.
- left_out: what the note says that you left out, with a short reason. clinician_flags: anything \
unclear or missing (a dose or schedule).
- If a <visit_conversation> or <questionnaire> is given, it is context only: never take a diagnosis, \
medicine, dose or plan from it. Anything in it that disagrees with the note (another medicine, a different \
dose, an allergy) goes in clinician_flags.
"""


def claude_summary(note: str, grade: int, context: str = "") -> Summary:
    import anthropic
    from pydantic import BaseModel

    class Med(BaseModel):
        category: str
        name: str
        purpose: str
        how_to_take: str
        note: str

    class LeftOut(BaseModel):
        text: str
        reason: str

    class Rewrite(BaseModel):
        overview: list[str]
        medicines: list[Med]
        next_steps: list[str]
        left_out: list[LeftOut]
        clinician_flags: list[str]

    approved = sorted({f"{f.text} -> {f.replace_with or f.explain} [{f.source}]"
                       for f in analyze(note) if f.standard and (f.replace_with or f.explain)})
    info = {m: lookup(m, tries=1) for m in note_medicines(note)}
    med_info = "\n".join(f"{m}: {i['why']} [{i['url']}]" for m, i in info.items() if i.get("found"))
    messages = [{"role": "user", "content": f"<approved_words>\n{chr(10).join(approved)}\n</approved_words>\n\n"
                 f"<medicine_info>\n{med_info}\n</medicine_info>\n\n<clinician_note>\n{note}\n</clinician_note>"
                 + (f"\n\n{context}" if context else "")}]
    client = anthropic.Anthropic()

    def make(_level: int) -> Summary:
        response = client.beta.messages.parse(
            model=CLAUDE_MODEL, max_tokens=6000, output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            system=SUMMARY_PROMPT.format(grade=grade), messages=messages, output_format=Rewrite)
        if response.parsed_output is None:
            raise RuntimeError(f"no summary (stop_reason={response.stop_reason})")
        data = response.parsed_output
        steps = [s[1:].lstrip() if s.startswith("!") else s for s in data.next_steps]
        summary = Summary(
            [parse_markup(s) for s in data.overview],
            [Medicine(m.name, parse_markup(m.purpose), parse_markup(m.how_to_take) if m.how_to_take else [],
                      info.get(m.name.lower(), {}).get("url", ""), category=m.category,
                      note=parse_markup(m.note) if m.note else []) for m in data.medicines],
            [parse_markup(s) for s in steps], f"Claude ({CLAUDE_MODEL})",
            {i for i, s in enumerate(data.next_steps) if s.startswith("!")},
            [x.model_dump() for x in data.left_out], data.clinician_flags, grade=grade)
        checked = check(summary, note, grade)
        if not checked.ready:  # tell Claude what the reader wouldn't follow
            problems = "; ".join(f"{c['name']}: {c['detail']}" for c in checked.checks if not c["ok"])
            messages.extend([{"role": "assistant", "content": data.model_dump_json()},
                             {"role": "user", "content": f"A reader at grade {grade} would struggle: {problems}. "
                              f"Rewrite it so they can follow every sentence."}])
        return summary

    return best_of_tries(note, make, grade)


def summarize_note(note: str, use_claude: bool = False, grade: int = READER_GRADE, context: str = "") -> Summary:
    """context: the visit conversation and check-in answers, for Claude (the offline writer uses the note only;
    ai_at_70's cross-check compares them with the note)."""
    if use_claude:
        return claude_summary(note, grade, context)
    return best_of_tries(note, lambda level: offline_summary(note, level, grade), grade)


# ---------- HTML ----------

def source_name(key: str) -> dict:
    if not key or key == "note":
        return {}
    if key == MODEL:
        return {"name": "From model knowledge, not a standard source (verify)", "url": ""}
    if key == LWV:
        return {"name": "Living Word Vocabulary (Dale & O'Rourke; Brysbaert & Biemiller 2017)", "url": "https://osf.io/kz2px"}
    if key.startswith("http"):
        site, _, page = re.sub(r"^https?://(www\.)?", "", key).partition("/")
        name = {"medlineplus.gov": "MedlinePlus", "cdc.gov": "CDC"}.get(site, site)
        if "druginfo" in page:
            name += " drug information"
        elif page.startswith("ency/"):
            name += " Medical Encyclopedia"
        return {"name": f"{name}: {page.rstrip('/').split('/')[-1].removesuffix('.html') or site}", "url": key}
    info = lay_dictionary()[2].get(key, {})
    return {"name": info.get("name", key), "url": info.get("url", "")}


def sources_used(summary: Summary) -> list[dict]:
    out = {}
    for s in summary.terms():
        info = source_name(s.source)
        if info:
            out[info["name"]] = info
    for m in summary.medicines:
        if m.source:
            info = source_name(m.source)
            out[info["name"]] = info
    return sorted(out.values(), key=lambda s: (s["name"].startswith("From model"), s["name"]))


def checklist(summary: Summary) -> list[dict]:
    """Every medicine, changed word, left-out item and open question, for the clinician to tick."""
    items, seen = [], set()
    for m in summary.medicines:
        items.append({"group": "Medicines", "kind": "medicine", "original": f"{m.category} ({m.name})" if m.category else m.name,
                      "plain": clean(m.purpose),
                      "detail": clean(m.instruction) or "(not in the note: blank line on the printout)",
                      "source": source_name(m.source).get("name", ""), "flag": "; ".join(m.flags)})
    labels = {"med": "Medical terms", "word": "Everyday words", "keep": "Kept names"}
    for s in summary.terms():
        key = (s.kind, s.text.lower(), s.plain.lower())
        if s.kind == "drug" or key in seen:
            continue
        seen.add(key)
        items.append({"group": labels[s.kind], "kind": s.kind, "original": s.text, "plain": s.plain, "detail": "",
                      "source": source_name(s.source).get("name", ""), "flag": s.flag})
    if not summary.reading_ok:
        items.insert(0, {"group": "Reading level", "kind": "question", "original":
                         f"After {len(summary.tries)} tries: {summary.readability['describe']} "
                         "I have checked it reads simply enough for this patient.", "plain": "", "detail": "",
                         "source": "", "flag": "below target"})
    items += [{"group": "Questions for the clinician", "kind": "question", "original": q, "plain": "", "detail": "",
               "source": "", "flag": ""} for q in summary.clinician_flags]
    return items


def context(summary: Summary, name: str = "", visit_date: str = "", phone: str = "") -> dict:
    return {"s": summary, "name": name, "phone": phone,
            "visit_date": visit_date or date.today().strftime("%B %-d, %Y"),
            "checklist": checklist(summary), "sources": sources_used(summary)}


def render_page(summary: Summary, **details) -> str:
    return jinja().get_template("summary_page.html").render(**context(summary, **details))


def main() -> None:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())
    parser = argparse.ArgumentParser(description="Make a plain-language visit summary from a clinician note.")
    parser.add_argument("notes", type=Path, nargs="+")
    parser.add_argument("--name", default="")
    parser.add_argument("--grade", type=int, default=READER_GRADE, choices=[5, 6, 7], help="reader's grade level")
    parser.add_argument("--claude", action="store_true", help="write it with Claude (needs ANTHROPIC_API_KEY)")
    args = parser.parse_args()
    OUTPUT.mkdir(exist_ok=True)
    for path in args.notes:
        summary = summarize_note(path.read_text(), args.claude, args.grade)
        tries = " -> ".join(f"{t['known']}" for t in summary.tries)
        print(f"{path.name}: {summary.readability['describe']} (known per 100 by try: {tries}; "
              f"SMOG {summary.readability['smog']})")
        for c in summary.checks:
            if not c["ok"]:
                print(f"  [FAIL] {c['name']}: {c['detail']}")
        out = OUTPUT / f"{path.stem}.summary.html"
        out.write_text(render_page(summary, name=args.name))
        print(f"  -> {out}")
    sys.exit(0)


if __name__ == "__main__":
    main()
