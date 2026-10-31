# Test results

Written by `python scripts/test_sample_visits.py` (offline summary and translation, no API keys). Each visit's files are in its `results/` folder.

| Visit | Language | Conversation | Checks | Inputs disagree | Translation flags | Errors |
|---|---|---|---|---|---|---|
| [Maria Rodriguez](1_maria_rodriguez_english/) | English | audio, transcribed | all pass | none | none (English) | none |
| [Wei Chen](2_wei_chen_mandarin/) | Mandarin | audio, transcribed | all pass | Mentioned in the conversation but not in the note: ibuprofen<br>On the patient's check-in medicine list but not in the note: ibuprofen | Mandarin: 20 | none |
| [João Silva](3_joao_silva_portuguese/) | Portuguese | audio, transcribed | all pass | none | Portuguese: 5 | none |
| [Fatima Haddad](4_fatima_haddad_arabic/) | Arabic | audio, transcribed | all pass | none | Arabic: 10 | none |
| [Rosa Gómez](5_rosa_gomez_spanish/) | Spanish | skipped | all pass | none | Spanish: 2 | none |
