"""Retrieval evaluation for committee-question (ADR 0004, decisions 3 and 5).

Builds the search index over gold chunks, runs every question in
docs/eval/committee-question.yaml, ranks records by their best chunk, and
reports Recall@5 and MRR.
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

TOP_K = 5  # Recall@5
CUTOFF = 20  # MRR counts a first expected record only within the top 20


def first_rank(ranked, answers):
    """1-based rank of the first expected record in ranked, or None if absent."""
    return next((i for i, rid in enumerate(ranked, 1) if rid in answers), None)


def recall_at(ranks, k=TOP_K):
    """Share of questions whose first expected record is within the top k."""
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def mrr(ranks, cutoff=CUTOFF):
    """Mean reciprocal rank; a question scores 0 if its record is absent or below cutoff."""
    return sum(1 / r for r in ranks if r is not None and r <= cutoff) / len(ranks) if ranks else 0.0


def rrf(*rankings, k=60):
    """Reciprocal Rank Fusion (ADR 0004, decision 3): records by summed 1 / (k + rank).

    Ties are broken by record id so the order never depends on input order.
    """
    scores = {}
    for ranking in rankings:
        for i, rid in enumerate(ranking, 1):
            scores[rid] = scores.get(rid, 0.0) + 1 / (k + i)
    return sorted(scores, key=lambda rid: (-scores[rid], rid))


INDEX_DIR = Path("data/gold/committee-question/index=0.1")
QUESTIONS = Path("docs/eval/committee-question.yaml")

BM25_SQL = f"""
SELECT record_id, max(score) AS best FROM (
    SELECT record_id, fts_main_chunks.match_bm25(chunk_id, ?) AS score FROM chunks)
WHERE score IS NOT NULL GROUP BY record_id ORDER BY best DESC, record_id LIMIT {CUTOFF}
"""


def load_questions(path=QUESTIONS):
    """The evaluation set: a list of dicts with id, question and answers."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["questions"] or []


def build_bm25(con, chunks):
    """Load the gold chunks into con and index their searched text; return the chunk count."""
    con.execute("INSTALL fts; LOAD fts")
    con.execute(f"CREATE OR REPLACE TABLE chunks AS SELECT chunk_id, record_id, searched FROM read_parquet('{chunks}')")
    con.execute("PRAGMA create_fts_index('chunks', 'chunk_id', 'searched', overwrite = 1)")
    return con.execute("SELECT count(*) FROM chunks").fetchone()[0]


def search_bm25(con, text):
    """Records ranked by their best chunk's BM25 score, best first, at most CUTOFF of them."""
    return [row[0] for row in con.execute(BM25_SQL, [text]).fetchall()]


def vector_sql(dims):
    """Records ranked by their best chunk's cosine similarity to a query vector of dims floats."""
    return f"""
SELECT record_id, max(array_cosine_similarity(embedding, ?::FLOAT[{dims}])) AS best FROM emb
GROUP BY record_id ORDER BY best DESC, record_id LIMIT {CUTOFF}
"""


def build_vectors(con, chunks, emb, dims):
    """Load the chunk vectors and their record ids into con as arrays of dims floats; return the count."""
    con.execute(f"CREATE OR REPLACE TABLE emb AS SELECT e.chunk_id, c.record_id, e.embedding::FLOAT[{dims}] AS embedding "
                f"FROM read_parquet('{emb}') e JOIN read_parquet('{chunks}') c USING (chunk_id)")
    return con.execute("SELECT count(*) FROM emb").fetchone()[0]


def search_vector(con, vec, dims):
    """Records ranked by their best chunk's cosine similarity to vec, best first, at most CUTOFF of them.

    Exact: every chunk is compared, so no approximate index (vss) is needed at this size.
    """
    return [row[0] for row in con.execute(vector_sql(dims), [vec]).fetchall()]


def fuse(bm25, vector):
    """The hybrid ranking (ADR 0004, decision 3): the two rankings fused by RRF, at most CUTOFF records."""
    return rrf(bm25, vector)[:CUTOFF]


def evaluate(questions, search):
    """(id, question, rank) for each answerable question, using search(text) -> ranked record ids."""
    return [(q["id"], q["question"], first_rank(search(q["question"]), q["answers"]))
            for q in questions if q.get("answers")]


def report(method, rows, meta):
    """The results file: setup, Recall@5, MRR and every question's rank, as Markdown."""
    ranks = [rank for _, _, rank in rows]
    lines = [f"# Retrieval evaluation: {method}, {meta['date']}", "",
             f"- Index: {meta['index']}, {meta['chunks']:,} chunks",
             f"- Questions: {len(rows)} answerable, from {meta['questions']}",
             f"- Recall@{TOP_K}: {recall_at(ranks):.2f}",
             f"- MRR (cutoff {CUTOFF}): {mrr(ranks):.2f}", "",
             "| Question | Rank |", "|---|---|"]
    lines += [f"| {qid} {text.replace('|', '/')} | {rank if rank else f'not in the top {CUTOFF}'} |"
              for qid, text, rank in rows]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate BM25 retrieval over gold chunks (ADR 0004).")
    ap.add_argument("--index-dir", default=INDEX_DIR, type=Path)
    ap.add_argument("--questions", default=QUESTIONS, type=Path)
    ap.add_argument("--out", default=Path("docs/eval/results"), type=Path)
    args = ap.parse_args(argv)
    import duckdb  # here, not at the top, so the offline checks never need an index

    con = duckdb.connect(str(args.index_dir / "search.duckdb"))
    chunks = build_bm25(con, args.index_dir / "chunks.parquet")
    rows = evaluate(load_questions(args.questions), lambda text: search_bm25(con, text))
    meta = {"date": dt.date.today().isoformat(), "index": args.index_dir.name, "chunks": chunks,
            "questions": args.questions}
    text = report("BM25", rows, meta)
    out = args.out / f"{meta['date']}-{meta['index']}-bm25.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(text + f"written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
