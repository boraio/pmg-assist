"""Embeddings for gold chunks (ADR 0004, decision 4; embedding spike 2026-11-20).

Reads <index-dir>/chunks.jsonl and writes <index-dir>/emb=<model>.jsonl, one
line per chunk with its embedding. A run that stops part-way resumes where it
left off. PyTorch and sentence-transformers are imported only when a model is
loaded, so the offline checks run without them.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from . import bronze

MODEL = "BAAI/bge-small-en-v1.5"
# The maintainers' retrieval prefix for bge-small: questions get it, chunks do not.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
THREADS = 8  # fastest on nia in the 2026-11-20 benchmark
BATCH = 8


def model_slug(name=MODEL):
    """The part of a model name used in file names: "BAAI/bge-small-en-v1.5" -> "bge-small-en-v1.5"."""
    return name.rsplit("/", 1)[-1]


def resume(partial):
    """Ids already embedded in a partial output, after dropping a half-written last line.

    The file is rewritten with only its complete lines, so appending to it is safe.
    """
    if not partial.exists():
        return set()
    lines = []
    for line in partial.read_text(encoding="utf-8").splitlines():
        try:
            lines.append((json.loads(line)["chunk_id"], line))
        except (json.JSONDecodeError, KeyError):
            break
    partial.write_text("".join(text + "\n" for _, text in lines), encoding="utf-8")
    return {cid for cid, _ in lines}


def embed_all(chunks, encode, out, batch=BATCH, every=500, report=print):
    """Write {"chunk_id", "embedding"} for every chunk to out, resuming a partial run.

    encode(texts) returns one vector per text. Values are rounded to 6 decimals,
    far below what changes a ranking, to keep the file small. Returns how many
    chunks were already done and how many were embedded now.
    """
    partial = out.with_name(out.name + ".partial")
    done = resume(partial)
    todo = [c for c in chunks if c["chunk_id"] not in done]
    with partial.open("a", encoding="utf-8") as f:
        for start in range(0, len(todo), batch):
            group = todo[start:start + batch]
            for c, vec in zip(group, encode([c["searched"] for c in group])):
                f.write(json.dumps({"chunk_id": c["chunk_id"], "embedding": [round(float(x), 6) for x in vec]}) + "\n")
            if (start // batch) % every == every - 1:
                f.flush()
                report(f"{len(done) + start + len(group)} of {len(chunks)} chunks embedded")
    partial.replace(out)
    return len(done), len(todo)


def run(index_dir, encode, info, batch=BATCH):
    """Embed index_dir's chunks with encode and write a marker beside the output.

    info describes the model and settings (model, dimensions, max_seq_length,
    threads, batch); the marker adds counts and the time taken.
    """
    index_dir = Path(index_dir)
    with (index_dir / "chunks.jsonl").open(encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]
    slug = model_slug(info["model"])
    t = time.time()
    before, now = embed_all(chunks, encode, index_dir / f"emb={slug}.jsonl", batch)
    marker = dict(info, query_prefix=QUERY_PREFIX, chunks=len(chunks), embedded_before=before,
                  embedded_now=now, seconds=round(time.time() - t))
    bronze.write_atomic(index_dir / f"_emb={slug}.json", json.dumps(marker, indent=2).encode())
    return marker


def main(argv=None):
    ap = argparse.ArgumentParser(description="Embed gold chunks for vector search (ADR 0004).")
    ap.add_argument("--index-dir", default=Path("data/gold/committee-question/index=0.1"), type=Path)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--threads", default=THREADS, type=int)
    ap.add_argument("--batch", default=BATCH, type=int)
    args = ap.parse_args(argv)
    import torch  # here, not at the top, so the offline checks never need PyTorch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(args.threads)
    model = SentenceTransformer(args.model, device="cpu")
    info = {"model": args.model, "dimensions": model.get_embedding_dimension(),
            "max_seq_length": model.max_seq_length, "threads": args.threads, "batch": args.batch}
    m = run(args.index_dir, lambda texts: model.encode(texts, batch_size=args.batch, normalize_embeddings=True,
                                                        show_progress_bar=False), info, args.batch)
    print(f"embedded {m['embedded_now']} chunks ({m['embedded_before']} already done) "
          f"of {m['chunks']} in {m['seconds']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
