"""Simple web page to try the visit summary: paste or upload a clinician note, get a large-print printout.

    python Ethan/conversion_library/app.py        # http://localhost:5051

Writes the summary with Claude if ANTHROPIC_API_KEY is set and "Write with Claude" is ticked, otherwise
with the offline rewriter; both retry until the reading level is in range and show the best try.
Printing unlocks when the clinician has ticked every item. Notes are processed in memory and not saved.
"""

import argparse
import io
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from flask import Flask, render_template, request

from make_printout import TEMPLATES
from reader import READER_GRADE
from visit_summary import context, summarize_note

HERE = Path(__file__).resolve().parent
SAMPLE_DIRS = {"Synthetic samples": HERE / "samples",
               "PriMock57 (test)": HERE / "test_notes" / "primock57",
               "MTSamples (test)": HERE / "test_notes" / "mtsamples"}
MAX_NOTE_CHARS = 30_000

load_dotenv(find_dotenv())
app = Flask(__name__, template_folder=str(TEMPLATES))
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


def samples() -> dict[str, list[str]]:
    return {group: sorted(p.stem for p in folder.glob("*.txt"))
            for group, folder in SAMPLE_DIRS.items() if folder.is_dir() and any(folder.glob("*.txt"))}


def read_sample(value: str) -> str:
    group, _, name = value.partition("/")
    folder = SAMPLE_DIRS.get(group)
    path = folder / f"{name}.txt" if folder else None
    if not path or path.parent != folder or not path.is_file():  # only files listed in the dropdown
        return ""
    return path.read_text()


def read_upload(file) -> str:
    data = file.read()
    if file.filename.lower().endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    return data.decode("utf-8", errors="replace")


@app.route("/", methods=["GET", "POST"])
def index():
    form = request.form
    details = {k: form.get(k, "").strip() for k in ("name", "visit_date", "phone")}
    note, error, sample = form.get("note", ""), None, form.get("sample", "")
    upload = request.files.get("file")
    if upload and upload.filename:
        note = read_upload(upload)
    elif not note.strip() and sample:
        note = read_sample(sample)
    note = note.replace("\r\n", "\n")
    grade = int(form.get("grade") or READER_GRADE)
    claude_available = bool(os.environ.get("ANTHROPIC_API_KEY"))
    use_claude = claude_available and bool(form.get("claude"))
    page = {"note": note, "sample": sample, "samples": samples(), "s": None,
            "visit_date_input": details["visit_date"], "claude_available": claude_available,
            "use_claude": use_claude, "name": details["name"], "phone": details["phone"], "grade": grade}
    if request.method == "POST":
        if not note.strip():
            error = "Paste a note, upload a file, or pick a sample."
        elif len(note) > MAX_NOTE_CHARS:
            error = f"That note is very long ({len(note):,} characters). Try a single visit note."
        else:
            try:
                page.update(context(summarize_note(note, use_claude, grade), **details))
            except Exception as e:  # Claude errors, unreadable files
                error = f"Couldn't make a summary: {e.__class__.__name__}: {e}"
    page["error"] = error
    return render_template("index.html", **page)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visit summary web page.")
    parser.add_argument("--port", type=int, default=5051)
    args = parser.parse_args()
    app.run(host="127.0.0.1", port=args.port, debug=False)
