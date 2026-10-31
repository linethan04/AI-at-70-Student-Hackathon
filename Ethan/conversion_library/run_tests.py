"""Run the converter over every downloaded test note and report how it did.

    python Ethan/conversion_library/run_tests.py            # word-swap layer only
    python Ethan/conversion_library/run_tests.py --claude   # + Claude rewrite (needs ANTHROPIC_API_KEY)

Per note it records what was found (abbreviations, terms, medications, other jargon), how much
came from a standard plain-language source, what was flagged, and SMOG before/after.
Writes output/test_report.md plus a review copy per note in output/.
"""

import argparse
from collections import Counter
from pathlib import Path
from statistics import mean

from convert_note import OUTPUT, convert_file, summarize

HERE = Path(__file__).resolve().parent
TEST_NOTES = HERE / "test_notes"


def main() -> None:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())
    parser = argparse.ArgumentParser(description="Run the converter on all test notes.")
    parser.add_argument("--claude", action="store_true")
    parser.add_argument("--limit", type=int, help="only the first N notes per collection")
    args = parser.parse_args()

    rows, flags, unsourced = [], Counter(), Counter()
    for collection in sorted(p for p in TEST_NOTES.iterdir() if p.is_dir()):
        notes = sorted(collection.glob("*.txt"))[: args.limit]
        for path in notes:
            c, _ = convert_file(path, args.claude, 6)
            s = summarize(c)
            rows.append({"collection": collection.name, "note": path.stem, **s})
            for f in c.findings:
                if f.flag:
                    flags[f.flag.split(":")[0]] += 1
                if f.flag == "no standard source":
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
                  f"- SMOG grade: {mean(r['smog_before'] for r in rs):.1f} before -> {mean(r['smog_after'] for r in rs):.1f} after word swaps",
                  ""]
    lines += ["## Flags by reason", ""] + [f"- {k}: {v}" for k, v in flags.most_common()] + [""]
    lines += ["## Most common terms with no standard source", "",
              "Candidates to add from the Consumer Health Vocabulary or a clinician-approved list:", ""]
    lines += [f"- {t} ({n})" for t, n in unsourced.most_common(30)] + [""]
    lines += ["## Per note", "", "| collection | note | found | replaced | explained | flagged | SMOG before | after |",
              "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r['collection']} | {r['note']} | {r['found']} | {r['replaced']} | {r['explained']} | {r['flagged']} "
              f"| {r['smog_before']} | {r['smog_after']} |" for r in rows]
    report = OUTPUT / "test_report.md"
    report.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[: lines.index("## Per note")]))
    print(f"Full report: {report}")


if __name__ == "__main__":
    main()
