"""Silver for committee-question (ADR 0003).

Turns the newest complete bronze 0.2 fetch of each year into one JSON line per
record: typed fields, the question and reply as ordered blocks (paragraphs, and
tables kept as rows), and reply_kind.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from lxml import etree
from lxml import html as lhtml

from . import bronze

VERSION = "0.1"

# ADR 0003, decision 4. Matched against the reply with everything but letters
# removed, so spacing, punctuation and case variants ("Find here: R eply",
# "Find here reply :") reduce to one string. Typos seen in the measurements:
# "fid", "fimd".
POINTER_RE = re.compile(
    r"^(annexure[a-z]?)*(attached)?(please)?fi[mn]?d(here)?(reply|response)(here)?(annexure[a-z]?)*$"
    r"|^theresponseisavailableseeattachment$"
)


def is_pointer(text):
    """True when a reply only points to an attached document (ADR 0003)."""
    return bool(POINTER_RE.match(re.sub(r"[^a-z]", "", text.lower())))


# ---- HTML to blocks (ADR 0003, decisions 2 and 3)

SKIP_TAGS = {"head", "script", "style", "img", "title"}
BREAK_TAGS = {"p", "div", "li", "ul", "ol", "br", "hr", "blockquote",
              "h1", "h2", "h3", "h4", "h5", "h6"}
MAX_SPAN = 1000


def ws(text):
    """Collapse runs of whitespace (including non-breaking spaces) to one space."""
    return " ".join(text.split())


def tag_of(el):
    """Lower-case tag name, or None for comments and processing instructions."""
    return el.tag.lower() if isinstance(el.tag, str) else None


def span(cell, name):
    """rowspan or colspan as an int from 1 to MAX_SPAN; anything unreadable is 1."""
    try:
        n = int(cell.get(name, "1"))
    except ValueError:
        return 1
    return min(max(n, 1), MAX_SPAN)


def own_rows(table):
    """The <tr> rows of this table, not of tables nested inside it."""
    for child in table:
        tag = tag_of(child)
        if tag == "tr":
            yield child
        elif tag in ("thead", "tbody", "tfoot"):
            for tr in child:
                if tag_of(tr) == "tr":
                    yield tr


def cell_text(cell):
    """A cell's text. A nested table becomes its rows joined with " / "."""
    parts = []

    def walk(el):
        if el.text:
            parts.append(el.text)
        for child in el:
            tag = tag_of(child)
            if tag == "table":
                parts.append(" / ".join(" ".join(c for c in row if c) for row in table_rows(child)))
            elif tag and tag not in SKIP_TAGS:
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(cell)
    return ws(" ".join(parts))


def table_rows(table):
    """Rows of cell texts, rowspan and colspan expanded into a full grid.

    A spanned value is repeated in every cell it covers, so each row stands on
    its own. Rows whose cells are all empty are dropped.
    """
    rows, carry = [], {}  # carry: column -> (text, rows still to fill)

    def take(col, row):
        text, left = carry[col]
        row.append(text)
        if left == 1:
            del carry[col]
        else:
            carry[col] = (text, left - 1)

    for tr in own_rows(table):
        row = []
        for cell in tr:
            if tag_of(cell) not in ("td", "th"):
                continue
            while len(row) in carry:
                take(len(row), row)
            text, rs = cell_text(cell), span(cell, "rowspan")
            for _ in range(span(cell, "colspan")):
                if rs > 1:
                    carry[len(row)] = (text, rs - 1)
                row.append(text)
        for col in sorted(c for c in carry if c >= len(row)):
            row.extend([""] * (col - len(row)))
            take(col, row)
        if any(row):
            rows.append(row)
    return rows


# An XML declaration with an encoding makes lxml refuse a str; it carries no text.
XML_DECL = re.compile(r"<\?xml[^>]*\?>", re.IGNORECASE)


def blocks(html_text):
    """Question or reply HTML as ordered blocks (ADR 0003, decision 3).

    A block is {"type": "paragraph", "text": ..., "rows": None} or
    {"type": "table", "text": None, "rows": [[cell, ...], ...]}. Both keys are
    always present so every record has the same shape. Images are dropped.
    """
    if not html_text or not html_text.strip():
        return []
    try:
        root = lhtml.document_fromstring(XML_DECL.sub("", html_text))
    except etree.ParserError:  # nothing but comments
        return []
    out, buf = [], []

    def flush():
        text = ws(" ".join(buf))
        buf.clear()
        if text:
            out.append({"type": "paragraph", "text": text, "rows": None})

    def walk(el):
        tag = tag_of(el)
        if tag == "table":
            flush()
            rows = table_rows(el)
            if rows:
                out.append({"type": "table", "text": None, "rows": rows})
            return
        if tag is None or tag in SKIP_TAGS:
            return
        if tag in BREAK_TAGS:
            flush()
        if el.text:
            buf.append(el.text)
        for child in el:
            walk(child)
            if child.tail:
                buf.append(child.tail)
        if tag in BREAK_TAGS:
            flush()

    walk(root)
    flush()
    return out


# ---- one record (ADR 0003, decisions 1 and 4)


def reply_kind(reply):
    """empty, attachment_pointer or in_body. A reply with a table is never a pointer."""
    if not reply:
        return "empty"
    if all(b["type"] == "paragraph" for b in reply) and is_pointer(" ".join(b["text"] for b in reply)):
        return "attachment_pointer"
    return "in_body"


def to_silver(rec, fetched):
    """One bronze committee-question record as one silver row.

    Every row has the same keys. Attachments stay as JSON text so their
    drifting shape never changes the Parquet schema.
    """
    reply = blocks(rec.get("answer"))
    source_file = rec.get("source_file")
    return {
        "record_id": f"pmg-committee-question-{rec['id']}",
        "pmg_id": rec["id"],
        "url": rec.get("url"),
        "date": rec.get("date"),
        "year": rec.get("year"),
        "code": rec.get("code"),
        "answer_type": rec.get("answer_type"),
        "house_id": rec.get("house_id"),
        "minister_id": rec.get("minister_id"),
        "question_to_name": rec.get("question_to_name"),
        "asked_by_name": rec.get("asked_by_name"),
        "asked_by_member_id": rec.get("asked_by_member_id"),
        "question": blocks(rec.get("question")),
        "reply": reply,
        "reply_kind": reply_kind(reply),
        "source_file": None if source_file is None else json.dumps(source_file),
        "files": json.dumps(rec.get("files") or []),
        "bronze_fetched": fetched,
        "silver_version": VERSION,
    }


# ---- the whole set (ADR 0003, decisions 1 and 6)

CTYPE = "committee-question"


def bronze_years(bronze_root, ctype=CTYPE):
    """Years that have a bronze partition directory, ascending."""
    base = Path(bronze_root) / ctype
    return sorted(int(p.name.split("=", 1)[1]) for p in base.glob("year=*") if p.is_dir())


def records_in(fdir):
    """Every record in one bronze fetch, from its part=*.json files."""
    for part in sorted(Path(fdir).glob("part=*.json")):
        yield from json.loads(part.read_text(encoding="utf-8"))["results"]


def build(bronze_root, out_root, ctype=CTYPE):
    """Write records.jsonl and _marker.json for this silver version; return the marker.

    Reads the newest complete fetch of each year, as bronze defines it. The
    output depends only on the bronze fetches used, so a rerun gives the same rows.
    """
    out = Path(out_root) / ctype / f"version={VERSION}"
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "records.jsonl.tmp"
    seen, kinds, used, missing = set(), {}, {}, []
    with tmp.open("w", encoding="utf-8") as f:
        for year in bronze_years(bronze_root, ctype):
            fdir = bronze.latest_complete_dir(bronze_root, ctype, year)
            if fdir is None:
                missing.append(year)
                continue
            fetched = fdir.name.split("=", 1)[1]
            used[str(year)] = fetched
            for rec in records_in(fdir):
                if rec["id"] in seen:
                    raise ValueError(f"record {rec['id']} appears twice (year {year})")
                seen.add(rec["id"])
                try:
                    row = to_silver(rec, fetched)
                except Exception as e:
                    raise RuntimeError(f"record {rec['id']} (year {year}) failed") from e
                kinds[row["reply_kind"]] = kinds.get(row["reply_kind"], 0) + 1
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(out / "records.jsonl")
    marker = {"silver_version": VERSION, "ctype": ctype, "rows": len(seen),
              "reply_kinds": dict(sorted(kinds.items())), "bronze_fetches": used,
              "years_without_complete_fetch": missing}
    bronze.write_atomic(out / "_marker.json", json.dumps(marker, indent=2).encode())
    return marker


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build silver committee-question from bronze (ADR 0003).")
    ap.add_argument("--bronze-root", default="data/bronze", type=Path)
    ap.add_argument("--out", default="data/silver", type=Path)
    args = ap.parse_args(argv)
    m = build(args.bronze_root, args.out)
    print(f"silver {VERSION}: {m['rows']} rows, {m['reply_kinds']}, "
          f"years without a complete fetch: {m['years_without_complete_fetch'] or 'none'}")
    return 1 if m["years_without_complete_fetch"] else 0


if __name__ == "__main__":
    sys.exit(main())
