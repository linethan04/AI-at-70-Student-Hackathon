# tools/

These are the building blocks behind the app. [`scripts/run_ai_at_70.py`](../scripts/run_ai_at_70.py) joins them into one page. Each tool can also run on its own from the command line.

| Tool | Job in the pipeline | Read more |
|---|---|---|
| [`questionnaire/`](questionnaire/) | **Input 1:** the patient's check-in, in 5 languages; exports JSON | [README](questionnaire/README.md) |
| [`transcription/`](transcription/) | **Input 3:** records the visit and writes it out, tells speakers apart, and checks medical terms | [README](transcription/README.md) |
| [`plain_language/`](plain_language/) | **Input 2 → summary:** turns the clinician's note into a checked, plain-language summary at a 5th-grade level, then builds the printout, email and phone script | [README](plain_language/README.md) |
| [`translation/`](translation/) | **Outputs in other languages:** Spanish, Mandarin, Portuguese, Arabic, with a back-translation check on every line | [README](translation/README.md) |
| [`voice/`](voice/) | **Phone call:** natural neural voices in each language | [README](voice/README.md) |

```
questionnaire ──┐
typed note ─────┼─> plain_language ──> clinician approves ──> printout / email / phone call
transcription ──┘                                              (translation, voice)
```

Each tool keeps its downloaded models in its own git-ignored folder. Build them with [`scripts/setup/`](../scripts/setup/).
