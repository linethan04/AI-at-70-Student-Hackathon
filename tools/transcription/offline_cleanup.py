"""Offline, no-API-key version of the transcript review in clean_transcript.py.

Produces the same TranscriptReview that Claude would, so the rest of the pipeline
(dictionary verification, output files) is shared. Weaker than Claude on hard cases.

Speakers: split by VOICE, not by meaning. Each sentence's audio is turned into a
  voice "fingerprint" with NVIDIA's TitaNet speaker model (run locally via sherpa-onnx),
  and similar fingerprints are grouped. Roles are guessed from word use: the speaker
  using the most medical terms and numbers is the clinician; the one saying "I"/"my"
  most is the patient.
Medical terms: words the speech recognizer itself was unsure of, and that are neither
  English nor already medical, are fuzzy-matched against RxNorm drug names and a ~98k-word
  medical spelling list. Strong single-word matches ("orthostratic" -> "orthostatic")
  become corrections; weaker ones become "did you mean" suggestions for the clinician.
  Words the recognizer was confident about are left alone unless they closely match a
  drug name (modern words like "smoothies" aren't in the English list, but aren't errors). Garbled multi-word phrases
  ("glitz preside" -> "glipizide") are beyond this method; Claude handles those.
"""

import re
import urllib.request
from pathlib import Path

import numpy as np

from clean_transcript import Issue, SpeakerInfo, TermCandidate, TranscriptReview, UtteranceSpeaker
from medical_dictionary import CACHE_DIR, drug_names, medical_words

SAMPLE_RATE = 16_000
SPEAKER_MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                     "speaker-recongition-models/nemo_en_titanet_small.onnx")
ENGLISH_WORDS = Path("/usr/share/dict/words")  # present on macOS and most Linux

MIN_EMBED_SECONDS = 1.5       # shorter clips are padded with surrounding audio
SAME_SPEAKER_SIMILARITY = 0.3  # average voice similarity needed to merge two groups
MIN_SPEAKER_SHARE = 0.05       # groups with under 5% of the speech (or 2.5 s) are merged into the closest one
AUTO_FIX_SCORE = 85            # fuzzy-match score (0-100) to auto-correct a word
SUGGEST_SCORE = 72             # ...and to suggest it for review


# ---------- speakers ----------

def _speaker_model() -> Path:
    path = CACHE_DIR / "nemo_en_titanet_small.onnx"
    if not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        print("Downloading speaker model (~40 MB, one time)...")
        urllib.request.urlretrieve(SPEAKER_MODEL_URL, path)
    return path


def _voice_fingerprints(audio: np.ndarray, segments: list[dict]) -> np.ndarray:
    import sherpa_onnx

    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(_speaker_model()), num_threads=2))
    out = []
    for seg in segments:
        start, end = seg["start"], seg["end"]
        if end - start < MIN_EMBED_SECONDS:
            mid = (start + end) / 2
            start, end = max(0.0, mid - MIN_EMBED_SECONDS / 2), mid + MIN_EMBED_SECONDS / 2
        stream = extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)])
        stream.input_finished()
        emb = np.array(extractor.compute(stream))
        out.append(emb / np.linalg.norm(emb))
    return np.array(out)


def _cluster(emb: np.ndarray, num_speakers: int | None) -> list[list[int]]:
    """Average-linkage clustering on cosine similarity: keep merging the two most similar
    groups until `num_speakers` remain, or (if unknown) until no pair is similar enough."""
    n = len(emb)
    groups = {i: [i] for i in range(n)}
    sums = emb @ emb.T  # sums[a, b] = total similarity between members of groups a and b
    sizes = np.ones(n)
    active = np.ones(n, dtype=bool)
    while len(groups) > 1:
        avg = sums / np.outer(sizes, sizes)
        avg[~active, :] = avg[:, ~active] = -np.inf
        np.fill_diagonal(avg, -np.inf)
        a, b = np.unravel_index(np.argmax(avg), avg.shape)
        if (num_speakers and len(groups) <= num_speakers) or (not num_speakers and avg[a, b] < SAME_SPEAKER_SIMILARITY):
            break
        sums[a, :] += sums[b, :]
        sums[:, a] += sums[:, b]
        sizes[a] += sizes[b]
        active[b] = False
        groups[a] += groups.pop(b)
    return list(groups.values())


def _is_fragment(seg: dict) -> bool:
    """A short piece cut mid-sentence ("I think", "That's") is usually the same person continuing."""
    return seg["end"] - seg["start"] < 1.0 and not seg["text"].rstrip().endswith((".", "?", "!"))


def assign_speakers(audio_path: Path, segments: list[dict], num_speakers: int | None) -> tuple[list[int], list[str]]:
    """Returns a speaker index (0, 1, ...) and a confidence for every segment."""
    from faster_whisper import decode_audio  # decodes wav/mp3/m4a to 16 kHz mono

    audio = decode_audio(str(audio_path), sampling_rate=SAMPLE_RATE)
    emb = _voice_fingerprints(audio, segments)
    core = [i for i, s in enumerate(segments) if not _is_fragment(s)] or list(range(len(segments)))
    groups = [[core[j] for j in g] for g in _cluster(emb[core], num_speakers)]

    # Too little speech to be a real extra person: fold into the most similar group.
    duration = lambda g: sum(segments[i]["end"] - segments[i]["start"] for i in g)
    min_seconds = max(2.5, MIN_SPEAKER_SHARE * duration(core))
    while not num_speakers and len(groups) > 1 and min(map(duration, groups)) < min_seconds:
        small = min(groups, key=duration)
        groups.remove(small)
        closest = max(groups, key=lambda g: np.mean(emb[small] @ emb[g].T))
        closest += small

    groups.sort(key=min)  # Speaker 1 = first to talk
    centroids = np.array([emb[g].mean(axis=0) for g in groups])
    labels, confidence = [0] * len(segments), ["low"] * len(segments)
    for k, g in enumerate(groups):
        for i in g:
            labels[i] = k
            sims = centroids @ emb[i]
            margin = sims[k] - max(np.delete(sims, k), default=-1.0)
            confidence[i] = "high" if margin >= 0.15 else "medium" if margin >= 0.05 else "low"
    # Fragments take the speaker of the sentence they run into.
    for i in reversed(range(len(segments))):
        if i not in core:
            labels[i] = labels[i + 1] if i + 1 < len(segments) else labels[i - 1]
            confidence[i] = "medium"
    return labels, confidence


# ---------- medical terms ----------

def _english_words() -> set[str]:
    return {w.strip().lower() for w in ENGLISH_WORDS.read_text().splitlines()} if ENGLISH_WORDS.exists() else set()


def _is_known(word: str, known: set[str]) -> bool:
    """Known as-is or after removing a common ending (episodes, tighter, having)."""
    if word in known:
        return True
    if word.endswith("ies") and word[:-3] + "y" in known:  # diaries, stories
        return True
    for suffix in ("s", "es", "ed", "d", "ing", "er", "est", "ly"):
        base = word[: -len(suffix)]
        if word.endswith(suffix) and len(base) >= 3 and (base in known or base + "e" in known):
            return True
    return False


TITLE_BEFORE = re.compile(r"\b(mr|mrs|ms|miss|dr|doctor)\.?\s*$", re.IGNORECASE)  # "Mrs. Alvarez"


def find_terms(segments: list[dict]) -> tuple[list[TermCandidate], list[Issue]]:
    from rapidfuzz import fuzz, process

    drugs = {d for d in drug_names() if re.fullmatch(r"[a-z]{4,}", d)}
    medical = medical_words()
    vocab = sorted({w for w in medical | drugs if len(w) >= 5})
    known = _english_words() | medical | drugs

    terms, issues = [], []
    for i, seg in enumerate(segments):
        # Older transcripts have no confidence info: treat every word as unsure.
        unsure = {u.lower() for u in seg["unsure_words"]} if "unsure_words" in seg else None
        for word in dict.fromkeys(re.findall(r"[A-Za-z]+(?:'[a-z]+)?", seg["text"])):  # splits "left-hand"
            if "'" in word:  # contractions: let's, you're, it's
                continue
            w = word.lower()
            confident = unsure is not None and w not in unsure
            # Capitalized mid-sentence = probably a name ("Mrs. Alvarez"); only flag strong matches.
            before = seg["text"][: seg["text"].find(word)] or (segments[i - 1]["text"] if i else "")
            is_name = word[0].isupper() and (bool(TITLE_BEFORE.search(before))
                                             or not seg["text"].startswith(word))
            if w in drugs and w not in _english_words():
                # A drug name spelled correctly: still list it so it shows as confirmed.
                terms.append(TermCandidate(utterance_id=i, heard=word, corrected_text=word,
                                           dictionary_term=w, category="medication"))
                continue
            if len(w) < 5 or _is_known(w, known):
                continue
            # Confident words and capitalized names: only check for (brand) drug names.
            choices = sorted(drugs) if (confident or is_name) else vocab
            match = process.extractOne(w, choices, scorer=fuzz.ratio,
                                       score_cutoff=AUTO_FIX_SCORE if is_name else SUGGEST_SCORE)
            if not match:
                continue
            best, score = match[0], match[1]
            if score >= AUTO_FIX_SCORE:
                terms.append(TermCandidate(utterance_id=i, heard=word, corrected_text=best, dictionary_term=best,
                                           category="medication" if best in drugs else "medical_term"))
            else:
                issues.append(Issue(utterance_id=i, problem=f'Unrecognized word "{word}". Did you mean "{best}"?'))
    return terms, issues


# ---------- combined review ----------

CLINICAL_CUES = re.compile(r"\b(your|you're|let's|i'm going to|we'll|mg|milligrams?|\d+)\b", re.IGNORECASE)
PATIENT_CUES = re.compile(r"\b(i|i'm|i've|my|me)\b", re.IGNORECASE)


def _guess_roles(segments: list[dict], labels: list[int], terms: list[TermCandidate], n: int) -> list[SpeakerInfo]:
    medical = medical_words()
    stats = []
    for k in range(n):
        text = " ".join(s["text"] for s, l in zip(segments, labels) if l == k)
        words = max(1, len(text.split()))
        med = sum(1 for w in re.findall(r"[a-z]+", text.lower()) if w in medical and len(w) > 6)
        med += sum(1 for t in terms if labels[t.utterance_id] == k)
        stats.append({"clinical": (med * 3 + len(CLINICAL_CUES.findall(text))) / words,
                      "personal": len(PATIENT_CUES.findall(text)) / words, "words": words})

    roles = ["unknown"] * n
    clinician = max(range(n), key=lambda k: stats[k]["clinical"])
    roles[clinician] = "clinician"
    others = [k for k in range(n) if k != clinician]
    if others:
        roles[max(others, key=lambda k: stats[k]["personal"] * min(stats[k]["words"], 50))] = "patient"
    return [SpeakerInfo(label=f"Speaker {k + 1}", role=roles[k],
                        evidence=f"voice group; {stats[k]['words']} words, clinical-language score "
                                 f"{stats[k]['clinical']:.2f}, first-person score {stats[k]['personal']:.2f}")
            for k in range(n)]


def review_offline(segments: list[dict], audio_path: Path | None, num_speakers: int | None,
                   log=print) -> TranscriptReview:
    issues: list[Issue] = []
    if audio_path and audio_path.exists():
        log("Separating speakers by voice (TitaNet, offline)...")
        labels, confidence = assign_speakers(audio_path, segments, num_speakers)
    else:
        labels, confidence = [0] * len(segments), ["low"] * len(segments)
        issues.append(Issue(utterance_id=0, problem=f"Audio file not found ({audio_path}); speakers not separated."))

    log("Matching words against medical dictionaries (offline)...")
    terms, term_issues = find_terms(segments)
    n = max(labels) + 1
    return TranscriptReview(
        speakers=_guess_roles(segments, labels, terms, n),
        utterances=[UtteranceSpeaker(id=i, speaker=f"Speaker {l + 1}", confidence=c)
                    for i, (l, c) in enumerate(zip(labels, confidence))],
        terms=terms,
        issues=issues + term_issues,
    )
