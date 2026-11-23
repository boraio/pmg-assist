# 0006 — Grounded generation: three refusal layers, checked citations, judged groundedness

- Status: Proposed
- Date: 2026-11-23
- Milestone: 2

## Context

- ADR 0001 fixes the answer's shape: a list of statements, each citing at least
  one citation; every citation carries a verbatim `quote`, and `quote.speaker`
  is null unless the record itself names who said it. A refusal is its own
  outcome with an open-set `reason`; the spec already lists
  `insufficient_evidence`, `outside_corpus`, `requests_evaluation` and
  `unsupported_language`.
- ADR 0002 (decision 4) puts the generator behind an OpenAI-compatible chat
  endpoint and makes its choice an eval result: local models that fit in 12 GB
  against one hosted model, compared on groundedness, attribution errors,
  refusal rate and p95 latency.
- Retrieval is measured (2026-11-23, index 0.1, bge-small-en-v1.5): fused RRF
  search finds the first expected record in the top 5 for 32 of 38 answerable
  questions.
- The eval set has 38 answerable questions, 7 unanswerable ones (q039–q045)
  and 3 that must be refused on policy (q046–q048: a prediction, a
  characterisation, a voting choice). The owner judged q039–q045 unanswerable
  on 2026-11-23; if a generator answers one, the review (decision 5) checks the
  answer against its record anyway. Several have close records that look
  relevant, which test the generator directly: lion population estimates in
  Kruger for q042 (40466, 41235), a seasonal forecast for q044 (41265), and
  Bafana Bafana's qualification for q045 (36472).
- Refusal spike, 2026-11-23: the top record's cosine similarity does not
  separate the groups. Medians are 0.749 for answerable questions, 0.724 for
  unanswerable and 0.671 for must-refuse; the highest unanswerable score
  (q045, 0.761) is above most answerable ones. The lowest answerable score is
  0.688 (q026, found at rank 1). No threshold above 0.68 avoids refusing
  answerable questions, and 0.68 catches 5 of the 10 others with a margin of
  0.008. BM25 separates no better (q042 scores 15.44).

## Decisions

### 1. One pipeline: retrieve, floor, generate, check

For each question: fused retrieval (ADR 0004) → the similarity floor
(decision 2) → the generator, given the best chunks of the top 5 records →
the server's checks (decision 4) → an answer or a refusal. The eval harness and,
later, the API run the same code.

Each chunk reaches the generator with a short id (`c1`, `c2`, …), its record's
date, committee code and addressee, and its text. Only the text can be quoted;
the context line from ADR 0004 is metadata, never quote material. How many
chunks per record, and the context size that implies, is measured per
candidate (Open).

### 2. Refusal has three layers, and the score is the weakest

1. **Similarity floor.** If the top record's cosine similarity is below the
   floor, the question is refused with `insufficient_evidence` without calling
   the generator. The floor is the lowest top similarity among answerable eval
   questions minus 0.02, recomputed whenever the eval set or the embedding model
   changes: 0.668 today, which on its own catches one of the ten negatives. It
   saves generator calls on questions nothing is near; it is not the refusal
   mechanism and is never reported as one.
2. **The generator.** It answers only from the given chunks. It refuses with
   `insufficient_evidence` when they do not answer the question, and with
   `requests_evaluation` when the question asks for a prediction, an opinion, a
   ranking, a characterisation or a political choice, whatever the chunks say.
3. **The server.** Statements that fail a check (decision 4) are dropped. If
   none remain, the answer becomes an `insufficient_evidence` refusal.

### 3. The generator returns JSON, not prose

The generator returns one JSON object: either `outcome: answered` with
`statements`, each a `text` and one or more `citations` of `{chunk, quote}`,
or `outcome: refused` with a `reason`. The prompt says: plain text, no
Markdown; no statement without a citation; a quote is copied, never
reworded; no names of people unless the quoted text contains them; no
opinions, rankings or characterisations. Temperature 0. Where an endpoint can
enforce a JSON schema, it is used; whether each candidate's endpoint does is
checked, not assumed. Output that does not parse is a refusal and is counted.

### 4. The server checks every statement mechanically

A statement is kept only if:

- every cited chunk id is one that was given to the generator;
- every quote is a verbatim substring of that chunk's text, after collapsing
  whitespace and nothing else;
- every capitalised name in the statement (a run of capitalised words, past the
  first word, outside a short stoplist of institutions and places used in
  questions) appears in the text of a chunk it cites.

The name check is a heuristic, and it errs towards dropping. `quote.speaker`
stays null throughout Milestone 2: statements report what a record says, not
who said it. Attribution to a named speaker is a later, separate decision with
its own checks. Statements are dropped, never repaired. Drops are counted per
candidate, because a generator whose statements are often dropped is a poor
one even when what survives is correct.

### 5. Groundedness is judged by the owner, from a review sheet

For each candidate and question, the harness writes the kept statements next to
the full text of the chunks they cite. The owner marks each statement:
supported, partly supported, or not supported by its citations, and separately
flags any attribution error (words, positions or actions given to a person
that the cited text does not give them). The sheet lives outside the repo,
because chunks can contain private people's names; only counts are committed.

Reported per candidate, in a dated results file:

- answerable questions: answered, refused (false refusals), and how many
  answered ones cite an expected record;
- unanswerable questions: refused, and answered (false answers);
- must-refuse questions: refused with `requests_evaluation`;
- statements: kept, dropped by each check, and the owner's judgements;
- groundedness: supported statements over kept statements;
- attribution errors: a count, every one listed by question id;
- p95 latency and output tokens per second.

The ship rule in PROJECT.md applies: a candidate with attribution errors at any
meaningful rate is not used, whatever its other numbers.

### 6. Candidates and where they run

- **Local:** one or two instruction models of about 7–9B parameters at 4-bit,
  served by a llama.cpp server in `pmg-assist` on GPU 1, pinned as in ADR 0005,
  and running only during an eval. Each is recorded with its exact file, size
  and quantisation. They are chosen from current model cards when the harness is
  ready, not from memory.
- **Hosted:** one model, chosen by the owner. Its API key lives outside the
  repo (an environment variable on nia, a Kubernetes secret if it runs on the
  cluster).
- The `llama-server` on GPU 0 is not a candidate: it is a code model, and aider
  depends on it.

## Consequences

- The harness grows a generation step beside retrieval, in `eval/`, with
  checks that use a fake generator and no network.
- The owner's review is the slow step: roughly 100–150 kept statements per
  candidate. Reviewing every candidate in full may not be worth it; the
  mechanical numbers decide which candidates get the full review.
- A hosted run costs money: 48 questions at a few thousand tokens each, per
  candidate and run.
- No contract change: the refusal reasons used are already in
  `docs/api.openapi.yaml`. The description of `insufficient_evidence` ("retrieval
  did not clear the threshold") is narrower than its use here and should be
  widened when the API gains generation; that is a wording change in the spec,
  not a schema change.
- Ten negative questions are few. The refusal numbers carry that caveat until
  the owner adds more.

## Open

- Chunks per record and context size per candidate.
- Whether each candidate's endpoint enforces a JSON schema.
- The floor, once there are more negative questions.
- Which local models and which hosted model.
