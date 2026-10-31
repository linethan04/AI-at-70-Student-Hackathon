"""Check medical terms against free U.S. National Library of Medicine (NLM) vocabularies.

No API key needed.
    medication   RxNorm drug names (~28k names, downloaded once and cached in tools/transcription/.cache/)
    drug_class   RxClass (e.g. "sulfonylureas", "ACE inhibitors")
    condition    ICD-10-CM diagnoses, then the consumer-friendly Conditions list
    lab_test     LOINC lab and observation names
    procedure    HCPCS procedure names, then LOINC studies
    medical_term ~98k-word medical spelling list (OpenMedSpel-based, cached; used by the offline cleanup)

    python tools/transcription/medical_dictionary.py medication glipizide
"""

import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / ".cache"
RXNAV = "https://rxnav.nlm.nih.gov/REST"
CLINICAL_TABLES = "https://clinicaltables.nlm.nih.gov/api"
MEDICAL_WORDLIST_URL = "https://raw.githubusercontent.com/glutanimate/wordlist-medicalterms-en/master/wordlist.txt"

CATEGORIES = ("medication", "drug_class", "condition", "lab_test", "procedure", "medical_term", "other")


@dataclass
class Lookup:
    found: bool | None          # None = couldn't check (category "other" or network error)
    matched: str | None = None  # the dictionary's own spelling of the term
    source: str = ""
    suggestions: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def sounds_similar(heard: str, corrected: str) -> float:
    """0-1 similarity of the letters only, so 'glitz preside' vs 'glipizide' compares as one word."""
    a, b = re.sub(r"[^a-z]", "", heard.lower()), re.sub(r"[^a-z]", "", corrected.lower())
    return difflib.SequenceMatcher(None, a, b).ratio()


def _get(url: str, **params) -> object:
    resp = httpx.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


@lru_cache(maxsize=1)
def drug_names() -> dict[str, str]:
    """normalized name -> RxNorm display name, e.g. 'glipizide' -> 'glipiZIDE'."""
    cache = CACHE_DIR / "rxnorm_display_names.json"
    if not cache.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        terms = _get(f"{RXNAV}/displaynames.json")["displayTermsList"]["term"]
        cache.write_text(json.dumps(terms))
    return {normalize(t): t for t in json.loads(cache.read_text())}


@lru_cache(maxsize=1)
def medical_words() -> set[str]:
    """Lowercase medical spelling list, e.g. 'orthostatic', 'hypoglycemic', 'sulfonylureas'."""
    cache = CACHE_DIR / "medical_wordlist.txt"
    if not cache.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        resp = httpx.get(MEDICAL_WORDLIST_URL, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        cache.write_text(resp.text)
    return {w.strip().lower() for w in cache.read_text().splitlines() if w.strip()}


def _singular_forms(term: str) -> list[str]:
    t = normalize(term)
    return [t] + ([t[:-1]] if t.endswith("s") else [])


def _lookup_medication(term: str) -> Lookup:
    names = drug_names()
    for t in _singular_forms(term):
        if t in names:
            return Lookup(True, names[t], "RxNorm")
    try:
        suggestions = _get(f"{RXNAV}/spellingsuggestions.json", name=term)["suggestionGroup"]["suggestionList"]
    except httpx.HTTPError:
        suggestions = None  # offline: fall back to the cached list below
    close = difflib.get_close_matches(normalize(term), names.keys(), n=3, cutoff=0.75)
    return Lookup(False, source="RxNorm",
                  suggestions=list(dict.fromkeys((suggestions or {}).get("suggestion", []) + [names[c] for c in close])))


def _lookup_drug_class(term: str) -> Lookup:
    for t in _singular_forms(term):
        data = _get(f"{RXNAV}/rxclass/class/byName.json", className=t)
        concepts = (data.get("rxclassMinConceptList") or {}).get("rxclassMinConcept", [])
        if concepts:
            return Lookup(True, concepts[0]["className"], "RxClass")
    return Lookup(False, source="RxClass")


def _clinical_tables(table: str, term: str, **params) -> list[str]:
    """Clinical Tables search: every word of `term` must prefix-match the result. Returns display names."""
    data = _get(f"{CLINICAL_TABLES}/{table}/v3/search", terms=term, maxList=5, **params)
    return [row[-1] for row in data[3]]


def _lookup_condition(term: str) -> Lookup:
    hits = _clinical_tables("icd10cm", term, sf="code,name")
    if hits:
        return Lookup(True, hits[0], "ICD-10-CM", hits[1:])
    hits = _clinical_tables("conditions", term)
    return Lookup(bool(hits), hits[0] if hits else None, "Conditions", hits[1:])


def _lookup_lab(term: str) -> Lookup:
    hits = _clinical_tables("loinc_items", term)
    return Lookup(bool(hits), hits[0] if hits else None, "LOINC", hits[1:])


def _lookup_procedure(term: str) -> Lookup:
    hits = _clinical_tables("hcpcs", term)
    if hits:
        return Lookup(True, hits[0], "HCPCS", hits[1:])
    hits = _clinical_tables("loinc_items", term)  # imaging/studies, e.g. "echocardiogram"
    return Lookup(bool(hits), hits[0] if hits else None, "LOINC", hits[1:])


def _lookup_medical_term(term: str) -> Lookup:
    words = normalize(term).split()
    found = bool(words) and all(w in medical_words() or w in drug_names() for w in words)
    return Lookup(found, term.lower() if found else None, "medical spelling list")


_LOOKUPS = {
    "medication": _lookup_medication,
    "drug_class": _lookup_drug_class,
    "condition": _lookup_condition,
    "lab_test": _lookup_lab,
    "procedure": _lookup_procedure,
    "medical_term": _lookup_medical_term,
}


def lookup(term: str, category: str) -> Lookup:
    """Is `term` a real medical term of this category? Falls back across drug tables, since
    a drug class is easily mistaken for a drug name and vice versa."""
    if category not in _LOOKUPS:
        return Lookup(None, source="not checked")
    try:
        result = _LOOKUPS[category](term)
        if not result.found and category in ("medication", "drug_class"):
            other = _LOOKUPS["drug_class" if category == "medication" else "medication"](term)
            if other.found:
                return other
        return result
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return Lookup(None, source=f"lookup failed: {e.__class__.__name__}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in CATEGORIES:
        sys.exit(f"usage: python {Path(__file__).name} <{'|'.join(CATEGORIES)}> <term>")
    print(lookup(sys.argv[2], sys.argv[1]))
