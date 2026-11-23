# Embedding spike on nia, 2026-11-18 and 2026-11-20

Throwaway checks, run before any embedding code was written, to choose the
first embedding model for vector search (ADR 0004, decision 4): its real
properties, how much of our text it can see, and how long the corpus takes on
nia's CPU.

## Setup

- A separate virtual environment with PyTorch 2.15.0 (CPU build) and
  sentence-transformers, kept out of the main venv and CI as ADR 0004 requires.
- Samples of `searched` text from
  `data/gold/committee-question/index=0.1/chunks.parquet` (DuckDB reservoir
  sample, seed 7): 2,000 chunks for bge-small, 500 for bge-m3, 256 for the
  thread benchmark.
- Model properties were read from the loaded models, not from their cards.

## The two candidates

| | BAAI/bge-small-en-v1.5 | BAAI/bge-m3 |
|---|---|---|
| Parameters | 33M | 568M |
| Download | 133 MB | 2.27 GB (fetched twice, in two formats) |
| Embedding size | 384 | 1,024 |
| Longest input | 512 tokens | 8,192 tokens |
| Tokens per chunk (p50 / p99 / max) | 156 / 600 / 816 | 180 / 682 / 719 |
| Chunks longer than the input limit | 51 of 2,000 (2.6%), cut at 512 | 0 of 500 |
| Speed in the first run (32 threads) | 12 chunks/s | 1 chunk/s |
| Whole corpus at that speed | about 3.4 hours | about 30 hours |

## bge-m3 is dropped

- On nia's CPU it would take about 30 hours for one index version.
- It was listed for a second official language. The AfriMTEB benchmark
  (arXiv 2510.23896) reports its retrieval at 69.6 for isiZulu and 69.1 for
  isiXhosa, against about 78 for mE5-large-instruct and higher for AfriE5, and
  gives nothing for Sesotho or the other official languages.
- The second language is not chosen yet (PROJECT.md: chosen from where the
  users are, Milestone 3). When it is, AfriE5 is the first candidate to
  evaluate for it. It is built on a model of about bge-m3's size, so the same
  CPU-or-GPU question will come back then.

## Why bge-small was slow

The first run asked PyTorch for 32 threads. PyTorch's own default on nia is 16
while the machine reports 32 hardware threads, so 32 made the threads compete
for the same cores. Measured on 256 chunks:

| Threads | Batch 8 | Batch 32 |
|---|---|---|
| 1 | 8.6 | 6.3 |
| 4 | 22.7 | 17.5 |
| 8 | **30.6** | 22.7 |
| 16 | 25.4 | 27.9 |
| 32 | 5.2 | 9.6 |

(chunks per second)

The best setting, 8 threads with batches of 8, embeds the 149,067 chunks in
about 80 minutes. Speed stops rising after 8 threads, so something besides the
cores, probably memory speed, limits it. Embedding runs once per index
version, so this is acceptable without a GPU.

## Decisions

- **First model: bge-small-en-v1.5**, at 8 threads and batches of 8.
- **Questions get the model's retrieval prefix,** "Represent this sentence for
  searching relevant passages: ", and chunks do not, following the
  maintainers' advice (Hugging Face discussion on BAAI/bge-small-en-v1.5).
- The 2.6% of chunks longer than 512 tokens are embedded from their first 512
  tokens; BM25 still sees all of their text.

## Not measured

- Several processes of 4 threads each on separate slices of the corpus.
- The ONNX runtime, often faster than PyTorch on CPU.
- Whether vectors improve Recall@5 over the BM25 baseline (0.79): that is the
  next measurement.
