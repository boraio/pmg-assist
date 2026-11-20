"""Embeddings for gold chunks (ADR 0004, decision 4; embedding spike 2026-11-20).

Reads <index-dir>/chunks.jsonl and writes <index-dir>/emb=<model>.jsonl, one
line per chunk with its embedding. A run that stops part-way resumes where it
left off. PyTorch and sentence-transformers are imported only when a model is
loaded, so the offline checks run without them.
"""

import json
import sys

MODEL = "BAAI/bge-small-en-v1.5"
# The maintainers' retrieval prefix for bge-small: questions get it, chunks do not.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
THREADS = 8  # fastest on nia in the 2026-11-20 benchmark
BATCH = 8


def main(argv=None):
    raise SystemExit("the embedding step is not written yet")


if __name__ == "__main__":
    sys.exit(main())
