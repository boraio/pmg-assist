# 0004 — Gold: chunks, embeddings and retrieval evaluation in DuckDB

- Status: Accepted (2026-11-06)
- Date: 2026-11-06
- Milestone: 1

## Context

Silver 0.1 (ADR 0003) holds 41,156 committee-question records as ordered
blocks. Sizes measured on 2026-11-06 over
`data/silver/committee-question/version=0.1/records.parquet`, in characters:

| Unit | Count | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|
| Reply paragraph | 337,243 | 102 | 440 | 870 | 5,534 |
| Table row (cells joined with " \| ") | 351,849 | 55 | 144 | 536 | 17,142 |
| Question | 41,156 | 411 | 844 | 1,556 | 17,909 |
| Whole record (question + reply) | 41,156 | 1,545 | 4,646 | 15,957 | 1,094,207 |

25,252 records (61%) are at most 2,000 characters in total, and 35,610 (87%)
at most 4,000. At roughly four characters per English token, 2,000 characters
is about 500 tokens; the real tokenizer is measured once a model is chosen.

Only 147 reply paragraphs and 462 table rows are longer than 1,500
characters. nia has 32 CPU threads and 440 GB of memory, and DuckDB's `fts`
and `vss` extensions install and load there (checked 2026-11-06).

Milestone 1's exit is Recall@5 written down. The owner chose on 2026-11-06 to
evaluate retrieval in DuckDB on nia, so no database on the cluster is needed
yet. ADR 0002's serving path (Postgres with pgvector) is unchanged and comes
when the API serves retrieval.

## Decisions

### 1. Chunks never cross a record, and tables split only between rows

- Each record gives question chunks and zero or more reply chunks. A question
  is one chunk unless it is longer than the limit (just over 1% are); then it
  is split like a paragraph.
- Reply paragraphs are packed in order into chunks of at most 1,500 characters.
  A paragraph longer than that is split at sentence ends.
- A table is packed row by row into chunks of at most 1,500 characters. Every
  chunk of a table after the first starts with the table's first row,
  labelled "First row of the table:", never as column names (ADR 0003). A
  single row longer than the limit becomes its own chunk, split at cell
  boundaries.
- A pointer reply (`attachment_pointer`) gives no reply chunk. Its question
  chunk is still indexed, so the API can say the reply is in an attached
  document and link to it.
- A chunk records its record, its kind, its position, and the exact text it
  holds. Quotes shown to a user come only from that text, as PROJECT.md
  requires for any attribution.

### 2. What is searched

Each chunk is searched as a short context line plus its text:
`<code>, <date>. Question to: <question_to_name>.` followed by the chunk text.
`question_to_name` is PMG's extracted text and stays labelled as such. The
context line helps both BM25 and the embedding find the right record. It is
never shown to the user as a quote.

### 3. Two retrievers, fused by rank

- **BM25** with DuckDB's `fts` extension, over the searched text.
- **Vectors** with DuckDB's `vss` extension (cosine similarity), over the
  embedding of the searched text.
- **Fusion by Reciprocal Rank Fusion** with k = 60: score = sum of
  1 / (60 + rank) over the two lists. It needs no calibration between BM25
  scores and cosine similarities.
- Results are reported per record: a record's rank is the rank of its best
  chunk.

### 4. The embedding model is an evaluation result

No model is chosen ahead of time, as with the generator in ADR 0002.
Candidates are run on CPU on nia first, each producing its own embeddings
under the same chunks:

- a small English model (e.g. BAAI bge-small-en-v1.5, 384 dimensions);
- a larger multilingual model with a long context (e.g. BAAI bge-m3), because
  a second official language is planned.

The model facts above are from memory and are checked against each model card
before use. Embedding time per model is measured and recorded. The GPU on
`zeru` is used only if CPU time becomes the obstacle; scheduling it is a
cluster concern.

### 5. The evaluation set is written by hand and kept in the repo

- `docs/eval/committee-question.yaml`: about 50 questions, each with the PMG
  record ids that genuinely answer it, written by the owner.
- Questions are phrased the way a citizen would ask, not copied from the
  record, and are found by reading records (PMG's site or silver) rather than
  by the search being evaluated, so the set does not favour BM25.
- Some questions should have no answer in the corpus, to test refusal later
  (Milestone 2); they are excluded from Recall@5 and MRR.
- **Recall@5**: share of answerable questions with at least one expected
  record in the top 5 records. **MRR**: mean of 1 / rank of the first expected
  record (0 if not in the top 20). Both are reported for BM25 alone, vectors
  alone, and fused, per embedding model, and committed with the date and
  index version.

### 6. Layout

```
data/gold/committee-question/index=<v>/chunks.parquet          chunks + searched text
data/gold/committee-question/index=<v>/emb=<model>.parquet     one embedding per chunk
data/gold/committee-question/index=<v>/search.duckdb            fts and vss indexes
docs/eval/committee-question.yaml                               the evaluation set
docs/eval/results/<date>-index-<v>.md                           committed metrics
```

`index=<v>` is the `index_version` that later feeds `corpus.index_published_at`
in the API contract (ADR 0002).

## Consequences

- Embedding dependencies (a model runtime such as sentence-transformers and
  PyTorch for CPU) go in a separate requirements file. CI does not install
  them; chunking and fusion checks run in CI with a fake embedder.
- Private individuals' names in tables are indexed as in silver, lab only
  (ADR 0003, decision 5).
- Chunk limits and the context line are first choices. Changing them is
  measured against the evaluation set, not argued.

## Open

- How long each candidate model takes to embed the corpus on nia's CPU.
- The sentence splitter for the 147 long paragraphs, chosen when the chunker
  is built and covered by checks.
