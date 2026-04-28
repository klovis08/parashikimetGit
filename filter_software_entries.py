#!/usr/bin/env python3
"""Create a software-focused subset from registry_2026.csv (legacy CSV path).

Prefer DB-driven exports via ``export_registry.py export`` when the SQLite
pipeline is available. This script delegates classification to
``registry_classifier`` so rules stay aligned with exports.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from registry_classifier import (
    classify_software_broad,
    hardware_repair_exclusion_signals,
)
from registry_parse import COLUMNS

INPUT = Path("registry_2026.csv")
FULL_COPY = Path("registry_2026_full.csv")
OUTPUT = Path("registry_2026_software_broad.csv")
QC_OUT = Path("registry_2026_software_qc.csv")
STRICT_OUTPUT = Path("registry_2026_software.csv")
STRICT_QC_OUT = Path("registry_2026_software_strict_qc.csv")

SOFTWARE_EXTRA_COLS = ["software_match_reason", "software_match_score"]


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT}")

    shutil.copy2(INPUT, FULL_COPY)

    total = 0
    selected = 0
    selected_strict = 0

    out_fields = list(COLUMNS) + SOFTWARE_EXTRA_COLS
    qc_rows: list[dict[str, str]] = []

    with INPUT.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)

        with OUTPUT.open("w", encoding="utf-8-sig", newline="") as dst, STRICT_OUTPUT.open(
            "w", encoding="utf-8-sig", newline=""
        ) as strict_dst:
            writer = csv.DictWriter(dst, fieldnames=out_fields)
            strict_writer = csv.DictWriter(strict_dst, fieldnames=out_fields)
            writer.writeheader()
            strict_writer.writeheader()

            for row in reader:
                total += 1
                rec = {k: row.get(k, "") for k in COLUMNS}
                is_match, reasons = classify_software_broad(rec)
                if not is_match:
                    continue
                selected += 1
                rec["software_match_reason"] = " | ".join(reasons)
                rec["software_match_score"] = str(len(reasons))
                writer.writerow({k: rec.get(k, "") for k in out_fields})

                qc_rows.append(
                    {
                        "objekti_procedurave": rec.get("objekti_procedurave", ""),
                        "autoriteti_kontraktues": rec.get("autoriteti_kontraktues", ""),
                        "software_match_score": rec["software_match_score"],
                        "software_match_reason": rec["software_match_reason"],
                    }
                )

                excluded, ex_reasons = hardware_repair_exclusion_signals(rec)
                if not excluded:
                    selected_strict += 1
                    strict_writer.writerow({k: rec.get(k, "") for k in out_fields})
                else:
                    qc_rows.append(
                        {
                            "objekti_procedurave": rec.get("objekti_procedurave", ""),
                            "autoriteti_kontraktues": rec.get("autoriteti_kontraktues", ""),
                            "software_match_score": "excluded",
                            "software_match_reason": " | ".join(ex_reasons),
                        }
                    )

    with QC_OUT.open("w", encoding="utf-8-sig", newline="") as qf:
        qc_writer = csv.DictWriter(
            qf,
            fieldnames=[
                "objekti_procedurave",
                "autoriteti_kontraktues",
                "software_match_score",
                "software_match_reason",
            ],
        )
        qc_writer.writeheader()
        qc_writer.writerows(qc_rows)

    with STRICT_QC_OUT.open("w", encoding="utf-8-sig", newline="") as sqf:
        qc_writer = csv.DictWriter(
            sqf,
            fieldnames=[
                "objekti_procedurave",
                "autoriteti_kontraktues",
                "software_match_score",
                "software_match_reason",
            ],
        )
        qc_writer.writeheader()
        for row in qc_rows:
            if row.get("software_match_score") == "excluded":
                qc_writer.writerow(row)

    print(f"Input rows: {total}")
    print(f"Software-related rows (broad): {selected}")
    print(f"Software strict rows (excluding hardware repair): {selected_strict}")
    print(f"Preserved full copy: {FULL_COPY}")
    print(f"Broad output: {OUTPUT}")
    print(f"Strict output: {STRICT_OUTPUT}")
    print(f"Match audit file: {QC_OUT}")
    print(f"Strict exclusion audit file: {STRICT_QC_OUT}")


if __name__ == "__main__":
    main()
