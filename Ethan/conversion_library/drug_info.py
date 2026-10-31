"""What a medicine does, in plain words, from MedlinePlus drug information (NLM).

    name in the note -> RxNorm id (RxNav) -> MedlinePlus Connect -> the drug page's
    "Why is this medication prescribed?" text, e.g.
    metformin: "Metformin is used to treat type 2 diabetes ... helps to control the amount of glucose
    (sugar) in your blood."

UK names RxNorm doesn't know are looked up under their US name (paracetamol -> acetaminophen);
the note's own name is always the one shown. Results are cached in data/drug_info.json
(committed), so the app works offline for any medicine looked up before.

    python Ethan/conversion_library/drug_info.py                  # look up every medicine in the test notes
    python Ethan/conversion_library/drug_info.py metformin aspirin
"""

import html
import json
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
CACHE = HERE / "data" / "drug_info.json"
RXNAV = "https://rxnav.nlm.nih.gov/REST/rxcui.json"
CONNECT = ("https://connect.medlineplus.gov/service?mainSearchCriteria.v.cs=2.16.840.1.113883.6.88"
           "&mainSearchCriteria.v.c={rxcui}&knowledgeResponseType=application/json")
UK_NAMES = {  # British Approved Name -> US name used by RxNorm / MedlinePlus
    "paracetamol": "acetaminophen", "salbutamol": "albuterol", "alendronic acid": "alendronate", "alendronic": "alendronate",
    "co-codamol": "acetaminophen and codeine", "co-amoxiclav": "amoxicillin and clavulanate",
    "frusemide": "furosemide", "glyceryl trinitrate": "nitroglycerin", "adrenaline": "epinephrine",
    "lignocaine": "lidocaine", "colecalciferol": "cholecalciferol", "beclometasone": "beclomethasone",
    "budesonide/formoterol": "budesonide and formoterol", "ibuprofen gel": "ibuprofen", "clenil": "beclomethasone",
}
FAILED: set[str] = set()
HEADERS = {"User-Agent": "AI-at-70-hackathon/1.0 (https://github.com/linethan04/AI-at-70-Student-Hackathon; educational)"}


@lru_cache(maxsize=1)
def cache() -> dict:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def save() -> None:
    CACHE.write_text(json.dumps(dict(sorted(cache().items())), indent=1, ensure_ascii=False) + "\n")


def fetch(name: str) -> dict:
    query = re.sub(r"\s*[/+]\s*", " and ", UK_NAMES.get(name, name))  # "sacubitril/valsartan" -> "... and valsartan"
    with httpx.Client(timeout=10, headers=HEADERS) as client:
        ids = client.get(RXNAV, params={"name": query, "search": 2}).json().get("idGroup", {}).get("rxnormId", [])
        if not ids:
            return {"found": False, "query": query}
        feed = client.get(CONNECT.format(rxcui=ids[0])).json().get("feed", {})
    for entry in feed.get("entry", []):
        link = next((l["href"] for l in entry.get("link", []) if "/druginfo/meds/" in l["href"]), None)
        if link:
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", entry.get("summary", {}).get("_value", ""))))
            return {"found": True, "query": query, "title": entry["title"]["_value"],
                    "url": link.split("?")[0], "why": text.strip()}
    return {"found": False, "query": query}


def lookup(name: str, online: bool = True, tries: int = 3) -> dict:
    """MedlinePlus info for a medicine named in a note ({"found": False} if none)."""
    key = name.lower().strip()
    us_name = UK_NAMES.get(key)
    if key not in cache() and us_name in cache():
        return cache()[us_name]  # "paracetamol": use what was found for "acetaminophen"
    if key not in cache() and online and key not in FAILED:
        for attempt in range(tries):
            try:
                cache()[key] = fetch(key)
                save()
                break
            except (httpx.HTTPError, ValueError):  # network blip or a non-JSON error page
                time.sleep(1.5 * (attempt + 1))
        else:
            FAILED.add(key)  # don't wait on the network again this session
            return {"found": False, "query": key, "error": "offline"}
    return cache().get(key, {"found": False, "query": key})


def main() -> None:
    names = sys.argv[1:]
    if not names:
        from visit_summary import note_medicines
        notes = list((HERE / "test_notes").glob("*/*.txt")) + list((HERE / "samples").glob("*.txt"))
        names = sorted({m for p in notes for m in note_medicines(p.read_text())})
    for name in names:
        info = lookup(name)
        print(f"{name}: {info.get('title', '-')}  {info.get('url', 'not found')}")


if __name__ == "__main__":
    main()
