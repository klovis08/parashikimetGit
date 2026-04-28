import csv
import tempfile
import unittest
from pathlib import Path

from export_registry import export_all
from registry_store import connect, init_schema, upsert_tenders


class ExportRegistryTests(unittest.TestCase):
    def test_export_all_uses_requested_year_in_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "registry.db"
            out_dir = root / "out"

            conn = connect(db_path)
            init_schema(conn)
            upsert_tenders(
                conn,
                [
                    {
                        "objekti_procedurave": "Zhvillim software per platforme",
                        "autoriteti_kontraktues": "AK Test",
                        "burimi_financimit": "Buxheti",
                        "fondi_limit_raw": "100 Lek",
                        "fondi_limit_lek": "100.00",
                        "data_publikimit": "01-01-2031",
                        "ora_publikimit": "",
                        "data_iso": "2031-01-01",
                        "viti": "2031",
                        "koha_zhvillimit": "",
                        "kodi_cpv_raw": "72000000-5",
                        "cpv_spans": "",
                        "tipi_procedures": "",
                        "anulluar": "",
                        "page_fetched": "1",
                        "row_index_on_page": "1",
                    }
                ],
            )
            conn.commit()
            conn.close()

            summary = export_all(db_path, out_dir, "2031")
            paths = summary["paths"]

            self.assertTrue(paths["canonical"].endswith("registry_2031.csv"))
            self.assertTrue(paths["software_broad"].endswith("registry_2031_software_broad.csv"))
            self.assertTrue(paths["software_strict"].endswith("registry_2031_software.csv"))
            self.assertTrue(paths["software_near_miss"].endswith("registry_2031_software_near_miss.csv"))
            self.assertTrue(paths["software_review_queue"].endswith("registry_2031_software_review_queue.csv"))
            self.assertEqual(summary["full"], 1)
            self.assertIn("near_miss_rows", summary)

            with open(paths["canonical"], encoding="utf-8-sig", newline="") as fp:
                rows = list(csv.DictReader(fp))
            self.assertEqual(len(rows), 1)
            with open(paths["software_broad"], encoding="utf-8-sig", newline="") as fp:
                broad_rows = list(csv.DictReader(fp))
            self.assertEqual(len(broad_rows), 1)
            self.assertIn("software_confidence", broad_rows[0])
            self.assertIn("software_top_signals", broad_rows[0])

    def test_review_queue_is_sorted_by_confidence_score_then_date(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "registry.db"
            out_dir = root / "out"

            conn = connect(db_path)
            init_schema(conn)
            upsert_tenders(
                conn,
                [
                    {
                        "objekti_procedurave": "Zhvillim software dhe riparim printeresh",
                        "autoriteti_kontraktues": "AK A",
                        "burimi_financimit": "",
                        "fondi_limit_raw": "",
                        "fondi_limit_lek": "",
                        "data_publikimit": "02-01-2031",
                        "ora_publikimit": "",
                        "data_iso": "2031-01-02",
                        "viti": "2031",
                        "koha_zhvillimit": "",
                        "kodi_cpv_raw": "",
                        "cpv_spans": "",
                        "tipi_procedures": "",
                        "anulluar": "",
                        "page_fetched": "1",
                        "row_index_on_page": "1",
                    },
                    {
                        "objekti_procedurave": "Implementim sistemi elektronik",
                        "autoriteti_kontraktues": "AK B",
                        "burimi_financimit": "",
                        "fondi_limit_raw": "",
                        "fondi_limit_lek": "",
                        "data_publikimit": "01-01-2031",
                        "ora_publikimit": "",
                        "data_iso": "2031-01-01",
                        "viti": "2031",
                        "koha_zhvillimit": "",
                        "kodi_cpv_raw": "72000000-5",
                        "cpv_spans": "",
                        "tipi_procedures": "",
                        "anulluar": "",
                        "page_fetched": "1",
                        "row_index_on_page": "2",
                    },
                ],
            )
            conn.commit()
            conn.close()

            summary = export_all(db_path, out_dir, "2031")
            with open(summary["paths"]["software_review_queue"], encoding="utf-8-sig", newline="") as fp:
                rows = list(csv.DictReader(fp))
            self.assertGreaterEqual(len(rows), 1)
            self.assertEqual(rows[0]["objekti_procedurave"], "Zhvillim software dhe riparim printeresh")


if __name__ == "__main__":
    unittest.main()
