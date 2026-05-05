#!/usr/bin/env python3
from __future__ import annotations

import unittest

from ingest_registry import (
    latest_recorded_publication_datetime,
    parse_publication_time,
    row_in_datetime_window,
    row_publication_datetime,
)
from registry_store import connect, init_schema, upsert_tenders


class IngestRegistryWindowTests(unittest.TestCase):
    def test_parse_publication_time_accepts_common_formats(self) -> None:
        self.assertEqual(parse_publication_time("09:45"), (9, 45))
        self.assertEqual(parse_publication_time("Ora 7:05"), (7, 5))
        self.assertEqual(parse_publication_time("14.30"), (14, 30))

    def test_parse_publication_time_rejects_invalid_values(self) -> None:
        self.assertIsNone(parse_publication_time(""))
        self.assertIsNone(parse_publication_time("no-time"))
        self.assertIsNone(parse_publication_time("25:01"))

    def test_row_publication_datetime_falls_back_to_midnight(self) -> None:
        row = {"data_iso": "2026-05-05", "data_publikimit": "", "ora_publikimit": ""}
        dt = row_publication_datetime(row)
        assert dt is not None
        self.assertEqual(dt.isoformat(timespec="minutes"), "2026-05-05T00:00")

    def test_row_in_datetime_window_is_inclusive(self) -> None:
        row = {
            "data_iso": "2026-05-05",
            "data_publikimit": "",
            "ora_publikimit": "09:30",
        }
        lower = row_publication_datetime(row)
        assert lower is not None
        upper = lower
        self.assertTrue(row_in_datetime_window(row, lower=lower, upper=upper))

    def test_latest_recorded_publication_datetime_uses_db_latest(self) -> None:
        conn = connect(":memory:")
        init_schema(conn)
        rows = [
            {
                "objekti_procedurave": "A",
                "autoriteti_kontraktues": "AK",
                "burimi_financimit": "",
                "fondi_limit_raw": "",
                "fondi_limit_lek": "",
                "data_publikimit": "05-05-2026",
                "ora_publikimit": "08:30",
                "data_iso": "2026-05-05",
                "viti": "2026",
                "koha_zhvillimit": "",
                "kodi_cpv_raw": "",
                "cpv_spans": "",
                "tipi_procedures": "",
                "anulluar": "",
                "page_fetched": "1",
                "row_index_on_page": "0",
            },
            {
                "objekti_procedurave": "B",
                "autoriteti_kontraktues": "AK",
                "burimi_financimit": "",
                "fondi_limit_raw": "",
                "fondi_limit_lek": "",
                "data_publikimit": "05-05-2026",
                "ora_publikimit": "10:15",
                "data_iso": "2026-05-05",
                "viti": "2026",
                "koha_zhvillimit": "",
                "kodi_cpv_raw": "",
                "cpv_spans": "",
                "tipi_procedures": "",
                "anulluar": "",
                "page_fetched": "1",
                "row_index_on_page": "1",
            },
        ]
        upsert_tenders(conn, rows)
        latest = latest_recorded_publication_datetime(conn, "2026")
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.isoformat(timespec="minutes"), "2026-05-05T10:15")
        conn.close()


if __name__ == "__main__":
    unittest.main()
