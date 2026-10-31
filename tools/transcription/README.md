# tools/transcription/

This tool records the visit and writes out the conversation. It also tells the speakers apart and checks medical terms. In the app it is mounted at `/audio` and runs behind the **Record** and **Upload audio** buttons. Recording is optional, but it adds helpful detail.

| File | What it does |
|---|---|
| [`EL_audio.py`](EL_audio.py) | Records from the microphone or reads a file, then transcribes it. ElevenLabs Scribe is used when `ELEVENLABS_API_KEY` is set (speaker labels, medical keyterms); otherwise local Whisper (`faster-whisper`, offline). Writes `transcripts/<name>.txt` and `.json`. |
| [`clean_transcript.py`](clean_transcript.py) | Assigns each sentence to a speaker (Clinician, Patient, Family) and proposes fixes for misheard medical terms. A fix is applied only if the term exists in an NLM vocabulary and sounds like what was heard; otherwise it is flagged. Uses Claude when `ANTHROPIC_API_KEY` is set. |
| [`offline_cleanup.py`](offline_cleanup.py) | The no-key fallback. Separates speakers by voice (NVIDIA TitaNet via `sherpa-onnx`) and fuzzy-matches unknown words against RxNorm and a ~98k medical word list. |
| [`medical_dictionary.py`](medical_dictionary.py) | Free NLM lookups: RxNorm (drugs), RxClass (drug classes), ICD-10-CM and Conditions, LOINC (labs), HCPCS (procedures). Cached in `.cache/`. |
| [`app.py`](app.py) + [`static/`](static/) | Its own small web page: record or upload, then read the transcript. |

## Run on its own

```bash
python tools/transcription/EL_audio.py record                         # record until Enter, then transcribe
python tools/transcription/EL_audio.py transcribe visit.wav --clean   # transcribe a file + speakers + term check
python tools/transcription/EL_audio.py transcribe visit.wav --engine whisper --keyterms "metformin,lisinopril"
python tools/transcription/clean_transcript.py tools/transcription/transcripts/<name>.json [--num-speakers 2] [--engine auto|claude|offline]
python tools/transcription/medical_dictionary.py medication glipizide # check one term
python tools/transcription/app.py                                     # web page: http://localhost:5050 (settings at /advanced)
python tools/transcription/app.py --public                            # visitors only see their own result
```

The first offline run downloads the speaker model (~40 MB) and the word lists into `.cache/`.

**Privacy:** `recordings/` and `transcripts/` are git-ignored. Never commit real patient audio or transcripts.
