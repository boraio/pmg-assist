"""Offline checks for pmg_eval.retrieval. No network: no index is built here.

Run: python eval/tests/test_retrieval.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pmg_eval import retrieval as r

RESULTS = {"PASS": 0, "FAIL": 0}


def check(label, got, want):
    ok = got == want
    RESULTS["PASS" if ok else "FAIL"] += 1
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


def main():
    check("Recall@5 and an MRR cutoff of 20", (r.TOP_K, r.CUTOFF), (5, 20))

    # scoring (ADR 0004, decision 5)
    check("first rank is 1-based", r.first_rank(["a", "b", "c"], ["b"]), 2)
    check("first rank takes the earliest of several answers", r.first_rank(["a", "b", "c"], ["c", "a"]), 1)
    check("no expected record, no rank", r.first_rank(["a", "b"], ["z"]), None)
    ranks = [1, 3, 6, None]
    check("Recall@5 counts ranks 1 to 5 only", r.recall_at(ranks), 0.5)
    check("MRR averages 1/rank, absent counts 0", r.mrr(ranks), (1 + 1 / 3 + 1 / 6) / 4)
    check("MRR ignores ranks below the cutoff", r.mrr([21, 1]), 0.5)
    check("no questions, no score", (r.recall_at([]), r.mrr([])), (0.0, 0.0))

    # fusion (ADR 0004, decision 3)
    check("a record high in both lists comes first", r.rrf(["a", "b", "c"], ["b", "a", "d"])[:2], ["a", "b"])
    check("a record in only one list still appears", set(r.rrf(["a"], ["b"])), {"a", "b"})
    check("ties are broken by record id", r.rrf(["b"], ["a"]), ["a", "b"])
    check("one list fused alone keeps its order", r.rrf(["c", "a", "b"]), ["c", "a", "b"])

    # loading, evaluating and reporting, with a fake search instead of an index
    with tempfile.TemporaryDirectory() as tmp:
        qfile = Path(tmp) / "q.yaml"
        qfile.write_text("questions:\n"
                         "  - id: q1\n    question: A?\n    answers: [r1]\n"
                         "  - id: q2\n    question: B | C?\n    answers: [r9]\n"
                         "  - id: q3\n    question: Unanswerable?\n    answers: []\n")
        qs = r.load_questions(qfile)
    check("questions load from YAML", [q["id"] for q in qs], ["q1", "q2", "q3"])
    fake = {"A?": ["r2", "r1"], "B | C?": ["r3"]}
    rows = r.evaluate(qs, lambda text: fake[text])
    check("unanswerable questions are not scored", [qid for qid, _, _ in rows], ["q1", "q2"])
    check("each question gets the rank of its first expected record", [rank for _, _, rank in rows], [2, None])
    meta = {"date": "2026-11-17", "index": "index=0.1", "chunks": 149067, "questions": "q.yaml"}
    text = r.report("BM25", rows, meta)
    check("the report states both scores",
          ("- Recall@5: 0.50" in text, "- MRR (cutoff 20): 0.25" in text), (True, True))
    check("the report lists every scored question", text.count("\n| q"), 2)
    check("a pipe in a question cannot break the table", "| q2 B / C? | not in the top 20 |" in text, True)
    check("the chunk count is shown with separators", "149,067 chunks" in text, True)
    check("BM25 search keeps at most CUTOFF records", "LIMIT 20" in r.BM25_SQL, True)

    # vector search and fusion, with fake three-dimensional vectors in DuckDB (no model, no index)
    check("vector search keeps at most CUTOFF records", "LIMIT 20" in r.vector_sql(384), True)
    check("vector search fixes the vector size", "FLOAT[384]" in r.vector_sql(384), True)
    check("fused search keeps at most CUTOFF records", len(r.fuse([f"a{i}" for i in range(30)], [f"b{i}" for i in range(30)])), 20)
    check("fused search puts a record high in both lists first", r.fuse(["x", "y"], ["y", "z"])[0], "y")
    import duckdb

    with tempfile.TemporaryDirectory() as tmp:
        con = duckdb.connect()
        con.execute("COPY (SELECT * FROM (VALUES ('c1', 'r1', 'x'), ('c2', 'r1', 'y'), ('c3', 'r2', 'z'), ('c4', 'r3', 'w')) "
                    f"t(chunk_id, record_id, searched)) TO '{tmp}/chunks.parquet' (FORMAT parquet)")
        con.execute("COPY (SELECT chunk_id, embedding::FLOAT[] AS embedding FROM (VALUES ('c1', [1.0, 0.0, 0.0]), "
                    "('c2', [0.0, 1.0, 0.0]), ('c3', [0.6, 0.8, 0.0]), ('c4', [0.0, 0.0, 1.0])) t(chunk_id, embedding)) "
                    f"TO '{tmp}/emb.parquet' (FORMAT parquet)")
        check("every chunk vector is loaded with its record", r.build_vectors(con, f"{tmp}/chunks.parquet", f"{tmp}/emb.parquet", 3), 4)
        check("records are ranked by their best chunk, not their total",
              r.search_vector(con, [0.6, 0.8, 0.0], 3), ["r2", "r1", "r3"])
        check("vector ties are broken by record id", r.search_vector(con, [0.0, 0.0, 1.0], 3), ["r3", "r1", "r2"])

    # the side-by-side report for several methods, reusing the rows scored above
    text = r.compare({"BM25": rows, "vector": [("q1", "A?", 1), ("q2", "B | C?", 3)]},
                     dict(meta, embeddings="fake, 3 dimensions"))
    check("the comparison scores every method",
          ("| BM25 | 0.50 | 0.25 |" in text, "| vector | 1.00 | 0.67 |" in text), (True, True))
    check("the comparison names the embeddings", "- Embeddings: fake, 3 dimensions" in text, True)
    check("each question's ranks sit side by side", "| q1 A? | 2 | 1 |" in text, True)
    check("a missing rank shows as a dash", "| q2 B / C? | - | 3 |" in text, True)

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
