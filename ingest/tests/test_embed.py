"""Offline checks for pmg_ingest.embed. No network and no model: a fake encoder stands in.

Run: python ingest/tests/test_embed.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pmg_ingest import embed as e

RESULTS = {"PASS": 0, "FAIL": 0}


def check(label, got, want):
    ok = got == want
    RESULTS["PASS" if ok else "FAIL"] += 1
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


def main():
    check("first model and the measured settings", (e.MODEL, e.THREADS, e.BATCH, e.GROUP), ("BAAI/bge-small-en-v1.5", 8, 8, 512))

    check("model slug for file names", e.model_slug("BAAI/bge-small-en-v1.5"), "bge-small-en-v1.5")

    # embed_all with a fake encoder: a 2-number vector per text
    chunks = [{"chunk_id": f"r#{i}", "searched": "x" * i} for i in range(1, 6)]
    seen = []

    def fake(texts):
        seen.extend(texts)
        return [[len(t), 0.12345678] for t in texts]

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "emb=test.jsonl"
        notes = []
        got = e.embed_all(chunks, fake, out, batch=2, every=1, report=notes.append)
        lines = [json.loads(x) for x in out.read_text().splitlines()]
        check("every chunk embedded once, in order", [x["chunk_id"] for x in lines], [c["chunk_id"] for c in chunks])
        check("values rounded to 6 decimals", lines[0]["embedding"], [1.0, 0.123457])
        check("counts: nothing done before, 5 now", got, (0, 5))
        check("progress reported per batch when every=1", notes[-1], "5 of 5 chunks embedded")
        check("no partial file left behind", sorted(p.name for p in Path(tmp).iterdir()), ["emb=test.jsonl"])

        # a run that stopped part-way: 2 complete lines and a half-written third
        out2 = Path(tmp) / "emb=resume.jsonl"
        partial = Path(tmp) / "emb=resume.jsonl.partial"
        partial.write_text('{"chunk_id": "r#1", "embedding": [1.0]}\n{"chunk_id": "r#2", "embedding": [2.0]}\n{"chunk_')
        seen.clear()
        got = e.embed_all(chunks, fake, out2, batch=2, report=notes.append)
        ids = [json.loads(x)["chunk_id"] for x in out2.read_text().splitlines()]
        check("a resumed run embeds only what is missing", seen, ["xxx", "xxxx", "xxxxx"])
        check("the half-written line is dropped, nothing doubled", ids, ["r#1", "r#2", "r#3", "r#4", "r#5"])
        check("counts: 2 done before, 3 now", got, (2, 3))

    # run: reads chunks.jsonl, writes the embeddings and a marker beside them
    with tempfile.TemporaryDirectory() as tmp:
        idx = Path(tmp)
        (idx / "chunks.jsonl").write_text("".join(json.dumps(c) + "\n" for c in chunks))
        info = {"model": "BAAI/bge-small-en-v1.5", "dimensions": 2, "max_seq_length": 512, "threads": 8, "batch": 2}
        m = e.run(idx, fake, info, group=2)
        check("output and marker are named after the model",
              sorted(p.name for p in idx.iterdir()),
              ["_emb=bge-small-en-v1.5.json", "chunks.jsonl", "emb=bge-small-en-v1.5.jsonl"])
        check("the marker records model, prefix and counts",
              (m["model"], m["query_prefix"], m["chunks"], m["embedded_before"], m["embedded_now"]),
              ("BAAI/bge-small-en-v1.5", e.QUERY_PREFIX, 5, 0, 5))
        check("marker on disk matches", json.loads((idx / "_emb=bge-small-en-v1.5.json").read_text()), m)

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
