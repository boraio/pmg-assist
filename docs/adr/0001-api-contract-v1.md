# 0001 — API contract v1: citations, refusals, conversation state, versioning

- Status: Proposed
- Date: 2026-10-07
- Milestone: 0

## Context

Two native clients (Swift, Kotlin) generate their models from
`docs/api.openapi.yaml`. Once a build ships, its decoder is frozen on users'
phones until they update. The response shape is therefore the most expensive
thing in the project to change, and it carries the correctness requirements
in PROJECT.md: every answer cited, refusal over weak paraphrase, no attribution
without verbatim support, record dates prominent.

## Decisions

### 1. Citations are structural, not decorative

The answer is a list of `statements`, each with `text` and `citation_ids`
(min 1). There is no free-text answer field, so an uncited claim has nowhere
to live. `citations` (min 1) carry:

- `record` — what a source card renders: title, type, `record_date` (date of
  the sitting, not publication), PMG `url` for tap-through, `publisher`
  (attribution on every card, pending PMG's terms), committee, participants
  with roles **as recorded at the time**.
- `ministry` — separate from `committee` and explicitly *derived* by us, with
  an `as_of` date. Committees are what PMG records; ministries are our
  time-varying mapping. Conflating them would bake a non-temporal model into
  the contract.
- `quote` — verbatim `text`, plus `speaker`, which is null unless the
  retrieved text itself names who said it. A client shows a speaker only when
  the server supplies one.

The schema cannot check that a quote is verbatim or that a statement's named
person matches a cited `quote.speaker`. Those are server-side guarantees,
tested in Milestone 2.

Text is plain, not Markdown: two native renderers would render Markdown
differently, and plain text keeps the two apps in step.

### 2. Refusal is a 200 with `outcome: refused`

`QueryResponse` is a `oneOf` discriminated on `outcome` (`answered` |
`refused`). A refusal carries a `reason` and a display-ready `message`. Non-2xx
is reserved for "could not process the request" (validation, rate limit,
outage), so a client never confuses "the records don't say" with "the server
is down". Both outcomes carry `corpus` freshness, so a refusal can say
"records up to 2 October".

`reason` is an open string set, not an enum: we will want new reasons, and an
old client must degrade to showing `message`, not fail to decode. `outcome`
is closed: a third outcome is a breaking change (see 4).

Refusals do not include "nearby" records. Showing weak matches next to a
refusal invites the user to read them as the answer.

### 3. Conversation state lives on the client

The server is stateless. The client sends up to 10 prior `history` turns
(question, displayed answer text, cited record IDs).

- No server-side session store, which means nothing identifiable persisted by
  design — the cheapest POPIA posture, and it keeps that option open.
- Any API instance serves any request; restarts lose nothing.
- Cost: requests grow with history, hence the cap.

`history` is untrusted client input. It is used only to interpret the new
question (resolve "she", "that meeting"), never as evidence or citation
material. Otherwise a modified client could put words in a minister's mouth
via a fake prior answer and have them repeated with apparent authority.

Note: statelessness covers storage, not processing. Whether the server *logs*
questions is a separate POPIA decision, still open.

### 4. Versioning: path major version, additive-only within it, forced upgrade from day one

- The client contract lives under `/v1/`. `/health` is unversioned
  infrastructure.
- Within v1, only additive changes: new optional request fields, new
  response fields, new values in open string sets (`record_type`, `reason`,
  `code`). Clients must ignore unknown fields and tolerate unknown open-set
  values.
- Breaking changes (removing/renaming fields, tightening types, new `outcome`
  values, new required request fields) ship as `/v2/`, run alongside v1 until
  v1 traffic is gone.
- Every request sends `PMG-Client-Version`. The server can answer `426` with
  `minimum_client_version`, and every v1 build must handle 426 by prompting
  an update. This must exist in the first shipped build; it cannot be added to
  builds already installed.

The 426 path is also our escape hatch for decisions not yet made — notably
authentication, which would be a new required header and therefore breaking.

## Consequences

- Clients get one decode path for answers and refusals, and must render
  `record_date` and `publisher` on every source card.
- Server must enforce: citation IDs resolve; `quote.text` is a verbatim
  substring of the record; named attribution only with a matching
  `quote.speaker`.
- FastAPI emits its own OpenAPI document. CI must diff it against this file so
  the committed contract and the running code cannot drift.

## To verify before relying on this (not yet checked)

- OpenAPI 3.1 `oneOf` + `discriminator`, and `type: [string, 'null']`, in the
  chosen Swift and Kotlin generators. Kotlin generator not yet chosen; if its
  3.1 support is poor, downgrading this file to 3.0.3 is cheap now and
  expensive later.
- Unknown-field tolerance in each generated client's decoder configuration.
  kotlinx.serialization in particular rejects unknown keys unless configured
  otherwise — check the generated setup.
- FastAPI's default 422 body is not RFC 9457; the skeleton needs a custom
  validation handler to match `Problem`.

## Open

- Authentication / abuse control for a public endpoint that spends LLM money.
- Whether questions are logged (POPIA).
- Deep-linking to a position within a PMG page — depends on whether PMG pages
  expose stable anchors. Additive later if so.
