"""Pydantic models for docs/api.openapi.yaml.

The YAML is the contract; these models implement it. Where the two disagree,
the YAML wins and these are the bug. api/tests/test_contract.py validates
real responses against the YAML's schemas, so drift fails a test rather than
shipping.

Nullable-but-required fields (`quote.speaker`) are typed `X | None` with no
default, so they are always emitted, as null when absent.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- request


class Turn(BaseModel):
    question: str = Field(max_length=1000)
    answer_text: str | None = Field(default=None, max_length=4000)
    cited_record_ids: list[str] = Field(default_factory=list, max_length=20)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[Turn] = Field(default_factory=list, max_length=10)


# --------------------------------------------------------------- response


class Person(BaseModel):
    name: str
    role_as_recorded: str | None = None


class Publisher(BaseModel):
    name: str
    url: str


class Committee(BaseModel):
    name: str


class MinistryAtDate(BaseModel):
    name: str
    as_of: dt.date


class Record(BaseModel):
    record_id: str
    record_type: str  # open set; see the spec
    title: str
    record_date: dt.date
    url: str
    publisher: Publisher
    committee: Committee | None = None
    ministry: MinistryAtDate | None = None
    participants: list[Person]


class Quote(BaseModel):
    text: str = Field(min_length=1)
    speaker: Person | None  # required, nullable: set only if the record names the speaker


class Citation(BaseModel):
    id: str
    record: Record
    quote: Quote


class Statement(BaseModel):
    text: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)


class Answer(BaseModel):
    statements: list[Statement] = Field(min_length=1)


class Corpus(BaseModel):
    latest_record_date: dt.date
    index_published_at: dt.datetime


class Refusal(BaseModel):
    reason: str  # open set; see the spec
    message: str


class AnsweredResponse(BaseModel):
    outcome: Literal["answered"] = "answered"
    response_id: UUID
    answer: Answer
    citations: list[Citation] = Field(min_length=1)
    corpus: Corpus


class RefusedResponse(BaseModel):
    outcome: Literal["refused"] = "refused"
    response_id: UUID
    refusal: Refusal
    corpus: Corpus


QueryResponse = Annotated[AnsweredResponse | RefusedResponse, Field(discriminator="outcome")]


class Health(BaseModel):
    status: Literal["ok"] = "ok"
