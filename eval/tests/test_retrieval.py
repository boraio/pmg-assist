"""Offline checks for pmg_eval.retrieval. No network: no index is built here.

Run: python eval/tests/test_retrieval.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pmg_eval import retrieval as r

RESULTS = {"PASS": 0, "FAIL": 0}


def check(label, got, want):
    ok = got == want
    RESULTS["PASS" if ok else "FAIL"] += 1
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


def main():
    check("Recall@5 and an MRR cutoff of 20", (r.TOP_K, r.CUTOFF), (5, 20))

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
