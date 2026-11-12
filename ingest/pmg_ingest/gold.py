"""Gold for committee-question (ADR 0004): chunks from silver.

Reads silver's records.jsonl and writes one JSON line per chunk: the record it
belongs to, its kind and position, the exact text it holds, and the text that
is searched (a context line plus the chunk text).
"""

import re
import sys

# A sentence ends at ".", "!" or "?" followed by one space and an upper-case
# letter, digit, bracket or quote. Silver text has single spaces only, so the
# pieces below join back with one space into exactly the original text.
SENTENCE_END = re.compile(r"(?<=[.!?]) (?=[A-Z0-9(\"'])")


def pack(units, limit=MAX_CHARS, sep=" "):
    """Join units in order into strings of at most limit chars.

    A unit longer than limit is never cut here; it stands alone.
    """
    out, cur = [], None
    for u in units:
        if cur is None:
            cur = u
        elif len(cur) + len(sep) + len(u) <= limit:
            cur += sep + u
        else:
            out.append(cur)
            cur = u
    if cur is not None:
        out.append(cur)
    return out


def split_long(text, limit=MAX_CHARS):
    """Text as pieces of at most limit chars, cut at sentence ends, else at spaces.

    " ".join(pieces) == text always. A run with no space that is longer than
    limit stays whole, so a piece can exceed limit only in that case.
    """
    if len(text) <= limit:
        return [text]
    units = []
    for sent in SENTENCE_END.split(text):
        units.extend([sent] if len(sent) <= limit else sent.split(" "))
    return pack(units, limit, " ")

VERSION = "0.1"  # the index version, <v> in data/gold/committee-question/index=<v>
MAX_CHARS = 1500  # ADR 0004, decision 1
HEAD_MAX = 500  # a table's first row is repeated in later chunks only if this short
FIRST_ROW = "First row of the table:"


def main(argv=None):
    raise SystemExit("gold build is not written yet")


if __name__ == "__main__":
    sys.exit(main())
