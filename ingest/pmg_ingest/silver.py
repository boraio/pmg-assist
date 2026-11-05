"""Silver for committee-question (ADR 0003).

Turns the newest complete bronze 0.2 fetch of each year into one JSON line per
record: typed fields, the question and reply as ordered blocks (paragraphs, and
tables kept as rows), and reply_kind.
"""

VERSION = "0.1"
