"""Gold for committee-question (ADR 0004): chunks from silver.

Reads silver's records.jsonl and writes one JSON line per chunk: the record it
belongs to, its kind and position, the exact text it holds, and the text that
is searched (a context line plus the chunk text).
"""

import re
import sys

VERSION = "0.1"  # the index version, <v> in data/gold/committee-question/index=<v>
MAX_CHARS = 1500  # ADR 0004, decision 1
HEAD_MAX = 500  # a table's first row is repeated in later chunks only if this short
FIRST_ROW = "First row of the table:"


def main(argv=None):
    raise SystemExit("gold build is not written yet")


if __name__ == "__main__":
    sys.exit(main())
