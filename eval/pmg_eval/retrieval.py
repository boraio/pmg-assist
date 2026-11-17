"""Retrieval evaluation for committee-question (ADR 0004, decisions 3 and 5).

Builds the search index over gold chunks, runs every question in
docs/eval/committee-question.yaml, ranks records by their best chunk, and
reports Recall@5 and MRR.
"""

import sys

TOP_K = 5  # Recall@5
CUTOFF = 20  # MRR counts a first expected record only within the top 20


def first_rank(ranked, answers):
    """1-based rank of the first expected record in ranked, or None if absent."""
    return next((i for i, rid in enumerate(ranked, 1) if rid in answers), None)


def recall_at(ranks, k=TOP_K):
    """Share of questions whose first expected record is within the top k."""
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def mrr(ranks, cutoff=CUTOFF):
    """Mean reciprocal rank; a question scores 0 if its record is absent or below cutoff."""
    return sum(1 / r for r in ranks if r is not None and r <= cutoff) / len(ranks) if ranks else 0.0


def rrf(*rankings, k=60):
    """Reciprocal Rank Fusion (ADR 0004, decision 3): records by summed 1 / (k + rank).

    Ties are broken by record id so the order never depends on input order.
    """
    scores = {}
    for ranking in rankings:
        for i, rid in enumerate(ranking, 1):
            scores[rid] = scores.get(rid, 0.0) + 1 / (k + i)
    return sorted(scores, key=lambda rid: (-scores[rid], rid))


def main(argv=None):
    raise SystemExit("the evaluation harness is not written yet")


if __name__ == "__main__":
    sys.exit(main())
