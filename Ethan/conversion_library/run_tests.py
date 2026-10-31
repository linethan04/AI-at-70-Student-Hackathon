"""Run the converter over every downloaded test note and report how it did.

    python Ethan/conversion_library/run_tests.py            # word-swap layer only
    python Ethan/conversion_library/run_tests.py --claude   # + Claude rewrite (needs ANTHROPIC_API_KEY)
    python Ethan/conversion_library/run_tests.py --summaries  # only the visit summaries (samples + primary care notes)

Per note it records what was found (abbreviations, terms, medications, other jargon), how much
came from a standard plain-language source, what was flagged, and SMOG before/after; then builds
the offline printout (make_printout.py) and checks its reading level, length and that no number or
medicine name went missing. Writes output/test_report.md plus a review copy and printout per note.
"""

import argparse
import html
import json
from collections import Counter
from pathlib import Path
from statistics import mean

from convert_note import MAX_GRADE, OUTPUT, TARGET_GRADE, convert_file, summarize
from make_printout import ONE_PAGE_WORDS, make_printout, render_page
from reader import READER_GRADE
from visit_summary import patient_text, render_page as render_summary, summarize_note

PRIMARY_CARE = ("primock57/", "mtsamples/general_medicine", "mtsamples/office", "mtsamples/soap")  # not hospital discharges

HERE = Path(__file__).resolve().parent
TEST_NOTES = HERE / "test_notes"
SAMPLES = HERE / "samples"


def summary_tests() -> list[str]:
    """The patient visit summary (visit_summary.py) on every primary care note."""
    results = []
    paths = sorted(SAMPLES.glob("*.txt")) + [p for p in sorted(TEST_NOTES.glob("*/*.txt"))
                                              if f"{p.parent.name}/{p.stem}".startswith(PRIMARY_CARE)]
    for path in paths:
        s = summarize_note(path.read_text())
        (OUTPUT / f"{path.stem}.summary.html").write_text(render_summary(s))
        r = s.readability
        results.append({"collection": path.parent.name, "note": path.stem, "known": r["reader"]["known_per_100"],
                        "doctor_talk": r.get("doctor_talk", []), "first_line": patient_text(s).split("\n")[0],
                        "max_sentence": r["reader"]["max_sentence"], "reader_ok": s.reading_ok, "ready": s.ready,
                        "unknown": r["reader"]["unknown"], "smog": r["smog"], "smog_note": r["smog_note"],
                        "tries": len(s.tries), "words": r["reader"]["words"], "medicines": len(s.medicines),
                        "no_instruction": sum(1 for m in s.medicines if not m.instruction),
                        "failed": [c["name"] for c in s.checks if not c["ok"]]})
    (OUTPUT / "summary_results.json").write_text(json.dumps(results, indent=1))
    write_index(results)
    lines = ["## Patient visit summary (primary care notes)", ""]
    for collection in sorted({r["collection"] for r in results}):
        rs = [r for r in results if r["collection"] == collection]
        ok = [r for r in rs if r["reader_ok"]]
        meds = sum(r["medicines"] for r in rs)
        lines += [f"### {collection} ({len(rs)} notes)", "",
                  f"- Reader check passed (grade {READER_GRADE}: knows 98+ of 100 words, short sentences): {len(ok)} of {len(rs)}",
                  f"- Every check passed (reader, medicines, numbers, no jargon): {sum(1 for r in rs if r['ready'])} of {len(rs)}",
                  f"- Sounds like everyday talk (no doctor wording left): {sum(1 for r in rs if not r['doctor_talk'])} of {len(rs)}",
                  "- Doctor wording most often left: " + (", ".join(f"{w} ({n})" for w, n in Counter(
                      w for r in rs for w in r["doctor_talk"]).most_common(10)) or "none"),
                  f"- Words the reader knows: {mean(r['known'] for r in rs):.1f} of 100 on average "
                  f"(lowest {min(r['known'] for r in rs)})",
                  "- Tries needed (notes that passed): " + ", ".join(
                      f"{n}: {sum(1 for r in ok if r['tries'] == n)}" for n in range(1, 7)),
                  f"- Summary length: {mean(r['words'] for r in rs):.0f} words on average",
                  f"- Medicines with a how-to-take instruction from the note: {meds - sum(r['no_instruction'] for r in rs)} of {meds}",
                  f"- For reference, SMOG: {mean(scored(rs, 'smog_note')):.1f} note -> {mean(scored(rs, 'smog')):.1f} summary",
                  "- Words the reader most often may not know: " + ", ".join(
                      f"{w} ({n})" for w, n in Counter(w for r in rs for w in r["unknown"]).most_common(12)),
                  f"- Failing other checks: " + (", ".join(f"{k} {v}" for k, v in Counter(
                      f for r in rs for f in r["failed"] if f != "Reading level").most_common()) or "none"), ""]
    return lines


def write_index(results: list[dict]) -> None:
    """output/summaries.html: every summary with its checks, to open and read one by one."""
    rows = []
    for r in results:
        status = "pass" if r["ready"] else "check"
        rows.append(f"<tr class='{status}'><td>{html.escape(r['collection'])}</td>"
                    f"<td><a href='{html.escape(r['note'])}.summary.html'>{html.escape(r['note'])}</a></td>"
                    f"<td>{'all checks pass' if r['ready'] else html.escape(', '.join(r['failed']))}</td>"
                    f"<td>{r['known']}</td><td>{html.escape(', '.join(r['doctor_talk'])) or '-'}</td>"
                    f"<td>{html.escape(r['first_line'])}</td></tr>")
    passed = sum(1 for r in results if r["ready"])
    (OUTPUT / "summaries.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Visit summaries</title><style>body{font:15px system-ui;margin:24px}"
        "table{border-collapse:collapse}td,th{border-bottom:1px solid #ddd;padding:6px 10px;text-align:left;vertical-align:top}"
        "tr.pass td:nth-child(3){color:#176b2c}tr.check td:nth-child(3){color:#a33}</style>"
        f"<h1>Visit summaries</h1><p>{passed} of {len(results)} pass every check. Click a note to open its summary "
        "and clinician checklist.</p><table><tr><th>collection</th><th>note</th><th>checks</th><th>words known /100</th>"
        "<th>doctor wording left</th><th>Your visit (first sentence)</th></tr>" + "".join(rows) + "</table>")


def scored(rows: list[dict], key: str) -> list[float]:
    return [r[key] for r in rows if r[key] is not None]  # SMOG needs 3+ sentences


def main() -> None:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())
    parser = argparse.ArgumentParser(description="Run the converter on all test notes.")
    parser.add_argument("--claude", action="store_true")
    parser.add_argument("--limit", type=int, help="only the first N notes per collection")
    parser.add_argument("--summaries", action="store_true", help="only the visit summaries (faster)")
    args = parser.parse_args()
    if args.summaries:
        lines = summary_tests()
        (OUTPUT / "summary_report.md").write_text("\n".join(lines) + "\n")
        print("\n".join(lines))
        print(f"Open: {OUTPUT / 'summaries.html'}")
        return

    rows, flags, unsourced = [], Counter(), Counter()
    for collection in sorted(p for p in TEST_NOTES.iterdir() if p.is_dir()):
        notes = sorted(collection.glob("*.txt"))[: args.limit]
        for path in notes:
            c, _ = convert_file(path, args.claude, TARGET_GRADE)
            s = summarize(c)
            p = make_printout(path.read_text())
            (OUTPUT / f"{path.stem}.printout.html").write_text(render_page(p))
            r = p.readability["printout"]
            rows.append({"collection": collection.name, "note": path.stem, **s,
                         "fk_before": c.readability["original"]["flesch_kincaid"],
                         "smog_printout": r["smog"], "fk_printout": r["flesch_kincaid"],
                         "printout_words": p.word_count, "missing": p.missing})
            for f in c.findings:
                if f.flag:
                    flags[f.flag.split(":")[0]] += 1
                if f.flag == "no standard source" and not f.replace_with and not f.explain:
                    unsourced[f.text.lower()] += 1

    lines = ["# Conversion test report", ""]
    for collection in sorted({r["collection"] for r in rows}):
        rs = [r for r in rows if r["collection"] == collection]
        found = sum(r["found"] for r in rs)
        lines += [f"## {collection} ({len(rs)} notes)", "",
                  f"- Jargon found: {found} ({mean(r['found'] for r in rs):.1f} per note)",
                  f"- Replaced with an everyday word: {sum(r['replaced'] for r in rs)}",
                  f"- Kept and explained: {sum(r['explained'] for r in rs)}",
                  f"- From a standard plain-language source (CDC / MedlinePlus): "
                  f"{sum(r['standard_source'] for r in rs)} ({sum(r['standard_source'] for r in rs) / max(1, found):.0%})",
                  f"- Flagged for the clinician: {sum(r['flagged'] for r in rs)}",
                  f"- SMOG grade: {mean(r['smog_before'] for r in rs):.1f} original -> {mean(r['smog_after'] for r in rs):.1f} "
                  f"after word swaps -> {mean(scored(rs, 'smog_printout')):.1f} printout (target {TARGET_GRADE}-{MAX_GRADE})",
                  f"- Flesch-Kincaid grade: {mean(r['fk_before'] for r in rs):.1f} original -> {mean(r['fk_printout'] for r in rs):.1f} printout",
                  f"- Printouts at grade {MAX_GRADE} or lower (SMOG): {sum(1 for v in scored(rs, 'smog_printout') if v <= MAX_GRADE)}"
                  f" of {len(scored(rs, 'smog_printout'))} scored",
                  f"- Printouts that fit one page (<= {ONE_PAGE_WORDS} words): {sum(1 for r in rs if r['printout_words'] <= ONE_PAGE_WORDS)} of {len(rs)}",
                  f"- Printouts missing a number or medicine name from the note: {sum(1 for r in rs if r['missing'])}",
                  ""]
    lines += ["## Flags by reason", ""] + [f"- {k}: {v}" for k, v in flags.most_common()] + [""]
    lines += ["## Most common terms with no standard source and no simple wording yet", "",
              "Candidates to add from the Consumer Health Vocabulary or to data/simple_words.json:", ""]
    lines += [f"- {t} ({n})" for t, n in unsourced.most_common(30)] + [""]
    lines += ["## Per note", "", "| collection | note | found | replaced | explained | flagged | SMOG before | swaps | printout | words | missing |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r['collection']} | {r['note']} | {r['found']} | {r['replaced']} | {r['explained']} | {r['flagged']} "
              f"| {r['smog_before']} | {r['smog_after']} | {r['smog_printout']} | {r['printout_words']} | {', '.join(r['missing'])} |"
              for r in rows]
    lines += summary_tests()
    report = OUTPUT / "test_report.md"
    report.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[: lines.index("## Per note")]))
    print(f"Full report: {report}")


if __name__ == "__main__":
    main()
