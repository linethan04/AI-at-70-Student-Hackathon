"""Step 1b: clean up a raw transcript from EL_audio.py.

1. Speakers: Claude reads the whole conversation and assigns every sentence to
   Speaker 1 / 2 / 3... using context (who asks vs. answers, clinical language,
   "doctor", "mom", ...), and guesses each speaker's role (clinician, patient, family).
   ElevenLabs' acoustic labels, when present, are passed along as hints.
2. Medical terms: Claude finds medical terms, including ones the speech recognizer garbled
   ("glitz preside" -> "glipizide"), and proposes the intended term.
3. Verification: every proposed term is checked against NLM vocabularies
   (medical_dictionary.py) and must sound like what was heard. Only corrections that
   pass both checks are applied; everything else is left as heard and flagged for the
   clinician. Claude never rewrites the text itself: this script makes the exact substitutions.

No Anthropic API key? Steps 1-2 fall back to offline_cleanup.py (speakers by voice,
terms by fuzzy dictionary match). Step 3 and the output format are the same.

    python Ethan/audio_workflow/clean_transcript.py Ethan/audio_workflow/transcripts/visit.json [--num-speakers 2]
    python Ethan/audio_workflow/clean_transcript.py ... --engine offline   # force offline (default: auto)

Writes <name>.clean.txt (for people) and <name>.clean.json (for the next pipeline step).
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable, Literal

import anthropic
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

from EL_audio import fmt_time
from medical_dictionary import lookup, sounds_similar

HERE = Path(__file__).resolve().parent
MODEL = "claude-opus-5-5"
MIN_SOUND_SIMILARITY = 0.5  # below this, a "correction" may be a different word, not a mishearing

SYSTEM_PROMPT = """\
You review automatic speech-recognition transcripts of primary-care visits with older adults. \
Your output is used to clean the transcript before a clinician reviews it, so accuracy matters \
more than completeness: when you are unsure, say so rather than guess.

The transcript arrives as numbered utterances. Some carry an acoustic speaker label from the \
recognizer; treat those as hints that can be wrong. Others have no speaker information at all.

1. Speakers. Assign every utterance to "Speaker 1", "Speaker 2", ... numbered in order of first \
appearance. Use context: who asks and who answers, who uses clinical language or gives \
instructions, how people address each other ("doctor", "Mom"), and natural turn-taking (a \
question is usually answered by someone else). Give each speaker a role and cite the evidence. \
Mark confidence "low" for any utterance you are guessing on. If one utterance seems to contain \
two speakers, assign it to the main one and report it as an issue.

2. Medical terms. List every medication, drug class, condition or symptom, lab test, and \
procedure mentioned, including ones the recognizer garbled into sound-alike words \
(e.g. "glitz preside" for "glipizide"). List correctly transcribed medications too, so they \
can be verified. For each:
- heard: copied exactly, character for character, from that utterance's text.
- corrected_text: what should replace it in the transcript (same grammatical form, e.g. \
"hypoglycemic"). Equal to heard if it was already right.
- dictionary_term: the standard name to look up (generic drug name, drug class name, condition \
as a noun such as "hypoglycemia", lab test name).
Only propose a correction when the sound and the clinical context make the intended term clear. \
Never change numbers, doses, or frequencies; if one looks wrong, report it as an issue.

3. Issues. Report anything a clinician should check: unintelligible passages, possible \
misheard numbers or doses, self-corrections or contradictions, and utterances that may mix \
speakers. Do not add medical information that is not in the transcript."""


class SpeakerInfo(BaseModel):
    label: str
    role: Literal["clinician", "patient", "family member or caregiver", "other", "unknown"]
    evidence: str


class UtteranceSpeaker(BaseModel):
    id: int
    speaker: str
    confidence: Literal["high", "medium", "low"]


class TermCandidate(BaseModel):
    utterance_id: int
    heard: str
    corrected_text: str
    dictionary_term: str
    category: Literal["medication", "drug_class", "condition", "lab_test", "procedure", "medical_term", "other"]


class Issue(BaseModel):
    utterance_id: int
    problem: str


class TranscriptReview(BaseModel):
    speakers: list[SpeakerInfo]
    utterances: list[UtteranceSpeaker]
    terms: list[TermCandidate]
    issues: list[Issue]


class NoCredentials(Exception):
    pass


def review_with_claude(segments: list[dict], acoustic_labels: bool, num_speakers: int | None) -> TranscriptReview:
    lines = []
    for i, seg in enumerate(segments):
        label = f" ({seg['speaker']})" if acoustic_labels else ""
        lines.append(f"[{i}] [{fmt_time(seg['start'])}]{label} {seg['text']}")
    hint = f"There were {num_speakers} people in the room.\n\n" if num_speakers else ""

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if Opus declines, the API retries on a recommended fallback model
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"{hint}<transcript>\n" + "\n".join(lines) + "\n</transcript>"}],
            output_format=TranscriptReview,
        )
    except (TypeError, anthropic.AuthenticationError) as e:
        if isinstance(e, TypeError) and "authentication" not in str(e):
            raise
        raise NoCredentials from e
    if response.stop_reason == "refusal" or response.parsed_output is None:
        sys.exit(f"Claude did not return a review (stop_reason={response.stop_reason}).")
    return response.parsed_output


def replace_once(text: str, old: str, new: str) -> str | None:
    """Replace the first exact occurrence of `old`, falling back to case-insensitive."""
    if old in text:
        return text.replace(old, new, 1)
    pattern = re.compile(re.escape(old), re.IGNORECASE)
    return pattern.sub(new, text, count=1) if pattern.search(text) else None


def check_terms(segments: list[dict], terms: list[TermCandidate]) -> list[dict]:
    """Verify each term against the dictionary and apply the safe corrections to `segments` in place."""
    results = []
    for term in terms:
        if not 0 <= term.utterance_id < len(segments):
            continue
        seg = segments[term.utterance_id]
        # Drug names (generic and brand) are in RxNorm as written, so verify the exact word we
        # insert. Conditions etc. change form ("hypoglycemic" vs "hypoglycemia"), so use the noun.
        is_drug = term.category in ("medication", "drug_class")
        found = lookup(term.corrected_text if is_drug else term.dictionary_term, term.category)
        similarity = sounds_similar(term.heard, term.corrected_text)
        is_change = term.heard.strip().lower() != term.corrected_text.strip().lower()

        if found.found is None:
            status = "not checked"
        elif not found.found:
            status = "not in dictionary"
        elif is_change and similarity < MIN_SOUND_SIMILARITY:
            status = "needs review"  # real term, but it doesn't sound like what was heard
        elif is_change:
            new_text = replace_once(seg["text"], term.heard, term.corrected_text)
            status = "corrected" if new_text else "needs review"
            if new_text:
                seg["text"] = new_text
        else:
            status = "confirmed"

        results.append({
            "time": fmt_time(seg["start"]),
            "utterance_id": term.utterance_id,
            "heard": term.heard,
            "corrected_text": term.corrected_text,
            "dictionary_term": term.dictionary_term,
            "category": term.category,
            "status": status,
            "dictionary_match": found.matched,
            "dictionary_source": found.source,
            "suggestions": found.suggestions[:3],
            "sound_similarity": round(similarity, 2),
        })
    return results


def merge_turns(segments: list[dict]) -> list[dict]:
    """Join consecutive utterances by the same speaker into one turn."""
    turns: list[dict] = []
    for seg in segments:
        if turns and turns[-1]["speaker"] == seg["speaker"]:
            turns[-1]["text"] += " " + seg["text"]
            turns[-1]["end"] = seg["end"]
        else:
            turns.append(dict(seg))
    return turns


STATUS_MARK = {"corrected": "✓ corrected", "confirmed": "✓ confirmed", "needs review": "? review",
               "not in dictionary": "✗ not found", "not checked": "- unchecked"}


def render_text(method: str, speakers: list[dict], turns: list[dict], term_results: list[dict], issues: list[dict],
                low_confidence: list[dict]) -> str:
    out = [f"Reviewed by: {method}", "", "SPEAKERS"]
    out += [f"  {s['label']}: {s['role']} ({s['evidence']})" for s in speakers]

    out += ["", "TRANSCRIPT"]
    for t in turns:
        out.append(f"[{fmt_time(t['start'])}] {t['speaker']} ({t['role']}): {t['text']}\n")

    out += ["MEDICAL TERM CHECK (RxNorm, RxClass, ICD-10-CM, LOINC, HCPCS, medical spelling list)"]
    for r in term_results:
        change = f'"{r["heard"]}" -> "{r["corrected_text"]}"' if r["heard"] != r["corrected_text"] else f'"{r["heard"]}"'
        detail = f"{r['dictionary_source']}: {r['dictionary_match']}" if r["dictionary_match"] else r["dictionary_source"]
        if r["status"] in ("not in dictionary", "needs review") and r["suggestions"]:
            detail += f"; did you mean: {', '.join(r['suggestions'])}"
        out.append(f"  {STATUS_MARK[r['status']]:<13} [{r['time']}] {change}  [{detail}]")

    review = [f"  [{i['time']}] {i['problem']}" for i in issues]
    review += [f"  [{r['time']}] Check term: \"{r['heard']}\" ({r['status']})"
               for r in term_results if r["status"] not in ("corrected", "confirmed")]
    review += [f"  [{u['time']}] Speaker unsure ({u['speaker']}?): {u['text']}" for u in low_confidence]
    out += ["", "NEEDS CLINICIAN REVIEW"] + (review or ["  Nothing flagged."])
    return "\n".join(out) + "\n"


OFFLINE_METHOD = "offline (TitaNet voice clustering + dictionary fuzzy matching)"


def find_audio(raw: dict, json_path: Path) -> Path | None:
    """The transcript records where its audio was; fall back to recordings/ if files moved."""
    if not raw.get("source_audio"):
        return None
    recorded = Path(raw["source_audio"])
    for candidate in (recorded, HERE / "recordings" / recorded.name, json_path.parent.parent / "recordings" / recorded.name):
        if candidate.exists():
            return candidate
    return recorded


def clean_transcript(json_path: Path, num_speakers: int | None = None, engine: str = "auto",
                     log: Callable[[str], None] = print) -> Path:
    """`log` receives short progress messages (the web app shows them as status)."""
    raw = json.loads(json_path.read_text())
    segments = [dict(s) for s in raw["segments"]]
    acoustic = raw.get("engine") == "elevenlabs"

    review = None
    if engine in ("auto", "claude"):
        log(f"Reviewing {len(segments)} utterances with Claude ({MODEL})...")
        try:
            review, method = review_with_claude(segments, acoustic, num_speakers), MODEL
        except NoCredentials:
            if engine == "claude":
                sys.exit("No valid Anthropic credentials. Add ANTHROPIC_API_KEY=... to .env in the project root.")
            log("No Anthropic API key found; using the offline method instead.")
    if review is None:
        from offline_cleanup import review_offline
        review, method = review_offline(segments, find_audio(raw, json_path), num_speakers, log), OFFLINE_METHOD

    assigned = {u.id: u for u in review.utterances}
    roles = {s.label: s.role for s in review.speakers}
    low_confidence = []
    for i, seg in enumerate(segments):
        u = assigned.get(i)
        seg["acoustic_speaker"] = seg["speaker"] if acoustic else None
        seg["speaker"] = u.speaker if u else "Unknown"
        seg["role"] = roles.get(seg["speaker"], "unknown")
        seg["speaker_confidence"] = u.confidence if u else "low"
        if seg["speaker_confidence"] == "low" and len(seg["text"].split()) >= 4:  # skip "Okay."/"Yeah."
            low_confidence.append({"time": fmt_time(seg["start"]), "speaker": seg["speaker"], "text": seg["text"]})

    log(f"Checking {len(review.terms)} medical terms against medical dictionaries...")
    term_results = check_terms(segments, review.terms)
    issues = [{"time": fmt_time(segments[i.utterance_id]["start"]) if 0 <= i.utterance_id < len(segments) else "--:--",
               "utterance_id": i.utterance_id, "problem": i.problem} for i in review.issues]
    speakers = [s.model_dump() for s in review.speakers]
    turns = merge_turns(segments)

    out_json = json_path.with_name(json_path.stem + ".clean.json")
    out_txt = json_path.with_name(json_path.stem + ".clean.txt")
    out_json.write_text(json.dumps({
        "source_transcript": str(json_path),
        "method": method,
        "speakers": speakers,
        "turns": turns,
        "utterances": segments,
        "term_checks": term_results,
        "issues": issues,
    }, indent=2))
    out_txt.write_text(render_text(method, speakers, turns, term_results, issues, low_confidence))

    if log is print:
        print("\n" + out_txt.read_text())
    log(f"Saved {out_txt}\nSaved {out_json}")
    return out_json


def main() -> None:
    load_dotenv(find_dotenv())  # searches upward for the project-root .env
    parser = argparse.ArgumentParser(description="Separate speakers and verify medical terms in a transcript.")
    parser.add_argument("transcript", type=Path, help="a .json transcript from EL_audio.py")
    parser.add_argument("--num-speakers", type=int, help="how many people were in the room, if known")
    parser.add_argument("--engine", choices=("auto", "claude", "offline"), default="auto",
                        help="auto = Claude if an API key works, otherwise offline")
    args = parser.parse_args()
    if not args.transcript.exists():
        parser.error(f"file not found: {args.transcript}")
    clean_transcript(args.transcript, args.num_speakers, args.engine)


if __name__ == "__main__":
    main()
