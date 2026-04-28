#!/usr/bin/env python3
"""Analyst feedback metrics, calibration and explainability reports."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from registry_classifier import classify_software_scored
from registry_parse import COLUMNS
from registry_store import connect, init_schema

DEFAULT_DB = "registry.db"


@dataclass
class LabelEval:
    label_id: int
    tender_id: int
    label: str
    timestamp: str
    reviewer: str | None
    note: str | None
    row: dict[str, str]
    scored: dict[str, object]
    snapshot: dict[str, object]


def _fetch_latest_labels(conn: Any) -> list[LabelEval]:
    rows = conn.execute(
        """
        WITH latest AS (
          SELECT tender_id, MAX(created_at) AS created_at
          FROM analyst_labels
          GROUP BY tender_id
        )
        SELECT
          al.id AS label_id,
          al.tender_id,
          al.label,
          al.created_at,
          al.reviewer,
          al.note,
          al.snapshot_score,
          al.snapshot_confidence,
          al.snapshot_top_signals_json,
          al.snapshot_broad_ok,
          al.snapshot_strict_ok,
          al.snapshot_near_miss_ok,
          al.snapshot_reasons_json,
          t.*
        FROM analyst_labels al
        JOIN latest l ON l.tender_id = al.tender_id AND l.created_at = al.created_at
        JOIN tenders t ON t.id = al.tender_id
        ORDER BY al.created_at DESC, al.id DESC
        """
    ).fetchall()
    out: list[LabelEval] = []
    for r in rows:
        row = {k: (r[k] if r[k] is not None else "") for k in COLUMNS}
        out.append(
            LabelEval(
                label_id=int(r["label_id"]),
                tender_id=int(r["tender_id"]),
                label=str(r["label"]),
                timestamp=str(r["created_at"]),
                reviewer=r["reviewer"],
                note=r["note"],
                row=row,
                scored=classify_software_scored(row),
                snapshot={
                    "score": int(r["snapshot_score"]),
                    "confidence": str(r["snapshot_confidence"]),
                    "top_signals": json.loads(r["snapshot_top_signals_json"] or "[]"),
                    "broad_ok": bool(r["snapshot_broad_ok"]),
                    "strict_ok": bool(r["snapshot_strict_ok"]),
                    "near_miss_ok": bool(r["snapshot_near_miss_ok"]),
                    "reasons": json.loads(r["snapshot_reasons_json"] or "{}"),
                },
            )
        )
    return out


def _confusion(entries: list[tuple[bool, bool]]) -> dict[str, int]:
    tp = fp = fn = tn = 0
    for predicted, actual in entries:
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _prf(conf: dict[str, int]) -> dict[str, float]:
    tp = conf["tp"]
    fp = conf["fp"]
    fn = conf["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def _score_bucket(score: int) -> str:
    lo = (score // 10) * 10
    hi = lo + 9
    if hi > 100:
        hi = 100
    return f"{lo:02d}-{hi:02d}"


def build_quality_report(labels: list[LabelEval]) -> dict[str, Any]:
    relevant_labels = [l for l in labels if l.label in {"relevant", "not_relevant"}]
    pairs_by_mode: dict[str, list[tuple[bool, bool]]] = {"strict": [], "broad": [], "near_miss": []}
    by_tier: dict[str, list[tuple[bool, bool]]] = {"high": [], "medium": [], "low": []}
    score_buckets: dict[str, int] = {}
    mode_counts = {"strict": 0, "broad": 0, "near_miss": 0}

    for item in relevant_labels:
        actual = item.label == "relevant"
        scored = item.scored
        strict = bool(scored["strict_ok"])
        broad = bool(scored["broad_ok"])
        near = bool(scored["near_miss_ok"])
        pairs_by_mode["strict"].append((strict, actual))
        pairs_by_mode["broad"].append((broad, actual))
        pairs_by_mode["near_miss"].append((near, actual))
        if strict:
            mode_counts["strict"] += 1
        if broad:
            mode_counts["broad"] += 1
        if near:
            mode_counts["near_miss"] += 1
        conf = str(scored["confidence"])
        if conf in by_tier:
            by_tier[conf].append((strict, actual))
        bucket = _score_bucket(int(scored["score"]))
        score_buckets[bucket] = score_buckets.get(bucket, 0) + 1

    metrics_by_mode: dict[str, Any] = {}
    for mode, pairs in pairs_by_mode.items():
        conf = _confusion(pairs)
        metrics_by_mode[mode] = {**conf, **_prf(conf)}

    tier_confusions: dict[str, dict[str, int]] = {}
    for tier, pairs in by_tier.items():
        tier_confusions[tier] = _confusion(pairs)

    return {
        "labels_total": len(labels),
        "labels_used_for_metrics": len(relevant_labels),
        "labels_maybe_excluded": len([l for l in labels if l.label == "maybe"]),
        "mode_counts": mode_counts,
        "metrics_by_mode": metrics_by_mode,
        "confidence_tier_confusions_strict": tier_confusions,
        "score_distribution_buckets": dict(sorted(score_buckets.items())),
    }


def build_calibration_report(
    labels: list[LabelEval], candidate_rules: dict[str, object]
) -> dict[str, Any]:
    relevant = [l for l in labels if l.label in {"relevant", "not_relevant"}]
    before_pairs: dict[str, list[tuple[bool, bool]]] = {"strict": [], "broad": [], "near_miss": []}
    after_pairs: dict[str, list[tuple[bool, bool]]] = {"strict": [], "broad": [], "near_miss": []}
    changed: list[dict[str, Any]] = []

    for item in relevant:
        actual = item.label == "relevant"
        before = item.scored
        after = classify_software_scored(item.row, rules=candidate_rules)
        for mode, key in (
            ("strict", "strict_ok"),
            ("broad", "broad_ok"),
            ("near_miss", "near_miss_ok"),
        ):
            before_pairs[mode].append((bool(before[key]), actual))
            after_pairs[mode].append((bool(after[key]), actual))
        if (
            int(before["score"]) != int(after["score"])
            or str(before["confidence"]) != str(after["confidence"])
            or bool(before["strict_ok"]) != bool(after["strict_ok"])
            or bool(before["near_miss_ok"]) != bool(after["near_miss_ok"])
        ):
            changed.append(
                {
                    "tender_id": item.tender_id,
                    "label": item.label,
                    "before": {
                        "score": int(before["score"]),
                        "confidence": str(before["confidence"]),
                        "strict_ok": bool(before["strict_ok"]),
                        "near_miss_ok": bool(before["near_miss_ok"]),
                        "top_signals": list(before["top_signals"]),
                    },
                    "after": {
                        "score": int(after["score"]),
                        "confidence": str(after["confidence"]),
                        "strict_ok": bool(after["strict_ok"]),
                        "near_miss_ok": bool(after["near_miss_ok"]),
                        "top_signals": list(after["top_signals"]),
                    },
                }
            )

    summary: dict[str, Any] = {"comparisons": {}}
    regressions: list[str] = []
    for mode in ("strict", "broad", "near_miss"):
        before_conf = _confusion(before_pairs[mode])
        after_conf = _confusion(after_pairs[mode])
        before_prf = _prf(before_conf)
        after_prf = _prf(after_conf)
        recall_delta = round(after_prf["recall"] - before_prf["recall"], 4)
        precision_delta = round(after_prf["precision"] - before_prf["precision"], 4)
        summary["comparisons"][mode] = {
            "before": {**before_conf, **before_prf},
            "after": {**after_conf, **after_prf},
            "delta": {"recall": recall_delta, "precision": precision_delta},
        }
        if recall_delta < 0:
            regressions.append(f"{mode}: recall dropped {recall_delta}")

    return {
        "labels_used_for_calibration": len(relevant),
        "summary": summary,
        "regressions": regressions,
        "changed_tenders": changed[:50],
    }


def write_csv_report(path: Path, labels: list[LabelEval]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "tender_id",
                "label",
                "timestamp",
                "snapshot_score",
                "current_score",
                "snapshot_confidence",
                "current_confidence",
                "snapshot_strict_ok",
                "current_strict_ok",
                "snapshot_near_miss_ok",
                "current_near_miss_ok",
                "snapshot_top_signals",
                "current_top_signals",
            ],
        )
        writer.writeheader()
        for item in labels:
            writer.writerow(
                {
                    "tender_id": item.tender_id,
                    "label": item.label,
                    "timestamp": item.timestamp,
                    "snapshot_score": item.snapshot["score"],
                    "current_score": int(item.scored["score"]),
                    "snapshot_confidence": item.snapshot["confidence"],
                    "current_confidence": str(item.scored["confidence"]),
                    "snapshot_strict_ok": int(bool(item.snapshot["strict_ok"])),
                    "current_strict_ok": int(bool(item.scored["strict_ok"])),
                    "snapshot_near_miss_ok": int(bool(item.snapshot["near_miss_ok"])),
                    "current_near_miss_ok": int(bool(item.scored["near_miss_ok"])),
                    "snapshot_top_signals": " | ".join(item.snapshot["top_signals"]),
                    "current_top_signals": " | ".join(item.scored["top_signals"]),
                }
            )


def main() -> int:
    ap = argparse.ArgumentParser(description="Feedback-loop metrics and calibration tools.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_report = sub.add_parser("report", help="Compute quality monitoring metrics")
    p_report.add_argument("--db", default=DEFAULT_DB)
    p_report.add_argument("--out-json", default="")
    p_report.add_argument("--out-csv", default="")

    p_cal = sub.add_parser("calibrate", help="Compare baseline vs candidate rules")
    p_cal.add_argument("--db", default=DEFAULT_DB)
    p_cal.add_argument("--candidate-rules", required=True)
    p_cal.add_argument("--out-json", default="")

    p_exp = sub.add_parser("explain", help="Show current vs snapshot explainability deltas")
    p_exp.add_argument("--db", default=DEFAULT_DB)
    p_exp.add_argument("--limit", type=int, default=20)

    args = ap.parse_args()
    conn = connect(args.db)
    init_schema(conn)
    labels = _fetch_latest_labels(conn)
    conn.close()

    if args.cmd == "report":
        out = build_quality_report(labels)
        if args.out_json:
            Path(args.out_json).write_text(
                json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        if args.out_csv:
            write_csv_report(Path(args.out_csv), labels)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "calibrate":
        candidate_rules = json.loads(Path(args.candidate_rules).read_text(encoding="utf-8"))
        out = build_calibration_report(labels, candidate_rules)
        if args.out_json:
            Path(args.out_json).write_text(
                json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1 if out["regressions"] else 0

    if args.cmd == "explain":
        diffs: list[dict[str, Any]] = []
        for item in labels[: max(1, args.limit)]:
            current = item.scored
            if (
                int(item.snapshot["score"]) != int(current["score"])
                or str(item.snapshot["confidence"]) != str(current["confidence"])
                or bool(item.snapshot["strict_ok"]) != bool(current["strict_ok"])
            ):
                diffs.append(
                    {
                        "tender_id": item.tender_id,
                        "label": item.label,
                        "timestamp": item.timestamp,
                        "score": {
                            "snapshot": int(item.snapshot["score"]),
                            "current": int(current["score"]),
                        },
                        "confidence": {
                            "snapshot": str(item.snapshot["confidence"]),
                            "current": str(current["confidence"]),
                        },
                        "strict_ok": {
                            "snapshot": bool(item.snapshot["strict_ok"]),
                            "current": bool(current["strict_ok"]),
                        },
                        "top_signals": {
                            "snapshot": item.snapshot["top_signals"],
                            "current": list(current["top_signals"]),
                        },
                    }
                )
        print(json.dumps({"diffs": diffs, "checked": min(len(labels), args.limit)}, indent=2, ensure_ascii=False))
        return 0

    raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
