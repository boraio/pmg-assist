"""Milestone 0 stub: fixed, fictional, correctly shaped responses.

No retrieval and no model. This exists so the two clients can be built and
rendered against the real wire format before retrieval exists. It is
replaced, not extended, in Milestone 2.

All data here is fictional and matches the examples in docs/api.openapi.yaml
(a test checks that). Do not swap it for statements by real people.

A question containing "[refuse]" returns the refusal, so client developers
can exercise both render paths against the deployed API.
"""

from __future__ import annotations

import uuid

REFUSE_TRIGGER = "[refuse]"

CORPUS = {
    "latest_record_date": "2026-10-02",
    "index_published_at": "2026-10-03T04:00:00+02:00",
}

ANSWERED = {
    "outcome": "answered",
    "answer": {
        "statements": [
            {
                "text": "The Portfolio Committee on Water and Sanitation received a briefing on "
                "water-use licence turnaround times on 10 September 2026.",
                "citation_ids": ["c1"],
            },
            {
                "text": "Example Person A told the committee that the department aimed to clear "
                "the licence backlog by March.",
                "citation_ids": ["c1"],
            },
        ]
    },
    "citations": [
        {
            "id": "c1",
            "record": {
                "record_id": "pmg-cm-00000",
                "record_type": "committee_meeting",
                "title": "Water-use licence turnaround times (example record)",
                "record_date": "2026-09-10",
                "url": "https://pmg.org.za/committee-meeting/00000/",
                "publisher": {"name": "Parliamentary Monitoring Group", "url": "https://pmg.org.za"},
                "committee": {"name": "Portfolio Committee on Water and Sanitation"},
                "ministry": {"name": "Ministry of Water and Sanitation", "as_of": "2026-09-10"},
                "participants": [
                    {"name": "Example Person A", "role_as_recorded": "Director-General"},
                    {"name": "Example Person B", "role_as_recorded": "Chairperson"},
                ],
            },
            "quote": {
                "text": "The department aims to clear the licence backlog by the end of March.",
                "speaker": {"name": "Example Person A", "role_as_recorded": "Director-General"},
            },
        }
    ],
    "corpus": CORPUS,
}

REFUSED = {
    "outcome": "refused",
    "refusal": {
        "reason": "insufficient_evidence",
        "message": "I couldn't find parliamentary records that answer this question. "
        "Records are available up to 2 October 2026.",
    },
    "corpus": CORPUS,
}


def respond(question: str) -> dict:
    body = REFUSED if REFUSE_TRIGGER in question else ANSWERED
    return {**body, "response_id": str(uuid.uuid4())}
