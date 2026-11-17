"""Retrieval evaluation for committee-question (ADR 0004, decisions 3 and 5).

Builds the search index over gold chunks, runs every question in
docs/eval/committee-question.yaml, ranks records by their best chunk, and
reports Recall@5 and MRR.
"""

import sys

TOP_K = 5  # Recall@5
CUTOFF = 20  # MRR counts a first expected record only within the top 20


def main(argv=None):
    raise SystemExit("the evaluation harness is not written yet")


if __name__ == "__main__":
    sys.exit(main())
