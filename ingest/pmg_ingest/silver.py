"""Silver for committee-question (ADR 0003).

Turns the newest complete bronze 0.2 fetch of each year into one JSON line per
record: typed fields, the question and reply as ordered blocks (paragraphs, and
tables kept as rows), and reply_kind.
"""

import re

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
