"""pmg-assist API, Milestone 0 skeleton.

Run:  uvicorn pmg_api.main:app --app-dir api --reload

The OpenAPI document this app serves at /openapi.json is the committed
docs/api.openapi.yaml, not FastAPI's generated one. Clients and humans see
the contract itself; the tests check that the code honours it.
"""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import stub
from .models import Health, QueryRequest, QueryResponse

CLIENT_VERSION_PATTERN = r"^(ios|android)/[0-9]+\.[0-9]+\.[0-9]+$"
DEFAULT_SPEC = Path(__file__).resolve().parents[2] / "docs" / "api.openapi.yaml"
PROBLEM = "application/problem+json"


def parse_semver(v: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", v)
    if not m:
        raise ValueError(f"not a version: {v!r}")
    return int(m[1]), int(m[2]), int(m[3])


def problem(status: int, title: str, code: str, detail: str | None = None, **extra) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status, "code": code}
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


@cache
def load_spec(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def create_app(min_client_version: str | None = None, spec_path: str | None = None) -> FastAPI:
    min_version = min_client_version or os.environ.get("PMG_MIN_CLIENT_VERSION", "0.0.0")
    min_tuple = parse_semver(min_version)  # fail at startup, not on the first request
    spec_file = spec_path or os.environ.get("PMG_OPENAPI_PATH", str(DEFAULT_SPEC))

    app = FastAPI(title="pmg-assist API")
    app.openapi = lambda: load_spec(spec_file)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        fields = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return problem(422, "Invalid request", "invalid_request", fields)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        # Detail deliberately omitted: never leak internals to a client.
        return problem(500, "Internal error", "internal_error")

    @app.get("/health", response_model=Health, tags=["ops"])
    def get_health() -> Health:
        return Health()

    @app.post("/v1/query", response_model=QueryResponse, tags=["query"])
    def post_query(
        body: QueryRequest,
        client_version: Annotated[
            str, Header(alias="PMG-Client-Version", pattern=CLIENT_VERSION_PATTERN)
        ],
    ):
        version = client_version.split("/", 1)[1]
        if parse_semver(version) < min_tuple:
            return problem(
                426, "Upgrade required", "upgrade_required",
                f"{client_version} is no longer supported",
                minimum_client_version=min_version,
            )
        return stub.respond(body.question)

    return app


app = create_app()
