#!/usr/bin/env python3
"""
Export canonical registry CSVs from SQLite + software subsets (broad/strict).

Reads ``tenders`` via ``registry_store.iter_tenders_dicts`` (same row order as
``export_tenders_csv``: ``ORDER BY data_iso, id``). Outputs UTF-8 with BOM
(``utf-8-sig``) to match existing CSV consumers.

CLI
---
  python export_registry.py export [--db PATH] [--out-dir PATH]
  python export_registry.py validate [--db PATH]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from registry_classifier import (
    classify_software_broad,
    classify_software_scored,
    classify_near_miss,
    classify_software_strict,
    hardware_repair_exclusion_signals,
    mixed_it_bundle_signal,
    validate_classification_invariants,
)
from registry_parse import COLUMNS
from registry_store import connect, init_schema, iter_tenders_dicts

DEFAULT_DB = "registry.db"

def _file_names_for_year(year: str) -> dict[str, str]:
    y = str(year).strip()
    return {
        "canonical": f"registry_{y}.csv",
        "software_broad": f"registry_{y}_software_broad.csv",
        "software_strict": f"registry_{y}_software.csv",
        "software_qc": f"registry_{y}_software_qc.csv",
        "software_strict_qc": f"registry_{y}_software_strict_qc.csv",
        "software_near_miss": f"registry_{y}_software_near_miss.csv",
        "software_review_queue": f"registry_{y}_software_review_queue.csv",
    }

SOFTWARE_EXTRA_COLS = [
    "software_match_reason",
    "software_match_score",
    "software_confidence",
    "software_top_signals",
]
QC_FIELDNAMES = [
    "objekti_procedurave",
    "autoriteti_kontraktues",
    "software_match_score",
    "software_match_reason",
]


def _software_out_fields() -> list[str]:
    return list(COLUMNS) + SOFTWARE_EXTRA_COLS


def _attach_software_metadata(row: dict[str, str], reasons: list[str]) -> None:
    scored = classify_software_scored(row)
    row["software_match_reason"] = " | ".join(reasons)
    row["software_match_score"] = str(scored["score"])
    row["software_confidence"] = str(scored["confidence"])
    row["software_top_signals"] = " | ".join(scored["top_signals"])


def export_all(db_path: str | Path, out_dir: str | Path, year: str) -> dict[str, int]:
    """
    Write all pipeline CSVs under ``out_dir``. Returns per-file row counts.

    Idempotent with respect to DB contents: stable ordering yields stable files.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect(db_path)
    init_schema(conn)

    file_names = _file_names_for_year(year)
    path_canonical = out_dir / file_names["canonical"]
    path_broad = out_dir / file_names["software_broad"]
    path_strict = out_dir / file_names["software_strict"]
    path_qc = out_dir / file_names["software_qc"]
    path_strict_qc = out_dir / file_names["software_strict_qc"]
    path_near_miss = out_dir / file_names["software_near_miss"]
    path_review_queue = out_dir / file_names["software_review_queue"]

    out_fields = _software_out_fields()
    qc_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []

    n_full = 0
    n_broad = 0
    n_strict = 0
    n_near_miss = 0

    with path_canonical.open("w", encoding="utf-8-sig", newline="") as fp_full, path_broad.open(
        "w", encoding="utf-8-sig", newline=""
    ) as fp_broad, path_strict.open("w", encoding="utf-8-sig", newline="") as fp_strict, path_near_miss.open(
        "w", encoding="utf-8-sig", newline=""
    ) as fp_near_miss:
        w_full = csv.DictWriter(fp_full, fieldnames=list(COLUMNS))
        w_broad = csv.DictWriter(fp_broad, fieldnames=out_fields)
        w_strict = csv.DictWriter(fp_strict, fieldnames=out_fields)
        w_near_miss = csv.DictWriter(fp_near_miss, fieldnames=out_fields)
        w_full.writeheader()
        w_broad.writeheader()
        w_strict.writeheader()
        w_near_miss.writeheader()

        for row in iter_tenders_dicts(conn):
            n_full += 1
            base = {k: row.get(k, "") for k in COLUMNS}
            w_full.writerow(base)

            broad_ok, broad_reasons = classify_software_broad(row)
            if not broad_ok:
                continue

            n_broad += 1
            sw_row = {**base}
            _attach_software_metadata(sw_row, broad_reasons)
            w_broad.writerow({k: sw_row.get(k, "") for k in out_fields})

            qc_rows.append(
                {
                    "objekti_procedurave": sw_row.get("objekti_procedurave", ""),
                    "autoriteti_kontraktues": sw_row.get("autoriteti_kontraktues", ""),
                    "software_match_score": sw_row["software_match_score"],
                    "software_match_reason": sw_row["software_match_reason"],
                }
            )

            excluded, excl_reasons = hardware_repair_exclusion_signals(row)
            if not excluded:
                n_strict += 1
                w_strict.writerow({k: sw_row.get(k, "") for k in out_fields})
            else:
                mixed_ok, mixed_reasons = mixed_it_bundle_signal(row)
                qc_rows.append(
                    {
                        "objekti_procedurave": sw_row.get("objekti_procedurave", ""),
                        "autoriteti_kontraktues": sw_row.get("autoriteti_kontraktues", ""),
                        "software_match_score": "excluded",
                        "software_match_reason": " | ".join(
                            ["mixed_it_bundle"]
                            + (mixed_reasons if mixed_ok else excl_reasons)
                        ),
                    }
                )

            near_ok, near_reasons = classify_near_miss(row)
            if near_ok:
                n_near_miss += 1
                near_row = {**base}
                _attach_software_metadata(near_row, near_reasons)
                w_near_miss.writerow({k: near_row.get(k, "") for k in out_fields})
                review_rows.append({k: near_row.get(k, "") for k in out_fields})
            elif broad_ok and excluded:
                mixed_row = {**base}
                _attach_software_metadata(
                    mixed_row,
                    [f"mixed_it_bundle:{r}" for r in (mixed_reasons if mixed_ok else excl_reasons)],
                )
                review_rows.append({k: mixed_row.get(k, "") for k in out_fields})

    conn.close()

    with path_qc.open("w", encoding="utf-8-sig", newline="") as fp_qc:
        w_qc = csv.DictWriter(fp_qc, fieldnames=QC_FIELDNAMES)
        w_qc.writeheader()
        w_qc.writerows(qc_rows)

    with path_strict_qc.open("w", encoding="utf-8-sig", newline="") as fp_sq:
        w_sq = csv.DictWriter(fp_sq, fieldnames=QC_FIELDNAMES)
        w_sq.writeheader()
        for r in qc_rows:
            if r.get("software_match_score") == "excluded":
                w_sq.writerow(r)

    conf_rank = {"high": 3, "medium": 2, "low": 1}
    review_rows.sort(
        key=lambda r: (
            -conf_rank.get(r.get("software_confidence", "low"), 1),
            -int(r.get("software_match_score", "0") or "0"),
            r.get("data_iso", ""),
            r.get("row_index_on_page", ""),
        )
    )
    with path_review_queue.open("w", encoding="utf-8-sig", newline="") as fp_rq:
        w_rq = csv.DictWriter(fp_rq, fieldnames=out_fields)
        w_rq.writeheader()
        w_rq.writerows(review_rows)

    return {
        "full": n_full,
        "software_broad": n_broad,
        "software_strict": n_strict,
        "excluded_from_strict": n_broad - n_strict,
        "near_miss_rows": n_near_miss,
        "qc_rows": len(qc_rows),
        "paths": {
            "canonical": str(path_canonical),
            "software_broad": str(path_broad),
            "software_strict": str(path_strict),
            "software_qc": str(path_qc),
            "software_strict_qc": str(path_strict_qc),
            "software_near_miss": str(path_near_miss),
            "software_review_queue": str(path_review_queue),
        },
    }


def validate_db(db_path: str | Path) -> dict[str, object]:
    """Compute counts, exclusion tally, and classification sanity flags."""
    conn = connect(db_path)
    init_schema(conn)

    n_full = 0
    n_broad = 0
    n_strict = 0
    n_near_miss = 0
    n_mixed = 0
    invariant_failures = 0
    sample_excluded: list[str] = []

    for row in iter_tenders_dicts(conn):
        n_full += 1
        broad_ok, _ = classify_software_broad(row)
        strict_ok, _, excl = classify_software_strict(row)

        viol = validate_classification_invariants(row)
        if viol:
            invariant_failures += 1

        if broad_ok:
            n_broad += 1
        if strict_ok:
            n_strict += 1
        near_ok, _ = classify_near_miss(row)
        mixed_ok, _ = mixed_it_bundle_signal(row)
        if near_ok:
            n_near_miss += 1
        if mixed_ok:
            n_mixed += 1

        if broad_ok and not strict_ok and len(sample_excluded) < 5:
            title = (row.get("objekti_procedurave") or "").strip()
            if title:
                sample_excluded.append(title[:120])

    conn.close()

    return {
        "total_full_rows": n_full,
        "broad_rows": n_broad,
        "strict_rows": n_strict,
        "excluded_from_strict_count": n_broad - n_strict,
        "near_miss_rows": n_near_miss,
        "mixed_it_bundle_rows": n_mixed,
        "classification_invariant_violations": invariant_failures,
        "sample_excluded_titles": sample_excluded,
    }


def _hardware_repair_sanity() -> dict[str, object]:
    """
    Built-in examples: broad IT signal present, strict must reject repair flavor.
    """
    cases = [
        {
            "name": "antivirus_broad_keyword",
            "row": {
                "objekti_procedurave": "Mirëmbajtje antivirus dhe riparim printerësh",
                "kodi_cpv_raw": "",
                "tipi_procedures": "",
            },
            "expect_broad": True,
            "expect_strict": False,
        },
        {
            "name": "cpv_hardware_exclusion",
            "row": {
                "objekti_procedurave": "Shërbime IT",
                "kodi_cpv_raw": "50312000-5 - Some hardware repair CPV",
                "tipi_procedures": "",
            },
            "expect_broad": True,
            "expect_strict": False,
        },
        {
            "name": "pure_software_development",
            "row": {
                "objekti_procedurave": "Zhvillim software për portalin digjital",
                "kodi_cpv_raw": "72000000-5 - IT services",
                "tipi_procedures": "",
            },
            "expect_broad": True,
            "expect_strict": True,
        },
    ]
    results = []
    for c in cases:
        row = c["row"]
        b, _ = classify_software_broad(row)
        s, _, ex = classify_software_strict(row)
        ok = b == c["expect_broad"] and s == c["expect_strict"]
        results.append(
            {
                "case": c["name"],
                "ok": ok,
                "broad": b,
                "strict": s,
                "excluded_reasons": ex,
            }
        )
    return {"hardware_repair_sanity_cases": results, "all_ok": all(r["ok"] for r in results)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Export registry CSVs from SQLite DB.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export", help="Write registry_<year>*.csv deliverables")
    p_exp.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    p_exp.add_argument("--year", default="2026", help="Year used in output filenames")
    p_exp.add_argument(
        "--out-dir",
        default=".",
        help="Directory for output CSVs (default: current directory)",
    )

    p_val = sub.add_parser("validate", help="Print row counts and sanity checks")
    p_val.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    p_val.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON only",
    )

    args = ap.parse_args()

    if args.cmd == "export":
        summary = export_all(args.db, args.out_dir, args.year)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    if args.cmd == "validate":
        counts = validate_db(args.db)
        sanity = _hardware_repair_sanity()
        out = {**counts, **sanity}
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(f"total_full_rows: {counts['total_full_rows']}")
            print(f"broad_rows: {counts['broad_rows']}")
            print(f"strict_rows: {counts['strict_rows']}")
            print(f"excluded_from_strict_count: {counts['excluded_from_strict_count']}")
            print(f"classification_invariant_violations: {counts['classification_invariant_violations']}")
            print("hardware_repair_sanity_cases:")
            for r in sanity["hardware_repair_sanity_cases"]:  # type: ignore[index]
                status = "OK" if r["ok"] else "FAIL"
                print(f"  [{status}] {r['case']} broad={r['broad']} strict={r['strict']}")
            if counts["sample_excluded_titles"]:
                print("sample_excluded_titles (first titles broad-not-strict):")
                for t in counts["sample_excluded_titles"]:
                    print(f"  - {t}")
        if not sanity["all_ok"]:  # type: ignore[index]
            sys.exit(1)
        if counts["classification_invariant_violations"]:
            sys.exit(2)
        return

    raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
