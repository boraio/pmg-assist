"""Count the owner's review marks into a generation results file (ADR 0006, decision 5).

The review sheet lives under the gitignored data/review, because it quotes records. Only counts and statement
ids reach the results file: never the statement text, and never what an attribution note says.
"""

import argparse
import re
import sys
from pathlib import Path

MARKS = ("supported", "partly", "not")
PENDING = "- Groundedness and attribution errors: from the owner's review sheet, not yet counted"
BLOCK = re.compile(r"### (q\d+ s\d+)\s*$")
GROUP = re.compile(r"## (q\d+) \((\w+)\)")
KEPT = re.compile(r"^- Statements kept: (\d+);", re.MULTILINE)


def parse_sheet(text):
    """Each statement block as a dict: id ('q001 s1'), group, mark and attribution; None where still '?'."""
    rows, groups, cur = [], {}, None
    for line in text.splitlines():
        g = GROUP.match(line)
        if g:
            groups[g.group(1)] = g.group(2)
        m = BLOCK.match(line)
        if m:
            cur = {"id": m.group(1), "group": groups.get(m.group(1).split()[0]), "mark": None, "attribution": None}
            rows.append(cur)
        elif cur and line.startswith("mark:"):
            value = line[len("mark:"):].strip().lower()
            cur["mark"] = None if value in ("", "?") else value.split()[0]
        elif cur and line.startswith("attribution:"):
            value = line[len("attribution:"):].strip()
            cur["attribution"] = None if value in ("", "?") else value
    return rows


def problems(rows):
    """What stops the count: a mark that is unfilled or not one of MARKS, or an unfilled attribution."""
    bad = []
    for r in rows:
        if r["mark"] not in MARKS:
            bad.append(f"{r['id']} mark {r['mark'] or '?'}")
        if r["attribution"] is None:
            bad.append(f"{r['id']} attribution ?")
    return bad


def section(rows, sheet_name):
    """The lines that replace PENDING in the results file: counts and statement ids only."""
    n = len(rows)
    counts = {m: sum(r["mark"] == m for r in rows) for m in MARKS}
    errors = [r["id"] for r in rows if r["attribution"].lower() != "no"]
    misplaced = [r["id"] for r in rows if r["group"] != "answerable"]
    lines = [(f"- Groundedness (owner's review, {sheet_name}): {counts['supported']} of {n} kept statements "
              f"supported by their citations ({counts['supported'] / n:.0%}); partly {counts['partly']}; "
              f"not {counts['not']}"),
             f"- Attribution errors: {len(errors)}" + (f" ({', '.join(errors)})" if errors else "")]
    if misplaced:
        lines.append(f"- Of these, {len(misplaced)} statements answer questions that should have been refused "
                     f"({', '.join(misplaced)})")
    return "\n".join(lines)


def count(sheet_text, results_text, sheet_name):
    """The results text with PENDING replaced, or a string saying why it cannot be counted yet."""
    rows = parse_sheet(sheet_text)
    if not rows:
        return None, "no statements in the sheet"
    bad = problems(rows)
    if bad:
        return None, f"{len(bad)} marks to fill in or fix, first: " + "; ".join(bad[:5])
    kept = KEPT.search(results_text)
    if not kept or int(kept.group(1)) != len(rows):
        return None, (f"the sheet has {len(rows)} statements but the results file says "
                      f"{kept.group(1) if kept else 'nothing'}: not the same run?")
    if PENDING not in results_text:
        return None, "the results file has no pending groundedness line: already counted?"
    return results_text.replace(PENDING, section(rows, sheet_name)), None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Count review marks into a generation results file (ADR 0006).")
    ap.add_argument("--sheet", required=True, type=Path, help="the filled-in review sheet, under data/review")
    ap.add_argument("--results", required=True, type=Path, help="the run's results file, under docs/eval/results")
    args = ap.parse_args(argv)
    text, why = count(args.sheet.read_text(encoding="utf-8"), args.results.read_text(encoding="utf-8"),
                      args.sheet.name)
    if why:
        return why
    args.results.write_text(text, encoding="utf-8")
    print(section(parse_sheet(args.sheet.read_text(encoding="utf-8")), args.sheet.name))
    print(f"written to {args.results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
