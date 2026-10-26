"""Offline checks for pmg_ingest.bronze. No network, no object storage.

Run: python ingest/tests/test_bronze.py   (prints PASS/FAIL lines, exits 1 on any FAIL)
"""

import datetime as dt
import io
import json
import sys
import tempfile
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pmg_ingest import bronze as b

RESULTS = {"PASS": 0, "FAIL": 0}


def check(label, got, want):
    ok = got == want
    RESULTS["PASS" if ok else "FAIL"] += 1
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


def raises(exc_type, fn):
    try:
        fn()
    except exc_type:
        return True
    except Exception as e:  # noqa: BLE001 -- a wrong exception type is a FAIL line, not a crash
        return f"raised {type(e).__name__}: {e}"
    return False


class FakeResp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(body)
        self.status = status


def opener_from(script):
    """script: list of (status, body_bytes) or Exception, consumed in order."""
    calls = []

    def opener(req, timeout):
        calls.append(req)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, None)
        return FakeResp(status, body)

    return opener, calls


def page(ids, count, nxt):
    return {"count": count, "next": nxt, "results": [{"id": i} for i in ids]}


def fake_fetch(pages):
    """fetch for backfill: returns pages in order regardless of URL; records URLs."""
    urls = []

    def fetch(url):
        urls.append(url)
        p = pages.pop(0)
        return json.dumps(p).encode(), p

    return fetch, urls


NOW = dt.datetime(2026, 10, 26, 9, 30, tzinfo=dt.UTC)


def main():
    # user_agent
    check("user_agent includes contact", b.user_agent("me@example.org"), "pmg-assist-ingest/0.1 (+me@example.org)")
    check("user_agent rejects missing contact", raises(ValueError, lambda: b.user_agent(None)), True)
    check("user_agent rejects blank contact", raises(ValueError, lambda: b.user_agent("  ")), True)

    # list_url
    check("list_url without year", b.list_url("committee-question", 3),
          "https://api.pmg.org.za/committee-question/?page=3")
    check("list_url with year encodes filter", b.list_url("committee-question", 0, 2024),
          "https://api.pmg.org.za/committee-question/?page=0&filter%5Byear%5D=2024")

    # classify / backoff
    check("classify 200", b.classify(200), "ok")
    check("classify 404", b.classify(404), "abort")
    check("classify 429", b.classify(429), "retry")
    check("classify 503", b.classify(503), "retry")
    check("classify no response", b.classify(None), "retry")
    check("backoff grows", [b.backoff_s(i) for i in range(3)], [2.0, 4.0, 8.0])
    check("backoff capped", b.backoff_s(20), 120.0)

    # year_range
    check("year_range span", b.year_range("2024-2026"), [2024, 2025, 2026])
    check("year_range single", b.year_range("2024"), [2024])
    check("year_range reversed raises", raises(ValueError, lambda: b.year_range("2026-2024")), True)

    # check_partitioning
    check("partitioning clean", b.check_partitioning(10, {2025: 4, 2026: 6}),
          {"total": 10, "partitioned": 10, "unpartitioned": 0})
    check("partitioning short is reported", b.check_partitioning(10, {2026: 7})["unpartitioned"], 3)
    check("partitioning filter ignored aborts",
          raises(b.Abort, lambda: b.check_partitioning(10, {2025: 10, 2026: 10})), True)

    # fetch_stamp
    check("fetch_stamp UTC", b.fetch_stamp(NOW), "20261026T093000Z")
    check("fetch_stamp rejects naive", raises(ValueError, lambda: b.fetch_stamp(dt.datetime(2026, 1, 1))), True)

    # plan
    check("plan: past complete skipped, current always",
          b.plan([2024, 2025, 2026], 2026, {2024: True, 2025: False, 2026: True}, False), [2025, 2026])
    check("plan: force takes all", b.plan([2024, 2026], 2026, {2024: True, 2026: True}, True), [2024, 2026])

    # check_page
    check("check_page accepts valid", b.check_page(page([1], 1, None), "u")["count"], 1)
    check("check_page rejects missing next",
          raises(b.Abort, lambda: b.check_page({"count": 1, "results": []}, "u")), True)
    check("check_page rejects non-int count",
          raises(b.Abort, lambda: b.check_page({"count": "1", "results": [], "next": None}, "u")), True)

    # make_fetch: retry then succeed, sends User-Agent
    good = json.dumps(page([1], 1, None)).encode()
    sleeps = []
    opener, calls = opener_from([(503, b""), (200, good)])
    fetch = b.make_fetch("UA/1", opener=opener, sleep=sleeps.append)
    _raw, data = fetch("https://x/")
    check("fetch retries 503 then returns page", data["count"], 1)
    check("fetch slept once with backoff", sleeps, [2.0])
    check("fetch sends User-Agent", calls[0].get_header("User-agent"), "UA/1")

    opener, _ = opener_from([(404, b"")])
    fetch = b.make_fetch("UA/1", opener=opener, sleep=lambda s: None)
    check("fetch aborts on 404", raises(b.Abort, lambda: fetch("https://x/")), True)

    opener, _ = opener_from([(503, b"")] * 3)
    fetch = b.make_fetch("UA/1", opener=opener, sleep=lambda s: None, attempts=3)
    check("fetch gives up after attempts", raises(b.Abort, lambda: fetch("https://x/")), True)

    opener, _ = opener_from([urllib.error.URLError("down"), (200, good)])
    fetch = b.make_fetch("UA/1", opener=opener, sleep=lambda s: None)
    check("fetch retries a connection error", fetch("https://x/")[1]["count"], 1)

    opener, _ = opener_from([(200, b"<html>")])
    fetch = b.make_fetch("UA/1", opener=opener, sleep=lambda s: None)
    check("fetch aborts on non-JSON body", raises(b.Abort, lambda: fetch("https://x/")), True)

    # backfill_partition
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fetch, urls = fake_fetch([page([5, 4], 5, "n1"), page([3, 2], 5, "n2"), page([1], 5, None)])
        m = b.backfill_partition(fetch, root, "committee-question", 2026, NOW, 0, sleep=lambda s: None)
        fdir = root / "committee-question" / "year=2026" / "fetched=20261026T093000Z"
        check("backfill complete when ids == count", m["complete"], True)
        check("backfill counts pages", m["pages"], 3)
        check("backfill writes one file per page",
              sorted(p.name for p in fdir.glob("page=*.json")),
              ["page=00000.json", "page=00001.json", "page=00002.json"])
        check("backfill page file is the raw body", json.loads((fdir / "page=00001.json").read_text())["results"][0]["id"], 3)
        check("backfill requests carry the year filter", all("filter%5Byear%5D=2026" in u for u in urls), True)
        check("marker readable", b.read_marker(fdir)["unique_ids"], 5)
        check("latest_complete finds it", b.latest_complete(root, "committee-question", 2026)["api_count"], 5)
        check("no tmp files left", list(fdir.glob("*.tmp")), [])

        fetch, _ = fake_fetch([page([1], 1, None)])
        check("backfill refuses to overwrite an existing fetch",
              raises(b.Abort, lambda: b.backfill_partition(fetch, root, "committee-question", 2026, NOW, 0,
                                                            sleep=lambda s: None)), True)

        # page shift: a duplicate id across pages means a record was missed
        later = NOW + dt.timedelta(hours=1)
        fetch, _ = fake_fetch([page([5, 4], 5, "n"), page([4, 3], 5, "n"), page([2], 5, None)])
        m = b.backfill_partition(fetch, root, "committee-question", 2025, later, 0, sleep=lambda s: None)
        check("backfill incomplete when ids != count", m["complete"], False)
        check("incomplete fetch is not 'latest complete'", b.latest_complete(root, "committee-question", 2025), None)

        # next never null
        endless = [page([i], 2, "n") for i in range(20)]
        fetch, _ = fake_fetch(endless)
        check("backfill aborts when paging never ends",
              raises(b.Abort, lambda: b.backfill_partition(fetch, root, "committee-question", 2024, later, 0,
                                                            sleep=lambda s: None)), True)
        check("aborted fetch leaves no marker",
              b.latest_complete(root, "committee-question", 2024), None)

    print(f"\n{RESULTS['PASS']} PASS, {RESULTS['FAIL']} FAIL")
    return 1 if RESULTS["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
