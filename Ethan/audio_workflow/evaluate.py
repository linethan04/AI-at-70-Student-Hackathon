"""Score a pipeline transcript against a human answer key from fetch_test_audio.py.

    python Ethan/audio_workflow/evaluate.py transcripts/primock_day1_consultation01.clean.json \
        test_data/primock_day1_consultation01.reference.json

Reports:
  Word error rate   share of words wrong/missing/extra vs. the human transcript, ignoring
                    "um"/"uh" fillers (lower is better)
  Speaker accuracy  share of speech time attributed to the right person, after matching
                    "Speaker 1/2" to Doctor/Patient (higher is better)
  Role labels       whether the speaker the pipeline called "clinician" really is the doctor
  Drug names        RxNorm drug names in the human transcript that also appear in ours
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from medical_dictionary import drug_names


FILLERS = {"um", "uh", "er", "erm", "hmm", "mm", "mhm", "ah", "eh", "oh"}


def words(text: str) -> list[str]:
    """Lowercase words without punctuation or filler sounds, which transcribers handle differently."""
    return [w for w in re.findall(r"[a-z0-9']+", text.lower().replace("-", " ")) if w not in FILLERS]


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    return Levenshtein.distance(ref, hyp) / max(1, len(ref))


def overlap(a: dict, b: dict) -> float:
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def speaker_scores(reference: list[dict], hypothesis: list[dict]) -> tuple[float, dict[str, str]]:
    """Map each pipeline speaker to the reference speaker it overlaps most, then measure
    the share of overlapping speech time that lands on the correct person."""
    time = defaultdict(float)  # (hyp speaker, ref speaker) -> seconds
    for h in hypothesis:
        for r in reference:
            time[h["speaker"], r["speaker"]] += overlap(h, r)
    mapping = {}
    for hyp_spk in {h["speaker"] for h in hypothesis}:
        options = {ref: t for (hs, ref), t in time.items() if hs == hyp_spk}
        mapping[hyp_spk] = max(options, key=options.get) if any(options.values()) else "?"
    total = sum(time.values())
    correct = sum(t for (hs, ref), t in time.items() if mapping.get(hs) == ref)
    return (correct / total if total else 0.0), mapping


def drug_recall(reference: str, hypothesis: str) -> tuple[list[str], list[str]]:
    drugs = drug_names()
    ref_words, hyp_words = set(words(reference)), set(words(hypothesis))
    english_like = {"water", "oxygen", "alcohol", "iron", "salt", "sugar", "caffeine", "coffee", "tea", "today",
                    "tomorrow", "cholesterol", "latex", "lactose", "halls", "cocaine"}  # RxNorm has products named these
    mentioned = sorted(w for w in ref_words if w in drugs and len(w) > 4 and w not in english_like)
    return mentioned, [w for w in mentioned if w in hyp_words]


def evaluate(hyp_path: Path, ref_path: Path) -> dict:
    hyp = json.loads(hyp_path.read_text())
    ref = json.loads(ref_path.read_text())
    ref_utts = ref["utterances"]
    hyp_utts = hyp.get("utterances") or hyp["segments"]  # .clean.json or raw transcript .json

    ref_text = " ".join(u["text"] for u in ref_utts)
    hyp_text = " ".join(u["text"] for u in hyp_utts)
    wer = word_error_rate(ref_text, hyp_text)
    accuracy, mapping = speaker_scores(ref_utts, hyp_utts)
    mentioned, found = drug_recall(ref_text, hyp_text)

    roles = {s["label"]: s["role"] for s in hyp.get("speakers", [])}
    role_check = {spk: f"{roles.get(spk, '?')} -> actually {who}" for spk, who in mapping.items()}

    print(f"Pipeline output : {hyp_path.name}  ({hyp.get('method', hyp.get('engine', ''))})")
    print(f"Answer key      : {ref_path.name}  ({len(ref_utts)} human-transcribed utterances)")
    print(f"Word error rate : {wer:.1%}   (share of words wrong vs. the human transcript)")
    print(f"Speaker accuracy: {accuracy:.1%}   (share of speech time given to the right person)")
    for spk, check in sorted(role_check.items()):
        print(f"  {spk}: labeled {check}")
    print(f"Drug names      : {len(found)}/{len(mentioned)} found  {found}"
          + (f"  missing: {sorted(set(mentioned) - set(found))}" if set(mentioned) - set(found) else ""))
    return {"wer": wer, "speaker_accuracy": accuracy, "mapping": mapping, "drugs_mentioned": mentioned,
            "drugs_found": found}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a pipeline transcript with a human answer key.")
    parser.add_argument("transcript", type=Path, help=".clean.json (or raw .json) from the pipeline")
    parser.add_argument("reference", type=Path, help=".reference.json from fetch_test_audio.py")
    args = parser.parse_args()
    evaluate(args.transcript, args.reference)


if __name__ == "__main__":
    main()
