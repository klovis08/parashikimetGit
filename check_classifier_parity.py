#!/usr/bin/env python3
"""
Verify parity between Python and TypeScript software classifiers.

Reads shared vectors from qa/classifier_parity_vectors.json, evaluates Python
classification locally, invokes the web TypeScript classifier via Node, and
fails if any broad/strict decisions or reasons diverge.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from registry_classifier import (
    classify_near_miss,
    classify_software_broad,
    classify_software_scored,
    classify_software_strict,
    mixed_it_bundle_signal,
)


def _normalized_reasons(values: list[str]) -> list[str]:
    return sorted(set(v.strip() for v in values if v and v.strip()))


def _py_eval(vectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in vectors:
        name = str(entry.get("name") or "")
        record = entry.get("record") or {}
        broad_ok, broad_reasons = classify_software_broad(record)
        strict_ok, _strict_broad_reasons, strict_excluded = classify_software_strict(record)
        mixed_ok, mixed_reasons = mixed_it_bundle_signal(record)
        near_ok, near_reasons = classify_near_miss(record)
        scored = classify_software_scored(record)
        out.append(
            {
                "name": name,
                "broad_ok": bool(broad_ok),
                "broad_reasons": _normalized_reasons(list(broad_reasons)),
                "strict_ok": bool(strict_ok),
                "strict_excluded_reasons": _normalized_reasons(list(strict_excluded)),
                "mixed_it_bundle": bool(mixed_ok),
                "mixed_reasons": _normalized_reasons(list(mixed_reasons)),
                "near_miss_ok": bool(near_ok),
                "near_miss_reasons": _normalized_reasons(list(near_reasons)),
                "score": int(scored["score"]),
                "confidence": str(scored["confidence"]),
                "top_signals": _normalized_reasons(list(scored["top_signals"])),
            }
        )
    return out


def _ts_eval(repo_root: Path, vectors_path: Path) -> list[dict[str, Any]]:
    web_dir = repo_root / "web"
    cmd = [
        "node",
        "--experimental-strip-types",
        "scripts/classifier-parity-eval.mjs",
        str(vectors_path),
    ]
    cp = subprocess.run(
        cmd,
        cwd=str(web_dir),
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            "TypeScript classifier execution failed:\n"
            f"cmd={' '.join(cmd)}\n"
            f"stdout={cp.stdout}\n"
            f"stderr={cp.stderr}"
        )
    try:
        raw = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from TypeScript classifier: {cp.stdout}") from exc
    out: list[dict[str, Any]] = []
    for item in raw:
        out.append(
            {
                "name": str(item.get("name") or ""),
                "broad_ok": bool(item.get("broad_ok")),
                "broad_reasons": _normalized_reasons(list(item.get("broad_reasons") or [])),
                "strict_ok": bool(item.get("strict_ok")),
                "strict_excluded_reasons": _normalized_reasons(
                    list(item.get("strict_excluded_reasons") or [])
                ),
                "mixed_it_bundle": bool(item.get("mixed_it_bundle")),
                "mixed_reasons": _normalized_reasons(list(item.get("mixed_reasons") or [])),
                "near_miss_ok": bool(item.get("near_miss_ok")),
                "near_miss_reasons": _normalized_reasons(list(item.get("near_miss_reasons") or [])),
                "score": int(item.get("score") or 0),
                "confidence": str(item.get("confidence") or ""),
                "top_signals": _normalized_reasons(list(item.get("top_signals") or [])),
            }
        )
    return out


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    vectors_path = repo_root / "qa" / "classifier_parity_vectors.json"
    if not vectors_path.exists():
        print(f"Missing vectors file: {vectors_path}", file=sys.stderr)
        return 2

    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    py_results = _py_eval(vectors)
    ts_results = _ts_eval(repo_root, vectors_path)

    by_name_py = {r["name"]: r for r in py_results}
    by_name_ts = {r["name"]: r for r in ts_results}
    all_names = sorted(set(by_name_py) | set(by_name_ts))

    mismatches: list[str] = []
    for name in all_names:
        pr = by_name_py.get(name)
        tr = by_name_ts.get(name)
        if pr is None or tr is None:
            mismatches.append(f"{name}: present_in_py={pr is not None} present_in_ts={tr is not None}")
            continue
        for key in (
            "broad_ok",
            "broad_reasons",
            "strict_ok",
            "strict_excluded_reasons",
            "mixed_it_bundle",
            "mixed_reasons",
            "near_miss_ok",
            "near_miss_reasons",
            "score",
            "confidence",
            "top_signals",
        ):
            if pr[key] != tr[key]:
                mismatches.append(
                    f"{name}: {key} py={pr[key]!r} ts={tr[key]!r}"
                )

    if mismatches:
        print("check_classifier_parity: FAIL", file=sys.stderr)
        for line in mismatches:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"check_classifier_parity: OK ({len(all_names)} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
