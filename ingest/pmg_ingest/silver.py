"""Silver for committee-question (ADR 0003).

Turns the newest complete bronze 0.2 fetch of each year into one JSON line per
record: typed fields, the question and reply as ordered blocks (paragraphs, and
tables kept as rows), and reply_kind.
"""

import re

from lxml import etree
from lxml import html as lhtml

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
