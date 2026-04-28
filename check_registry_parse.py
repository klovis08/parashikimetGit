#!/usr/bin/env python3
"""Regression checks: parse_fondi locales and default CSV export header shape."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from registry_parse import COLUMNS, parse_fondi
from registry_store import connect, export_tenders_csv, init_schema


def _check_parse_fondi() -> None:
    cases: list[tuple[str, str]] = [
        ("600,000.00 Lekë", "600000.00"),
        ("1.000.000,00 Lekë", "1000000.00"),
        ("600,000.00 Lek", "600000.00"),
        ("1.000.000,00 Lek", "1000000.00"),
        ("350,000.00 Lekë", "350000.00"),
        ("600,00 Lekë", "600.00"),
        ("1.000.000 Lekë", "1000000.00"),
        ("600.50 Lekë", "600.50"),
        ("", ""),
    ]
    for raw_in, want_lek in cases:
        raw_out, lek = parse_fondi(raw_in)
        if not raw_in:
            assert raw_out == "" and lek == "", f"empty: got {(raw_out, lek)}"
            continue
        assert raw_out == raw_in.strip(), f"raw preserved: {raw_in!r} -> {raw_out!r}"
        assert lek == want_lek, f"fondi {raw_in!r}: want {want_lek!r}, got {lek!r}"


def _check_export_header_default() -> None:
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute(
        """
        INSERT INTO tenders (
          source_hash, objekti_procedurave, first_seen_at, last_seen_at
        ) VALUES ('x', 'y', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
        """
    )
    conn.commit()
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".csv", delete=False, encoding="utf-8-sig", newline=""
    ) as tmp:
        path = Path(tmp.name)
    try:
        export_tenders_csv(conn, path, include_source_hash=False)
        with path.open("r", encoding="utf-8-sig", newline="") as fp:
            r = csv.reader(fp)
            header = next(r)
        assert header == list(COLUMNS), (
            f"export header mismatch:\n  got {header}\n  want {list(COLUMNS)}"
        )

        export_tenders_csv(conn, path, include_source_hash=True)
        with path.open("r", encoding="utf-8-sig", newline="") as fp:
            r = csv.reader(fp)
            header_h = next(r)
        assert header_h == list(COLUMNS) + ["source_hash"], header_h
    finally:
        conn.close()
        path.unlink(missing_ok=True)


def main() -> None:
    _check_parse_fondi()
    _check_export_header_default()
    print("check_registry_parse: OK")


if __name__ == "__main__":
    main()
