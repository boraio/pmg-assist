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


def row_text(row):
    """A table row as one line, cells joined with " | "."""
    return " | ".join(row)


def table_chunks(rows, limit=MAX_CHARS):
    """A table's rows packed into chunks, split only between rows (ADR 0004).

    Every chunk after the first starts with the table's first row, labelled as
    the first row (never as column names), when that line is at most HEAD_MAX
    chars. A row longer than limit is split at cell boundaries into chunks of
    its own.
    """
    if not rows:
        return []
    texts = [row_text(r) for r in rows]
    head = f"{FIRST_ROW} {texts[0]}"
    repeat = len(head) <= HEAD_MAX
    out, cur = [], []
    for i, (row, text) in enumerate(zip(rows, texts)):
        if len(text) > limit:
            if cur:
                out.append("\n".join(cur))
                cur = []
            out.extend(pack([p for cell in row for p in split_long(cell, limit)], limit, " | "))
            continue
        if cur and len("\n".join(cur)) + 1 + len(text) <= limit:
            cur.append(text)
            continue
        if cur:
            out.append("\n".join(cur))
        cur = [head, text] if i > 0 and repeat and len(head) + 1 + len(text) <= limit else [text]
    if cur:
        out.append("\n".join(cur))
    return out


def main(argv=None):
    raise SystemExit("gold build is not written yet")


if __name__ == "__main__":
    sys.exit(main())
