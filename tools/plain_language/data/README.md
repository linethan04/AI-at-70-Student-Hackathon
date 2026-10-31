# tools/plain_language/data/

| File | What it is | Made by |
|---|---|---|
| `lay_dictionary.json` | Plain wording from standard sources, in priority order: CDC Everyday Words, MedlinePlus health topics and lab tests, Federal Plain Language Guidelines. Also abbreviation expansions from Wikipedia's list. | [`scripts/setup/build_dictionaries.py`](../../../scripts/setup/build_dictionaries.py) (committed) |
| `simple_words.json` | Hand-made everyday wording for words and phrases no standard source covers ("bilaterally" → "on both sides"). Its `phrases` table turns clinical phrases into spoken ones; keys starting with `~` are regular expressions. Every use is flagged "no standard source". | by hand; edit freely |
| `word_knowledge.json` | Which words a reader knows by school grade, and which words 99% of adults know (used by `reader.py`) | [`scripts/setup/build_reader_baseline.py`](../../../scripts/setup/build_reader_baseline.py) (committed) |
| `drug_info.json` | Cached MedlinePlus drug pages: what each medicine is for | `drug_info.py` (committed; new medicines are looked up once, online) |
| `medical_vocab.txt`, `raw/` | Medical word list and downloaded source files | `build_dictionaries.py` (git-ignored) |

Sources: [REFERENCES.md](../../../REFERENCES.md).
