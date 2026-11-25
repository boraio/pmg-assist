"""Offline checks for pmg_eval.review, on a sheet and results file made by pmg_eval.generate itself.

Run: python eval/tests/test_review.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pmg_eval import generate as g
from pmg_eval import review as rv

RESULTS = {"PASS": 0, "FAIL": 0}


def check(label, got, want):
    ok = got == want
    RESULTS["PASS" if ok else "FAIL"] += 1
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


C1 = {"id": "c1", "chunk_id": "r1#0", "record_id": "r1", "header": "H", "text": "Ms Private Person repaired 42 boreholes."}
S1 = {"text": "It repaired 42 boreholes.", "citations": [{"chunk": "c1", "quote": "repaired 42 boreholes"}]}
S2 = {"text": "Work started in 2024.", "citations": [{"chunk": "c1", "quote": "repaired"}]}
BASE = {"drops": {}, "tokens": 5, "seconds": 1.0, "parse": "strict", "cites_expected": True, "context": {"c1": C1},
        "outcome": "answered", "layer": "answered", "reason": None}
RUN = [dict(BASE, id="q001", question="Boreholes?", group="answerable", statements=[S1, S2]),
       dict(BASE, id="q045", question="Football?", group="unanswerable", statements=[S1]),
       dict(BASE, id="q046", question="Vote?", group="refuse", outcome="refused", layer="floor",
            reason="insufficient_evidence", statements=[], context={}, tokens=None, seconds=None, parse=None)]
META = {"label": "fake", "date": "2026-11-25", "model": "m", "endpoint": "e", "schema": True, "index": "index=0.1",
        "embeddings": "x", "floor": 0.668, "questions": "q.yaml"}


def fill(sheet, marks):
    """Replace the sheet's '?' placeholders in order with (mark, attribution) pairs."""
    for mark, attribution in marks:
        sheet = sheet.replace("mark: ?", f"mark: {mark}", 1).replace("attribution: ?", f"attribution: {attribution}", 1)
    return sheet


def main():
    sheet = g.review_sheet(RUN, META)
    results = g.summary(RUN, META)
    rows = rv.parse_sheet(sheet)
    check("every kept statement is a block, with its group", [(r["id"], r["group"]) for r in rows],
          [("q001 s1", "answerable"), ("q001 s2", "answerable"), ("q045 s1", "unanswerable")])
    check("an unfilled sheet has every mark pending", rv.problems(rows)[:2], ["q001 s1 mark ?", "q001 s1 attribution ?"])
    text, why = rv.count(sheet, results, "sheet.md")
    check("an unfilled sheet is not counted", (text, why.startswith("6 marks to fill in")), (None, True))

    half = fill(sheet, [("supported", "no")])
    check("a half-filled sheet is not counted", rv.count(half, results, "s")[1].startswith("4 marks"), True)
    odd = fill(sheet, [("yes", "no"), ("not", "no"), ("partly", "no")])
    check("a mark outside supported, partly, not is refused", rv.count(odd, results, "s")[1],
          "1 marks to fill in or fix, first: q001 s1 mark yes")

    done = fill(sheet, [("Supported", "no"), ("not", "gives the repairs to Ms Private Person"), ("partly", "No")])
    text, why = rv.count(done, results, "sheet.md")
    check("a filled sheet is counted", why, None)
    check("groundedness is supported over kept",
          "- Groundedness (owner's review, sheet.md): 1 of 3 kept statements supported by their citations (33%); "
          "partly 1; not 1" in text, True)
    check("attribution errors are counted and listed by statement id", "- Attribution errors: 1 (q001 s2)" in text, True)
    check("statements on questions that should have been refused are called out",
          "- Of these, 1 statements answer questions that should have been refused (q045 s1)" in text, True)
    check("an attribution note's words never reach the results file", ("Private" in text, "repairs" in text),
          (False, False))
    check("the pending line is gone", rv.PENDING in text, False)
    check("a counted file is not counted twice", rv.count(done, text, "s")[1],
          "the results file has no pending groundedness line: already counted?")
    other = results.replace("- Statements kept: 3;", "- Statements kept: 4;")
    check("a sheet from another run is refused", rv.count(done, other, "s")[1],
          "the sheet has 3 statements but the results file says 4: not the same run?")
    check("an empty sheet is refused", rv.count("# Review\n", results, "s"), (None, "no statements in the sheet"))

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
