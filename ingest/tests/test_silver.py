"""Offline checks for pmg_ingest.silver. No network.

Run: python ingest/tests/test_silver.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pmg_ingest import bronze as b
from pmg_ingest import silver as s

RESULTS = {"PASS": 0, "FAIL": 0}


def check(label, got, want):
    ok = got == want
    RESULTS["PASS" if ok else "FAIL"] += 1
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


def main():
    check("silver version", s.VERSION, "0.1")

    # ADR 0003 decision 4: each pointer variant seen in the 2026-11-05 measurement
    for text in ["find reply here", "Find here: Reply", "Attached find here: Reply",
                 "Please find here: Reply", "Annexure Find reply here", "Find here: R eply",
                 "Find here: Response", "Fid reply here", "Fimd reply here", "Find reply h ere",
                 "Find here reply :", "Annexure A Annexure B Find reply here",
                 "Attached please find here: Reply", "The response is available see attachment",
                 "Find reply here Annexure"]:
        check(f"pointer: {text!r}", s.is_pointer(text), True)

    # real replies stay in_body, even when short or mentioning an attachment
    for text in ["No.", "(1-2) No.", "None.",
                 "Please refer to my reply to question 3797 on this matter.",
                 "(1)(2)(3) See Annexure A attached.",
                 "A reply to this parliamentary question has been logdged.",
                 "The information requested by the Honourable Member is not readily available."]:
        check(f"not a pointer: {text!r}", s.is_pointer(text), False)

    # ADR 0003 decision 3: tables stay tables, spans expanded so each row stands alone
    def rows(html_text):
        return [b["rows"] for b in s.blocks(html_text) if b["type"] == "table"]

    check("unclosed cells and rows are repaired",
          rows("<table><tr><td>A<td>B<tr><td>C<td>D</table>"), [[["A", "B"], ["C", "D"]]])
    check("rowspan repeats the value on each row it covers",
          rows('<table><tr><td rowspan="2">Limpopo</td><td>Makhado</td><td>42 000,00</td></tr>'
               '<tr><td>Musina</td><td>38 000,00</td></tr></table>'),
          [[["Limpopo", "Makhado", "42 000,00"], ["Limpopo", "Musina", "38 000,00"]]])
    check("colspan repeats the value across the columns it covers",
          rows('<table><tr><td colspan="2">Total</td><td>9</td></tr><tr><td>a</td><td>b</td><td>c</td></tr></table>'),
          [[["Total", "Total", "9"], ["a", "b", "c"]]])
    check("a rowspan in the last column carries over",
          rows('<table><tr><td>a</td><td rowspan="2">r</td></tr><tr><td>b</td></tr></table>'),
          [[["a", "r"], ["b", "r"]]])
    check("a nested table becomes text in its cell",
          rows("<table><tr><td>outer<table><tr><td>i1</td><td>i2</td></tr><tr><td>i3</td></tr></table></td>"
               "<td>z</td></tr></table>"),
          [[["outer i1 i2 / i3", "z"]]])
    check("unreadable spans count as 1; empty rows are dropped",
          rows('<table><tr><td colspan="x">a</td><td rowspan="0">b</td></tr><tr><td></td><td></td></tr></table>'),
          [[["a", "b"]]])
    check("thead and tbody rows in order, th counted as cells",
          rows("<table><thead><tr><th>Name</th><th>Amount</th></tr></thead>"
               "<tbody><tr><td>X</td><td>1</td></tr></tbody></table>"),
          [[["Name", "Amount"], ["X", "1"]]])

    # ADR 0003 decision 2: parsed, not stripped; images dropped; order kept
    def para(text):
        return {"type": "paragraph", "text": text, "rows": None}

    check("paragraph, table, paragraph in document order",
          s.blocks("<p>Intro<table><tr><td>A<td>B</table><p>After</p>"),
          [para("Intro"), {"type": "table", "text": None, "rows": [["A", "B"]]}, para("After")])
    check("entities decoded, whitespace collapsed, data: images dropped",
          s.blocks("<p>Q &amp; A&nbsp;&nbsp; here<img src='data:image/png;base64,AAAA'></p>"),
          [para("Q & A here")])
    check("<br> and list items split paragraphs; comments dropped",
          s.blocks("one<br>two <!-- note --> more<ul><li>three</li></ul>"),
          [para("one"), para("two more"), para("three")])
    check("head, style and script carry no text",
          s.blocks("<html><head><title>T</title><style>p{}</style></head>"
                   "<body><script>x()</script><p>B</p></body></html>"),
          [para("B")])
    check("empty, blank, None and comment-only input give no blocks",
          [s.blocks(h) for h in ("", "   ", None, "<!-- x -->", "<p></p>")], [[], [], [], [], []])
    check("an XML declaration with an encoding is ignored",
          s.blocks('<?xml version="1.0" encoding="utf-8"?><p>x</p>'), [para("x")])

    # ADR 0003 decisions 1 and 4: one silver row per record
    rec = {"id": 17523, "code": "NW2467", "date": "2022-01-11", "year": 2022, "answer_type": "written",
           "house_id": 3, "minister_id": 7, "question_to_name": "Minister of Agriculture",
           "asked_by_name": "Example Member", "asked_by_member_id": 99,
           "question": "<p>How many farmers?</p>", "answer": "<p>Find reply here</p>",
           "source_file": {"file_path": "x.docx"}, "files": [],
           "url": "http://pmg.org.za/committee-question/17523/"}
    row = s.to_silver(rec, "20261029T090000Z")
    check("record_id is stable and typed", row["record_id"], "pmg-committee-question-17523")
    check("PMG url kept as given", row["url"], "http://pmg.org.za/committee-question/17523/")
    check("question parsed into blocks", row["question"], [para("How many farmers?")])
    check("a pointer reply is classified", row["reply_kind"], "attachment_pointer")
    check("attachments kept as JSON text", (row["source_file"], row["files"]), ('{"file_path": "x.docx"}', "[]"))
    check("bronze fetch and silver version recorded",
          (row["bronze_fetched"], row["silver_version"]), ("20261029T090000Z", "0.1"))
    check("a reply with a table is in_body, even if a cell says find reply here",
          s.reply_kind(s.blocks("<table><tr><td>Find reply here</td></tr></table>")), "in_body")
    check("a blank reply is empty", s.reply_kind(s.blocks("<p>&nbsp;</p>")), "empty")
    check("a short real reply is in_body", s.reply_kind(s.blocks("<p>No.</p>")), "in_body")
    check("a sparse record has the same keys", sorted(s.to_silver({"id": 1}, "x")), sorted(row))

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
