#!/usr/bin/env python3
"""SQLite persistence for procurement registry tenders and scrape runs."""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from registry_hash import compute_source_hash
from registry_parse import COLUMNS

SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class UpsertStats:
    rows_inserted: int = 0
    duplicates_skipped: int = 0  # existing source_hash; last_seen_at refreshed


@dataclass
class RunSummary:
    pages_visited: int = 0
    rows_parsed: int = 0
    rows_inserted: int = 0
    duplicates_skipped: int = 0
    failures_retries: int = 0
    mode: str = ""
    target_year: str = ""
    status: str = "ok"
    error_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out = {
            "pages_visited": self.pages_visited,
            "rows_parsed": self.rows_parsed,
            "rows_inserted": self.rows_inserted,
            "duplicates_skipped": self.duplicates_skipped,
            "failures_retries": self.failures_retries,
            "mode": self.mode,
            "target_year": self.target_year,
            "status": self.status,
        }
        if self.error_message:
            out["error_message"] = self.error_message
        out.update(self.extra)
        return out


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS schema_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scrape_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          mode TEXT NOT NULL,
          status TEXT NOT NULL,
          target_year TEXT,
          pages_visited INTEGER NOT NULL DEFAULT 0,
          rows_parsed INTEGER NOT NULL DEFAULT 0,
          rows_inserted INTEGER NOT NULL DEFAULT 0,
          duplicates_skipped INTEGER NOT NULL DEFAULT 0,
          failures_retries INTEGER NOT NULL DEFAULT 0,
          error_message TEXT,
          summary_json TEXT
        );

        CREATE TABLE IF NOT EXISTS tenders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_hash TEXT NOT NULL,
          objekti_procedurave TEXT,
          autoriteti_kontraktues TEXT,
          burimi_financimit TEXT,
          fondi_limit_raw TEXT,
          fondi_limit_lek TEXT,
          data_publikimit TEXT,
          ora_publikimit TEXT,
          data_iso TEXT,
          viti TEXT,
          koha_zhvillimit TEXT,
          kodi_cpv_raw TEXT,
          cpv_spans TEXT,
          tipi_procedures TEXT,
          anulluar TEXT,
          page_fetched TEXT,
          row_index_on_page TEXT,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          UNIQUE (source_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_tenders_data_iso ON tenders (data_iso);
        CREATE INDEX IF NOT EXISTS idx_tenders_viti ON tenders (viti);
        """
    )
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'version'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
    conn.commit()


@contextmanager
def db_session(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        init_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def start_run(
    conn: sqlite3.Connection,
    mode: str,
    target_year: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO scrape_runs (
          started_at, mode, status, target_year
        ) VALUES (?, ?, 'running', ?)
        """,
        (utc_now_iso(), mode, target_year),
    )
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    summary: RunSummary,
) -> None:
    summary_json = json.dumps(summary.as_dict(), ensure_ascii=False)
    conn.execute(
        """
        UPDATE scrape_runs SET
          finished_at = ?,
          status = ?,
          pages_visited = ?,
          rows_parsed = ?,
          rows_inserted = ?,
          duplicates_skipped = ?,
          failures_retries = ?,
          error_message = ?,
          summary_json = ?
        WHERE id = ?
        """,
        (
            utc_now_iso(),
            summary.status,
            summary.pages_visited,
            summary.rows_parsed,
            summary.rows_inserted,
            summary.duplicates_skipped,
            summary.failures_retries,
            summary.error_message,
            summary_json,
            run_id,
        ),
    )


def _row_values(row: dict[str, str], source_hash: str, seen_at: str) -> tuple[Any, ...]:
    return (
        source_hash,
        *(row.get(c, "") or "" for c in COLUMNS),
        seen_at,
        seen_at,
    )


def upsert_tenders(
    conn: sqlite3.Connection,
    rows: list[dict[str, str]],
) -> UpsertStats:
    stats = UpsertStats()
    now = utc_now_iso()
    ph = ", ".join(["?"] * (1 + len(COLUMNS) + 2))
    insert_sql = f"""
        INSERT INTO tenders (
          source_hash, {", ".join(COLUMNS)},
          first_seen_at, last_seen_at
        ) VALUES ({ph})
    """
    for row in rows:
        h = compute_source_hash(row)
        exists = conn.execute(
            "SELECT 1 FROM tenders WHERE source_hash = ? LIMIT 1",
            (h,),
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE tenders SET last_seen_at = ? WHERE source_hash = ?",
                (now, h),
            )
            stats.duplicates_skipped += 1
        else:
            conn.execute(insert_sql, _row_values(row, h, now))
            stats.rows_inserted += 1
    return stats


def export_tenders_csv(
    conn: sqlite3.Connection,
    out_path: str | Path,
    *,
    include_source_hash: bool = False,
) -> int:
    """Write tenders ordered by data_iso, id. Default: canonical COLUMNS only (CSV pipeline shape)."""
    out_path = Path(out_path)
    cols = list(COLUMNS)
    if include_source_hash:
        cols = cols + ["source_hash"]
    select_sql = f"SELECT {', '.join(cols)} FROM tenders ORDER BY data_iso, id"
    cur = conn.execute(select_sql)
    n = 0
    with out_path.open("w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        for r in cur:
            w.writerow({k: r[k] for k in cols})
            n += 1
    return n


def iter_tenders_dicts(conn: sqlite3.Connection) -> Iterator[dict[str, str]]:
    """Yield each tender as a string dict in canonical column order (DB pipeline shape)."""
    select_sql = f"SELECT {', '.join(COLUMNS)} FROM tenders ORDER BY data_iso, id"
    for r in conn.execute(select_sql):
        yield {k: (r[k] if r[k] is not None else "") for k in COLUMNS}
