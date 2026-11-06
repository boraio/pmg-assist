"""Bronze backfill: raw PMG API responses, written unchanged to disk.

Layout, one immutable directory per fetch of a year:

    <root>/<type>/year=<YYYY>/fetched=<YYYYMMDDTHHMMSSZ>/part=<all|YYYY-MM-DD>.json
    <root>/<type>/year=<YYYY>/fetched=<...>/_marker.json

Why no paging. PMG orders committee questions by `date desc` alone and pages
with LIMIT/OFFSET (pmg/api/v1.py `paginate_request_query`). Questions that
share a date have no stable order between requests, so paging through a year
served some records twice and others never: the 0.1 backfill fetched 41,119
rows holding only 39,299 distinct ids. So every request here fits on one page:

- the v2 endpoint allows per_page up to 500 (verified live 2026-10-26);
- a year with <= 500 records is fetched in one request (`part=all`);
- a bigger year is fetched one calendar day at a time with `filter[date]`
  (verified live; the busiest day seen had 165 records). A day that does not
  fit on one page aborts the year rather than paging.

Why a marker: a year counts as done only when the records fetched contain no
duplicate ids and their number equals the API's count for that year, read
again after the fetch. For the current year a question added mid-run makes
the fetch incomplete, and the next run fetches the year again into a new
`fetched=` directory. Nothing is overwritten or deleted. Silver reads the
newest complete fetch of each year.

Stdlib only. Network calls need PMG_INGEST_CONTACT (an email or URL), which
goes into the User-Agent so PMG can see who is calling and reach the operator.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.pmg.org.za"
VERSION = "0.2"

# 0.2: the v2 endpoint, never paged (see the module docstring).
SOURCES = {"committee-question": "/v2/minister-questions/"}
PER_PAGE = 500  # v2's maximum (pmg-cms-2 config RESULTS_PER_PAGE_V2)

# Marker versions written in the current layout. latest_complete trusts no other:
# a 0.1 marker can say complete while its files are page=*.json, which 0.2 never reads.
LAYOUT_VERSIONS = {"0.2"}


class Abort(Exception):
    """A failure that retrying will not fix."""


# ---------------------------------------------------------------- pure pieces


def user_agent(contact: str | None) -> str:
    if not contact or not contact.strip():
        raise ValueError("PMG_INGEST_CONTACT must be set to an email or URL")
    return f"pmg-assist-ingest/{VERSION} (+{contact.strip()})"




def classify(status: int | None) -> str:
    """'ok', 'retry' or 'abort'. None means no HTTP response at all."""
    if status is None:
        return "retry"
    if 200 <= status < 300:
        return "ok"
    if status == 429 or status >= 500:
        return "retry"
    return "abort"


def backoff_s(attempt: int, base: float = 2.0, cap: float = 120.0) -> float:
    return min(cap, base * 2**attempt)


def check_page(data: object, url: str) -> dict:
    if not isinstance(data, dict):
        raise Abort(f"{url}: response is not a JSON object")
    if not isinstance(data.get("results"), list):
        raise Abort(f"{url}: no 'results' list")
    if not isinstance(data.get("count"), int):
        raise Abort(f"{url}: no integer 'count'")
    if "next" not in data:
        raise Abort(f"{url}: no 'next' field")
    return data


def year_range(spec: str) -> list[int]:
    """'2009-2026' or '2024'."""
    lo, _, hi = spec.partition("-")
    first, last = int(lo), int(hi or lo)
    if first > last:
        raise ValueError(f"empty year range: {spec}")
    return list(range(first, last + 1))


def check_partitioning(total: int, per_year: dict[int, int]) -> dict:
    """Does the year filter split the collection cleanly?

    sum > total means the filter was ignored or years overlap: abort, because
    every partition would hold everything. sum < total means some records fall
    outside the probed years or have no year; reported, not fatal.
    """
    s = sum(per_year.values())
    if s > total:
        raise Abort(
            f"year partitions sum to {s} but the collection has {total}: "
            "the year filter is not being honoured"
        )
    return {"total": total, "partitioned": s, "unpartitioned": total - s}


def fetch_stamp(now: dt.datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def partition_dir(root: Path, ctype: str, year: int) -> Path:
    return Path(root) / ctype / f"year={year}"




def latest_complete_dir(root: Path, ctype: str, year: int) -> Path | None:
    """The newest fetch directory of a year whose marker is complete and in a trusted layout."""
    pdir = partition_dir(root, ctype, year)
    if not pdir.is_dir():
        return None
    for fdir in sorted(pdir.glob("fetched=*"), reverse=True):
        m = read_marker(fdir)
        if m and m.get("complete") and m.get("ingest_version") in LAYOUT_VERSIONS:
            return fdir
    return None


def latest_complete(root: Path, ctype: str, year: int) -> dict | None:
    fdir = latest_complete_dir(root, ctype, year)
    return read_marker(fdir) if fdir else None


def plan(years: list[int], current_year: int, complete: dict[int, bool], force: bool) -> list[int]:
    """Which year partitions to fetch.

    The current year is always fetched, because records are still being added.
    A past year is fetched if it has no complete fetch, or if force is set.
    """
    todo = []
    for y in years:
        # Explicit branches, no merged boolean: ghpulse's plan() hid a
        # precedence bug in exactly the `A or B and C` shape ruff suggests.
        if force:  # noqa: SIM114
            todo.append(y)
        elif y >= current_year:  # noqa: SIM114
            todo.append(y)
        elif not complete.get(y, False):
            todo.append(y)
    return todo


def v2_url(ctype: str, *, year: int | None = None, date: dt.date | None = None,
           per_page: int = PER_PAGE) -> str:
    """A v2 list URL. Never carries a page parameter: nothing in 0.2 pages."""
    if year is not None and date is not None:
        raise ValueError("filter by year or by date, not both")
    query: dict[str, object] = {"per_page": per_page}
    if year is not None:
        query["filter[year]"] = year
    if date is not None:
        query["filter[date]"] = date.isoformat()
    return f"{API}{SOURCES[ctype]}?{urllib.parse.urlencode(query)}"


def days_in(year: int, until: dt.date) -> list[dt.date]:
    """Every calendar day of `year`, stopping at `until` (inclusive)."""
    first = dt.date(year, 1, 1)
    last = min(dt.date(year, 12, 31), until)
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


def mode_for(count: int) -> str:
    return "all" if count <= PER_PAGE else "day"


def requests_for(year: int, count: int, today: dt.date) -> int:
    """Requests a year costs: the fetch itself plus the closing count check."""
    units = 1 if mode_for(count) == "all" else len(days_in(year, today))
    return units + 1


def part_path(fetch_dir: Path, unit: dt.date | None) -> Path:
    return Path(fetch_dir) / f"part={unit.isoformat() if unit else 'all'}.json"


def count_of(fetch, ctype: str, **filters) -> int:
    """The API's count for a filter, fetching a single record to learn it."""
    _, page = fetch(v2_url(ctype, per_page=1, **filters))
    return page["count"]


def backfill_year(fetch, root: Path, ctype: str, year: int, count_before: int,
                  now: dt.datetime, delay: float, sleep=time.sleep) -> dict:
    fdir = partition_dir(root, ctype, year) / f"fetched={fetch_stamp(now)}"
    if fdir.exists():
        raise Abort(f"{fdir} already exists; refusing to overwrite a fetch")
    mode = mode_for(count_before)
    units: list[dt.date | None] = [None] if mode == "all" else days_in(year, now.date())

    ids: set = set()
    records = files = 0
    for unit in units:
        url = v2_url(ctype, year=year) if unit is None else v2_url(ctype, date=unit)
        raw, data = fetch(url)
        if data["next"] is not None:
            raise Abort(f"{ctype} {unit or year}: {data['count']} records do not fit on one "
                        f"page of {PER_PAGE}; this needs a finer partition, not paging")
        if data["results"]:
            write_atomic(part_path(fdir, unit), raw)
            files += 1
        for r in data["results"]:
            records += 1
            ids.add(r.get("id"))
        sleep(delay)

    count_after = count_of(fetch, ctype, year=year)
    marker = {
        "type": ctype,
        "year": year,
        "mode": mode,
        "fetched_at": now.astimezone(dt.UTC).isoformat(),
        "requests": len(units),
        "files": files,
        "api_count_before": count_before,
        "api_count_after": count_after,
        "records": records,
        "unique_ids": len(ids),
        "complete": records == len(ids) == count_after,
        "ingest_version": VERSION,
    }
    # Written after the data, so a crash leaves an incomplete fetch, never a false "complete".
    write_atomic(fdir / "_marker.json", json.dumps(marker, indent=2).encode())
    return marker

# ---------------------------------------------------------- side effects


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def read_marker(fetch_dir: Path) -> dict | None:
    p = Path(fetch_dir) / "_marker.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text())


def make_fetch(ua: str, opener=urllib.request.urlopen, sleep=time.sleep, attempts: int = 5):
    """Return fetch(url) -> (raw_bytes, parsed_page), with retries and backoff."""

    def fetch(url: str) -> tuple[bytes, dict]:
        last = None
        for attempt in range(attempts):
            req = urllib.request.Request(
                url, headers={"User-Agent": ua, "Accept": "application/json"}
            )
            status, body, retry_after = None, b"", None
            try:
                with opener(req, timeout=60) as resp:
                    status, body = resp.status, resp.read()
            except urllib.error.HTTPError as e:
                status, retry_after = e.code, e.headers.get("Retry-After") if e.headers else None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            kind = classify(status)
            if kind == "ok":
                try:
                    data = json.loads(body)
                except json.JSONDecodeError as e:
                    raise Abort(f"{url}: body is not JSON ({e})") from e
                return body, check_page(data, url)
            if kind == "abort":
                raise Abort(f"{url}: HTTP {status}")
            wait = backoff_s(attempt)
            if retry_after and retry_after.isdigit():
                wait = max(wait, float(retry_after))
            last = last or f"HTTP {status}"
            sleep(wait)
        raise Abort(f"{url}: gave up after {attempts} attempts ({last})")

    return fetch


def probe_counts(fetch, ctype: str, years: list[int], delay: float, sleep=time.sleep) -> tuple[int, dict[int, int]]:
    total = count_of(fetch, ctype)
    per_year = {}
    for y in years:
        sleep(delay)
        n = count_of(fetch, ctype, year=y)
        if n:
            per_year[y] = n
    return total, per_year




# ------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--type", default="committee-question", choices=sorted(SOURCES))
    ap.add_argument("--root", default="data/bronze", type=Path)
    ap.add_argument("--years", default=f"2000-{dt.date.today().year}")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--status", action="store_true", help="probe API counts and local state; write nothing")
    ap.add_argument("--dry-run", action="store_true", help="show the plan; write nothing")
    ap.add_argument("--force", action="store_true", help="refetch past years that are already complete")
    args = ap.parse_args(argv)

    years = year_range(args.years)
    now = dt.datetime.now(dt.UTC)
    fetch = make_fetch(user_agent(os.environ.get("PMG_INGEST_CONTACT")))

    total, per_year = probe_counts(fetch, args.type, years, args.delay)
    split = check_partitioning(total, per_year)
    complete = {y: latest_complete(args.root, args.type, y) is not None for y in per_year}

    print(f"{args.type}: total={split['total']} in-years={split['partitioned']} "
          f"outside-years={split['unpartitioned']}")
    for y in sorted(per_year):
        m = latest_complete(args.root, args.type, y)
        local = f"complete ({m['unique_ids']} @ {m['fetched_at']})" if m else "missing"
        print(f"  {y}: api={per_year[y]:>6}  mode={mode_for(per_year[y]):<3}  local={local}")
    if args.status:
        return 0

    todo = plan(sorted(per_year), now.year, complete, args.force)
    n = sum(requests_for(y, per_year[y], now.date()) for y in todo)
    print(f"plan: {len(todo)} years, ~{n} requests, ~{n * args.delay / 60:.0f} min at {args.delay}s "
          "(plus response time)")
    if args.dry_run:
        return 0

    failed = 0
    for y in todo:
        try:
            m = backfill_year(fetch, args.root, args.type, y, per_year[y], now, args.delay)
            flag = "OK  " if m["complete"] else "INCOMPLETE"
            print(f"{flag} {y}: {m['unique_ids']} ids in {m['records']} records, "
                  f"api {m['api_count_before']}->{m['api_count_after']}, "
                  f"{m['files']} files from {m['requests']} requests ({m['mode']})", flush=True)
            failed += not m["complete"]
        except Abort as e:
            print(f"ABORT {y}: {e}", file=sys.stderr, flush=True)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
