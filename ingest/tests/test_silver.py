"""Offline checks for pmg_ingest.silver. No network.

Run: python ingest/tests/test_silver.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
