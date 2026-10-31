"""The patient visit summary: a short story of the visit in plain words, checked before it can print.

A summary is five sections of sentences (CLAUDE.md order, primary care):
    Why you came in / What the doctor found / What to do now / Other notes from your visit / Future visits
Inside a sentence, every changed word is written as
    [[original|plain words|kind|source]]
    kind:   med  = medical term, defined in plain words          (shown struck through + green)
            word = hard everyday word, said more simply           (shown struck through + blue)
            keep = name that must stay (lab test), explained after it
            drug = medicine name, kept exactly (CLAUDE.md); plain part only if the note says what it's for
    source: a key from data/lay_dictionary.json ("MedlinePlus", "CDC Everyday Words", "plainlanguage.gov"...),
            a specific medlineplus.gov / cdc.gov page URL, "note" (the clinician's own words), or "model"
            (model knowledge: flagged "no standard source" for the clinician).
A sentence that starts with "!" is a when-to-get-help instruction and prints in bold.

Where summaries come from:
    rewrites/<note>.json   written for a specific note (e.g. by Claude in a Claude Code session) and
                           checked with this script until it passes
    --claude               the Anthropic API writes one and retries with the checker's feedback
    otherwise              the offline rule-based draft from make_printout.py (usually fails the
                           reading-level check, so it isn't printed)

The gate (nothing prints unless all pass): SMOG grade <= 7 (CLAUDE.md: 5th-7th, ideally 5th or lower),
every number and medicine in the note is in the summary or listed as left out, no medical jargon or
abbreviation is left in the patient's text, and every changed word has plain words.

    python Ethan/conversion_library/visit_summary.py check rewrites/day1_consultation07.json
    python Ethan/conversion_library/visit_summary.py render <note.txt | rewrite.json> [--name "Mary Smith"] [--claude]
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import textstat
from wordfreq import zipf_frequency

from convert_note import MAX_GRADE, OUTPUT, TARGET_GRADE, analyze, convert, drug_names, lay_dictionary, simple_words
from make_printout import FLAG_OFF, FLAG_ON, INDEX, WHEN_TO_CALL, WORD_OFF, WORD_ON, jinja, make_printout, strip_markers

HERE = Path(__file__).resolve().parent
REWRITES = HERE / "rewrites"

SECTIONS = {
    "reason": "Why you came in",
    "diagnosis": "What the doctor found",
    "todo": "What to do now",
    "other": "Other notes from your visit",
    "future": "Future visits",
}
# make_printout's sections -> summary sections
FROM_DRAFT = {"reason": "reason", "found": "diagnosis", "found_plan": "diagnosis", "tests": "diagnosis",
              "plan": "todo", "meds": "todo", "followup": "future", "course": "other", "history": "other",
              "other": "other"}
KINDS = ("med", "word", "keep", "drug")
EVERYDAY_ZIPF = 3.5  # single words at least this common aren't counted as leftover jargon ("hypertension" is 3.4)
MARKUP = re.compile(r"\[\[([^\]|]*)\|([^\]|]*)\|([^\]|]*)\|([^\]|]*)\]\]")


# ---------- model ----------

@dataclass
class Segment:
    text: str                      # plain text, or the original term for a term segment
    kind: str = "text"             # text | med | word | keep | drug
    plain: str = ""                # plain words for the patient
    source: str = ""
    flag: str = ""


@dataclass
class Summary:
    sections: dict[str, list[list[Segment]]]
    origin: str                                    # who wrote it
    left_out: list[dict] = field(default_factory=list)          # {"text", "reason"} not on the printout
    clinician_flags: list[str] = field(default_factory=list)    # questions for the clinician
    urgent: set = field(default_factory=set)                    # (section, index) of when-to-get-help sentences
    checks: list[dict] = field(default_factory=list)            # gate results: {"ok", "name", "detail"}
    readability: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    def terms(self) -> list[Segment]:
        return [s for items in self.sections.values() for item in items for s in item if s.kind != "text"]


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


def patient_text(summary: Summary) -> str:
    return "\n".join(clean(item) for items in summary.sections.values() for item in items)


# ---------- parsing ----------

def parse_markup(sentence: str) -> list[Segment]:
    segments, pos = [], 0
    for m in MARKUP.finditer(sentence):
        if m.start() > pos:
            segments.append(Segment(sentence[pos:m.start()]))
        original, plain, kind, source = (g.strip() for g in m.groups())
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r} in {m.group(0)}")
        flag = "no standard source (model knowledge, verify)" if source == "model" else ""
        segments.append(Segment(original, kind, plain, source, flag))
        pos = m.end()
    if pos < len(sentence):
        segments.append(Segment(sentence[pos:]))
    if "[[" in "".join(s.text for s in segments if s.kind == "text"):
        raise ValueError(f"broken [[...]] in: {sentence}")
    return segments


def from_rewrite(data: dict, origin: str) -> Summary:
    sections, urgent = {}, set()
    for key in SECTIONS:
        sections[key] = []
        for i, sentence in enumerate(data.get("sections", {}).get(key, [])):
            if sentence.startswith("!"):
                urgent.add((key, i))
                sentence = sentence[1:].lstrip()
            sections[key].append(parse_markup(sentence))
    return Summary(sections, origin, data.get("left_out", []), data.get("clinician_flags", []), urgent)


def source_key(name: str | None) -> str:
    return "model" if name and "model knowledge" in name else (name or "")


def from_draft(note: str) -> Summary:
    """The offline rule-based draft (make_printout.py) in summary form."""
    p = make_printout(note)
    marked = re.compile(f"([{FLAG_ON}{WORD_ON}])(.*?){INDEX}(\\d+)([{FLAG_OFF}{WORD_OFF}])")
    sections, urgent = {k: [] for k in SECTIONS}, set()
    for section in p.sections:
        key = FROM_DRAFT[section.key]
        for item in section.items:
            segments, pos = [], 0
            for m in marked.finditer(item):
                if m.start() > pos:
                    segments.append(Segment(strip_markers(item[pos:m.start()])))
                f, shown = p.findings[int(m.group(3))], m.group(2)
                if f.kind == "medication":
                    seg = Segment(shown, "drug", "", "note")
                elif f.source == "MedlinePlus Lab Tests" and not f.replace_with:
                    seg = Segment(shown, "keep", f.explain or "", f.source)
                else:
                    seg = Segment(f.text, "word" if f.kind == "wording" else "med",
                                  shown if f.replace_with else (f.explain or ""), source_key(f.source))
                seg.flag = f.flag or ""
                segments.append(seg)
                pos = m.end()
            if pos < len(item):
                segments.append(Segment(strip_markers(item[pos:])))
            if section.key == "followup" and WHEN_TO_CALL.search(strip_markers(item)):
                urgent.add((key, len(sections[key])))
            sections[key].append(segments)
    left_out = [{"text": f"{h}: {t}", "reason": "exam findings are for the clinician"} for h, t in p.left_off]
    return Summary(sections, "Offline rule-based draft (make_printout.py)", left_out)


# ---------- the gate ----------

def numbers_in(text: str) -> set[str]:
    text = re.sub(r"(?m)^\s*\d+[.)]\s", "", text)  # list numbering "1." isn't content
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def note_medicines(note: str) -> set[str]:
    """Medicine names in the note: RxNorm names that aren't everyday words ("aspirin" counts, "water" doesn't)."""
    found = {f.text.lower() for f in analyze(note) if f.kind == "medication"}
    lab_tests = {t for t, e in lay_dictionary()[1].items() if e.get("kind") == "lab_test"}
    for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", note):
        if w.lower() in drug_names() and zipf_frequency(w.lower(), "en") < 4.5 and w.lower() not in lab_tests:
            found.add(w.lower())
    return found


def leftover_jargon(summary: Summary) -> list[str]:
    """Medical words or abbreviations still in the patient's text (outside kept names)."""
    kept = {s.text.lower() for s in summary.terms() if s.kind in ("keep", "drug")}
    left = set()
    for f in analyze(patient_text(summary)):
        word = f.text.lower()
        if f.kind == "medication" or word in kept or any(word in k for k in kept):
            continue
        if f.kind == "wording" or (f.kind == "term" and not f.replace_with and f.explain):
            continue  # a long everyday word, or a plain term MedlinePlus names (e.g. "heart failure")
        if f.kind == "term" and " " not in word and zipf_frequency(word, "en") >= EVERYDAY_ZIPF:
            continue  # "medicines", "arthritis": MedlinePlus topic names that are everyday words
        left.add(f.text)
    return sorted(left)


def reading_level(text: str) -> dict:
    sentences = textstat.sentence_count(text)
    return {"smog": round(textstat.smog_index(text), 1) if sentences >= 3 else None,
            "flesch_kincaid": round(textstat.flesch_kincaid_grade(text), 1), "sentences": sentences,
            "words": textstat.lexicon_count(text),
            "long_words": sorted({w for w in re.findall(r"[A-Za-z'-]+", text) if textstat.syllable_count(w) >= 3},
                                 key=str.lower)}


def check(summary: Summary, note: str) -> Summary:
    text = patient_text(summary)
    r = summary.readability = {"summary": reading_level(text), "note": reading_level(note)}
    smog = r["summary"]["smog"]
    accounted = text + " " + " ".join(x["text"] for x in summary.left_out)
    missing_numbers = sorted(numbers_in(convert(note).plain_text) - numbers_in(accounted), key=float)
    missing_meds = sorted(m for m in note_medicines(note) if m not in accounted.lower())
    unresolved = sorted({s.text for s in summary.terms() if s.kind in ("med", "word") and not s.plain})
    jargon = leftover_jargon(summary)
    summary.checks = [
        {"name": "Reading level", "ok": smog is not None and smog <= MAX_GRADE,
         "detail": (f"SMOG {smog} (target {TARGET_GRADE}-{MAX_GRADE})" if smog is not None
                    else "too short to score (needs 3+ sentences)")},
        {"name": "Numbers kept", "ok": not missing_numbers,
         "detail": "all numbers from the note are here" if not missing_numbers
         else "missing: " + ", ".join(missing_numbers)},
        {"name": "Medicines kept", "ok": not missing_meds,
         "detail": "all medicine names from the note are here" if not missing_meds
         else "missing: " + ", ".join(missing_meds)},
        {"name": "No medical jargon left", "ok": not jargon and not unresolved,
         "detail": "none found" if not (jargon or unresolved)
         else "still in the text: " + ", ".join(sorted(set(jargon) | set(unresolved)))},
    ]
    return summary


# ---------- Claude (when ANTHROPIC_API_KEY is set) ----------

CLAUDE_MODEL = "claude-opus-5-5"
SUMMARY_PROMPT = """\
You write a visit summary for an older adult after a primary care visit, from the clinician's \
note only. It is read by the patient and their family. Tell the story of the visit in order, in \
short, complete sentences, as "you" (the patient):
  reason: why you came in. diagnosis: what the doctor found. todo: what to do now (treatment and \
medicines). other: other notes from your visit (health history, allergies, habits). future: \
future visits, tests to get, and when to get help sooner.

Rules:
- Reading level: SMOG grade {grade} or lower (5th to 7th grade, ideally 5th). SMOG counts words of 3+ \
syllables, so use few of them: short words, one idea per sentence. Respectful, never childish.
- Every medical term or abbreviation from the note is written as [[original|plain words|med|source]], \
where the plain words say what it means in simple language (a short definition, not just a synonym). \
Hard everyday words become [[original|simpler words|word|source]]. Medicine names stay exactly as \
written: [[name|what it is for|drug|note]], with the plain part empty unless the note says what it \
is for. Lab test names that must stay: [[name|what it measures|keep|source]].
- source: use the source given in <approved_words> when the word is there. Otherwise write "model" \
(it will be flagged for the clinician). Never name a source that wasn't given.
- Never add, drop or soften a diagnosis, test, instruction, warning or follow-up. No advice, side \
effects or explanations the note doesn't contain. Numbers, doses and times stay exactly as written.
- Start a sentence with "!" if it says when to get help sooner or call 911/999.
- left_out: anything in the note you did not include (e.g. exam findings), with a short reason. \
clinician_flags: anything unclear or missing (e.g. a dose or schedule).
"""


def claude_summary(note: str, attempts: int = 4) -> Summary:
    import anthropic
    from pydantic import BaseModel

    class LeftOut(BaseModel):
        text: str
        reason: str

    class Sections(BaseModel):
        reason: list[str]
        diagnosis: list[str]
        todo: list[str]
        other: list[str]
        future: list[str]

    class Rewrite(BaseModel):
        sections: Sections
        left_out: list[LeftOut]
        clinician_flags: list[str]

    approved = sorted({f"{f.text} -> {f.replace_with or f.explain} [{f.source}]"
                       for f in analyze(note) if f.standard and (f.replace_with or f.explain)})
    messages = [{"role": "user", "content": "<approved_words>\n" + "\n".join(approved) + "\n</approved_words>\n\n"
                 f"<clinician_note>\n{note}\n</clinician_note>"}]
    client = anthropic.Anthropic()
    summary = None
    for _ in range(attempts):
        response = client.beta.messages.parse(
            model=CLAUDE_MODEL, max_tokens=8000, output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            system=SUMMARY_PROMPT.format(grade=MAX_GRADE), messages=messages, output_format=Rewrite)
        if response.parsed_output is None:
            raise RuntimeError(f"no summary (stop_reason={response.stop_reason})")
        data = response.parsed_output.model_dump()
        try:
            summary = check(from_rewrite(data, f"Claude ({CLAUDE_MODEL})"), note)
        except ValueError as e:
            problems = str(e)
        else:
            if summary.ready:
                return summary
            r = summary.readability["summary"]
            problems = "; ".join(f"{c['name']}: {c['detail']}" for c in summary.checks if not c["ok"])
            problems += f". Words with 3+ syllables: {', '.join(r['long_words'])}"
        messages += [{"role": "assistant", "content": json.dumps(data)},
                     {"role": "user", "content": f"This failed the checks: {problems}. Rewrite it to pass."}]
    return summary


# ---------- building a summary for a note ----------

def find_rewrite(note: str) -> tuple[dict, Path] | None:
    """A summary written earlier for this exact note (rewrites/*.json)."""
    for path in sorted(REWRITES.glob("*.json")):
        data = json.loads(path.read_text())
        source = HERE / data["note"]
        if source.is_file() and source.read_text().strip() == note.strip():
            return data, path
    return None


def summarize_note(note: str, use_claude: bool = False) -> Summary:
    found = find_rewrite(note)
    if found:
        data, path = found
        return check(from_rewrite(data, f"{data.get('written_by', 'Written for this note')} ({path.name})"), note)
    if use_claude:
        return claude_summary(note)
    return check(from_draft(note), note)


# ---------- HTML ----------

def sources_used(summary: Summary) -> list[dict]:
    known = lay_dictionary()[2]
    out = {}
    for s in summary.terms():
        key = s.source
        if not key or key == "note":
            continue
        if key == "model":
            out[key] = {"name": "From model knowledge, not a standard source (verify)", "url": ""}
        elif key.startswith("http"):
            site, _, page = re.sub(r"^https?://(www\.)?", "", key).partition("/")
            name = {"medlineplus.gov": "MedlinePlus", "cdc.gov": "CDC"}.get(site, site)
            if page.startswith("ency/"):
                name += " Medical Encyclopedia"
            out[key] = {"name": f"{name}: {page.rstrip('/').split('/')[-1].removesuffix('.html') or site}", "url": key}
        else:
            info = known.get(key, {})
            out[key] = {"name": info.get("name", key), "url": info.get("url", "")}
    return sorted(out.values(), key=lambda s: (s["name"].startswith("From model"), s["name"]))


def checklist(summary: Summary) -> list[dict]:
    """Every change, kept medicine, left-out item and open question, for the clinician to tick."""
    items, seen = [], set()
    labels = {"med": "Medical term", "word": "Everyday word", "keep": "Kept name", "drug": "Medicine"}
    for s in summary.terms():
        key = (s.kind, s.text.lower(), s.plain.lower())
        if key in seen:
            continue
        seen.add(key)
        source = next((x["name"] for x in sources_used(Summary({"x": [[s]]}, ""))), "the clinician's note")
        items.append({"group": labels[s.kind], "kind": s.kind, "original": s.text, "plain": s.plain,
                      "source": source, "flag": s.flag})
    items += [{"group": "Left off the printout", "kind": "left", "original": x["text"], "plain": "",
               "source": "", "flag": x["reason"]} for x in summary.left_out]
    items += [{"group": "Question for the clinician", "kind": "question", "original": q, "plain": "",
               "source": "", "flag": ""} for q in summary.clinician_flags]
    order = ["Medical term", "Everyday word", "Medicine", "Kept name", "Left off the printout", "Question for the clinician"]
    return sorted(items, key=lambda x: (order.index(x["group"]), not x["flag"]))


def context(summary: Summary, name: str = "", visit_date: str = "", phone: str = "") -> dict:
    return {"s": summary, "sections": SECTIONS, "name": name, "phone": phone,
            "visit_date": visit_date or date.today().strftime("%B %-d, %Y"),
            "checklist": checklist(summary), "sources": sources_used(summary),
            "target": TARGET_GRADE, "max_grade": MAX_GRADE}


def render_page(summary: Summary, **details) -> str:
    return jinja().get_template("summary_page.html").render(**context(summary, **details))


def main() -> None:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())
    parser = argparse.ArgumentParser(description="Check or render a plain-language visit summary.")
    parser.add_argument("command", choices=["check", "render"])
    parser.add_argument("path", type=Path, help="a rewrite (rewrites/*.json) or a clinician note (.txt)")
    parser.add_argument("--name", default="")
    parser.add_argument("--claude", action="store_true", help="write the summary with Claude (needs ANTHROPIC_API_KEY)")
    args = parser.parse_args()

    if args.path.suffix == ".json":
        data = json.loads(args.path.read_text())
        note = (HERE / data["note"]).read_text()
        summary = check(from_rewrite(data, data.get("written_by", args.path.name)), note)
        stem = Path(data["note"]).stem
    else:
        note, stem = args.path.read_text(), args.path.stem
        summary = summarize_note(note, args.claude)

    r = summary.readability
    print(f"{summary.origin}\n  note SMOG {r['note']['smog']} -> summary SMOG {r['summary']['smog']}, "
          f"{r['summary']['sentences']} sentences, {r['summary']['words']} words")
    for c in summary.checks:
        print(f"  [{'ok' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}")
    print(f"  3+ syllable words: {', '.join(r['summary']['long_words']) or 'none'}")
    if args.command == "render":
        OUTPUT.mkdir(exist_ok=True)
        out = OUTPUT / f"{stem}.summary.html"
        out.write_text(render_page(summary, name=args.name))
        print(f"  -> {out}" + ("" if summary.ready else "  (blocked: shows why, no printout)"))
    sys.exit(0 if summary.ready else 1)


if __name__ == "__main__":
    main()
