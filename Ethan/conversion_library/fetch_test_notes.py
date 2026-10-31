"""Download real-style clinician notes to test the converter on.

- PriMock57 (Babylon Health, CC BY 4.0): 57 short GP consultation notes written by clinicians,
  full of UK shorthand ("2/7", "BD", "U+Es", "NKDA").  github.com/babylonhealth/primock57
- MTSamples (mtsamples.com, sample transcribed reports; credit requested): general medicine
  consults and hospital discharge summaries, US style, longer and lab-heavy. Pulled from the
  Hugging Face mirror "anurag-raapid/mt-samples".

These are mock/sample documents, not real patient records.

    python Ethan/conversion_library/fetch_test_notes.py

Writes test_notes/primock57/*.txt and test_notes/mtsamples/*.txt
"""

import json
import re
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
TEST_NOTES = HERE / "test_notes"
PRIMOCK_API = "https://api.github.com/repos/babylonhealth/primock57/contents/notes"
PRIMOCK_RAW = "https://raw.githubusercontent.com/babylonhealth/primock57/main/notes/{name}"
MTSAMPLES_ROWS = "https://datasets-server.huggingface.co/rows?dataset=anurag-raapid/mt-samples&config=default&split={split}&offset={offset}&length=100"
MTSAMPLES_KEEP = ("General Medicine", "Discharge Summary", "SOAP / Chart / Progress Notes", "Office Notes")


def fetch_primock(client: httpx.Client) -> int:
    out = TEST_NOTES / "primock57"
    out.mkdir(parents=True, exist_ok=True)
    names = [f["name"] for f in client.get(PRIMOCK_API).json() if f["name"].endswith(".json")]
    for name in names:
        note = client.get(PRIMOCK_RAW.format(name=name)).json()
        text = f"Presenting complaint: {note['presenting_complaint']}\n\n{note['note'].strip()}\n"
        (out / name.replace(".json", ".txt")).write_text(text)
    return len(names)


def tidy(text: str) -> str:
    """The mirror is tokenized ("fever , weight"); put punctuation back where it belongs."""
    text = re.sub(r" +([,.;:?!)%])", r"\1", text)
    text = re.sub(r"([(]) +", r"\1", text)
    return re.sub(r"[ \t]+", " ", text).strip() + "\n"


def fetch_mtsamples(client: httpx.Client) -> int:
    out = TEST_NOTES / "mtsamples"
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for split in ("train", "test"):
        for offset in (0, 100):
            rows = client.get(MTSAMPLES_ROWS.format(split=split, offset=offset)).json().get("rows", [])
            for row in rows:
                text = row["row"]["text"]
                specialty = re.search(r"Specialty\s*:\s*([^\n]+)", text)
                name = re.search(r"Sample Name\s*:\s*([^\n]+)", text)
                if not (specialty and name) or not specialty.group(1).strip().startswith(MTSAMPLES_KEEP):
                    continue
                # Drop the site's header lines; keep the report itself.
                body = re.split(r"\n\s*(?:Description|Template Description)\s*:", text, maxsplit=1)[-1]
                slug = re.sub(r"[^a-z0-9]+", "_", f"{specialty.group(1)} {name.group(1)}".lower()).strip("_")[:60]
                (out / f"{slug}.txt").write_text(tidy(body))
                count += 1
    return count


def main() -> None:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        print(f"PriMock57: {fetch_primock(client)} notes")
        print(f"MTSamples: {fetch_mtsamples(client)} reports")
    print(f"Saved to {TEST_NOTES}")


if __name__ == "__main__":
    main()
