# tools/plain_language/templates/

These are the Jinja2 templates for the summary pages that the command-line tools write to `output/`.

| Template | Used for |
|---|---|
| `summary_page.html` | the full page from `visit_summary.py`: the summary plus the clinician checklist |
| `_result.html`, `_summary.html`, `_checklist.html` | its parts: the patient's summary, and the checklist with Select all |
| `standalone.html`, `_printout.html`, `_review.html` | the printout page from `make_printout.py`, with its review panel |
| `_style.css` | shared styles: large print and high contrast for printing |

The AI at 70 app draws its own page ([`outputs/interface/index.html`](../../../outputs/interface/index.html)) and does not use these templates.
