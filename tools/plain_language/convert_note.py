"""Turn a clinician's note into plain language, using the dictionaries from build_dictionaries.py.

Layer 1 (offline, always runs): find jargon and swap or explain it from standard sources.
    - Abbreviations are expanded ("SOB" -> "shortness of breath"). Ambiguous ones are resolved
      from context ("furosemide BD" -> "twice a day") or flagged.
    - Terms with a standard plain word are replaced ("hypertension" -> "high blood pressure").
    - Terms that must stay (drug names, "heart failure", lab tests) are kept and explained in a
      word list ("creatinine: a normal waste product in your body").
    - Common words no standard source covers get a simple replacement from data/simple_words.json
      ("bilaterally" -> "on both sides", "abx" -> "antibiotics", "5/7" -> "5 days"), always
      flagged "no standard source". Other jargon is just flagged (CLAUDE.md rule).
    - Dosing abbreviations (BID, BD, PRN...) are expanded and flagged for the clinician.
Layer 2 (Claude, when ANTHROPIC_API_KEY is set): rewrite the whole note in short, plain
    sentences at the target reading level, grounded in layer 1's word choices, then check that
    every number and drug name survived.

    python tools/plain_language/convert_note.py note.txt [--claude] [--grade 5]

Writes output/<name>.plain.md (clinician review copy) and output/<name>.plain.json.
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import textstat
from wordfreq import zipf_frequency

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUTPUT = HERE / "output"

TARGET_GRADE = 5  # CLAUDE.md: 5th-7th grade, ideally 5th or lower (SMOG)
MAX_GRADE = 7
COMMON_WORD_ZIPF = 3.0   # below this a word is uncommon enough to count as possible jargon
PLAIN_PHRASE_ZIPF = 3.5  # an abbreviation's expansion is only used in the text if it's this everyday
HEADING_WORD_ZIPF = 5.0  # ALL-CAPS tokens this common are headings/words ("PLAN"), not abbreviations
MEDICAL_PREFIXES = ("un", "post", "pre", "non", "peri", "hyper", "hypo", "dys", "intra", "inter", "trans", "sub", "anti", "brady", "tachy")
DOSING_WORDS = re.compile(r"\b(a day|daily|hours?|needed|necessary|bedtime|morning|night|every|weekly|times)\b", re.I)


# ---------- dictionaries ----------

@lru_cache(maxsize=1)
def lay_dictionary() -> tuple[dict, dict, dict]:
    """(case-sensitive abbreviations, lowercase terms, source info)."""
    path = DATA / "lay_dictionary.json"
    if not path.exists():
        sys.exit("Run build_dictionaries.py first.")
    data = json.loads(path.read_text())
    abbrevs, terms = {}, {}
    for e in data["entries"]:
        # Lab-test short names ("BNP", "HbA1c") are matched like abbreviations.
        is_abbrev = e.get("kind") == "abbreviation" or any(c.isupper() for c in e["term"])
        (abbrevs if is_abbrev else terms)[e["term"]] = e
    aliases = json.loads((DATA / "simple_words.json").read_text()).get("aliases", {})
    for alias, target in aliases.items():  # "urine microalbumin" -> MedlinePlus "microalbumin creatinine ratio"
        if target in terms and alias not in terms:
            terms[alias] = {**terms[target], "term": alias}
    for e in data["entries"]:
        for k in ("plain", "explain"):
            if e.get(k):
                e[k] = re.sub(r"\s+([,.;:)])", r"\1", e[k])  # "blood sugar , levels" -> "blood sugar, levels"
    return abbrevs, terms, data["sources"]


@lru_cache(maxsize=1)
def simple_words() -> dict:
    """Hand-made fallback wording (model knowledge, always flagged); see data/simple_words.json."""
    return json.loads((DATA / "simple_words.json").read_text())


@lru_cache(maxsize=1)
def medical_vocab() -> set[str]:
    return set((DATA / "medical_vocab.txt").read_text().split("\n"))


@lru_cache(maxsize=1)
def drug_names() -> set[str]:
    names = json.loads((DATA / "raw" / "rxnorm_display_names.json").read_text())
    return {n.lower() for n in names if re.fullmatch(r"[A-Za-z][A-Za-z-]{3,}", n)} | set(simple_words()["medications"])


@lru_cache(maxsize=1)
def term_pattern() -> re.Pattern:
    """One regex for all non-abbreviation terms, longest first so 'chronic kidney disease' beats 'kidney'."""
    _, terms, _ = lay_dictionary()

    def usable(term: str, e: dict) -> bool:
        if not (e.get("plain") or e.get("explain")) or e.get("context_dependent") or len(term) <= 3:
            return False
        if e.get("kind") == "wording":  # plainlanguage.gov: only long words, where context matters least
            return " " in term or textstat.syllable_count(term) >= 3
        # Single everyday words ("access", "cough") aren't jargon even if a source lists them.
        return " " in term or zipf_frequency(term, "en") < 3.8

    usable_terms = sorted((t for t, e in terms.items() if usable(t, e)), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(map(re.escape, usable_terms)) + r")\b", re.IGNORECASE)


@lru_cache(maxsize=1)
@lru_cache(maxsize=1)
def phrase_patterns() -> list[tuple[re.Pattern, str]]:
    """Whole clinical phrases -> everyday phrases ("worsening breathlessness" -> "your breathing has gotten worse"),
    longest first; keys starting with "~" are regular expressions."""
    phrases = simple_words().get("phrases", {})
    keys = sorted(phrases, key=len, reverse=True)
    return [(re.compile(rf"(?<![\w-])(?:{k[1:] if k.startswith('~') else re.escape(k)})(?![\w-])", re.I), phrases[k])
            for k in keys]


def simple_term_pattern() -> re.Pattern:
    terms = sorted(simple_words()["terms"], key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(map(re.escape, terms)) + r")\b", re.IGNORECASE)


# ---------- analysis ----------

@dataclass
class Finding:
    text: str                 # exactly as written in the note
    start: int
    end: int
    kind: str                 # abbreviation | term | phrase (whole clinical phrase) | wording (everyday, non-medical) | medication | jargon
    replace_with: str | None = None   # plain wording to put in the text (None = keep)
    explain: str | None = None        # plain explanation for the word list
    source: str | None = None
    source_url: str | None = None
    standard: bool = False            # from an approved plain-language source (CLAUDE.md)
    flag: str | None = None           # reason a clinician should look


@dataclass
class Conversion:
    original: str
    plain_text: str
    review_text: str
    findings: list[Finding] = field(default_factory=list)
    readability: dict = field(default_factory=dict)
    claude: dict | None = None


def is_common_word(word: str) -> bool:
    w = word.lower()
    return any(zipf_frequency(f, "en") >= COMMON_WORD_ZIPF for f in (w, w[:-1] if w.endswith("s") else w))


def looks_like_jargon(word: str) -> bool:
    """Word frequency alone can't split 'numbness' (2.9) from 'supple' (2.9), so in the borderline
    band also look at the word's shape: everyday English endings and compounds are plain."""
    w = word.lower()
    z = max(zipf_frequency(w, "en"), zipf_frequency(w[:-1], "en") if w.endswith("s") else 0)
    if z >= COMMON_WORD_ZIPF:
        return False
    if z < 2.5:
        return True
    if w.endswith(("ness", "ing")):  # shortness, numbness, wheezing, swelling
        return False
    if w.startswith(MEDICAL_PREFIXES):  # postoperative, nontender, hypotensive
        return True
    # Compounds of two everyday words: followup, pacemaker, midline
    return not any(zipf_frequency(w[:i], "en") >= 3.5 and zipf_frequency(w[i:], "en") >= 3.5
                   for i in range(2, len(w) - 1))


def phrase_plainness(phrase: str) -> float:
    words = re.findall(r"[a-z]+", phrase.lower())
    return sum(zipf_frequency(w, "en") for w in words) / len(words) if words else 0.0


def strip_notes(text: str) -> str:
    """'history (of)' -> 'history'; 'by mouth, that is, orally' -> 'by mouth'."""
    text = re.sub(r"\s*\([^)]*\)", "", text)
    return re.split(r",\s*(?:that is|i\.e\.|or|formerly|also)\b", text)[0].strip()


def plain_for(phrase: str) -> tuple[str | None, str | None, dict | None]:
    """Standard-source plain wording or explanation for a phrase, e.g. an abbreviation's expansion."""
    _, terms, _ = lay_dictionary()
    entry = terms.get(phrase.lower())
    if entry and entry.get("standard"):
        return entry.get("plain"), entry.get("explain"), entry
    return None, None, None


def choose_meaning(entry: dict, note: str, start: int) -> tuple[str | None, str | None]:
    """Pick an abbreviation's meaning. Returns (meaning, flag)."""
    if entry.get("expands_to"):
        return entry["expands_to"], None
    options = entry.get("meanings", [])
    line_start = note.rfind("\n", 0, start) + 1
    is_heading = not note[line_start:start].strip() and note[start:start + 12].split()[0].endswith(":")
    if is_heading and "past medical history" in options:  # "PMH:" heading
        return "past medical history", None
    before = note[max(0, start - 40):start].lower()
    dosing = [m for m in options if DOSING_WORDS.search(m)]
    near_drug_or_dose = bool(re.search(r"\d|mg|mcg|ml\b", before)) or any(w in drug_names() for w in re.findall(r"[a-z]+", before))
    if dosing and near_drug_or_dose:
        return dosing[0], None
    return None, f"ambiguous abbreviation: could mean {', '.join(options[:3])}"


def analyze(note: str) -> list[Finding]:
    abbrevs, terms, sources = lay_dictionary()
    vocab, drugs, simple = medical_vocab(), drug_names(), simple_words()
    findings: list[Finding] = []
    taken = [False] * len(note)

    def claim(f: Finding) -> None:
        if not any(taken[f.start:f.end]):
            findings.append(f)
            for i in range(f.start, f.end):
                taken[i] = True

    # 0. Whole clinical phrases, said the way a person would say them (model knowledge, flagged). A standard
    # source's plain wording for the exact same phrase still wins.
    matches = [m for pattern, _ in phrase_patterns() for m in pattern.finditer(note)]
    plain_of = {id(pattern): plain for pattern, plain in phrase_patterns()}
    for m in sorted(matches, key=lambda m: (m.start() - m.end(), m.start())):  # longest match wins
        entry = terms.get(m.group(0).lower(), {})
        if entry.get("standard") and entry.get("plain"):
            continue  # a standard source's plain word for this exact phrase (an explanation alone doesn't count)
        claim(Finding(m.group(0), m.start(), m.end(), "phrase", replace_with=m.expand(plain_of[id(m.re)]),
                      source=simple["source"], flag="no standard source"))

    # 1. Multi-word and single terms with a standard plain word or explanation.
    for m in term_pattern().finditer(note):
        e = terms[m.group(0).lower()]
        if m.group(0).lower() in drugs and e.get("kind") != "lab_test":
            continue  # medicines are kept exactly as written (step 3); "creatinine" is a lab test
        claim(Finding(m.group(0), m.start(), m.end(), "wording" if e.get("kind") == "wording" else "term",
                      replace_with=e.get("plain"),
                      explain=e.get("explain") if not e.get("plain") else None, source=e["source"],
                      source_url=e.get("source_url"), standard=e.get("standard", False)))

    # 2. Abbreviations (case-sensitive; mixed-case ones like "HbA1c" also match in any case).
    folded = {k.lower(): v for k, v in abbrevs.items() if any(c.islower() for c in k)}
    for m in re.finditer(r"(?<![\w/.])(?:(?:[A-Za-z]\.){2,}|[A-Za-z0-9][A-Za-z0-9+&]*(?:/[A-Za-z])?)(?![\w])", note):
        tok = m.group(0)
        # Also try "U+Es" -> "U&E", "LFTs" -> "LFT", "t.i.d." -> "TID"
        candidates = [tok, tok.replace("+", "&")]
        if "." in tok:
            candidates.append(tok.replace(".", "").upper())
        candidates += [c[:-1] for c in candidates if c.endswith("s") and len(c) > 2]
        entry = next((abbrevs.get(c) or folded.get(c.lower()) for c in candidates
                      if abbrevs.get(c) or folded.get(c.lower())), None)
        if not entry or tok.isdigit():
            continue
        if tok.islower() and is_common_word(tok) and not re.search(r"[/.]", tok):  # but "y/o", "b.i.d."
            continue  # ordinary word that happens to be an abbreviation ("am", "ice")
        if tok.isupper() and zipf_frequency(tok.lower(), "en") >= HEADING_WORD_ZIPF:
            continue  # "PLAN", "OR", "ALL" in headings
        meaning, flag = choose_meaning(entry, note, m.start())
        default = next((simple["abbreviations"][c] for c in candidates if c in simple["abbreviations"]), None)
        if meaning and default in entry.get("meanings", []):
            meaning = default  # "PRN": "as needed" rather than "as necessary"
        if default and (meaning is None or not entry.get("standard")) and entry.get("kind") != "lab_test":
            # "CT", "BP", "DH": several listed meanings, but one is the usual one in a clinic note.
            flag = f"{flag}; read as \"{default}\", confirm" if flag else "no standard source"
            claim(Finding(tok, m.start(), m.end(), "abbreviation", replace_with=default, source=simple["source"],
                          flag=flag if not DOSING_WORDS.search(default)
                          else "dosing abbreviation: confirm the exact times with the clinician (CLAUDE.md)"))
            continue
        if entry.get("kind") == "lab_test":
            meaning = None  # lab names stay as on the lab report ("BUN"); the explanation does the work
        meaning = strip_notes(meaning) if meaning else None
        plain, explain, plain_entry = plain_for(meaning) if meaning else (None, None, None)
        if meaning and DOSING_WORDS.search(meaning):
            flag = "dosing abbreviation: confirm the exact times with the clinician (CLAUDE.md)"
        if entry.get("standard"):  # a MedlinePlus abbreviation like HTN or MI, or a lab test like BNP
            plain, explain = entry.get("plain") or plain, entry.get("explain") or explain
        if plain:
            explain = None  # replaced by an everyday word: nothing left to explain
        elif meaning and (phrase_plainness(meaning) < PLAIN_PHRASE_ZIPF
                          or any(zipf_frequency(w, "en") < 2.5 for w in re.findall(r"[a-z]+", meaning.lower()))):
            # "BNP" -> "brain natriuretic peptide" is no easier to read: keep it and explain it.
            explain = explain or f"short for {meaning}"
            meaning = None
            if not entry.get("standard"):
                flag = flag or "no standard source for a plain explanation"
        claim(Finding(tok, m.start(), m.end(), "abbreviation",
                      replace_with=plain or meaning, explain=explain,
                      source=(plain_entry or entry)["source"] if (plain or entry.get("standard")) else entry["source"],
                      source_url=(plain_entry or entry).get("source_url"),
                      standard=bool(plain or entry.get("standard")), flag=flag))

    # 2b. Clinic shorthand no standard source lists: "abx", "c/o", "5/7" (5 days), "? LRTI" (possible).
    unsourced = "no standard source"
    for key, plain in simple["abbreviations"].items():
        flag = unsourced
        if DOSING_WORDS.search(plain):
            flag = "dosing abbreviation: confirm the exact times with the clinician (CLAUDE.md)"
            if key == "OD":
                flag += "; on eye-drop orders OD means right eye"
        for m in re.finditer(r"(?<![\w/.-])" + re.escape(key) + r"(?![\w/])", note):
            claim(Finding(m.group(0), m.start(), m.end(), "abbreviation", replace_with=plain,
                          source=simple["source"], flag=flag))
    for m in re.finditer(r"\b[qQ]\.?\s?(\d+)\s?(?:h|hr|hrs|hours?)\b\.?", note):  # q4h, q.3 h.
        claim(Finding(m.group(0), m.start(), m.end(), "abbreviation", replace_with=f"every {m.group(1)} hours",
                      source=simple["source"], flag="dosing abbreviation: confirm the exact times with the clinician (CLAUDE.md)"))
    units = {"7": ("day", "days"), "52": ("week", "weeks"), "12": ("month", "months")}
    for m in re.finditer(r"(?<![\d/.])([1-9]\d?)/(7|52|12)(?![\d/])", note):
        n = m.group(1)
        unit = units[m.group(2)][n != "1"]
        claim(Finding(m.group(0), m.start(), m.end(), "abbreviation", replace_with=f"{n} {unit}",
                      source=simple["source"], flag=f"{unsourced}: UK shorthand for {n} {unit}, confirm"))
    for m in re.finditer(r"(?<![\w?])\?\s*(?=[A-Za-z])", note):
        claim(Finding(m.group(0), m.start(), m.end(), "abbreviation", replace_with="possible ",
                      source=simple["source"], flag=f"{unsourced}: \"?\" read as \"possible\", confirm"))

    # 2c. Common words no standard source covers, with a simple replacement (always flagged).
    for m in simple_term_pattern().finditer(note):
        e = simple["terms"][m.group(0).lower()]
        claim(Finding(m.group(0), m.start(), m.end(), "term", replace_with=e.get("plain"), explain=e.get("explain"),
                      source=simple["source"], flag=unsourced))

    # 3. Drug names stay exactly as written (CLAUDE.md); list them for the clinician.
    lab_tests = {t for t, e in terms.items() if e.get("kind") == "lab_test"}
    for m in re.finditer(r"[A-Za-z][A-Za-z-]{3,}", note):
        w = m.group(0).lower()
        if w in drugs and not is_common_word(w) and w not in lab_tests:  # "creatinine" is a lab, not a drug
            claim(Finding(m.group(0), m.start(), m.end(), "medication", source="RxNorm",
                          flag="medication: name kept as written; explain its purpose only if the clinician did"))

    # 4. Remaining hard words: medical but uncommon, or not a known word at all (e.g. misspellings).
    for m in re.finditer(r"[A-Za-z][a-z]{4,}", note):
        w = m.group(0).lower()
        if w in simple["plain_words"] or not looks_like_jargon(w):
            continue
        known = w in vocab or w.rstrip("s") in vocab or zipf_frequency(w, "en") > 0
        reason = "no standard source" if known else "unrecognized word (misspelling?)"
        claim(Finding(m.group(0), m.start(), m.end(), "jargon", flag=reason))

    return sorted(findings, key=lambda f: f.start)


# ---------- conversion ----------

def match_case(note: str, start: int, original: str, replacement: str, kind: str) -> str:
    """Capitalize only where a sentence or line starts ("SOB" mid-sentence -> "shortness of breath")."""
    before = note[:start].rstrip(" \t")
    after_dotted_abbrev = re.search(r"(?:\b[A-Za-z]\.){2,}$|\b(?:mg|ml|mcg|[0-9])\.?$", before) is not None  # "b.i.d. p.o."
    question = before.endswith("?") and before[-2:-1].isalnum()  # "Worse?" ends a sentence; "URTI/? LRTI" doesn't
    sentence_start = not before or ((before[-1] in ".!\n:-" or question) and not after_dotted_abbrev)
    if sentence_start or (kind in ("term", "wording") and original[:1].isupper()):
        return replacement[:1].upper() + replacement[1:]
    if kind == "abbreviation" and re.match(r"[A-Z][a-z]", replacement):
        return replacement[0].lower() + replacement[1:]  # "with DM2" -> "with type 2 diabetes"
    return replacement


def convert(note: str) -> Conversion:
    findings = analyze(note)
    plain, review, pos = [], [], 0
    for f in findings:
        plain.append(note[pos:f.start])
        review.append(note[pos:f.start])
        if f.replace_with:
            new = match_case(note, f.start, f.text, f.replace_with, f.kind)
            plain.append(new)
            review.append(f"**{new}** ~~{f.text}~~")
        else:
            plain.append(f.text)
            review.append(f"`{f.text}`" if f.flag else f.text)
        pos = f.end
    plain.append(note[pos:])
    review.append(note[pos:])
    plain_text = "".join(plain)
    return Conversion(note, plain_text, "".join(review), findings,
                      {"original": reading_level(note), "plain": reading_level(plain_text)})


def reading_level(text: str) -> dict:
    """SMOG grade (CLAUDE.md's measure for English) plus Flesch-Kincaid for comparison."""
    return {"smog": round(textstat.smog_index(text), 1), "flesch_kincaid": round(textstat.flesch_kincaid_grade(text), 1),
            "hard_words": textstat.difficult_words(text), "words": textstat.lexicon_count(text)}


# ---------- layer 2: Claude rewrite ----------

CLAUDE_MODEL = "claude-opus-5-5"
REWRITE_PROMPT = """\
You rewrite clinician notes about older adults into plain language for the patient and their \
family. Follow these rules exactly:

- Reading level: 5th to 7th grade, ideally grade {grade} or lower (SMOG). Short sentences, \
common words, active voice. Respectful, never childish.
- Use the word choices in <approved_words> wherever those terms come up. They come from CDC \
Everyday Words and MedlinePlus. Do not invent other definitions for those terms.
- For any other medical term you must simplify, use a simple replacement and list it in \
"unsourced_terms" so the clinician can check it.
- Never add, drop or soften any diagnosis, test, instruction, warning or follow-up. Do not add \
advice, side effects or explanations the clinician did not write.
- Drug names, doses, numbers, dates and times stay exactly as written. If a dose or schedule is \
unclear (for example "BD" or "PRN"), keep the meaning and list it in "flags".
- Lead with what matters most: what was found, what to do, when to come back, and when to call \
the doctor or 911 (only if the note says so).
- Write "you" for the patient. Leave out content the patient does not need (abbreviated \
history headings, internal shorthand) only if nothing clinically meaningful is lost; otherwise \
include it in plain words.
"""


def rewrite_with_claude(conversion: Conversion, grade: int) -> dict:
    import anthropic
    from pydantic import BaseModel

    class Rewrite(BaseModel):
        plain_text: str
        unsourced_terms: list[str]
        flags: list[str]

    approved = sorted({f"{f.text} -> {f.replace_with or f.text}" + (f" ({f.explain})" if f.explain else "")
                       + f" [{f.source}]" for f in conversion.findings if f.standard})
    response = anthropic.Anthropic().beta.messages.parse(
        model=CLAUDE_MODEL,
        max_tokens=8000,
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=REWRITE_PROMPT.format(grade=grade),
        messages=[{"role": "user", "content": "<approved_words>\n" + "\n".join(approved) + "\n</approved_words>\n\n"
                   f"<clinician_note>\n{conversion.original}\n</clinician_note>"}],
        output_format=Rewrite,
    )
    if response.parsed_output is None:
        return {"error": f"no rewrite (stop_reason={response.stop_reason})"}
    out = response.parsed_output.model_dump()
    # Safety check: every number and drug name in the note must survive the rewrite.
    numbers = set(re.findall(r"\d+(?:\.\d+)?", conversion.original))
    meds = {f.text.lower() for f in conversion.findings if f.kind == "medication"}
    out["missing_numbers"] = sorted(n for n in numbers if n not in out["plain_text"])
    out["missing_medications"] = sorted(m for m in meds if m not in out["plain_text"].lower())
    out["readability"] = reading_level(out["plain_text"])
    return out


# ---------- output ----------

def render_review(c: Conversion, name: str, sources: dict) -> str:
    lines = [f"# Plain-language conversion: {name}", "",
             "Clinician review copy. **Bold** = replaced (original struck through); `code` = kept and flagged.", "",
             "## Reading level (SMOG grade)", "",
             f"- Original note: **{c.readability['original']['smog']}** (Flesch-Kincaid {c.readability['original']['flesch_kincaid']})",
             f"- After word swaps: **{c.readability['plain']['smog']}** (Flesch-Kincaid {c.readability['plain']['flesch_kincaid']})"]
    if c.claude and "readability" in c.claude:
        lines.append(f"- After Claude rewrite: **{c.claude['readability']['smog']}** (target {TARGET_GRADE}-{MAX_GRADE})")
    lines += ["", "## Plain version (word swaps)", "", c.plain_text.strip(), "",
              "## Review version", "", c.review_text.strip(), ""]
    if c.claude and "plain_text" in c.claude:
        lines += ["## Plain version (Claude rewrite)", "", c.claude["plain_text"], ""]
        for key in ("missing_numbers", "missing_medications", "unsourced_terms", "flags"):
            if c.claude.get(key):
                lines.append(f"- **{key.replace('_', ' ')}:** {', '.join(c.claude[key])}")
        lines.append("")

    explained = {f.text.lower(): f for f in c.findings if f.explain}
    if explained:
        lines += ["## What these words mean", ""]
        lines += [f"- **{f.text}**: {f.explain} *({f.source})*" for f in explained.values()]
        lines.append("")
    flagged = {(f.text, f.flag): f for f in c.findings if f.flag}
    if flagged:
        lines += ["## Please check", ""]
        lines += [f"- `{f.text}`: {f.flag}" for f in flagged.values()]
        lines.append("")
    used = sorted({f.source for f in c.findings if f.source and (f.replace_with or f.explain)})
    lines += ["## Sources used for word choices", ""]
    lines += [f"- {s}: {sources.get(s, {}).get('url', '')}" for s in used] or ["- none"]
    return "\n".join(lines) + "\n"


def summarize(c: Conversion) -> dict:
    kinds = {}
    for f in c.findings:
        kinds[f.kind] = kinds.get(f.kind, 0) + 1
    return {
        "found": len(c.findings), "by_kind": kinds,
        "replaced": sum(1 for f in c.findings if f.replace_with),
        "explained": sum(1 for f in c.findings if f.explain and not f.replace_with),
        "standard_source": sum(1 for f in c.findings if f.standard),
        "flagged": sum(1 for f in c.findings if f.flag),
        "smog_before": c.readability["original"]["smog"], "smog_after": c.readability["plain"]["smog"],
    }


def convert_file(path: Path, use_claude: bool, grade: int) -> tuple[Conversion, Path]:
    note = path.read_text()
    c = convert(note)
    if use_claude:
        try:
            c.claude = rewrite_with_claude(c, grade)
        except Exception as e:  # missing key, network...
            c.claude = {"error": f"{e.__class__.__name__}: {e}"}
    OUTPUT.mkdir(exist_ok=True)
    md = OUTPUT / f"{path.stem}.plain.md"
    md.write_text(render_review(c, path.stem, lay_dictionary()[2]))
    (OUTPUT / f"{path.stem}.plain.json").write_text(json.dumps(
        {"summary": summarize(c), **asdict(c)}, indent=1, ensure_ascii=False))
    return c, md


def main() -> None:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())
    parser = argparse.ArgumentParser(description="Convert a clinician note into plain language.")
    parser.add_argument("notes", type=Path, nargs="+", help="text file(s) with a clinician note")
    parser.add_argument("--claude", action="store_true", help="also do a full Claude rewrite (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--grade", type=int, default=TARGET_GRADE, help="target reading grade for the Claude rewrite")
    args = parser.parse_args()
    for path in args.notes:
        c, md = convert_file(path, args.claude, args.grade)
        s = summarize(c)
        print(f"{path.name}: {s['found']} terms found, {s['replaced']} replaced, {s['explained']} explained, "
              f"{s['flagged']} flagged; SMOG {s['smog_before']} -> {s['smog_after']}  ->  {md}")
        if c.claude and "error" in c.claude:
            print(f"  Claude rewrite skipped: {c.claude['error']}")


if __name__ == "__main__":
    main()
