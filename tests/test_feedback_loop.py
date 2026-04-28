import json
import tempfile
import unittest
from pathlib import Path

from feedback_loop import build_calibration_report, build_quality_report
from registry_store import (
    connect,
    init_schema,
    insert_analyst_label,
    list_analyst_labels,
    upsert_tenders,
)


def _seed_db(db_path: Path) -> None:
    conn = connect(db_path)
    init_schema(conn)
    upsert_tenders(
        conn,
        [
            {
                "objekti_procedurave": "Zhvillim software per portal",
                "autoriteti_kontraktues": "AK 1",
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
                "row_index_on_page": "1",
            },
            {
                "objekti_procedurave": "Blerje materialesh pastrimi",
                "autoriteti_kontraktues": "AK 2",
                "burimi_financimit": "",
                "fondi_limit_raw": "",
                "fondi_limit_lek": "",
                "data_publikimit": "01-01-2031",
                "ora_publikimit": "",
                "data_iso": "2031-01-01",
                "viti": "2031",
                "koha_zhvillimit": "",
                "kodi_cpv_raw": "39830000-9",
                "cpv_spans": "",
                "tipi_procedures": "",
                "anulluar": "",
                "page_fetched": "1",
                "row_index_on_page": "2",
            },
        ],
    )
    rows = conn.execute("SELECT id FROM tenders ORDER BY id ASC").fetchall()
    insert_analyst_label(
        conn,
        tender_id=int(rows[0]["id"]),
        label="relevant",
        reviewer="qa",
        note="high confidence",
        snapshot_score=82,
        snapshot_confidence="high",
        snapshot_top_signals=["status:strict(+8)"],
        snapshot_broad_ok=True,
        snapshot_strict_ok=True,
        snapshot_near_miss_ok=False,
        snapshot_reasons={"broad": ["kw:software"], "strict_excluded": [], "near_miss": [], "mixed": []},
    )
    insert_analyst_label(
        conn,
        tender_id=int(rows[1]["id"]),
        label="not_relevant",
        reviewer="qa",
        note=None,
        snapshot_score=8,
        snapshot_confidence="low",
        snapshot_top_signals=["near_kw_hits(+8)"],
        snapshot_broad_ok=False,
        snapshot_strict_ok=False,
        snapshot_near_miss_ok=True,
        snapshot_reasons={"broad": [], "strict_excluded": [], "near_miss": ["near_kw:sistem"], "mixed": []},
    )
    conn.commit()
    conn.close()


class FeedbackLoopTests(unittest.TestCase):
    def test_label_persistence_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "registry.db"
            _seed_db(db_path)
            conn = connect(db_path)
            init_schema(conn)
            labels = list_analyst_labels(conn, limit=10)
            conn.close()
            self.assertEqual(len(labels), 2)
            self.assertIn(labels[0]["label"], ("relevant", "not_relevant"))
            self.assertIn("snapshot", labels[0])

    def test_quality_and_calibration_reports_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "registry.db"
            _seed_db(db_path)
            conn = connect(db_path)
            init_schema(conn)
            from feedback_loop import _fetch_latest_labels  # local import for test-only helper

            labels = _fetch_latest_labels(conn)
            conn.close()
            quality = build_quality_report(labels)
            self.assertEqual(quality["labels_used_for_metrics"], 2)
            self.assertIn("strict", quality["metrics_by_mode"])
            candidate_rules = json.loads(Path("classifier_rules.json").read_text(encoding="utf-8"))
            candidate_rules["scoring"]["confidence_thresholds"]["high"] = 95
            calibration = build_calibration_report(labels, candidate_rules)
            self.assertIn("summary", calibration)
            self.assertIn("comparisons", calibration["summary"])


if __name__ == "__main__":
    unittest.main()
