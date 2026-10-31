# scripts/setup/

These scripts download or build data the tools need. Run each one once. Large downloads are git-ignored.

| Script | Needed for | Size | Run |
|---|---|---|---|
| [`build_translation_models.py`](build_translation_models.py) | the language buttons: Spanish, Mandarin, Portuguese and Arabic, offline, both directions | ~900 MB → `tools/translation/models/` | `python scripts/setup/build_translation_models.py` |
| [`build_voices.py`](build_voices.py) | the phone-call voices (Kokoro, plus Piper for Arabic) | ~770 MB → `tools/voice/models/` | `python scripts/setup/build_voices.py` |
| [`build_dictionaries.py`](build_dictionaries.py) | refreshing the plain-wording dictionary (`lay_dictionary.json`, committed), and the medical word list `convert_note.py` uses (`medical_vocab.txt`, git-ignored) | ~35 MB of downloads → `tools/plain_language/data/` | `python scripts/setup/build_dictionaries.py` (`--refresh` to download again) |
| [`build_reader_baseline.py`](build_reader_baseline.py) | refreshing the reading-check data (`word_knowledge.json`, committed) | small | `python scripts/setup/build_reader_baseline.py` |

On a fresh copy, the first two are needed for the language buttons and voices. Run `build_dictionaries.py` once too, because the summary uses the medical word list it creates. The other data files are already committed.

Sources for every download are in [REFERENCES.md](../../REFERENCES.md).
