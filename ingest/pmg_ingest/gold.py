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


def paragraph_chunks(texts, limit=MAX_CHARS):
    """Consecutive paragraphs packed into chunks, one per line; a paragraph is cut only if over limit."""
    return pack([p for t in texts for p in split_long(t, limit)], limit, "\n")


def blocks_chunks(blocks, limit=MAX_CHARS):
    """Silver blocks as chunk texts, in order: runs of paragraphs packed, each table on its own."""
    out, run = [], []
    for b in blocks:
        if b["type"] == "table":
            out.extend(paragraph_chunks(run, limit))
            run = []
            out.extend(table_chunks(b["rows"], limit))
        else:
            run.append(b["text"])
    out.extend(paragraph_chunks(run, limit))
    return out


def context_line(rec):
    """Searched before each chunk's text (ADR 0004, decision 2); never shown as a quote."""
    return f"{rec.get('code') or ''}, {rec.get('date') or ''}. Question to: {rec.get('question_to_name') or ''}."


def chunks_for(rec, limit=MAX_CHARS):
    """All chunks of one silver record, in order: the question, then the reply if it is in the body."""
    parts = [("question", t) for t in blocks_chunks(rec.get("question") or [], limit)]
    if rec.get("reply_kind") == "in_body":
        parts += [("reply", t) for t in blocks_chunks(rec.get("reply") or [], limit)]
    ctx = context_line(rec)
    return [{"chunk_id": f"{rec['record_id']}#{i}", "record_id": rec["record_id"], "kind": kind,
             "position": i, "text": text, "searched": f"{ctx}\n{text}", "index_version": VERSION}
            for i, (kind, text) in enumerate(parts)]


def build(silver_root, out_root, ctype=silver.CTYPE, limit=MAX_CHARS):
    """Write chunks.jsonl and _marker.json for this index version; return the marker.

    Reads silver's records.jsonl for silver.VERSION. The output depends only on
    that file, so a rerun gives the same chunks.
    """
    src = Path(silver_root) / ctype / f"version={silver.VERSION}"
    silver_rows = json.loads((src / "_marker.json").read_text())["rows"]
    out = Path(out_root) / ctype / f"index={VERSION}"
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "chunks.jsonl.tmp"
    records = chunks = over = 0
    kinds = {}
    with (src / "records.jsonl").open(encoding="utf-8") as f, tmp.open("w", encoding="utf-8") as w:
        for line in f:
            rec = json.loads(line)
            records += 1
            for c in chunks_for(rec, limit):
                chunks += 1
                kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
                over += len(c["text"]) > limit
                w.write(json.dumps(c, ensure_ascii=False) + "\n")
    tmp.replace(out / "chunks.jsonl")
    marker = {"index_version": VERSION, "silver_version": silver.VERSION, "ctype": ctype, "max_chars": limit,
              "records": records, "silver_rows": silver_rows, "chunks": chunks,
              "kinds": dict(sorted(kinds.items())), "over_limit": over}
    bronze.write_atomic(out / "_marker.json", json.dumps(marker, indent=2).encode())
    return marker


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build gold chunks for committee-question from silver (ADR 0004).")
    ap.add_argument("--silver-root", default="data/silver", type=Path)
    ap.add_argument("--out", default="data/gold", type=Path)
    args = ap.parse_args(argv)
    m = build(args.silver_root, args.out)
    print(f"gold {VERSION}: {m['records']} records (silver has {m['silver_rows']}), "
          f"{m['chunks']} chunks {m['kinds']}, over the limit: {m['over_limit']}")
    return 0 if m["records"] == m["silver_rows"] else 1


if __name__ == "__main__":
    sys.exit(main())
