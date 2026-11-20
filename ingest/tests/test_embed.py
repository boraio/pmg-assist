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
    check("first model and the measured settings", (e.MODEL, e.THREADS, e.BATCH), ("BAAI/bge-small-en-v1.5", 8, 8))

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
