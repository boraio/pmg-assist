# pmg-assist

Questions about South African parliamentary activity, answered from
[Parliamentary Monitoring Group](https://pmg.org.za) records, with a citation
on every answer.

**Status:** a lab-only proof of concept. Milestone 1 (retrieval measured
against a hand-written evaluation set) is in progress. Decisions, correctness
requirements and milestones are in [PROJECT.md](PROJECT.md).

## Rules the app keeps

- Every answer carries a citation to a PMG record.
- When retrieval is weak, it refuses rather than paraphrases.
- A statement is attributed to a person only if it appears verbatim in a
  retrieved record.
- No political positions, rankings or characterisations.

## What is here

| Path | What |
|---|---|
| `docs/api.openapi.yaml` | The API contract that both mobile clients consume |
| `docs/adr/` | Architecture decision records |
| `docs/measurements/` | Measurements behind the decisions |
| `api/` | FastAPI service, currently a fixed stub with no retrieval |
| `ingest/` | PMG API to bronze (raw) to silver (parsed) |
| `infra/k8s/` | Lab deployment |

## Running it

```
make venv      # create .pmgvenv and install the dev requirements
make check     # lint, offline checks and spec validation (what CI runs)
make api       # local API on port 8077
make bronze    # fetch committee questions from the PMG API (needs PMG_INGEST_CONTACT)
make silver    # parse bronze into silver (ADR 0003)
make help      # every target
```

Data under `data/` is not committed.

## Data

Records come from the Parliamentary Monitoring Group's public API and remain
PMG's. Their terms of use and the attribution they require are to be agreed
with PMG before any public release.
