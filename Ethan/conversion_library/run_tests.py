"""Run the converter over every downloaded test note and report how it did.

    python Ethan/conversion_library/run_tests.py            # word-swap layer only
    python Ethan/conversion_library/run_tests.py --claude   # + Claude rewrite (needs ANTHROPIC_API_KEY)

Per note it records what was found (abbreviations, terms, medications, other jargon), how much
came from a standard plain-language source, what was flagged, and SMOG before/after; then builds
the offline printout (make_printout.py) and checks its reading level, length and that no number or
medicine name went missing. Writes output/test_report.md plus a review copy and printout per note.
"""

import argparse
from collections import Counter
from pathlib import Path
from statistics import mean

from convert_note import MAX_GRADE, OUTPUT, TARGET_GRADE, convert_file, summarize
from make_printout import ONE_PAGE_WORDS, make_printout, render_page

HERE = Path(__file__).resolve().parent
TEST_NOTES = HERE / "test_notes"


def scored(rows: list[dict], key: str) -> list[float]:
    return [r[key] for r in rows if r[key] is not None]  # SMOG needs 3+ sentences


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
    report = OUTPUT / "test_report.md"
    report.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[: lines.index("## Per note")]))
    print(f"Full report: {report}")


if __name__ == "__main__":
    main()
