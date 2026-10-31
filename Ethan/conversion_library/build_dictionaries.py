"""Build the two dictionaries the conversion library uses.

1. Medical (baseline) vocabulary, for DETECTING jargon in clinician notes:
   - Medical spelling list (~98k words, OpenMedSpel-based)        data/raw/medical_wordlist.txt
   - RxNorm drug names, generic and brand (NLM)                    data/raw/rxnorm_display_names.json
   - Technical names from MedlinePlus topics and lab tests (below)

2. Lay dictionary, for REPLACING or EXPLAINING jargon, following CLAUDE.md's source order:
   standard = True (approved plain-language sources):
     - CDC Everyday Words for Public Health Communication (2016)  "Acute" -> "sudden; ..."
     - MedlinePlus health topics (NLM)        "Hypertension" -> "high blood pressure"
     - MedlinePlus lab tests (NLM)            "HbA1c" -> "a blood test that shows your average..."
     - Federal Plain Language Guidelines, "Use simple words and phrases" (plainlanguage.gov)
       for everyday (non-medical) wording: "approximately" -> "about". The live site moved to
       digital.gov and dropped the table, so it's read from the Internet Archive copy (Dec 2024).
   standard = False (nameable, but not a plain-language standard; used only to EXPAND):
     - Wikipedia "List of medical abbreviations" (CC BY-SA 4.0)    "BID" -> "twice a day"
   The Consumer Health Vocabulary (CHV) is the next source in CLAUDE.md, but its files sit
   behind a sign-up page at GWU (biomedinfo.smhs.gwu.edu/chv-files), so it isn't downloaded
   automatically. Drop CHV_concepts_terms_flatfile_*.txt into data/raw/ to add it later.

    python Ethan/conversion_library/build_dictionaries.py          # build (downloads ~35 MB once)
    python Ethan/conversion_library/build_dictionaries.py --refresh  # re-download sources

Writes data/lay_dictionary.json (committed) and data/medical_vocab.txt (generated).
"""

import argparse
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx
from wordfreq import zipf_frequency

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "raw"
LAY_DICTIONARY = DATA / "lay_dictionary.json"
MEDICAL_VOCAB = DATA / "medical_vocab.txt"

CDC_PDF_URL = "https://www.cdc.gov/other/pdf/EverydayWordsForPublicHealthCommunication.pdf"
MEDLINEPLUS_XML_INDEX = "https://medlineplus.gov/xml.html"
MEDLINEPLUS_LAB_INDEX = "https://medlineplus.gov/lab-tests/"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
MEDICAL_WORDLIST_URL = "https://raw.githubusercontent.com/glutanimate/wordlist-medicalterms-en/master/wordlist.txt"
RXNORM_NAMES_URL = "https://rxnav.nlm.nih.gov/REST/displaynames.json"
PLAIN_LANGUAGE_URL = ("https://web.archive.org/web/20241217004940/"
                      "https://www.plainlanguage.gov/guidelines/words/use-simple-words-phrases/")

SOURCES = {
    "CDC Everyday Words": {"url": CDC_PDF_URL, "standard": True, "rank": 1},
    "MedlinePlus": {"url": "https://medlineplus.gov/", "standard": True, "rank": 1},
    "MedlinePlus Lab Tests": {"url": MEDLINEPLUS_LAB_INDEX, "standard": True, "rank": 1},
    "plainlanguage.gov": {"url": PLAIN_LANGUAGE_URL, "standard": True, "rank": 2,
                          "name": "Federal Plain Language Guidelines: Use simple words and phrases (plainlanguage.gov, "
                                  "archived Dec 2024)"},
    "Wikipedia: List of medical abbreviations": {
        "url": "https://en.wikipedia.org/wiki/List_of_medical_abbreviations", "standard": False, "rank": 9},
}

client = httpx.Client(timeout=60, follow_redirects=True, headers={
    # Wikipedia requires a descriptive User-Agent with contact info (https://w.wiki/4wJS)
    "User-Agent": "AI-at-70-hackathon/1.0 (https://github.com/linethan04/AI-at-70-Student-Hackathon; educational)"})


def download(url: str, dest: Path, refresh: bool) -> Path:
    if refresh or not dest.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {url}")
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def plainness(phrase: str) -> float:
    """How everyday a phrase is: average word frequency (Zipf scale, ~1 rare to ~7 very common)."""
    words = re.findall(r"[a-z]+", phrase.lower())
    return sum(zipf_frequency(w, "en") for w in words) / len(words) if words else 0.0


def is_abbreviation(term: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9][A-Za-z0-9+&/.-]{0,7}", term)) and any(c.isupper() for c in term[1:] or term)


def short_definition(sentence: str, names: list[str] | None = None) -> str | None:
    """'A hemoglobin A1C (HbA1C) test is a blood test that shows...' -> 'a blood test that shows...'
    With `names`, the sentence must be about one of them (not a related term defined first)."""
    # The sentence must be ABOUT one of the names: "Atrial fibrillation is..." or "A hemoglobin A1C test is..."
    lead = re.sub(r"^(?:an?|the)\s+", "", sentence.lower())
    if names and not any(lead.startswith(n.lower()) for n in names):
        return None
    m = re.search(r"\b(is|are|means|happens when|occurs when)\s+(.+)$", sentence)
    if not m:
        return None
    definition = m.group(2).rstrip(" .")
    # After "is/are", only accept something shaped like a definition ("a ...", "when ..."),
    # not a judgement like "Smoking is bad for your health".
    if m.group(1) in ("is", "are") and definition.split()[0].lower() not in DEFINITION_STARTS:
        return None
    if sentence[m.start():].startswith(("happens", "occurs")):
        definition = "when " + definition
    definition = re.sub(r"^that\s+", "", definition)  # "means that your heart can't..."
    if definition.lower().startswith(("not ", "also ", "often ", "sometimes ")):
        return None  # "Dizziness and vertigo are not the same thing" isn't a definition
    return definition if 3 <= len(definition.split()) <= 30 else None


DEFINITION_STARTS = {"a", "an", "when", "how", "your", "tiny", "small", "problems", "problem",
                     "conditions", "condition", "diseases", "disease", "disorders", "disorder", "inflammation",
                     "swelling", "damage", "pain", "loss", "infections", "infection"}


CONDITION_WORDS = (r"\b(high|low|pain|swelling|problems?|disease|attack|failure|loss|infection|inflammation|"
                   r"trouble|stones?|bleeding|cancer|sores?|rash|damage|weak|thin|fast|slow|irregular|blocked)\b")


def first_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


# ---------- 1. CDC Everyday Words ----------

def parse_cdc(refresh: bool) -> list[dict]:
    from pypdf import PdfReader
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    pdf = download(CDC_PDF_URL, RAW / "cdc_everyday_words.pdf", refresh)
    lines = [l.strip() for p in PdfReader(pdf).pages[3:] for l in (p.extract_text() or "").splitlines()]
    entries = []
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z][A-Za-z0-9 ,()/'’\-]{1,60}):\s*(.*)$", line)
        following = lines[i + 1:i + 4]
        end = next((j for j, x in enumerate(following) if x.startswith("CDC Original Sentence")), None)
        if not m or end is None:
            continue
        heading, meaning = m.group(1), " ".join([m.group(2)] + following[:end]).strip()
        context_dependent = meaning.lower().startswith("depends on context")
        # "Transmit, transmission" / "Adhere and Adherence" / "Agent (biological)"
        variants = [v.strip().lower() for v in re.split(r",| and ", re.sub(r"\(.*?\)", "", heading)) if v.strip()]
        first_choice = re.split(r"[;,]", meaning)[0].strip()
        for v in variants:
            entries.append({"term": v, "plain": None if context_dependent else first_choice, "explain": meaning,
                            "kind": "word", "source": "CDC Everyday Words", "context_dependent": context_dependent})
    return entries


def parse_plain_language(refresh: bool) -> list[dict]:
    """'Don't say / Say' table: "accompany" -> "go with", "utilize, utilization" -> "use"."""
    page = download(PLAIN_LANGUAGE_URL, RAW / "plainlanguage_simple_words.html", refresh).read_text()
    table = page[page.find("<table"):page.find("</table>")]
    entries = []
    for row in re.findall(r"<tr>(.*?)</tr>", table, re.S):
        cells = [clean(html.unescape(re.sub(r"<[^>]+>", " ", c))) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) != 2 or not cells[1]:
            continue
        say = re.split(r"[,;(]| or ", cells[1])[0].strip()
        if not say or "(" in cells[0] or cells[0].lower().startswith(("a ", "your ")):
            continue  # "a and/or b", "/ (slash)", "your office": patterns, not words
        for variant in cells[0].split(","):
            variant = variant.strip().lower()
            if re.fullmatch(r"[a-z][a-z' -]+", variant) and say.lower() != variant:
                entries.append({"term": variant, "plain": say, "explain": None, "kind": "wording",
                                "source": "plainlanguage.gov", "source_url": PLAIN_LANGUAGE_URL})
    return entries


# ---------- 2. MedlinePlus health topics ----------

def parse_medlineplus(refresh: bool, drug_names: set[str]) -> tuple[list[dict], set[str]]:
    dest = RAW / "medlineplus_topics.xml"
    if refresh or not dest.exists():
        page = client.get(MEDLINEPLUS_XML_INDEX).text
        latest = sorted(set(re.findall(r"https://medlineplus\.gov/xml/mplus_topics_[0-9-]+\.xml", page)))[-1]
        download(latest, dest, True)

    entries, technical = [], set()
    for topic in ET.parse(dest).getroot().findall("health-topic"):
        if topic.get("language") != "English":
            continue
        title = topic.get("title")
        # Title + "also called" names are synonyms. MeSH headings are broader index categories
        # ("Women's Health" is indexed under "Physical Examination"), so they're only used to
        # recognize jargon, never as something to swap.
        mesh = [m.findtext("descriptor") for m in topic.findall("mesh-heading") if m.findtext("descriptor")]
        technical.update(m.lower() for m in mesh)
        names = [title] + [a.text.strip() for a in topic.findall("also-called") if a.text]
        if len(mesh) == 1:  # a single index heading is a synonym ("Breathing Problems" = Dyspnea)
            names += mesh
        names = list(dict.fromkeys(n for n in names if "," not in n or n == title))
        summary = clean(topic.findtext("full-summary") or "")

        # Explanation: the first summary sentence that defines this topic by one of its names
        # (summaries often define a related term first, e.g. "What is blood pressure?").
        sentences = [s for s in first_sentences(summary) if not s.endswith("?")]
        defined = next(((s, d) for s in sentences[:6] if (d := short_definition(s, names))), None)
        explanation = defined[1] if defined else None
        subject = next((n for n in names if defined and re.sub(r"^(?:an?|the)\s+", "", defined[0].lower())
                        .startswith(n.lower())), None)

        # The plain name is MedlinePlus's own title (already its consumer-friendly name), unless an
        # "also called" name is clearly more everyday ("Hypoglycemia" -> "low blood sugar").
        # Index headings are only ever swapped TO the title, never used as the replacement.
        also = [a.text.strip() for a in topic.findall("also-called") if a.text and not is_abbreviation(a.text.strip())]
        plain = max([title] + also, key=lambda n: plainness(n) - (0.4 if n != title else 0))
        for name in names:
            technical.add(name.lower())
            # Only true synonyms: "Hypertension" -> "High Blood Pressure" is fine, but
            # "dizziness" -> "Dizziness and Vertigo" names a broader topic and would add meaning.
            broader = name.lower() in plain.lower() or " and " in plain.lower()
            everyday = all(zipf_frequency(w, "en") >= 3.5 for w in re.findall(r"[a-z]+", plain.lower()))
            is_drug = name.lower() in drug_names  # never rename a medicine ("prednisone" -> "steroids")
            # A disease word must map to a phrase that still names a condition:
            # "hyperlipidemia" -> "cholesterol" would turn a condition into a substance.
            disease_word = re.search(r"(emia|itis|osis|pathy|algia|uria|ia|ism)$", name.lower()) is not None
            still_condition = re.search(CONDITION_WORDS, plain.lower()) is not None
            better = plain if (name != plain and not is_abbreviation(plain) and not broader and everyday
                               and not is_drug and (still_condition or not disease_word)
                               and plainness(plain) > plainness(name) + 0.4) else None
            # The definition belongs to the name it defines, its abbreviations, and true synonyms,
            # not to every name in the topic ("hyperlipidemia" must not get cholesterol's definition).
            owns_definition = name == subject or is_abbreviation(name) or better is not None
            entries.append({"term": name if is_abbreviation(name) else name.lower(),
                            "plain": better.lower() if better else None,
                            "explain": explanation if owns_definition else None,
                            "kind": "abbreviation" if is_abbreviation(name) else "condition",
                            "expands_to": plain.lower() if is_abbreviation(name) else None,
                            "source": "MedlinePlus", "source_url": topic.get("url")})
    return entries, technical


# ---------- 3. MedlinePlus lab tests ----------

def parse_lab_tests(refresh: bool) -> tuple[list[dict], set[str]]:
    cache = RAW / "medlineplus_lab_tests.json"
    if refresh or not cache.exists():
        index = client.get(MEDLINEPLUS_LAB_INDEX).text
        urls = sorted(set(re.findall(r'href="(https://medlineplus\.gov/lab-tests/[a-z0-9-]+/)"', index)))
        print(f"Fetching {len(urls)} MedlinePlus lab test pages...")

        def fetch(url: str) -> dict | None:
            try:
                page = client.get(url).text
            except httpx.HTTPError:
                return None
            title = clean(re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S).group(1)) if "<h1" in page else ""
            m = re.search(r"<h2[^>]*>\s*What (?:is|are) .*?</h2>(.*?)<h2", page, re.S)
            return {"url": url, "title": title, "what_is": clean(m.group(1)) if m else ""}

        with ThreadPoolExecutor(6) as pool:
            pages = [p for p in pool.map(fetch, urls) if p and p["title"]]
        cache.write_text(json.dumps(pages, indent=1))
    pages = json.loads(cache.read_text())

    entries, technical = [], set()
    for page in pages:
        title = page["title"]
        explanation = next((d for d in map(short_definition, first_sentences(page["what_is"])[:2]) if d), None)
        base = re.sub(r"\s*\(.*?\)", "", title)
        variants = {base, re.sub(r"\s+(Blood |Urine )?Tests?$", "", base, flags=re.I)}
        variants |= {abbr for group in re.findall(r"\((.*?)\)", title) for abbr in re.split(r",\s*", group)}
        for v in variants:
            v = v.strip()
            if len(v) < 2 or v.lower() in ("test", "blood test"):
                continue
            technical.add(v.lower())
            entries.append({"term": v if is_abbreviation(v) else v.lower(), "plain": None, "explain": explanation,
                            "kind": "lab_test", "source": "MedlinePlus Lab Tests", "source_url": page["url"]})
    return entries, technical


# ---------- 4. Wikipedia abbreviations ----------

def unwiki(text: str) -> str:
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return clean(text.replace("''", ""))


def parse_abbreviations(refresh: bool) -> list[dict]:
    cache = RAW / "wikipedia_abbreviations.json"
    if refresh or not cache.exists():
        pages = {}
        for letter in ["0–9"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]:
            for attempt in range(4):  # Wikipedia rate-limits bursts; back off and retry
                resp = client.get(WIKIPEDIA_API, params={"action": "parse", "page": f"List of medical abbreviations: {letter}",
                                                         "prop": "wikitext", "format": "json", "formatversion": 2})
                if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/json"):
                    data = resp.json()
                    if "parse" in data:
                        pages[letter] = data["parse"]["wikitext"]
                    break
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  skipped page {letter} (HTTP {resp.status_code})")
            time.sleep(0.5)
        cache.write_text(json.dumps(pages))
    pages = json.loads(cache.read_text())

    meanings: dict[str, list[str]] = defaultdict(list)
    for wikitext in pages.values():
        for row in re.split(r"\n\|-", wikitext):
            cells = [c for c in re.split(r"\n\||\|\|", row.strip().lstrip("|")) if c.strip()]
            if len(cells) < 2:
                continue
            options = [unwiki(m) for m in re.split(r"<br\s*/?>|\n\*", cells[1])]  # one cell can hold several meanings
            for abbr in re.split(r"<br\s*/?>|,\s+", cells[0]):
                abbr = unwiki(abbr)
                if 1 < len(abbr) <= 12 and not abbr.startswith(("!", "{", "class=")):
                    meanings[abbr].extend(m for m in options if m)

    entries = []
    for abbr, options in meanings.items():
        # Drop editorial notes: "twice a day (from Latin bis in die)" -> "twice a day"
        options = list(dict.fromkeys(re.sub(r"\s*\((?:from|see|e\.g\.|also|for|if|in|as|blood test|abbreviation)[^)]*\)", "", o).strip(" ;,")
                                     for o in options))
        options = [o for o in options if o]
        entries.append({"term": abbr, "plain": None, "expands_to": options[0] if len(options) == 1 else None,
                        "meanings": options, "kind": "abbreviation", "ambiguous": len(options) > 1,
                        "source": "Wikipedia: List of medical abbreviations"})
    return entries


# ---------- assemble ----------

def build(refresh: bool) -> None:
    print("CDC Everyday Words...")
    cdc = parse_cdc(refresh)
    print(f"  {len(cdc)} entries")
    drugs = json.loads(download(RXNORM_NAMES_URL, RAW / "rxnorm_display_names.json", refresh).read_text())
    drugs = drugs["displayTermsList"]["term"] if isinstance(drugs, dict) else drugs
    (RAW / "rxnorm_display_names.json").write_text(json.dumps(drugs))
    print("MedlinePlus health topics...")
    mplus, mplus_terms = parse_medlineplus(refresh, {d.lower() for d in drugs})
    print(f"  {len(mplus)} entries")
    print("MedlinePlus lab tests...")
    labs, lab_terms = parse_lab_tests(refresh)
    print(f"  {len(labs)} entries")
    print("Wikipedia medical abbreviations...")
    abbrevs = parse_abbreviations(refresh)
    print(f"  {len(abbrevs)} abbreviations")
    print("plainlanguage.gov simple words...")
    wording = parse_plain_language(refresh)
    print(f"  {len(wording)} entries")

    # Merge by term; better-ranked sources come first. Abbreviations are case-sensitive.
    merged: dict[str, dict] = {}
    for entry in sorted(cdc + mplus + labs + wording + abbrevs, key=lambda e: SOURCES[e["source"]]["rank"]):
        key = entry["term"]
        entry["standard"] = SOURCES[entry["source"]]["standard"]
        entry["source_url"] = entry.get("source_url") or SOURCES[entry["source"]]["url"]
        if key not in merged:
            merged[key] = {k: v for k, v in entry.items() if v not in (None, False, [])}
            merged[key]["also_in"] = []
        else:
            existing = merged[key]
            for field in ("plain", "explain", "expands_to"):
                if not existing.get(field) and entry.get(field):
                    existing[field] = entry[field]
                    existing.setdefault("field_sources", {})[field] = entry["source"]
            if entry["source"] != existing["source"]:
                existing["also_in"] = sorted(set(existing["also_in"]) | {entry["source"]})

    DATA.mkdir(parents=True, exist_ok=True)
    LAY_DICTIONARY.write_text(json.dumps({
        "built": date.today().isoformat(),
        "sources": SOURCES,
        "attribution": "CDC, MedlinePlus and plainlanguage.gov content is U.S. government work. Abbreviation expansions from Wikipedia "
                       "'List of medical abbreviations', CC BY-SA 4.0.",
        "entries": sorted(merged.values(), key=lambda e: e["term"].lower()),
    }, indent=1, ensure_ascii=False))

    # Baseline vocabulary for detecting jargon.
    wordlist = download(MEDICAL_WORDLIST_URL, RAW / "medical_wordlist.txt", refresh).read_text().splitlines()
    vocab = {w.strip().lower() for w in wordlist if w.strip()} | mplus_terms | lab_terms
    MEDICAL_VOCAB.write_text("\n".join(sorted(vocab)) + "\n")

    n = merged.values()
    print(f"\nWrote {LAY_DICTIONARY.relative_to(HERE)}: {len(merged)} terms "
          f"({sum(1 for e in n if e.get('plain'))} with a plain replacement, "
          f"{sum(1 for e in n if e.get('explain'))} with a plain explanation, "
          f"{sum(1 for e in n if e.get('kind') == 'abbreviation')} abbreviations)")
    print(f"Wrote {MEDICAL_VOCAB.relative_to(HERE)}: {len(vocab)} medical terms, plus {len(drugs)} drug names")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the medical and lay dictionaries.")
    parser.add_argument("--refresh", action="store_true", help="re-download all sources")
    build(parser.parse_args().refresh)
