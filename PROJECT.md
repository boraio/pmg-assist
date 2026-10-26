# pmg-assist

A mobile app that makes South African parliamentary activity legible to
ordinary citizens, backed by retrieval over Parliamentary Monitoring Group
records.

## The problem

Staying informed about parliament is hard for anyone without specialist
knowledge. The primary sources are televised sittings and long documents, and
neither answers a question like "who is responsible for water policy and what
have they said about it this year?"

The app answers questions in conversation, over real parliamentary records,
**with citations**, so the user can verify every claim against its source.

## Scope

Three use cases carried over from the prototype:

1. **Find the responsible ministry** for a topic, sector or question.
2. **Query parliamentary exchanges** conversationally — what was discussed,
   when, by whom — without manual search.
3. **Identify relevant MPs and ministers** for a topic.

**One carried-over use case needs rethinking before it gets built.** The
prototype described "suggesting alternative ministers or MPs as replacements."
For a citizen-facing app, "who else could do this job" is political commentary
dressed as a feature, and it is not the same product as "what did parliament
discuss." Either reframe it as factual (who else sits on this committee, who
held this portfolio previously) or drop it. This is a product decision to make
deliberately, not inherit.

## Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Clients | Native — Swift/SwiftUI and Kotlin/Compose | Platform fidelity. Accepted cost: two codebases. |
| API | FastAPI (replacing Flask) | Generates and validates OpenAPI from the code, so two native clients cannot drift from the contract. |
| Retrieval | Postgres + pgvector, hybrid lexical + semantic | MP and ministry names are exact-match terms that embeddings handle badly; BM25 catches them, vectors catch paraphrase. Minsearch does not survive production. |
| Compute split | Hybrid — VYRA for batch, hosted for live | The cluster scrapes, chunks, embeds and evaluates. A hosted API serves app traffic, so availability does not depend on a home internet connection. |
| Distribution | Limited beta first | TestFlight and Play internal testing. Store submission is a later decision. |

### The hybrid boundary

This is the load-bearing architectural line, and it should stay clean:

```
VYRA (self-hosted)                      Hosted
─────────────────────                   ──────────────────────
scrape PMG            ──┐
chunk + normalise       │
generate embeddings     ├── push ──▶    managed Postgres + pgvector
evaluation harness      │                        ▲
index build             ──┘                      │
                                        FastAPI ─┘
                                           ▲
                                    iOS ───┴─── Android
```

VYRA never serves a user request. It produces artifacts and pushes them. If the
cluster is off, the app keeps working against the last published index. That
property is the whole reason for the split and must not be eroded by
convenience.

## Correctness and safety requirements

This app makes factual claims about named public figures and their official
conduct. Misattribution is a real harm, not a UX defect. These are
requirements, not aspirations:

- **Every answer carries citations** — source URL, record date, and the
  specific exchange. An answer without a citation is a bug.
- **Refuse rather than paraphrase when retrieval is weak.** A confident wrong
  answer about what a minister said is worse than "I couldn't find that."
  Define a retrieval-score threshold and honour it.
- **Never attribute a statement to a named person** unless that attribution
  appears verbatim in a retrieved chunk. No inference about who probably said
  something.
- **Surface the record date prominently.** Cabinet composition changes.
  "Who is the minister for X" has a different answer depending on when you ask,
  and a stale answer presented as current is a misinformation vector.
- **No political positions.** The app reports what was said and by whom. It
  does not evaluate whether a policy is good, rank parties, or characterise
  anyone's performance.
- **Date-aware portfolio questions.** Reshuffles mean the ministry–minister
  mapping is time-varying. Model it as such from the start; retrofitting
  temporality into a flat mapping is painful.

## Legal and compliance

Unresolved, and both block public distribution rather than development:

- **PMG's terms of use.** The data is theirs. Scraping and redistributing it
  needs their terms checked and, most likely, visible attribution and a link
  back on every citation. Worth approaching them directly — an NGO whose
  mission is public access to parliament may well be supportive, and permission
  is better than inference.
- **POPIA.** If the app stores queries, accounts or analytics, South Africa's
  Protection of Personal Information Act applies. Decide early whether to
  collect anything identifiable; the cheapest compliance posture is to collect
  nothing.

## Languages

South Africa has eleven official languages and parliament does not conduct
business only in English. English-only is an acceptable starting point but
should be an explicit, stated limitation rather than an unexamined default.
Pick a second language for the beta based on where the users are.

## Current state

A working prototype exists at `AfroGrit/jenga-resume`, under
`llm/pmg-assist/`: Python, Minsearch for full-text, Flask API, Questionary
CLI, OpenAI as the model, Grafana + Postgres for monitoring, Docker Compose.

**What carries over**: the problem framing, the three use cases, the scraper's
knowledge of PMG's page structure, and the dataset shape (discussion date,
responsible ministry, participant roles).

**What does not**: Minsearch, Flask, the CLI as the interface, and the
single-process deployment model.

## Milestones

### Milestone 0 — the contract and a thin slice

The hardest part of a two-client project is keeping them in step, so prove the
whole path end to end before building any feature depth.

- OpenAPI spec for `POST /query` and `GET /health`, committed and reviewed
- FastAPI skeleton returning a hardcoded but correctly-shaped answer with
  citations
- Deployed to the hosted target with TLS
- iOS and Android clients that call it and render the answer plus citations
- CI: lint and test the API, build both clients

**Exit**: a real build on a real iPhone and a real Android device, showing an
answer from the deployed API. No retrieval yet.

### Milestone 1 — retrieval that is measured, not assumed

- Ingest pipeline on VYRA: scrape, normalise, chunk, embed, push to pgvector
- Hybrid search: BM25 over names and titles, vectors over content, with a
  stated fusion method
- **An evaluation set of real questions** — around 50, written by hand, each
  with the source records that genuinely answer it
- Retrieval metrics: Recall@5 and MRR, committed to the repo

**Exit**: Recall@5 written down. A number, not an impression. Nothing after
this milestone can claim improvement without it.

### Milestone 2 — grounded generation

- LLM answers constrained to retrieved context, citations mandatory
- Refusal path when retrieval scores fall below threshold
- **Measured groundedness**: for each eval question, does the answer's claim
  actually appear in the cited source? Report the rate.

**Exit**: a groundedness number and a refusal rate. If the model fabricates
attributions at any meaningful rate, the app does not ship.

### Milestone 3 — the app proper

- Real UI on both platforms: conversation history, source cards, loading and
  error states
- Offline and poor-connectivity behaviour — relevant in South Africa, not an
  edge case
- Accessibility: dynamic type, screen reader labels, contrast
- Second language

**Exit**: TestFlight and Play internal builds in the hands of users who are
not you.

### Milestone 4 — operations

- Scheduled ingest with change detection, so new sittings appear without
  manual runs
- Monitoring and alerting on ingest freshness, API latency, error rate
- Crash reporting on both clients
- Cost tracking for the hosted LLM calls

## Repo layout

```
pmg-assist/
├── PROJECT.md                  this file
├── docs/
│   ├── api.openapi.yaml        the contract — both clients consume it
│   ├── adr/                    architecture decision records
│   └── eval/                   the evaluation question set
├── api/                        FastAPI, hosted
│   ├── pmg_api/
│   ├── tests/
│   └── Dockerfile
├── ingest/                     scrape, chunk, embed — runs on VYRA
│   ├── pmg_ingest/
│   └── tests/
├── eval/                       retrieval and groundedness harness
├── ios/                        Swift / SwiftUI
├── android/                    Kotlin / Compose
├── infra/                      k8s manifests for batch, hosted deploy config
└── .github/workflows/
```

## Conventions

- `docs/api.openapi.yaml` is the source of truth for the contract. Client model
  types are generated from it, not hand-written. A change to the API that
  doesn't update the spec is incomplete.
- Architecture decisions go in `docs/adr/` as short numbered records: context,
  decision, consequences. One file per decision, never edited after the fact —
  superseded decisions get a new record.
- Secrets never in the repo. Hosted credentials in the platform's secret store;
  local development via `.env` excluded by `.gitignore`.
- Tests that touch the network or a live database are marked and excluded from
  PR checks. CI validates code, not data.
- Comments and ADRs explain **why**. Never state a claim about a tool's
  behaviour that hasn't been verified.

## Non-goals

- **Real-time sitting transcription.** The data source is PMG's published
  records, not live broadcast.
- **Political analysis, scoring or endorsement.** Out of scope permanently, not
  deferred.
- **Replacing PMG.** This is an interface onto their work, with attribution,
  not a substitute for it.
- **Every official language at launch.** English plus one, stated clearly.
