"""Offline checks for pmg_ingest.gold. No network.

Run: python ingest/tests/test_gold.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pmg_ingest import gold as g

RESULTS = {"PASS": 0, "FAIL": 0}


def check(label, got, want):
    ok = got == want
    RESULTS["PASS" if ok else "FAIL"] += 1
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


def main():
    check("index version", g.VERSION, "0.1")

    # pack: in order, never over the limit unless a single unit is
    check("pack joins while it fits", g.pack(["aa", "bb", "cc"], 5), ["aa bb", "cc"])
    check("pack of nothing is nothing", g.pack([], 5), [])
    check("pack leaves an over-long unit whole", g.pack(["toolongunit", "a"], 5), ["toolongunit", "a"])
    check("pack uses the separator given", g.pack(["r1", "r2"], 10, "\n"), ["r1\nr2"])

    # split_long: sentence ends first, then spaces; always rejoins to the original
    short = "One sentence."
    check("short text is one piece", g.split_long(short, 100), [short])
    text = " ".join(["The department spent R5 million in 2024."] * 10)
    pieces = g.split_long(text, 100)
    check("long text is cut at sentence ends", pieces[0], "The department spent R5 million in 2024. "
          "The department spent R5 million in 2024.")
    check("no piece over the limit", max(len(p) for p in pieces) <= 100, True)
    check("pieces rejoin to the original", " ".join(pieces), text)
    words = " ".join(["word"] * 100)
    check("a sentence longer than the limit is cut at spaces",
          (max(len(p) for p in g.split_long(words, 30)) <= 30, " ".join(g.split_long(words, 30)) == words),
          (True, True))
    check("a run with no space stays whole", g.split_long("a" * 50 + " b", 20), ["a" * 50, "b"])
    check("a full stop before lower case is not a sentence end",
          g.SENTENCE_END.split("See p. ten. Then (2) more."), ["See p. ten.", "Then (2) more."])

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
