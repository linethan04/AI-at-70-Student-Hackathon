"""The three outputs, built from the checked plain-language English summary (visit_summary.py):

    printout   the patient's page: Your visit / Your medicines / What to do next (large print)
    email      the same summary for the patient or an authorized family member (next of kin), as text
    phone      a script written to be heard (CLAUDE.md: short sentences, no abbreviations or symbols,
               numbers said clearly, key instructions repeated), for a call to the same people

Each can be translated (translate.py) into Mandarin, Spanish, Portuguese or Arabic. The English version is
always built first and the translation is made from it, line by line, with the same names kept.
Nothing here sends anything: the clinician approves, then prints, opens the email draft, or makes the call.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "translation"))  # tools/translation
from translate import LABELS, LANGUAGES, NOT_VERIFIED, engine, translate_lines
from visit_summary import Summary  # noqa: E402

SPOKEN_UNITS = [(r"(\d)\s?mg\b", r"\1 milligrams"), (r"(\d)\s?mcg\b", r"\1 micrograms"), (r"(\d)\s?g\b", r"\1 grams"),
                (r"(\d)\s?ml\b", r"\1 milliliters"), (r"(\d)\s?L\b", r"\1 liters"), (r"\bDr\.", "Doctor"),
                (r"(\d+)/(\d+)", r"\1 and \2")]


def seg_json(item) -> list[dict]:
    """Segments as the page shows them: t = what the patient reads, o = the note's word (if changed), k = kind."""
    out = []
    for s in item:
        if s.kind in ("med", "word"):
            out.append({"t": s.plain, "o": s.text, "k": s.kind, "flag": s.flag})
        elif s.kind in ("keep", "drug"):
            out.append({"t": f"{s.text} ({s.plain})" if s.plain else s.text, "k": s.kind})
        else:
            out.append({"t": s.text, "k": "text"})
    return out


def document(s: Summary) -> dict:
    """The patient's page as data: English sentences with their changes, ready to show, edit or translate."""
    return {
        "visit": [seg_json(i) for i in s.overview],
        "medicines": [{"category": m.category, "name": m.name, "change": m.change,
                       "instruction": seg_json(m.instruction), "note": seg_json(m.note)} for m in s.medicines],
        "steps": [{"segs": seg_json(i), "urgent": n in s.urgent} for n, i in enumerate(s.steps)],
    }


def text_of(segs: list[dict]) -> str:
    return "".join(x["t"] for x in segs).strip()


def kept_names(doc: dict) -> set[str]:
    """Names that stay exactly as written in every language: medicines, tests, doctors."""
    names = {m["name"] for m in doc["medicines"]}
    for item in [s for v in doc["visit"] for s in v] + [s for st in doc["steps"] for s in st["segs"]] + \
            [s for m in doc["medicines"] for s in m["instruction"] + m["note"]]:
        if item["k"] in ("keep", "drug"):
            names.add(re.sub(r"\s*\(.*$", "", item["t"]))
    for match in re.finditer(r"\(([^)]*)\)", " ".join(line for line in lines(doc))):  # "(TSH, CBC and BMP)"
        names |= {w for w in re.split(r",\s*|\s+and\s+", match.group(1)) if re.fullmatch(r"[A-Z0-9-]{2,8}", w)}
    return {n for n in names if n}


def page_items(doc: dict) -> list[tuple[str, int, str, str]]:
    """Every line of the page as (part, index, field, English text), in order: what gets translated."""
    out = [("visit", i, "text", text_of(v)) for i, v in enumerate(doc["visit"])]
    for i, m in enumerate(doc["medicines"]):
        out.append(("medicines", i, "head", f"{m['category']} ({m['name']})." if m["category"] else f"{m['name']}."))
        out += [("medicines", i, "instruction", text_of(m["instruction"]))] if m["instruction"] else []
        out += [("medicines", i, "note", text_of(m["note"]))] if m["note"] else []
    out += [("steps", i, "text", text_of(st["segs"])) for i, st in enumerate(doc["steps"])]
    return [x for x in out if x[3]]


def lines(doc: dict) -> list[str]:
    return [x[3] for x in page_items(doc)]


def translated_page(doc: dict, rows: list[dict], labels: dict) -> dict:
    """The page in the chosen language, same parts as the English one."""
    page = {"visit": [""] * len(doc["visit"]),
            "medicines": [{"head": "", "instruction": "", "note": "", "change": labels.get(m["change"], m["change"]),
                           "name": m["name"]} for m in doc["medicines"]],
            "steps": [{"text": "", "urgent": st["urgent"]} for st in doc["steps"]]}
    for (part, i, field, _), row in zip(page_items(doc), rows):
        if part == "visit":
            page["visit"][i] = row["text"]
        else:
            page[part][i][field] = row["text"]
    return page


def email_lines(doc: dict, patient: str, recipient: str, relationship: str, office_phone: str) -> list[str]:
    first = patient.split()[0] if patient else "the patient"
    family = recipient and recipient != patient
    out = [f"§hello {recipient or first}",
           (f"{patient or 'Your family member'}'s care team is sharing the summary of today's visit, as {first} asked us to. "
            f"It is written to {first}, so \"you\" means {first}." if family else
            "Here is the summary of your visit today.")]
    out += ["§visit"] + [text_of(v) for v in doc["visit"]]
    if doc["medicines"]:
        out.append("§medicines")
        for m in doc["medicines"]:
            head = f"{m['category']} ({m['name']})" if m["category"] else m["name"]
            how = text_of(m["instruction"]) or "How to take it: ask the office."
            out.append(f"§change {m['change']}" if m["change"] else "")
            out.append(f"- {head}: {how}" + (f" {text_of(m['note'])}" if m["note"] else ""))
    out += ["§next"] + [f"- {text_of(s['segs'])}" for s in doc["steps"]]
    out.append(f"Questions? Call the office{': ' + office_phone if office_phone else ''}.")
    return out


def spoken(text: str) -> str:
    """'Take 1 pill (5 mg) each day.' -> 'Take 1 pill, 5 milligrams, each day.' (read aloud clearly)"""
    for pattern, new in SPOKEN_UNITS:
        text = re.sub(pattern, new, text)
    text = re.sub(r"\b(911|999|988|111)\b", lambda m: " ".join(m.group(1)), text)  # "9 1 1"
    text = re.sub(r"\s*\(([^)]*)\)", r", \1,", text)
    text = re.sub(r",\s*([.?!])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def phone_lines(doc: dict, patient: str, recipient: str, clinician: str, office_phone: str) -> list[str]:
    first = patient.split()[0] if patient else "the patient"
    family = recipient and recipient != patient
    out = [f"Hello{', ' + recipient if recipient else ''}. This is a call from {clinician or 'your doctor'}'s office.",
           f"I am calling with the summary of {first}'s visit today." if family else "I am calling with the summary of your visit today."]
    if family:
        out.append(f"{first} asked us to share it with you. When I say you, I mean {first}.")
    out += ["First, the visit."] + [spoken(text_of(v)) for v in doc["visit"]]
    if doc["medicines"]:
        out.append("Next, the medicines.")
        for m in doc["medicines"]:
            out.append(spoken(f"{m['category']}, called {m['name']}." if m["category"] else f"{m['name']}."))
            if m["change"]:
                out.append(f"This is a change: {m['change'].lower()}.")
            if m["instruction"]:
                out.append(spoken(text_of(m["instruction"])))
    out += ["Next, what to do."] + [spoken(text_of(s["segs"])) for s in doc["steps"]]
    key = [spoken(text_of(m["instruction"])) for m in doc["medicines"] if m["change"] and m["instruction"]] + \
          [spoken(text_of(s["segs"])) for s in doc["steps"] if s["urgent"]]
    if key:
        out += ["Let me say the most important things again."] + key
    out.append(f"If you have questions, please call the office{' at ' + spoken(office_phone) if office_phone else ''}. "
               "Thank you. Goodbye.")
    return [l for l in out if l]


def merged_flags(parts: list[tuple[str, list[dict]]]) -> list[dict]:
    """Translation problems, each line once, naming every output it appears in."""
    seen: dict[tuple, dict] = {}
    for part, rows in parts:
        for r in rows:
            if len(r["flags"]) > 1:
                key = (r["en"].lstrip("- "), r["text"].lstrip("- "))
                if key in seen:
                    seen[key]["part"] += f", {part}"
                else:
                    seen[key] = {"part": part, **r}
    return list(seen.values())


def label_line(line: str, labels: dict) -> str:
    """'§visit' -> 'YOUR VISIT' / 'SU VISITA'; '§hello Daniel' -> 'Hola, Daniel:'; '§change Lower dose' -> '[Lower dose]'."""
    key, _, rest = line[1:].partition(" ")
    if key == "hello":
        return labels["hello"].format(name=rest)
    if key == "change":
        return f"[{labels.get(rest, rest)}]"
    return labels[key].upper()


def outputs(doc: dict, lang: str, patient: str = "", recipient: str = "", relationship: str = "",
            clinician: str = "", office_phone: str = "") -> dict:
    """The printout, email and phone script in the chosen language, with translation flags for the clinician."""
    page, email, phone = lines(doc), email_lines(doc, patient, recipient, relationship, office_phone), \
        phone_lines(doc, patient, recipient, clinician, office_phone)
    keep = kept_names(doc) | {n for n in (patient, recipient, clinician) if n} | set(patient.split()) | set(recipient.split())
    labels = LABELS[lang]
    email = [l for l in email if l]
    fixed = {i for i, l in enumerate(email) if l.startswith("§")}  # headings, greeting, tags: fixed words per language
    words = [l for i, l in enumerate(email) if i not in fixed]
    rows = translate_lines(page + words, lang, keep)
    page_t, words_t = rows[:len(page)], rows[len(page):]
    phone_t = translate_lines(phone, lang, keep | {"9 1 1", "9 9 9", "9 8 8", "1 1 1"}, spoken=True)
    it = iter(words_t)
    email_t = [{"text": label_line(email[i], labels)} if i in fixed else next(it) for i in range(len(email))]
    subject = f"{LABELS[lang]['title']}: {patient}".strip(": ") if lang != "en" else f"Visit summary for {patient or 'you'}"
    return {
        "lang": lang, "language": LANGUAGES[lang], "labels": labels, "dir": "rtl" if lang == "ar" else "ltr",
        "page": translated_page(doc, page_t, labels), "email": {"subject": subject, "body": "\n".join(r["text"] for r in email_t)},
        "phone": [r["text"] for r in phone_t],
        "flags": [] if lang == "en" else merged_flags([("printout", page_t), ("email", words_t), ("phone call", phone_t)]),
        "engine": "" if lang == "en" else engine(),
        "not_verified": "" if lang == "en" else NOT_VERIFIED,
    }

