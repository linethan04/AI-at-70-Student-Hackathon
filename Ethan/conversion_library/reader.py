"""A model of the reader: would an older adult reading at a 5th-7th grade level understand this?

Instead of a readability formula, the check asks what a person needs to follow a text:
  1. Words they know. A word counts as known if most students know its easiest meaning by the
     target grade (Living Word Vocabulary, Brysbaert & Biemiller 2017), or, for words not in that
     list, if at least 99% of adults know it (Brysbaert et al. 2019 prevalence). Reading research
     finds people follow a text comfortably when they know about 98% of its words; below 95% they
     struggle. Medicine names, numbers and words explained in the text don't count against it.
  2. How much they must hold in mind: short sentences, one idea each.
The result reads like a person would say it: "would know 98 of every 100 words; might not know
'exacerbation'; longest sentence 14 words".

    python Ethan/conversion_library/reader.py "Your blood pressure is not yet at your goal."
"""

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
KNOWLEDGE = HERE / "data" / "word_knowledge.json"

READER_GRADE = 7          # CLAUDE.md: 5th-7th grade; the app can set 5, 6 or 7
COVERAGE_TARGET = 0.98    # share of words the reader knows
ADULT_KNOWN = 0.99        # for words without a school grade: known by this share of adults
ADULT_GRADE_WINDOW = 1    # a word taught one grade later still counts if 99% of adults know it ("urine")
TITLES = {"dr", "mr", "mrs", "ms"}
UNITS = {"mg", "mcg", "ml", "g", "kg", "mmol", "iu", "x", "mls", "hrs", "hr"}
MAX_SENTENCE_WORDS = 20   # longest sentence
AVG_SENTENCE_WORDS = 13   # average sentence
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


@lru_cache(maxsize=1)
def knowledge() -> dict:
    return json.loads(KNOWLEDGE.read_text())["words"]


def forms(word: str) -> list[str]:
    """The word and simpler forms of it: 'symptoms' -> 'symptom', 'worried' -> 'worry'."""
    w = re.sub(r"(?:'re|'s|'ll|n't|'ve|'d|'m)$", "", word.lower().strip("'-"))  # "you're" -> "you"
    out = [w]
    for suffix, repl in (("en", ""), ("n", ""), ("ies", "y"), ("ied", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"),
                         ("d", ""), ("ing", ""), ("ing", "e"), ("ly", ""), ("ness", ""), ("er", ""), ("est", "")):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            out.append(w[: len(w) - len(suffix)] + repl)
    if "-" in w:
        out += w.split("-")
    return out


def word_grade(word: str) -> float | None:
    """School grade by which most students know the word (None = not in the list)."""
    grades = [knowledge()[f]["grade"] for f in forms(word) if "grade" in knowledge().get(f, {})]
    return min(grades) if grades else None


def is_known(word: str, grade: int = READER_GRADE) -> bool:
    if word.lower().endswith(("n't", "n’t")):
        return True  # can't, don't, won't
    if forms(word)[0] in ("you", "we", "they", "it", "i", "he", "she", "that", "there", "can", "do", "is", "are", "was"):
        return True
    if len(word) <= 2 and word.lower() in {"a", "i", "an", "am", "as", "at", "be", "by", "do", "go", "he", "if", "in",
                                           "is", "it", "me", "my", "no", "of", "on", "or", "so", "to", "up", "us", "we"}:
        return True
    if "-" in word and all(is_known(p, grade) for p in word.split("-") if p):
        return True  # "follow-up", "check-up"
    w = word.lower()
    if w not in knowledge() and any(word_grade(w[:i]) is not None and word_grade(w[i:]) is not None
                                    and is_known(w[:i], grade) and is_known(w[i:], grade) for i in range(3, len(w) - 2)):
        return True  # "followup", "checkup"
    g = word_grade(word)
    adults = any(knowledge().get(f, {}).get("known", 0) >= ADULT_KNOWN for f in forms(word))
    if g is not None:
        return g <= grade or (g <= grade + ADULT_GRADE_WINDOW and adults)
    return adults


def gloss(word: str, grade: int = READER_GRADE) -> str | None:
    """A plain meaning from the Living Word Vocabulary, if the word has a single one the reader knows."""
    entry = next((knowledge()[f] for f in forms(word) if f in knowledge()), {})
    meanings = entry.get("meanings", [])
    if len(meanings) == 1 and all(is_known(w, grade) for w in WORD.findall(meanings[0])):
        return meanings[0]
    return None


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if WORD.search(p)]


def assess(text: str, skip: set[str] = frozenset(), grade: int = READER_GRADE) -> dict:
    """How a reader at this grade would get on with the text.
    skip: words that don't count (medicine names, words explained in the text)."""
    skip = {s.lower() for s in skip}
    counted, unknown = 0, {}
    for w in WORD.findall(text):
        if w.lower() in skip or w.lower().strip("'") in skip or w.lower() in UNITS or w.lower() in TITLES or len(w) == 1:
            continue
        if w.isupper() and len(w) <= 5 and w.lower() not in knowledge():
            unknown[w] = unknown.get(w, 0) + 1  # leftover abbreviation
            counted += 1
            continue
        counted += 1
        if not is_known(w, grade):
            unknown[w.lower()] = unknown.get(w.lower(), 0) + 1
    lengths = [len(WORD.findall(s)) for s in sentences(text)]
    coverage = 1 - sum(unknown.values()) / counted if counted else 1.0
    long_sentences = [s for s, n in zip(sentences(text), lengths) if n > MAX_SENTENCE_WORDS]
    return {
        "grade": grade,
        "coverage": round(coverage, 3),
        "known_per_100": round(coverage * 100),
        "unknown": sorted(unknown, key=lambda w: (-unknown[w], w)),
        "words": counted,
        "sentences": len(lengths),
        "avg_sentence": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "max_sentence": max(lengths, default=0),
        "long_sentences": long_sentences,
        "ok_words": coverage >= COVERAGE_TARGET,
        "ok_sentences": (max(lengths, default=0) <= MAX_SENTENCE_WORDS
                         and (sum(lengths) / len(lengths) if lengths else 0) <= AVG_SENTENCE_WORDS),
    }


def describe(r: dict) -> str:
    """The check in plain words, for the clinician."""
    text = f"A reader at grade {r['grade']} would likely know {r['known_per_100']} of every 100 words"
    if r["unknown"]:
        text += "; might not know " + ", ".join(f"'{w}'" for w in r["unknown"][:6])
    return text + f". Sentences: {r['avg_sentence']} words on average, longest {r['max_sentence']}."


if __name__ == "__main__":
    result = assess(" ".join(sys.argv[1:]) or sys.stdin.read())
    print(describe(result))
