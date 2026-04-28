#!/usr/bin/env python3
"""
Scrape APP Regjistri i Parashikimeve (procurement forecast registry).
Page 1: GET. Further pages: POST the next-page form (fa-angle-right).
Keeps rows where Viti == target year (default 2026).

For DB-backed incremental ingestion see ingest_registry.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

from registry_hash import compute_source_hash
from registry_parse import (
    BASE,
    COLUMNS,
    URL,
    find_next_form,
    next_page_payload,
    parse_page_info,
    parse_page_rows,
)

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


def run_scrape(
    out_csv: str,
    checkpoint_path: str,
    qc_path: str,
    delay_min: float,
    delay_max: float,
    max_pages: int | None,
    target_year: str,
) -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    all_rows: list[dict[str, str]] = []
    html = ""
    resume_from_post = False

    if os.path.isfile(checkpoint_path):
        with open(checkpoint_path, encoding="utf-8") as f:
            ck = json.load(f)
        if ck.get("rows"):
            all_rows = list(ck["rows"])
        if ck.get("next_token") and ck.get("next_ufprt"):
            html = "pending"
            resume_from_post = True

    if resume_from_post and html == "pending":
        with open(checkpoint_path, encoding="utf-8") as f:
            ck = json.load(f)
        r0 = session.post(
            URL,
            data={
                "__RequestVerificationToken": ck["next_token"],
                "ufprt": ck["next_ufprt"],
            },
            headers={**HEADERS, "Referer": URL},
            timeout=90,
        )
        r0.raise_for_status()
        html = r0.text
    else:
        r0 = session.get(URL, timeout=90)
        r0.raise_for_status()
        html = r0.text

    ptotal: int | None = None
    pages_visited = 0

    while True:
        pages_visited += 1
        if max_pages and pages_visited > max_pages:
            break

        pnum, ptotal = parse_page_info(html)
        if pnum is None:
            pnum = pages_visited

        rows = parse_page_rows(html, pnum)
        for row in rows:
            if (row.get("viti") or "").strip() == target_year:
                all_rows.append(row)

        soup = BeautifulSoup(html, "html.parser")
        next_form = find_next_form(soup)
        pnum, ptotal = parse_page_info(html) or (pnum, ptotal)
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            ck_out: dict[str, Any] = {
                "page": pnum,
                "total_reported": ptotal,
                "rows": all_rows,
            }
            if next_form:
                try:
                    payload = next_page_payload(next_form)
                    ck_out["next_token"] = payload["__RequestVerificationToken"]
                    ck_out["next_ufprt"] = payload["ufprt"]
                except ValueError as exc:
                    print(
                        f"[warn] checkpoint skipped pagination tokens: {exc}",
                        file=sys.stderr,
                    )
            json.dump(ck_out, f, ensure_ascii=False)

        with open(out_csv, "w", encoding="utf-8-sig", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=COLUMNS)
            w.writeheader()
            for rec in all_rows:
                w.writerow({k: rec.get(k, "") for k in COLUMNS})

        if not next_form:
            break
        if pnum is not None and ptotal is not None and pnum >= ptotal:
            break

        time.sleep(random.uniform(delay_min, delay_max))
        for attempt in range(5):
            try:
                r = post_next(session, next_form)
                r.raise_for_status()
                html = r.text
                _, ptotal = parse_page_info(html) or (None, ptotal)
                break
            except ValueError as exc:
                raise RuntimeError(f"pagination_form_error: {exc}") from exc
            except requests.RequestException:
                if attempt == 4:
                    raise
                time.sleep(2**attempt)
        else:
            break

    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    dupes = 0
    for row in all_rows:
        fp = compute_source_hash(row)
        if fp in seen:
            dupes += 1
            continue
        seen.add(fp)
        deduped.append(row)

    missing_obj = sum(
        1 for r in deduped if not (r.get("objekti_procedurave") or "").strip()
    )
    qc = {
        "row_count_deduped": len(deduped),
        "row_count_raw": len(all_rows),
        "duplicate_fingerprints": dupes,
        "rows_missing_object": missing_obj,
        "target_year": target_year,
        "last_page_number": pnum,
        "total_pages_reported": ptotal,
        "pages_visited": pages_visited,
    }
    with open(qc_path, "w", encoding="utf-8") as f:
        json.dump(qc, f, ensure_ascii=False, indent=2)

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        for rec in deduped:
            w.writerow({k: rec.get(k, "") for k in COLUMNS})

    print(json.dumps(qc, indent=2), file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="registry_2026.csv")
    ap.add_argument("--checkpoint", default="scrape_checkpoint.json")
    ap.add_argument("--qc", default="registry_2026_qc.json")
    ap.add_argument("--delay-min", type=float, default=0.35)
    ap.add_argument("--delay-max", type=float, default=0.9)
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--year", default="2026")
    args = ap.parse_args()
    run_scrape(
        args.out,
        args.checkpoint,
        args.qc,
        args.delay_min,
        args.delay_max,
        args.max_pages,
        args.year,
    )


if __name__ == "__main__":
    main()
