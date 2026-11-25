"""Grounded generation over fused retrieval, checked and measured (ADR 0006).

For each eval question: fused retrieval, the similarity floor, the generator (any OpenAI-compatible chat
endpoint), then the server's checks on every statement. Writes a dated results file of counts for the repo,
and, under the gitignored data/ folder, the raw outputs and a review sheet for the owner, because chunk text
can hold private people's names.
"""

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from . import retrieval as r

TOP_RECORDS = 5  # records whose chunks reach the generator (ADR 0006, decision 1)
CHUNKS_PER_RECORD = 2  # best-matching chunks per record; measured per candidate (ADR 0006, Open)
FLOOR_MARGIN = 0.02  # the floor sits this far below the lowest answerable top similarity (decision 2)
MAX_TOKENS = 1024
REASONS = ("insufficient_evidence", "requests_evaluation")
STOPLIST = frozenset()  # capitalised runs exempt from the name check: start empty, add only on review evidence
# sentence-initial words that are capitalised only because they start a sentence; never names
STARTERS = frozenset([
    "A", "About", "According", "After", "Also", "An", "As", "At", "Before", "Between", "Both", "By", "During",
    "Each", "For", "From", "How", "However", "If", "In", "It", "Its", "Most", "No", "Of", "On", "Only", "Over",
    "Since", "Some", "That", "The", "Their", "There", "These", "This", "Those", "To", "Under", "When", "Where",
    "Which", "While"])

SYSTEM = """You answer questions about South African parliamentary records, using only the numbered excerpts you are given.

Rules:
1. Use only the excerpts. Do not use anything you know from elsewhere.
2. If the excerpts do not answer the question, refuse with reason "insufficient_evidence".
3. If the question asks for a prediction, an opinion, a ranking, a characterisation of a person, party or policy, or advice on how to vote, refuse with reason "requests_evaluation", whatever the excerpts say.
4. Otherwise answer with one or more short statements in plain text, without Markdown.
5. Every statement cites at least one excerpt by its id, with a quote copied exactly, character for character, from that excerpt's text. Never reword a quote. Keep each quote to the words that support the statement.
6. Name a person only if the quoted text contains that name. Say what a record states, not who said it.
7. Each excerpt starts with its record's date. When the answer depends on time, give the date of the record.

Reply with one JSON object and nothing else, in one of these two forms:
{"outcome": "answered", "statements": [{"text": "...", "citations": [{"chunk": "c1", "quote": "..."}]}]}
{"outcome": "refused", "reason": "insufficient_evidence"}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["answered", "refused"]},
        "reason": {"type": "string", "enum": list(REASONS)},
        "statements": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "citations": {"type": "array", "minItems": 1, "items": {
                    "type": "object",
                    "properties": {"chunk": {"type": "string"}, "quote": {"type": "string"}},
                    "required": ["chunk", "quote"], "additionalProperties": False}},
            },
            "required": ["text", "citations"], "additionalProperties": False}},
    },
    "required": ["outcome"], "additionalProperties": False,
}

CHUNKS_SQL = """
SELECT e.chunk_id, e.record_id, t.position, t.text, t.searched,
       array_cosine_similarity(e.embedding, ?::FLOAT[{dims}]) AS sim
FROM emb e JOIN texts t USING (chunk_id) WHERE list_contains(?::VARCHAR[], e.record_id)
"""


def floor_from(top_sims, margin=FLOOR_MARGIN):
    """The similarity floor: the lowest top similarity among answerable questions, less the margin."""
    return round(min(top_sims) - margin, 3)


def load_texts(con, chunks):
    """Load every chunk's text and searched text next to the vectors, for building the generator's context."""
    con.execute("CREATE OR REPLACE TABLE texts AS SELECT chunk_id, position, text, searched "
                f"FROM read_parquet('{chunks}')")


def select_chunks(con, vec, dims, records, per_record=CHUNKS_PER_RECORD):
    """The context: each record's best-matching chunks, records in fused order, chunks in record order.

    Returns a list of dicts with id (c1, c2, ...), chunk_id, record_id, header (the context line: metadata,
    never quote material) and text.
    """
    rows = con.execute(CHUNKS_SQL.format(dims=dims), [vec, list(records)]).fetchall()
    by_record = {}
    for chunk_id, record_id, position, text, searched, sim in rows:
        by_record.setdefault(record_id, []).append((sim, position, chunk_id, text, searched))
    out = []
    for record_id in records:
        best = sorted(by_record.get(record_id, []), key=lambda x: (-x[0], x[1]))[:per_record]
        for _, _, chunk_id, text, searched in sorted(best, key=lambda x: x[1]):
            out.append({"chunk_id": chunk_id, "record_id": record_id, "header": searched.split("\n", 1)[0],
                        "text": text})
    for i, c in enumerate(out, 1):
        c["id"] = f"c{i}"
    return out


def build_messages(question, chunks):
    """The chat messages for one question: the rules, then the question and its numbered excerpts."""
    excerpts = "\n\n".join(f"[{c['id']}] {c['header']}\n{c['text']}" for c in chunks)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Question: {question}\n\nExcerpts:\n\n{excerpts}"}]


def valid(obj):
    """Whether a parsed reply has the shape decision 3 asks for."""
    if not isinstance(obj, dict) or obj.get("outcome") not in ("answered", "refused"):
        return False
    if obj["outcome"] == "refused":
        return isinstance(obj.get("reason"), str)
    statements = obj.get("statements")
    if not isinstance(statements, list) or not statements:
        return False
    for s in statements:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or not s["text"].strip():
            return False
        cites = s.get("citations")
        if not isinstance(cites, list) or not cites:
            return False
        for c in cites:
            if not isinstance(c, dict) or not isinstance(c.get("chunk"), str) or not isinstance(c.get("quote"), str):
                return False
    return True


def parse(text):
    """The reply as (object, how): how is 'strict', 'extracted' (JSON found inside other text) or 'failed'."""
    for how, candidate in (("strict", text.strip()), ("extracted", text[text.find("{"):text.rfind("}") + 1])):
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if valid(obj):
            return obj, how
    return None, "failed"


def normalise(text):
    """Collapse runs of whitespace to one space, and nothing else (decision 4)."""
    return " ".join(text.split())


NAME_RUN = re.compile(r"[A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*)*")
SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)$")


def names(statement):
    """Capitalised runs in a statement, as (run, at_sentence_start) pairs, outside the stoplist."""
    out = []
    for m in NAME_RUN.finditer(statement):
        if m.group(0) not in STOPLIST:
            out.append((m.group(0), bool(SENTENCE_START.search(statement[:m.start()]))))
    return out


def name_found(run, at_start, text):
    """Whether a capitalised run appears in text as whole words, ignoring case.

    A sentence's first word is skipped when it is in STARTERS; everything else must be found.
    """
    words = run.split()
    if at_start and words[0] in STARTERS:
        words = words[1:]
    if not words:
        return True
    pattern = r"\b" + r"\s+".join(re.escape(w.lower()) for w in words) + r"\b"
    return re.search(pattern, normalise(text).lower()) is not None


def check(answer, chunks):
    """Apply decision 4 to a parsed answer: (kept statements, {drop reason: count})."""
    given = {c["id"]: c for c in chunks}
    kept, drops = [], {}
    for s in answer["statements"]:
        cites = s["citations"]
        if any(c["chunk"] not in given for c in cites):
            why = "unknown_chunk"
        elif any(not normalise(c["quote"]) or normalise(c["quote"]) not in normalise(given[c["chunk"]]["text"])
                 for c in cites):
            why = "quote_not_verbatim"
        else:
            cited = "\n".join(given[c["chunk"]]["text"] for c in cites)
            why = None if all(name_found(run, start, cited) for run, start in names(s["text"])) else "unnamed_in_citation"
        if why:
            drops[why] = drops.get(why, 0) + 1
        else:
            kept.append(s)
    return kept, drops


def decide(top_sim, floor, generate, messages, chunks):
    """One question through layers 1-3 of decision 2. generate(messages) -> (reply text, output tokens, seconds).

    Returns the outcome, the refusal reason, which layer decided (floor, generator, checks, unparsed, error or
    answered), the parse result, kept statements, drops, the raw reply, output tokens and seconds. A failed
    call (an HTTP error, a timeout) is a counted refusal, so one bad call cannot end a run.
    """
    out = {"outcome": "refused", "reason": "insufficient_evidence", "layer": "floor", "parse": None,
           "statements": [], "drops": {}, "raw": None, "tokens": None, "seconds": None}
    if top_sim < floor:
        return out
    try:
        raw, tokens, seconds = generate(messages)
    except (OSError, ValueError, KeyError, IndexError) as e:  # HTTP errors, timeouts, a reply without choices
        detail = e.read().decode("utf-8", "replace")[:300] if hasattr(e, "read") else ""
        out.update(layer="error", raw=f"{type(e).__name__}: {e} {detail}".strip())
        return out
    out.update(raw=raw, tokens=tokens, seconds=seconds)
    answer, how = parse(raw)
    out["parse"] = how
    if answer is None:
        out["layer"] = "unparsed"
    elif answer["outcome"] == "refused":
        out.update(reason=answer["reason"], layer="generator")
    else:
        kept, drops = check(answer, chunks)
        out.update(statements=kept, drops=drops)
        if kept:
            out.update(outcome="answered", reason=None, layer="answered")
        else:
            out["layer"] = "checks"
    return out


def chat(endpoint, model, api_key=None, schema=False, timeout=600):
    """A generate() for an OpenAI-compatible endpoint (base URL ending in /v1), at temperature 0."""
    def generate(messages):
        body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": MAX_TOKENS}
        if schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "answer", "schema": SCHEMA}}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions",
                                     data=json.dumps(body).encode(), headers=headers)
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        return (data["choices"][0]["message"]["content"] or "", (data.get("usage") or {}).get("completion_tokens"),
                time.monotonic() - start)
    return generate


def p95(values):
    """The 95th percentile by the nearest-rank method; None for no values."""
    values = sorted(values)
    return values[math.ceil(0.95 * len(values)) - 1] if values else None


def group_of(q):
    """answerable, unanswerable or refuse, from the eval set's answers and note."""
    if q["answers"]:
        return "answerable"
    return "refuse" if "must refuse" in (q.get("note") or "") else "unanswerable"


def summary(results, meta):
    """The committed results file: counts only, no record text (decision 5)."""
    groups = {g: [x for x in results if x["group"] == g] for g in ("answerable", "unanswerable", "refuse")}
    ans = groups["answerable"]
    answered = [x for x in ans if x["outcome"] == "answered"]
    timed = [x["seconds"] for x in results if x["seconds"] is not None]
    tokens = sum(x["tokens"] or 0 for x in results)
    drops = {}
    for x in results:
        for k, v in x["drops"].items():
            drops[k] = drops.get(k, 0) + v
    kept = sum(len(x["statements"]) for x in results)
    lines = [f"# Generation evaluation: {meta['label']}, {meta['date']}", "",
             f"- Generator: {meta['model']} at {meta['endpoint']}, JSON schema sent: {meta['schema']}",
             (f"- Retrieval: {meta['index']}, {meta['embeddings']}; top {TOP_RECORDS} fused records, "
              f"{CHUNKS_PER_RECORD} chunks each"),
             f"- Similarity floor: {meta['floor']} (lowest answerable top similarity less {FLOOR_MARGIN})",
             (f"- Questions: {len(ans)} answerable, {len(groups['unanswerable'])} unanswerable, "
              f"{len(groups['refuse'])} must refuse, from {meta['questions']}"), "",
             "| Group | Questions | Answered | Refused | Refused by |", "|---|---|---|---|---|"]
    for g, xs in groups.items():
        by = {}
        for x in xs:
            if x["outcome"] == "refused":
                key = f"{x['layer']} ({x['reason']})" if x["layer"] == "generator" else x["layer"]
                by[key] = by.get(key, 0) + 1
        lines.append(f"| {g} | {len(xs)} | {sum(x['outcome'] == 'answered' for x in xs)} | "
                     f"{sum(x['outcome'] == 'refused' for x in xs)} | "
                     + (", ".join(f"{k}: {v}" for k, v in sorted(by.items())) or "-") + " |")
    lines += ["",
              (f"- Answerable questions answered with a citation to an expected record: "
               f"{sum(x['cites_expected'] for x in answered)} of {len(answered)}"),
              f"- Statements kept: {kept}; dropped: "
              + (", ".join(f"{k} {v}" for k, v in sorted(drops.items())) or "none"),
              "- Replies parsed: " + ", ".join(f"{h} {sum(x['parse'] == h for x in results)}"
                                               for h in ("strict", "extracted", "failed")),
              f"- Latency p95: {p95(timed):.1f} s over {len(timed)} calls" if timed else "- Latency p95: no calls",
              f"- Output tokens per second, prompt time included: {tokens / sum(timed):.1f}" if timed and tokens
              else "- Output tokens per second: not reported by the endpoint",
              "- Groundedness and attribution errors: from the owner's review sheet, not yet counted", "",
              "| Question | Group | Outcome | Layer | Kept | Dropped | Cites expected | Seconds |",
              "|---|---|---|---|---|---|---|---|"]
    for x in results:
        lines.append(f"| {x['id']} | {x['group']} | {x['outcome']} | {x['layer']} | {len(x['statements'])} | "
                     f"{sum(x['drops'].values())} | {'yes' if x['cites_expected'] else '-'} | "
                     + (f"{x['seconds']:.1f}" if x["seconds"] is not None else "-") + " |")
    return "\n".join(lines) + "\n"


def review_sheet(results, meta):
    """The owner's sheet (decision 5): each kept statement with marks to fill in, and the full cited text."""
    lines = [f"# Review: {meta['label']}, {meta['date']}", "",
             "For each statement, replace each ? : mark is supported, partly or not (by its citations alone);",
             "attribution is no, or what the statement gives a person that the cited text does not.",
             "Do not commit this file: the cited text can contain private people's names.", ""]
    for x in results:
        if x["outcome"] != "answered":
            continue
        flag = "" if x["group"] == "answerable" else f"  <- ANSWERED, BUT {x['group'].upper()}"
        lines += [f"## {x['id']} ({x['group']}){flag}", "", f"Question: {x['question']}", ""]
        cited = {}
        for i, s in enumerate(x["statements"], 1):
            lines += [f"### {x['id']} s{i}", f"Statement: {s['text']}",
                      "Cites: " + ", ".join(f"{c['chunk']} ({c['quote']})" for c in s["citations"]),
                      "mark: ?", "attribution: ?", ""]
            for c in s["citations"]:
                cited[c["chunk"]] = x["context"][c["chunk"]]
        for cid, c in sorted(cited.items(), key=lambda kv: int(kv[0][1:])):
            lines += [f"[{cid}] {c['record_id']} | {c['header']}", c["text"], ""]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate grounded generation over gold chunks (ADR 0006).")
    ap.add_argument("--endpoint", required=True, help="OpenAI-compatible base URL, ending in /v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True, help="short name for this candidate, used in file names")
    ap.add_argument("--api-key-env", help="name of the environment variable holding the API key, if any")
    ap.add_argument("--schema", action="store_true", help="ask the endpoint to enforce the JSON schema")
    ap.add_argument("--index-dir", default=r.INDEX_DIR, type=Path)
    ap.add_argument("--questions", default=r.QUESTIONS, type=Path)
    ap.add_argument("--vectors", default="bge-small-en-v1.5", metavar="SLUG")
    ap.add_argument("--only", help="comma-separated question ids, for a short trial run")
    ap.add_argument("--dry-run", action="store_true",
                    help="report prompt sizes and write the first question's messages under --private; call nothing")
    ap.add_argument("--out", default=Path("docs/eval/results"), type=Path)
    ap.add_argument("--private", default=Path("data/review"), type=Path,
                    help="raw replies and the review sheet; data/ is gitignored, like the records they quote")
    args = ap.parse_args(argv)
    # here, not at the top: the offline checks need neither DuckDB nor a model,
    # and only the embedding venv has sentence-transformers
    import duckdb
    from sentence_transformers import SentenceTransformer

    con = duckdb.connect(str(args.index_dir / "search.duckdb"))
    chunk_count = r.build_bm25(con, args.index_dir / "chunks.parquet")
    info = json.loads((args.index_dir / f"_emb={args.vectors}.json").read_text())
    dims = info["dimensions"]
    vcon = duckdb.connect()
    n = r.build_vectors(vcon, args.index_dir / "chunks.parquet", args.index_dir / f"emb={args.vectors}.parquet", dims)
    if n != chunk_count:
        return f"{n:,} vectors for {chunk_count:,} chunks: embed this index again, or rebuild its Parquet"
    load_texts(vcon, args.index_dir / "chunks.parquet")
    model = SentenceTransformer(info["model"], device="cpu")

    questions = r.load_questions(args.questions)
    prepared = []
    for q in questions:
        vec = model.encode(info["query_prefix"] + q["question"], normalize_embeddings=True).tolist()
        vrows = vcon.execute(r.vector_sql(dims), [vec]).fetchall()
        fused = r.fuse(r.search_bm25(con, q["question"]), [row[0] for row in vrows])
        chunks = select_chunks(vcon, vec, dims, fused[:TOP_RECORDS])
        prepared.append((q, vrows[0][1] if vrows else 0.0, chunks))
    floor = floor_from([sim for q, sim, _ in prepared if group_of(q) == "answerable"])
    if args.only:
        wanted = set(args.only.split(","))
        prepared = [p for p in prepared if p[0]["id"] in wanted]
    if args.dry_run:
        sizes = []
        for q, sim, chunks in prepared:
            size = sum(len(m["content"]) for m in build_messages(q["question"], chunks))
            sizes.append(size)
            print(f"{q['id']}: top similarity {sim:.3f}{' (below the floor)' if sim < floor else ''}, "
                  f"{len(chunks)} chunks, {size:,} characters")
        args.private.mkdir(parents=True, exist_ok=True)
        first = prepared[0]
        path = args.private / f"dry-run-{first[0]['id']}.txt"
        messages = build_messages(first[0]["question"], first[2])
        path.write_text("\n\n".join(f"--- {m['role']}\n{m['content']}" for m in messages), encoding="utf-8")
        print(f"floor {floor}; prompt size max {max(sizes):,} characters, median {sorted(sizes)[len(sizes) // 2]:,};"
              f" {first[0]['id']}'s messages written to {path} (not for pasting: it holds record text)")
        return 0

    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not api_key:
        return f"{args.api_key_env} is not set"
    generate = chat(args.endpoint, args.model, api_key, args.schema)
    results = []
    for q, sim, chunks in prepared:
        x = decide(sim, floor, generate, build_messages(q["question"], chunks), chunks)
        cited = {c["chunk"] for s in x["statements"] for c in s["citations"]}
        context = {c["id"]: c for c in chunks}
        x.update(id=q["id"], question=q["question"], group=group_of(q), top_sim=round(sim, 3), context=context,
                 cites_expected=any(context[c]["record_id"] in q["answers"] for c in cited))
        results.append(x)
        print(f"{x['id']} {x['group']:<12} {x['outcome']:<8} {x['layer']:<9} kept {len(x['statements'])} "
              f"dropped {sum(x['drops'].values())}" + (f" {x['seconds']:.1f}s" if x["seconds"] else ""), flush=True)

    meta = {"label": args.label, "date": dt.date.today().isoformat(), "model": args.model,
            "endpoint": args.endpoint, "schema": args.schema, "index": args.index_dir.name,
            "embeddings": info["model"], "floor": floor, "questions": args.questions}
    stem = f"{meta['date']}-{meta['index']}-gen-{args.label}"
    args.private.mkdir(parents=True, exist_ok=True)
    with open(args.private / f"{stem}.jsonl", "w", encoding="utf-8") as f:
        for x in results:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    (args.private / f"{stem}-review.md").write_text(review_sheet(results, meta), encoding="utf-8")
    text = summary(results, meta)
    out = args.out / f"{stem}.md"
    if not args.only:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    print(text + (f"written to {out}" if not args.only else "trial run: results file not written")
          + f"\nraw replies and review sheet in {args.private}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
