"""Offline checks for pmg_ingest.gold. No network.

Run: python ingest/tests/test_gold.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pmg_ingest import gold as g

RESULTS = {"PASS": 0, "FAIL": 0}


def check(label, got, want):
    ok = got == want
    RESULTS["PASS" if ok else "FAIL"] += 1
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


def main():
    check("index version", g.VERSION, "0.1")

    # pack: in order, never over the limit unless a single unit is
    check("pack joins while it fits", g.pack(["aa", "bb", "cc"], 5), ["aa bb", "cc"])
    check("pack of nothing is nothing", g.pack([], 5), [])
    check("pack leaves an over-long unit whole", g.pack(["toolongunit", "a"], 5), ["toolongunit", "a"])
    check("pack uses the separator given", g.pack(["r1", "r2"], 10, "\n"), ["r1\nr2"])

    # split_long: sentence ends first, then spaces; always rejoins to the original
    short = "One sentence."
    check("short text is one piece", g.split_long(short, 100), [short])
    text = " ".join(["The department spent R5 million in 2024."] * 10)
    pieces = g.split_long(text, 100)
    check("long text is cut at sentence ends", pieces[0], "The department spent R5 million in 2024. "
          "The department spent R5 million in 2024.")
    check("no piece over the limit", max(len(p) for p in pieces) <= 100, True)
    check("pieces rejoin to the original", " ".join(pieces), text)
    words = " ".join(["word"] * 100)
    check("a sentence longer than the limit is cut at spaces",
          (max(len(p) for p in g.split_long(words, 30)) <= 30, " ".join(g.split_long(words, 30)) == words),
          (True, True))
    check("a run with no space stays whole", g.split_long("a" * 50 + " b", 20), ["a" * 50, "b"])
    check("a full stop before lower case is not a sentence end",
          g.SENTENCE_END.split("See p. ten. Then (2) more."), ["See p. ten.", "Then (2) more."])

    # table_chunks: split only between rows, first row repeated and labelled (ADR 0004 decision 1)
    rows = [["Province", "Name", "Amount"]] + [["Limpopo", f"Person {i}", "1 000,00"] for i in range(200)]
    tch = g.table_chunks(rows, 200)
    check("a long table becomes several chunks, none over the limit",
          (len(tch) > 1, max(len(c) for c in tch) <= 200), (True, True))
    check("the first chunk starts with the first row, unlabelled", tch[0].split("\n")[0], "Province | Name | Amount")
    check("later chunks start with the first row, labelled as such",
          {c.split("\n")[0] for c in tch[1:]}, {"First row of the table: Province | Name | Amount"})
    check("every row appears once, whole and in order",
          [line for c in tch for line in c.split("\n") if not line.startswith(g.FIRST_ROW)],
          [g.row_text(r) for r in rows])
    check("a small table is one chunk", g.table_chunks([["A", "B"], ["1", "2"]]), ["A | B\n1 | 2"])
    check("no rows, no chunks", g.table_chunks([]), [])
    check("a row over the limit is split at cells, in a chunk of its own",
          g.table_chunks([["h"], ["a" * 30, "b" * 30], ["c"]], 40), ["h", "a" * 30, "b" * 30, "First row of the table: h\nc"])
    check("a long first row is not repeated",
          g.table_chunks([["x" * 600], ["y"], ["z" * 1000]], 1500), ["x" * 600 + "\ny", "z" * 1000])

    # paragraphs, blocks and whole records (ADR 0004 decisions 1 and 2)
    check("paragraphs pack one per line", g.paragraph_chunks(["One.", "Two."]), ["One.\nTwo."])
    long_para = g.paragraph_chunks(["A b. " * 10 + "End.", "Next."], 20)
    check("a paragraph over the limit is cut at sentence ends, none over the limit",
          max(len(c) for c in long_para) <= 20, True)
    check("the tail of a cut paragraph packs with the next one", long_para[-1], "A b. A b. End.\nNext.")
    para = {"type": "paragraph", "text": "Before.", "rows": None}
    table = {"type": "table", "text": None, "rows": [["A", "B"], ["1", "2"]]}
    after = {"type": "paragraph", "text": "After.", "rows": None}
    check("a table keeps its own chunk between paragraph runs",
          g.blocks_chunks([para, table, after]), ["Before.", "A | B\n1 | 2", "After."])
    check("no blocks, no chunks", g.blocks_chunks([]), [])

    rec = {"record_id": "pmg-committee-question-1", "code": "NW1", "date": "2022-01-11",
           "question_to_name": "Minister of Example", "reply_kind": "in_body",
           "question": [{"type": "paragraph", "text": "How many?", "rows": None}], "reply": [para, table]}
    chunks = g.chunks_for(rec)
    check("question first, then the reply, numbered in order",
          [(c["chunk_id"], c["kind"]) for c in chunks],
          [("pmg-committee-question-1#0", "question"), ("pmg-committee-question-1#1", "reply"),
           ("pmg-committee-question-1#2", "reply")])
    check("searched text is the context line plus the chunk text",
          chunks[0]["searched"], "NW1, 2022-01-11. Question to: Minister of Example.\nHow many?")
    check("the chunk text itself carries no context line", chunks[0]["text"], "How many?")
    check("every chunk carries the index version", {c["index_version"] for c in chunks}, {"0.1"})
    pointer = dict(rec, reply_kind="attachment_pointer")
    check("a pointer reply gives only its question chunk", [c["kind"] for c in g.chunks_for(pointer)], ["question"])
    check("an empty reply gives only its question chunk",
          [c["kind"] for c in g.chunks_for(dict(rec, reply_kind="empty", reply=[]))], ["question"])

    # build: silver records.jsonl in, chunks.jsonl and a marker out (ADR 0004 decision 6)
    with tempfile.TemporaryDirectory() as tmp:
        sroot, groot = Path(tmp) / "silver", Path(tmp) / "gold"
        sdir = sroot / "committee-question" / "version=0.1"
        sdir.mkdir(parents=True)
        recs = [rec, pointer]
        (sdir / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        (sdir / "_marker.json").write_text(json.dumps({"rows": 2}))
        m = g.build(sroot, groot)
        out = groot / "committee-question" / "index=0.1"
        lines = [json.loads(x) for x in (out / "chunks.jsonl").read_text().splitlines()]
        check("chunks for every record, in order", [c["kind"] for c in lines], ["question", "reply", "reply", "question"])
        check("marker counts records, chunks and kinds",
              (m["records"], m["silver_rows"], m["chunks"], m["kinds"], m["over_limit"]),
              (2, 2, 4, {"question": 2, "reply": 2}, 0))
        check("marker on disk matches", json.loads((out / "_marker.json").read_text()), m)
        check("no temporary file left behind", sorted(p.name for p in out.iterdir()), ["_marker.json", "chunks.jsonl"])
        check("a rerun gives the same bytes",
              ((out / "chunks.jsonl").read_bytes(), g.build(sroot, groot))[0], (out / "chunks.jsonl").read_bytes())
        check("main succeeds when every silver record was read",
              g.main(["--silver-root", str(sroot), "--out", str(groot)]), 0)
        (sdir / "_marker.json").write_text(json.dumps({"rows": 3}))
        check("main fails when silver's marker counts other rows",
              g.main(["--silver-root", str(sroot), "--out", str(groot)]), 1)

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
