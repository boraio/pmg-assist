"""Offline checks for pmg_eval.retrieval. No network: no index is built here.

Run: python eval/tests/test_retrieval.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import sys
import tempfile
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

    # scoring (ADR 0004, decision 5)
    check("first rank is 1-based", r.first_rank(["a", "b", "c"], ["b"]), 2)
    check("first rank takes the earliest of several answers", r.first_rank(["a", "b", "c"], ["c", "a"]), 1)
    check("no expected record, no rank", r.first_rank(["a", "b"], ["z"]), None)
    ranks = [1, 3, 6, None]
    check("Recall@5 counts ranks 1 to 5 only", r.recall_at(ranks), 0.5)
    check("MRR averages 1/rank, absent counts 0", r.mrr(ranks), (1 + 1 / 3 + 1 / 6) / 4)
    check("MRR ignores ranks below the cutoff", r.mrr([21, 1]), 0.5)
    check("no questions, no score", (r.recall_at([]), r.mrr([])), (0.0, 0.0))

    # fusion (ADR 0004, decision 3)
    check("a record high in both lists comes first", r.rrf(["a", "b", "c"], ["b", "a", "d"])[:2], ["a", "b"])
    check("a record in only one list still appears", set(r.rrf(["a"], ["b"])), {"a", "b"})
    check("ties are broken by record id", r.rrf(["b"], ["a"]), ["a", "b"])
    check("one list fused alone keeps its order", r.rrf(["c", "a", "b"]), ["c", "a", "b"])

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
