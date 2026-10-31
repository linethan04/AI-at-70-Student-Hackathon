# tools/plain_language/

This tool turns the clinician's typed note into a **checked, plain-language visit summary**. It then builds the three outputs from that summary.

The rules it follows are in [CLAUDE.md](../../CLAUDE.md):

- **Readable:** about a 5th-grade reading level.
- **Spoken, not clinical:** written the way you'd say it out loud, not doctor talk.
- **Medicines:** a plain category first, then the exact name. For example, **Blood pressure medicine** (Amlodipine), with "Take 1 pill (5 mg) each day."
- **Nothing invented:** every medicine and number traces back to the note.

## The summary

| File | What it does |
|---|---|
| [`visit_summary.py`](visit_summary.py) | **The summary.** Three parts: "Your visit", "Your medicines" and "What to do next". It rewrites the note up to 6 times until the reading check passes, and always keeps the best try. It also checks that it sounds like everyday talk, that every medicine is listed, that every number is kept or reported to the clinician, and that no jargon is left. `--claude` has Claude write it under the same checks. |
| [`reader.py`](reader.py) | **The reading check.** A model of a reader at a given grade: which words they know (from Living Word Vocabulary and word-prevalence research data). `DOCTOR_TALK` lists clinical phrasing a patient wouldn't say ("worsening", "shortness of breath", "referral"). |
| [`convert_note.py`](convert_note.py) | **Word level.** Expands abbreviations, swaps jargon for words from standard sources, and turns whole clinical phrases into everyday ones ("worsening breathlessness" → "your breathing has gotten worse"). It flags anything without a standard source. |
| [`drug_info.py`](drug_info.py) | What each medicine is for, from MedlinePlus drug information (via RxNav + MedlinePlus Connect). Cached in `data/drug_info.json`. |
| [`make_printout.py`](make_printout.py) | Shared page building for the printable summary (templates, highlighting, readability details). |
| [`deliver.py`](deliver.py) | **The three outputs** from the approved summary: the printout page, an email (to the patient or a consenting family member), and a phone script written to be heard ("5 milligrams", "9 1 1", the key points repeated). It also translates them through [`../translation/`](../translation/). |
| [`data/`](data/) | the dictionaries ([README](data/README.md)) |
| [`templates/`](templates/) | HTML for the summary page ([README](templates/README.md)) |

## Run on its own

```bash
python tools/plain_language/visit_summary.py note.txt --name "Maria Rodriguez"   # -> output/note.summary.html
python tools/plain_language/visit_summary.py note.txt --grade 6 --claude          # Claude writes it (ANTHROPIC_API_KEY)
python tools/plain_language/convert_note.py note.txt                              # word-level review copy -> output/note.plain.md
python tools/plain_language/reader.py "Your blood pressure is not yet at your goal."
python tools/plain_language/drug_info.py metformin amlodipine
python tools/plain_language/drug_info.py --note note.txt                          # every medicine in a note
```

Try it with [`scripts/video/maria_note.txt`](../../scripts/video/maria_note.txt). Output goes to `output/`, which is git-ignored.

**Needs** `data/medical_vocab.txt` and `data/raw/rxnorm_display_names.json`. Create them once with `python scripts/setup/build_dictionaries.py`.
