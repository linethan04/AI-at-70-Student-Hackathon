"""Build the reader baseline: which English words a reader at a given school grade knows.

Sources (free research data, Open Science Framework):
  - Test-based age-of-acquisition norms for 44,000 English word meanings (Brysbaert & Biemiller, 2017),
    built on Dale & O'Rourke's Living Word Vocabulary: the school grade at which most students
    tested knew each meaning, plus a short gloss of the meaning ("chronic": "lasting a long time").
    Also carries the Kuperman et al. (2012) age-of-acquisition ratings.     https://osf.io/kz2px
  - Word prevalence norms for 62,000 English words (Brysbaert, Mandera, McCormick & Keuleers, 2019):
    the share of ~220,000 adults who know each word.                         https://osf.io/nbu9e
Older adults know at least as many everyday words as younger adults; what trips them up is medical
vocabulary and memory load, which the reader check (reader.py) handles separately.

    python Ethan/conversion_library/build_reader_baseline.py

Writes data/word_knowledge.json (committed): word -> {"grade", "aoa", "known", "meanings"}.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
OUT = HERE / "data" / "word_knowledge.json"
TEST_BASED_URL = "https://osf.io/download/x7akt/"
PREVALENCE_URL = "https://osf.io/nbu9e/download"


def download(url: str, name: str) -> Path:
    path = RAW / name
    if not path.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {url}")
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            path.write_bytes(client.get(url).raise_for_status().content)
    return path


def rows(path: Path):
    import openpyxl
    import warnings
    warnings.filterwarnings("ignore", module="openpyxl")
    sheet = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    it = sheet.iter_rows(values_only=True)
    header = next(it)
    for row in it:
        yield dict(zip(header, row))


def number(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    words: dict[str, dict] = defaultdict(dict)
    meanings = defaultdict(list)
    for r in rows(download(TEST_BASED_URL, "testbased_aoa.xlsx")):
        word = str(r["WORD"] or "").strip().lower()
        grade = number(r["AoAtestbased"])
        if not re.fullmatch(r"[a-z][a-z' -]*", word) or grade is None:
            continue
        w = words[word]
        w["grade"] = min(grade, w.get("grade", 99))           # the easiest meaning
        if number(r["AoArating"]) is not None:
            w["aoa"] = round(number(r["AoArating"]), 1)
        meanings[word].append((grade, str(r["MEANING"] or "").strip()))
    for word, ms in meanings.items():
        words[word]["meanings"] = [m for _, m in sorted(ms)][:3]
    for r in rows(download(PREVALENCE_URL, "word_prevalence.xlsx")):
        word = str(r["Word"] or "").strip().lower()
        known = number(r["Pknown"])
        if re.fullmatch(r"[a-z][a-z' -]*", word) and known is not None:
            words[word]["known"] = round(known, 3)
    OUT.write_text(json.dumps({
        "sources": {
            "test_based": "Brysbaert & Biemiller (2017), Test-based age-of-acquisition norms for 44 thousand English "
                          "word meanings, Behavior Research Methods 49, 1520-1523; from Dale & O'Rourke (1981), "
                          "The Living Word Vocabulary. https://osf.io/kz2px",
            "prevalence": "Brysbaert, Mandera, McCormick & Keuleers (2019), Word prevalence norms for 62,000 English "
                          "lemmas, Behavior Research Methods 51, 467-479. https://osf.io/nbu9e",
        },
        "words": dict(sorted(words.items())),
    }, separators=(",", ":"), ensure_ascii=False))
    graded = sum(1 for w in words.values() if "grade" in w)
    print(f"Wrote {OUT.relative_to(HERE)}: {len(words)} words ({graded} with a school grade, "
          f"{sum(1 for w in words.values() if 'known' in w)} with adult prevalence), "
          f"{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
