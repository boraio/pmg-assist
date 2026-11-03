# 0002 — Ingest from the PMG API, models on VYRA, serving location decided by measurement

- Status: Accepted (2026-11-02)
- Date: 2026-10-26
- Milestone: 0 (revises the plan before step 2; does not change ADR 0001's contract)

## Context

PROJECT.md was written before three things were known:

1. **PMG has a live, read-only, documented API.** `GET https://api.pmg.org.za/`
   returned 200 on 2026-10-26 with 17 endpoints, including `question_reply`,
   `committee-question`, `committee-meeting`, `hansard`, `minister` and `member`
   (docs: OpenUpSA/pmg-cms-2 `API.md`). Pages hold 50 results, `next` is null on
   the last page, `count` gives the total, and `filter[field]=value` works on
   most fields. Committee-meeting `body` and `summary` are null for premium
   committees unless the caller is a subscriber, flagged by
   `premium_content_excluded` (from `pmg/api/schemas.py`).
   Record counts on 2026-10-26: `committee-question` 41,115,
   `committee-meeting` 35,194, `hansard` 2,558, `question_reply` 579,
   `member` 939, `committee` 313, `minister` 41. A sampled `question_reply`
   (id 580, 2017-11-02) is one whole sitting of oral replies: several
   question-and-reply exchanges, each with its own asker, in a single HTML
   `body`. The individual written questions the prototype scraped (`NW801` and
   similar codes) appear to be `committee-question` records; this is inferred
   from that model's `code` field and has not yet been checked against a
   record.
2. **What VYRA actually is** (from `kubectl` output, 2026-10-26): Kubernetes
   v1.34, two 4-CPU/16 GB control-plane nodes, three 8-CPU/~94 GB workers, and
   `zeru`, a 56-CPU/~504 GB node with 2× RTX 3060 (12 GB, Ampere). One of those
   GPUs is allocated, to `llama-server` in namespace `llm`, which is the local
   model aider uses. Storage is Ceph (RBD StorageClasses plus RadosGW S3 at
   `10.0.20.252`). MetalLB, ingress-nginx, Knative Serving and GitHub Actions
   runners (ARC) are installed. Node events show the nodes restarted about 30
   minutes before the output was captured.
3. **ghpulse already runs a working batch pattern on the same cluster.** It uses
   medallion layers on RadosGW, a resumable backfill with per-partition
   markers, DuckDB chosen over Spark after measuring, and offline-only CI on
   ARC.

The owner wants to self-host the models on VYRA rather than call a hosted LLM.

"RAG model" in this ADR means three separate models. An **embedding model**
(batch over the corpus, plus once per question), an optional **reranker**, and
a **generator** LLM that writes the answer. They have different placement
constraints.

The prototype (`AfroGrit/jenga-resume`, `llm/pmg-assist`) scraped HTML from
about 300 question replies. It stored no source URL, its record IDs collide
(300 rows, 263 distinct `id`s), some replies were never fetched (body
"Find replyhere"), and its scraper sent a spoofed `X-Forwarded-For` header.

## Decisions

### 1. Ingest from the PMG API, not HTML

- Every record gets a stable `record_id` of `pmg-<type>-<api id>` and a
  canonical PMG URL. That fixes the prototype's two citation blockers.
- The User-Agent is honest and names a contact. Spoofed headers are never sent.
  Pages are fetched serially with a delay, because this is an NGO's
  infrastructure.
- **Premium content is not ingested.** A record with
  `premium_content_excluded: true` is stored as metadata only (title, date,
  committee, URL) and is never chunked. Taking PMG's paid content needs their
  permission, not a token.
- First content type: `committee-question` (use cases 1 and 3). Then free
  `committee-meeting` (use case 2), then `hansard` and `question_reply`. Those
  last two bundle many exchanges into one HTML body, so silver must split them
  into exchanges, each with its asker, before any attribution is possible. Reference
  tables `minister`, `member` and `committee` are snapshotted each run with the
  fetch date, so the date-aware portfolio mapping has a history to build from.
- Reply attachments (the "Find replyhere" case) are a separate step. PDF
  extraction is its own source of error and is measured separately.

### 2. Medallion layers on RadosGW, borrowed from ghpulse

```
bronze  s3://pmg-assist/bronze/<type>/fetched=<date>/page=<n>.json   raw API pages, immutable
silver  s3://pmg-assist/silver/records/<type>.parquet                typed, deduplicated, record_id + url
gold    s3://pmg-assist/gold/chunks/<index_version>/                 chunks + embeddings + metadata
publish → Postgres + pgvector, one index_version at a time
```

- Bronze keeps ghpulse's marker or manifest approach, so the backfill resumes
  and reruns one partition at a time.
- DuckDB, not Spark. About 80,000 records across the four text types is a
  single-node workload. Bytes per record have not been measured yet, so this
  holds until that measurement says otherwise, which is ghpulse's rule:
  measure first.
- `index_version` is what feeds `corpus.index_published_at` in the API
  contract. Publishing switches the live version in one step, so the API never
  serves a half-loaded index.

### 3. Embeddings and reranking run on VYRA as batch

This is uncontroversial and fits the original split. It runs as a Kubernetes
Job on `zeru`. The free GPU is used if it is available, otherwise CPU (56
cores). Throughput on either has not been measured yet.

The API must embed each incoming question **with the same model** used for the
corpus. The model name and version are therefore recorded on the
`index_version`, and the API refuses to start if the two don't match. A small
embedding model can run on CPU inside the API process. That has to be checked
on whatever machine the API runs on.

### 4. The generator sits behind an OpenAI-compatible endpoint, and its choice is an eval result

- The API calls an OpenAI-compatible chat endpoint set by configuration. The
  llama.cpp server already running on VYRA exposes one, and so do hosted
  providers. Switching generators is a config change, not a code change.
- **No generator is chosen ahead of time.** In Milestone 2, the harness runs the
  same eval set through each candidate: one or more local models that fit in
  12 GB (roughly 7–8B parameters at 4-bit, an estimate to confirm) and one
  hosted model. It reports groundedness, attribution errors, refusal rate and
  p95 latency for each.
- The ship rule in PROJECT.md applies to every candidate: if a model fabricates
  attributions at a meaningful rate, it is not used. ghpulse has already logged
  one claim a local model fabricated that turned out false. That is a reason to
  measure, not to rule local models out.

### 5. Where user traffic is served is still open, and is decided at the end of Milestone 2

| Option | What runs where | For | Against |
|---|---|---|---|
| A. Hosted (PROJECT.md as written) | API, pgvector and generator hosted; VYRA batch only | The app survives a home outage or power cut | Ongoing hosting and LLM cost; uses none of the GPUs |
| B. All on VYRA | API, pgvector and llama-server on the cluster, exposed publicly | Near-zero running cost; uses the hardware | Availability equals home power and internet; one 3060 handles few requests at once; needs public ingress with TLS, which isn't there yet (MetalLB addresses are private 10.0.20.x) |
| C. Split serving | API and DB hosted, generator on VYRA through a tunnel | — | Rejected: still goes down when home goes down, and adds a network hop and a second failure point |

Until users exist (Milestones 1–2), everything runs on VYRA, because there is
no availability to protect yet. The code is kept so that A and B differ only in
configuration. The decision is made with three numbers in hand: the best local
generator's groundedness compared with the hosted one, p95 latency on one 3060
at expected beta load, and VYRA's observed uptime over the same period.

## Consequences

- ADR 0001's contract is unchanged. `record_type` is an open set, so adding
  `committee_question` costs nothing.
- PROJECT.md needs updating once this is accepted:
  - the hybrid-boundary section should say "VYRA never serves user traffic
    **unless decision 5 chooses B**";
  - Milestone 0's exit ("deployed to the hosted target with TLS") becomes
    "deployed with TLS to wherever decision 5 points, VYRA for now";
  - the repo layout gains the bronze, silver and gold paths;
  - the Current State section should list the prototype's data defects.
- The second GPU on `zeru` is now in demand from three places: batch embedding,
  Milestone 2 generator evals, and, under option B, live serving. GPU scheduling
  is a cluster concern. This project only declares its requests.
- A new RadosGW bucket `pmg-assist` and its credentials are needed. Creating
  them is cluster operation, outside this project's scope.

## Open

- Bytes per record and date range per content type, the share of
  committee meetings with premium content excluded, and how many
  `committee-question` records have a reply in the body rather than only in
  an attached file.
- Whether PMG agrees to the ingest and how attribution must look. This blocks
  distribution, not development.
- How a phone reaches the API in Milestone 0 if it runs on VYRA: on home Wi-Fi
  only, or through a public tunnel. iOS requires TLS from a trusted CA in
  either case.
