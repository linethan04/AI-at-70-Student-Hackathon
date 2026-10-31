# tools/translation/

[`translate.py`](translate.py) translates the **checked plain-language English summary**, never the clinician's note, into **Spanish, Mandarin, Portuguese or Arabic**. The same language is used for all three outputs. Changing the language removes the clinician's approval.

How it keeps the meaning:

- **Names and numbers can't change.** Medicine names, test names, doses, doctor names and phone numbers are swapped for placeholders before translating, then put back exactly as written.
- **Fixed everyday wording** (`GLOSSARY`, `WHOLE_LINES`) covers words the summary repeats, so a page says them the same way every time. In Spanish, for example, medicine labels are always "Medicina para la presión arterial" and every pill is "Tome 1 pastilla".
- **Every line is back-translated** to English. Lines whose meaning may have drifted, or that lost a number, are flagged for the clinician with the English, the translation and the back-translation.
- **Page headings and tags** ("Your medicines", "Higher dose") are fixed hand-written labels for each language (`LABELS`).
- **Every translation is marked** "translation not verified by a speaker of this language" until a qualified reviewer checks it.

**Engines:**

- **Offline (default):** Argos Translate's OPUS-MT models, run with CTranslate2. Spanish and Portuguese are usually close. Mandarin and Arabic get more flags.
- **Claude:** used when `ANTHROPIC_API_KEY` is set. The offline model still does the back-translation check.

## Run

```bash
python scripts/setup/build_translation_models.py                 # once: ~900 MB into models/ (git-ignored)
python tools/translation/translate.py es "Take 1 pill (5 mg) each day."   # one line, with its back-translation
```

In the app, use the language buttons above the patient's page.
