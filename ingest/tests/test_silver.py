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

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
