#!/usr/bin/env python3
"""
Ingest APP procurement registry into SQLite: bootstrap (full year) or daily (today + yesterday).
Parser (registry_parse) and persistence (registry_store) are separate modules.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from registry_parse import (
    BASE,
    URL,
    find_next_form,
    next_page_payload,
    parse_date_al,
    parse_page_info,
    parse_page_rows,
)
from registry_store import RunSummary, db_session, finish_run, start_run, upsert_tenders

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sq,en;q=0.9",
}


def post_next(session: requests.Session, form: Any) -> requests.Response:
    if form is None:
        raise ValueError("pagination form not found")
    act = form.get("action") or "/regjistri-i-parashikimeve/"
    if not act.startswith("http"):
        act = BASE + act
    data = next_page_payload(form)
    return session.post(
        act,
        data=data,
        headers={**HEADERS, "Referer": URL},
        timeout=90,
    )


def post_next_with_retries(
    session: requests.Session,
    form: Any,
    summary: RunSummary,
    max_attempts: int = 5,
) -> requests.Response | None:
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            r = post_next(session, form)
            r.raise_for_status()
            return r
        except ValueError as e:
            summary.status = "error"
            summary.error_message = f"pagination_form_error: {e}"
            raise RuntimeError(summary.error_message) from e
        except requests.RequestException as e:
            last_exc = e
            summary.failures_retries += 1
            if attempt == max_attempts - 1:
                break
            time.sleep(2**attempt)
    if last_exc:
        raise last_exc
    return None


def row_publication_date(row: dict[str, str]) -> date | None:
    iso = (row.get("data_iso") or "").strip()
    if iso:
        try:
            return date.fromisoformat(iso)
        except ValueError:
            pass
    raw = (row.get("data_publikimit") or "").strip()
    if not raw:
        return None
    _, diso = parse_date_al(raw)
    if not diso:
        return None
    try:
        return date.fromisoformat(diso)
    except ValueError:
        return None


def row_in_daily_window(row: dict[str, str], d0: date, d1: date) -> bool:
    pd = row_publication_date(row)
    if pd is None:
        return False
    return pd == d0 or pd == d1


def filter_bootstrap(row: dict[str, str], target_year: str) -> bool:
    return (row.get("viti") or "").strip() == target_year


def filter_daily(row: dict[str, str], target_year: str, today: date, yesterday: date) -> bool:
    if not filter_bootstrap(row, target_year):
        return False
    return row_in_daily_window(row, today, yesterday)


def run_ingest(
    db_path: str,
    mode: str,
    target_year: str,
    delay_min: float,
    delay_max: float,
    max_pages: int | None,
    stale_pages_without_hits: int,
    today: date | None = None,
    tz_name: str = "Europe/Tirane",
) -> RunSummary:
    if today is None:
        try:
            today = datetime.now(ZoneInfo(tz_name)).date()
        except Exception:
            today = date.today()
    yesterday = today - timedelta(days=1)

    summary = RunSummary(mode=mode, target_year=target_year)
    summary.extra["publication_window"] = {
        "timezone": tz_name,
        "today": today.isoformat(),
        "yesterday": yesterday.isoformat(),
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    r0 = session.get(URL, timeout=90)
    r0.raise_for_status()
    html = r0.text

    pages_visited = 0
    consecutive_empty_daily = 0
    row_filter: Callable[[dict[str, str]], bool]

    if mode == "bootstrap":
        row_filter = lambda r: filter_bootstrap(r, target_year)
    elif mode == "daily":
        row_filter = lambda r: filter_daily(r, target_year, today, yesterday)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    with db_session(db_path) as conn:
        run_id = start_run(conn, mode, target_year)
        try:
            while True:
                if max_pages and pages_visited >= max_pages:
                    summary.extra["stopped_reason"] = "max_pages"
                    break
                pages_visited += 1
                summary.pages_visited = pages_visited

                pnum, ptotal = parse_page_info(html)
                if pnum is None:
                    pnum = pages_visited

                page_rows = parse_page_rows(html, pnum)
                matched = [r for r in page_rows if row_filter(r)]
                summary.rows_parsed += len(page_rows)

                if matched:
                    st = upsert_tenders(conn, matched)
                    summary.rows_inserted += st.rows_inserted
                    summary.duplicates_skipped += st.duplicates_skipped

                if mode == "daily":
                    if not matched:
                        consecutive_empty_daily += 1
                        if consecutive_empty_daily >= stale_pages_without_hits:
                            summary.extra["stopped_reason"] = (
                                f"no_daily_window_rows_for_{stale_pages_without_hits}_consecutive_pages"
                            )
                            break
                    else:
                        consecutive_empty_daily = 0

                soup = BeautifulSoup(html, "html.parser")
                next_form = find_next_form(soup)
                pnum, ptotal = parse_page_info(html) or (pnum, ptotal)

                if not next_form:
                    summary.extra["stopped_reason"] = "no_next_page"
                    break
                if pnum is not None and ptotal is not None and pnum >= ptotal:
                    summary.extra["stopped_reason"] = "last_page"
                    break

                time.sleep(random.uniform(delay_min, delay_max))
                r = post_next_with_retries(session, next_form, summary)
                if r is None:
                    summary.status = "error"
                    summary.error_message = "pagination_failed"
                    break
                html = r.text

            finish_run(conn, run_id, summary)
        except Exception as e:
            summary.status = "error"
            summary.error_message = str(e)
            finish_run(conn, run_id, summary)
            raise

    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest procurement registry into SQLite.")
    ap.add_argument(
        "--mode",
        choices=("bootstrap", "daily"),
        help="bootstrap: all rows for --year; daily: today + yesterday only",
    )
    ap.add_argument("--db", default="registry.db", help="SQLite database path")
    ap.add_argument("--year", default="2026", help="Target viti filter")
    ap.add_argument("--delay-min", type=float, default=0.35)
    ap.add_argument("--delay-max", type=float, default=0.9)
    ap.add_argument("--max-pages", type=int, default=None, help="Stop after N pages (testing)")
    ap.add_argument(
        "--stale-pages",
        type=int,
        default=3,
        help="Daily mode: stop after this many consecutive pages with no today/yesterday rows",
    )
    ap.add_argument(
        "--tz",
        default="Europe/Tirane",
        help="IANA timezone for daily mode 'today' / 'yesterday' (default: Europe/Tirane)",
    )
    ap.add_argument(
        "--export-csv",
        metavar="PATH",
        help="After ingest, export all tenders from DB to CSV (UTF-8 BOM)",
    )
    ap.add_argument(
        "--export-only",
        metavar="PATH",
        help="Only export DB to CSV at PATH; do not scrape (implies no --mode)",
    )
    ap.add_argument(
        "--export-include-hash",
        action="store_true",
        help="With --export-csv / --export-only, append source_hash column",
    )
    args = ap.parse_args()

    if args.export_only:
        from registry_store import connect, export_tenders_csv, init_schema

        conn = connect(args.db)
        init_schema(conn)
        n = export_tenders_csv(
            conn, args.export_only, include_source_hash=args.export_include_hash
        )
        conn.close()
        print(json.dumps({"export_csv_rows": n, "path": args.export_only}, indent=2))
        return

    if not args.mode:
        ap.error("--mode is required unless --export-only is set")

    try:
        summary = run_ingest(
            db_path=args.db,
            mode=args.mode,
            target_year=args.year,
            delay_min=args.delay_min,
            delay_max=args.delay_max,
            max_pages=args.max_pages,
            stale_pages_without_hits=args.stale_pages,
            tz_name=args.tz,
        )
    except Exception as e:
        err_summary = RunSummary(
            mode=args.mode,
            target_year=args.year,
            status="error",
            error_message=str(e),
        )
        print(json.dumps(err_summary.as_dict(), indent=2, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from e

    print(json.dumps(summary.as_dict(), indent=2, ensure_ascii=False))

    if summary.status != "ok":
        raise SystemExit(1)

    if args.export_csv:
        from registry_store import connect, export_tenders_csv, init_schema

        conn = connect(args.db)
        init_schema(conn)
        n = export_tenders_csv(
            conn, args.export_csv, include_source_hash=args.export_include_hash
        )
        conn.close()
        summary.extra["export_csv_path"] = args.export_csv
        summary.extra["export_csv_rows"] = n
        print(json.dumps({"export_csv_rows": n, "path": args.export_csv}, indent=2))


if __name__ == "__main__":
    main()
