"""Contract tests: the running API against docs/api.openapi.yaml.

Every response body is validated against the committed spec's own schemas
(JSON Schema 2020-12, which is what OpenAPI 3.1 schemas are). The Pydantic
models are not trusted to describe the contract; the YAML is.

Run: pytest api/tests -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from pmg_api import stub
from pmg_api.main import create_app

SPEC = yaml.safe_load((ROOT / "docs" / "api.openapi.yaml").read_text())
REGISTRY = Registry().with_resource("urn:spec", DRAFT202012.create_resource(SPEC))
HEADERS = {"PMG-Client-Version": "ios/1.0.0"}


def errors(schema_name: str, instance) -> list[str]:
    v = Draft202012Validator(
        {"$ref": f"urn:spec#/components/schemas/{schema_name}"},
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )
    return [f"{list(e.path)}: {e.message}" for e in v.iter_errors(instance)]


def client(**kw) -> TestClient:
    return TestClient(create_app(**kw), raise_server_exceptions=False)


# ------------------------------------------------------------ routes


def test_routes_match_spec_paths():
    app = create_app()
    served = {
        (r.path, m.lower())
        for r in app.routes
        for m in getattr(r, "methods", set())
        if r.path in {"/health", "/v1/query"} or r.path.startswith("/v")
    }
    spec = {(p, m) for p, ops in SPEC["paths"].items() for m in ops}
    assert served == spec


def test_served_openapi_is_the_committed_spec():
    r = client().get("/openapi.json")
    assert r.status_code == 200
    assert r.json() == SPEC


# ------------------------------------------------------------ health


def test_health():
    r = client().get("/health")
    assert r.status_code == 200
    assert errors("Health", r.json()) == []


# ------------------------------------------------------------ query: success


def test_answer_matches_schema():
    r = client().post("/v1/query", json={"question": "water policy?"}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "answered"
    assert errors("QueryResponse", body) == []


def test_refusal_is_200_and_matches_schema():
    r = client().post("/v1/query", json={"question": "[refuse] anything"}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "refused"
    assert errors("QueryResponse", body) == []


def test_every_citation_id_resolves():
    body = client().post("/v1/query", json={"question": "q"}, headers=HEADERS).json()
    ids = {c["id"] for c in body["citations"]}
    for s in body["answer"]["statements"]:
        assert set(s["citation_ids"]) <= ids


def test_speaker_key_always_present():
    body = client().post("/v1/query", json={"question": "q"}, headers=HEADERS).json()
    for c in body["citations"]:
        assert "speaker" in c["quote"]


def test_response_ids_are_fresh():
    c = client()
    a = c.post("/v1/query", json={"question": "q"}, headers=HEADERS).json()["response_id"]
    b = c.post("/v1/query", json={"question": "q"}, headers=HEADERS).json()["response_id"]
    assert a != b


def test_history_accepted():
    req = {
        "question": "What did they say?",
        "history": [{"question": "Earlier?", "answer_text": "Something.", "cited_record_ids": ["x"]}],
    }
    r = client().post("/v1/query", json=req, headers=HEADERS)
    assert r.status_code == 200


def test_stub_matches_spec_examples():
    """The stub's fictional data is the spec's examples, so the two cannot drift."""
    examples = SPEC["components"]["examples"]
    for name, body in (("Answered", stub.ANSWERED), ("Refused", stub.REFUSED)):
        want = copy.deepcopy(examples[name]["value"])
        want.pop("response_id")
        assert body == want, name
