"""Offline checks for pmg_eval.generate. No network and no model: a fake generator, fake vectors in DuckDB.

Run: python eval/tests/test_generate.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pmg_eval import generate as g

RESULTS = {"PASS": 0, "FAIL": 0}


def check(label, got, want):
    ok = got == want
    RESULTS["PASS" if ok else "FAIL"] += 1
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


CHUNKS = [
    {"id": "c1", "chunk_id": "r1#0", "record_id": "r1", "header": "NW12, 2024-05-01. Question to: Minister of Water.",
     "text": "The   department has   repaired 42 boreholes in\nLimpopo since April 2024."},
    {"id": "c2", "chunk_id": "r2#3", "record_id": "r2", "header": "NW99, 2025-02-10. Question to: Minister of Police.",
     "text": "According to the reply, Ms Dlamini Zuma visited the station."},
]


def answer(*statements):
    return {"outcome": "answered", "statements": [
        {"text": text, "citations": [{"chunk": c, "quote": q} for c, q in cites]} for text, cites in statements]}


def fake(reply, tokens=7, seconds=1.5):
    calls = []

    def generate(messages):
        calls.append(messages)
        return reply, tokens, seconds
    return generate, calls


def main():
    check("top 5 records, 2 chunks each, a 0.02 margin, two generator reasons",
          (g.TOP_RECORDS, g.CHUNKS_PER_RECORD, g.FLOOR_MARGIN, g.REASONS),
          (5, 2, 0.02, ("insufficient_evidence", "requests_evaluation")))

    # the floor (decision 2, layer 1)
    check("the floor is the lowest answerable top similarity less 0.02", g.floor_from([0.75, 0.688, 0.8]), 0.668)

    # the prompt (decisions 1 and 3)
    msgs = g.build_messages("How many boreholes?", CHUNKS)
    check("two messages: the rules, then the question", [m["role"] for m in msgs], ["system", "user"])
    check("the rules name both refusal reasons",
          ('"insufficient_evidence"' in msgs[0]["content"], '"requests_evaluation"' in msgs[0]["content"]), (True, True))
    check("each excerpt carries its id and header, then its text",
          "[c1] NW12, 2024-05-01. Question to: Minister of Water.\nThe   department" in msgs[1]["content"], True)
    check("the question comes first", msgs[1]["content"].startswith("Question: How many boreholes?\n\nExcerpts:"), True)

    # parsing (decision 3)
    ok = answer(("It repaired 42 boreholes.", [("c1", "repaired 42 boreholes")]))
    check("plain JSON parses strictly", g.parse(json.dumps(ok)), (ok, "strict"))
    check("JSON inside other text is extracted", g.parse("```json\n" + json.dumps(ok) + "\n```")[1], "extracted")
    check("prose does not parse", g.parse("The department repaired 42 boreholes."), (None, "failed"))
    check("a refusal parses", g.parse('{"outcome": "refused", "reason": "requests_evaluation"}')[1], "strict")
    check("an answer with no statements is malformed", g.parse('{"outcome": "answered", "statements": []}')[1], "failed")
    check("a statement with no citation is malformed",
          g.parse('{"outcome": "answered", "statements": [{"text": "x", "citations": []}]}')[1], "failed")
    check("an unknown outcome is malformed", g.parse('{"outcome": "maybe"}')[1], "failed")

    # the server's checks (decision 4)
    kept, drops = g.check(ok, CHUNKS)
    check("a verbatim quote, ignoring whitespace runs, is kept", (len(kept), drops), (1, {}))
    kept, drops = g.check(answer(("x", [("c9", "repaired")])), CHUNKS)
    check("a chunk the generator was not given is dropped", (kept, drops), ([], {"unknown_chunk": 1}))
    kept, drops = g.check(answer(("It fixed 42 boreholes.", [("c1", "fixed 42 boreholes")])), CHUNKS)
    check("a reworded quote is dropped", drops, {"quote_not_verbatim": 1})
    kept, drops = g.check(answer(("x", [("c2", "According to the reply, Ms Dlamini-Zuma")])), CHUNKS)
    check("a quote differing only in punctuation is still not verbatim", drops, {"quote_not_verbatim": 1})
    kept, drops = g.check(answer(("x", [("c1", "")])), CHUNKS)
    check("an empty quote is dropped", drops, {"quote_not_verbatim": 1})
    kept, drops = g.check(answer(("Ms Dlamini Zuma visited the station.", [("c2", "visited the station")])), CHUNKS)
    check("a name found in the cited text is kept", len(kept), 1)
    kept, drops = g.check(answer(("Minister Cele visited the station.", [("c2", "visited the station")])), CHUNKS)
    check("a name not in the cited text is dropped", drops, {"unnamed_in_citation": 1})
    kept, drops = g.check(answer(("Ms Dlamini Zuma visited.", [("c1", "repaired 42 boreholes")])), CHUNKS)
    check("a name found only in another, uncited chunk is dropped", drops, {"unnamed_in_citation": 1})
    kept, drops = g.check(answer(("Water boreholes were repaired.", [("c1", "repaired 42 boreholes")])), CHUNKS)
    check("a name found only in the header is dropped", drops, {"unnamed_in_citation": 1})
    kept, drops = g.check(answer(("In Limpopo, the Department repaired 42 boreholes since April 2024.",
                                  [("c1", "repaired 42 boreholes")])), CHUNKS)
    check("names match ignoring case, past a sentence's first word", len(kept), 1)
    kept, drops = g.check(answer(("Dlamini repaired them.", [("c1", "repaired 42 boreholes")])), CHUNKS)
    check("a name as a sentence's first word is still checked", drops, {"unnamed_in_citation": 1})
    kept, drops = g.check(answer(("Lim repaired them.", [("c1", "repaired 42 boreholes")])), CHUNKS)
    check("names match whole words only", drops, {"unnamed_in_citation": 1})
    two = answer(("It repaired 42 boreholes.", [("c1", "repaired 42 boreholes")]),
                 ("It repaired 50.", [("c1", "repaired 50")]))
    kept, drops = g.check(two, CHUNKS)
    check("failing statements are dropped, the rest kept", (len(kept), drops), (1, {"quote_not_verbatim": 1}))

    # one question through the three layers (decision 2)
    generate, calls = fake(json.dumps(ok))
    x = g.decide(0.60, 0.668, generate, msgs, CHUNKS)
    check("below the floor: refused without calling the generator",
          (x["outcome"], x["reason"], x["layer"], calls), ("refused", "insufficient_evidence", "floor", []))
    x = g.decide(0.70, 0.668, generate, msgs, CHUNKS)
    check("above the floor, checked and kept: answered",
          (x["outcome"], x["layer"], len(x["statements"]), x["tokens"], x["seconds"]), ("answered", "answered", 1, 7, 1.5))
    generate, _ = fake('{"outcome": "refused", "reason": "requests_evaluation"}')
    x = g.decide(0.70, 0.668, generate, msgs, CHUNKS)
    check("the generator's refusal keeps its reason", (x["outcome"], x["reason"], x["layer"]),
          ("refused", "requests_evaluation", "generator"))
    generate, _ = fake(json.dumps(answer(("x", [("c1", "made up")]))))
    x = g.decide(0.70, 0.668, generate, msgs, CHUNKS)
    check("every statement dropped: refused by the checks", (x["outcome"], x["reason"], x["layer"], x["drops"]),
          ("refused", "insufficient_evidence", "checks", {"quote_not_verbatim": 1}))
    generate, _ = fake("I think the answer is 42.")
    x = g.decide(0.70, 0.668, generate, msgs, CHUNKS)
    check("an unparsed reply is a counted refusal", (x["outcome"], x["layer"], x["parse"], x["raw"]),
          ("refused", "unparsed", "failed", "I think the answer is 42."))

    def broken(messages):
        raise TimeoutError("timed out")
    x = g.decide(0.70, 0.668, broken, msgs, CHUNKS)
    check("a failed call is a counted refusal, not a crash", (x["outcome"], x["reason"], x["layer"]),
          ("refused", "insufficient_evidence", "error"))
    check("a failed call keeps its cause", x["raw"], "TimeoutError: timed out")

    # the endpoint call, with urlopen replaced: no network
    sent = {}

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(req, timeout):
        sent.update(url=req.full_url, body=json.loads(req.data), auth=req.get_header("Authorization"))
        return Reply(json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {"completion_tokens": 3}}).encode())

    real = g.urllib.request.urlopen
    g.urllib.request.urlopen = urlopen
    try:
        text, tokens, _ = g.chat("http://gen:8080/v1/", "m", "k", schema=True)(msgs)
        check("the call goes to /chat/completions", sent["url"], "http://gen:8080/v1/chat/completions")
        check("temperature 0, a token cap, and the messages",
              (sent["body"]["temperature"], sent["body"]["max_tokens"], sent["body"]["messages"]), (0, 1024, msgs))
        check("the schema is sent only when asked", sent["body"]["response_format"]["json_schema"]["schema"], g.SCHEMA)
        check("the key goes in a bearer header", sent["auth"], "Bearer k")
        check("the reply text and output tokens come back", (text, tokens), ("{}", 3))
        g.chat("http://gen:8080/v1", "m")(msgs)
        check("no schema and no key unless asked", ("response_format" in sent["body"], sent["auth"]), (False, None))
    finally:
        g.urllib.request.urlopen = real

    # reporting (decision 5)
    check("p95 by nearest rank", (g.p95([1, 2, 3, 4]), g.p95(list(range(1, 21))), g.p95([])), (4, 19, None))
    check("groups from answers and notes",
          [g.group_of(q) for q in ({"answers": ["r1"]}, {"answers": [], "note": "unanswerable"},
                                   {"answers": [], "note": "must refuse (prediction)"})],
          ["answerable", "unanswerable", "refuse"])
    base = {"drops": {}, "statements": [], "tokens": None, "seconds": None, "parse": None, "cites_expected": False}
    s1 = {"text": "It repaired 42 boreholes.", "citations": [{"chunk": "c1", "quote": "repaired 42 boreholes"}]}
    results = [
        dict(base, id="q1", question="Boreholes?", group="answerable", outcome="answered", layer="answered",
             statements=[s1], parse="strict", tokens=10, seconds=2.0, cites_expected=True,
             context={"c1": CHUNKS[0]}),
        dict(base, id="q2", question="Lions?", group="unanswerable", outcome="refused", layer="generator",
             reason="insufficient_evidence", parse="strict", tokens=5, seconds=1.0),
        dict(base, id="q3", question="Vote?", group="refuse", outcome="refused", layer="floor",
             reason="insufficient_evidence"),
        dict(base, id="q4", question="Weather?", group="unanswerable", outcome="answered", layer="answered",
             statements=[s1], parse="extracted", tokens=5, seconds=1.0, drops={"quote_not_verbatim": 2},
             context={"c1": CHUNKS[0]}),
    ]
    meta = {"label": "fake", "date": "2026-11-25", "model": "m", "endpoint": "http://gen/v1", "schema": False,
            "index": "index=0.1", "embeddings": "fake-emb", "floor": 0.668, "questions": "q.yaml"}
    text = g.summary(results, meta)
    check("the summary counts each group", ("| answerable | 1 | 1 | 0 | - |" in text,
                                            "| unanswerable | 2 | 1 | 1 | generator (insufficient_evidence): 1 |" in text,
                                            "| refuse | 1 | 0 | 1 | floor: 1 |" in text), (True, True, True))
    check("the summary counts kept and dropped statements", "- Statements kept: 2; dropped: quote_not_verbatim 2" in text, True)
    check("the summary counts how replies parsed", "- Replies parsed: strict 2, extracted 1, failed 0" in text, True)
    check("the summary gives p95 latency and tokens per second",
          ("- Latency p95: 2.0 s over 3 calls" in text, "prompt time included: 5.0" in text), (True, True))
    check("the summary leaves groundedness to the review", "from the owner's review sheet, not yet counted" in text, True)
    check("the summary holds no record text", ("boreholes" in text.split("| Question |")[0], "Limpopo" in text),
          (False, False))
    sheet = g.review_sheet(results, meta)
    check("the review sheet lists each kept statement with marks to fill in",
          ("### q1 s1\nStatement: It repaired 42 boreholes.\nCites: c1 (repaired 42 boreholes)\nmark: ?\nattribution: ?"
           in sheet), True)
    check("the review sheet shows the full cited text",
          "[c1] r1 | NW12, 2024-05-01. Question to: Minister of Water.\nThe   department has" in sheet, True)
    check("an answered question that should not have been is flagged", "## q4 (unanswerable)  <- ANSWERED, BUT UNANSWERABLE" in sheet, True)
    check("refused questions are not on the sheet", "q2" in sheet, False)

    # the context, with fake three-dimensional vectors in DuckDB
    import duckdb

    with tempfile.TemporaryDirectory() as tmp:
        con = duckdb.connect()
        con.execute("COPY (SELECT * FROM (VALUES ('a#0', 'a', 0, 'a zero', 'hdr a\na zero'), "
                    "('a#1', 'a', 1, 'a one', 'hdr a\na one'), ('a#2', 'a', 2, 'a two', 'hdr a\na two'), "
                    "('b#0', 'b', 0, 'b zero', 'hdr b\nb zero'), ('z#0', 'z', 0, 'z zero', 'hdr z\nz zero')) "
                    f"t(chunk_id, record_id, position, text, searched)) TO '{tmp}/chunks.parquet' (FORMAT parquet)")
        con.execute("COPY (SELECT chunk_id, embedding::FLOAT[] AS embedding FROM (VALUES ('a#0', [0.0, 1.0, 0.0]), "
                    "('a#1', [1.0, 0.0, 0.0]), ('a#2', [0.8, 0.6, 0.0]), ('b#0', [0.0, 0.0, 1.0]), "
                    "('z#0', [1.0, 0.0, 0.0])) t(chunk_id, embedding)) "
                    f"TO '{tmp}/emb.parquet' (FORMAT parquet)")
        g.r.build_vectors(con, f"{tmp}/chunks.parquet", f"{tmp}/emb.parquet", 3)
        g.load_texts(con, f"{tmp}/chunks.parquet")
        got = g.select_chunks(con, [1.0, 0.0, 0.0], 3, ["b", "a"])
        check("records keep their fused order; each record's best chunks, in record order",
              [c["chunk_id"] for c in got], ["b#0", "a#1", "a#2"])
        check("context ids run c1, c2, ...", [c["id"] for c in got], ["c1", "c2", "c3"])
        check("the header is the context line, apart from the text", (got[1]["header"], got[1]["text"]), ("hdr a", "a one"))
        check("records not asked for are left out", any(c["record_id"] == "z" for c in got), False)
        check("one chunk per record when asked", [c["chunk_id"] for c in g.select_chunks(con, [1.0, 0.0, 0.0], 3, ["a"], 1)],
              ["a#1"])

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
