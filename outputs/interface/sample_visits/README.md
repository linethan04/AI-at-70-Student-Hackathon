# outputs/interface/sample_visits/

Five made-up visits for testing the AI at 70 app by hand or automatically. Every patient, note and recording is fictional. The recordings are synthetic voices (macOS `say`).

| Visit | Patient | Language | What it tests |
|---|---|---|---|
| [1_maria_rodriguez_english](1_maria_rodriguez_english/) | Maria Rodriguez, 78 (the demo video's patient) | English | diabetes and blood pressure; a lower dose, a higher dose; a medicine that may cause swelling; email to the patient and her daughter |
| [2_wei_chen_mandarin](2_wei_chen_mandarin/) | Wei Chen, 81 | Mandarin | COPD flare-up; inhalers ("use", not "take"); a short steroid course; **inputs disagree**: ibuprofen is on his check-in and in the conversation but not in the note; no patient email, son has consent |
| [3_joao_silva_portuguese](3_joao_silva_portuguese/) | João Silva, 76 | Portuguese | heart failure; a water pill raised; daily weights and a salt limit; "call us if" rules |
| [4_fatima_haddad_arabic](4_fatima_haddad_arabic/) | Fatima Haddad, 73 | Arabic (right to left) | bladder infection and weak bones; an antibiotic for 5 days; vitamin and mineral; a urine test and a bone scan; a sulfa allergy |
| [5_rosa_gomez_spanish](5_rosa_gomez_spanish/) | Rosa Gómez, 84 | Spanish | no recording (**Skip**); a stopped medicine; a referral; no email or family consent, so nothing can be emailed |

## What is in each folder

| File | What it is | Where it goes in the app |
|---|---|---|
| `checkin.json` | the patient's check-in, as exported by the questionnaire (free-text answers in the patient's language) | step 1, **Choose file** |
| `conversation.m4a` | the visit recording (not in Rosa's visit) | step 2, **Upload audio** |
| `conversation.txt` | the same conversation as text | step 2, **Upload transcript**, if you'd rather not wait for transcription |
| `note.txt` | the clinician's typed note | step 3, **Upload note** |
| `results/` | what the app produced in the last automatic run (see below) | |

## Try one by hand

1. Start the app: `python scripts/run_ai_at_70.py`, then open http://localhost:5070.
2. **Start a visit**, then choose the visit's `checkin.json`.
3. **Upload audio** (`conversation.m4a`) and wait for the transcript, or **Skip**.
4. **Upload note** (`note.txt`), type "Dr. Lee" and "555-0100", then **Write the summary**.
5. **Select all**, then **Approve summary**. Try the **Printout / Email / Phone call** tabs and the language buttons.

## Run them all automatically

```bash
python scripts/run_ai_at_70.py               # in another terminal
python scripts/test_sample_visits.py         # all five (about 5 minutes)
python scripts/test_sample_visits.py 2_wei_chen_mandarin --audio   # one visit; --audio re-voices its conversation
```

The script drives the real page in Chrome, approves the summary in the patient's language and again in English, and writes to each `results/` folder:

| File | What it is |
|---|---|
| `printout_<lang>.pdf` | the large-print patient copy, as printed from the page |
| `email_patient_<lang>.txt`, `email_family_<lang>.txt` | the emails, with the address the consent allows (or "not sent") |
| `phone_patient_<lang>.txt`, `phone_family_<lang>.txt` | the phone scripts |
| `phone_call_<lang>.m4a` | the phone call in the neural voice for the language |
| `review_<lang>.png` | the review screen after approval |
| `transcript.txt` | what the app transcribed from `conversation.m4a` |
| `report.json` | checks, inputs that disagree, translation flags, page errors |

[RESULTS.md](RESULTS.md) sums up the last run. These results come from the offline methods (no API keys). Offline Mandarin and Arabic translations get many flags, and offline speaker separation can mix up who is talking. Both are flagged for the clinician, and both are better with Claude or ElevenLabs keys (see the main [README](../../../README.md)).
