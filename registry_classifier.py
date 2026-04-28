#!/usr/bin/env python3
"""
Deterministic software/IT classification for procurement registry rows.

Used by CSV filters and DB export. Logic mirrors the historical
``filter_software_entries.py`` intent:

- **Broad**: software / IT / systems / web / SaaS signals (keywords + CPV prefixes).
- **Strict**: broad rows minus hardware repair / maintenance style entries
  (keyword + CPV exclusion prefixes).

All decisions are rule-based (no ML). Combined text is built from
``objekti_procedurave``, ``kodi_cpv_raw``, and ``tipi_procedures`` — the same
fields as the legacy CSV workflow.
"""

from __future__ import annotations

import re
import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Literal

RULES_PATH = Path(__file__).resolve().parent / "classifier_rules.json"
_MOJIBAKE_FIXES = {
    "Ã«": "e",
    "Ã§": "c",
    "Ã‰": "e",
    "â€™": "'",
    "â€œ": '"',
    "â€": '"',
    "â€“": "-",
    "â€”": "-",
    "�": "",
}


@lru_cache(maxsize=1)
def _rules() -> dict[str, object]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


ConfidenceTier = Literal["high", "medium", "low"]


def norm(value: str) -> str:
    text = value or ""
    for wrong, fixed in _MOJIBAKE_FIXES.items():
        text = text.replace(wrong, fixed)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    return " ".join(text.split())


def parse_cpv_codes(cpv_text: str) -> list[str]:
    """Extract CPV codes like ``44312000-0`` from raw CPV cell text."""
    return re.findall(r"\b\d{8}-\d\b", cpv_text or "")


def _combined_text(record: dict[str, str]) -> str:
    return norm(
        " ".join(
            [
                record.get("objekti_procedurave", ""),
                record.get("kodi_cpv_raw", ""),
                record.get("tipi_procedures", ""),
            ]
        )
    )


def _get_rules(rules: dict[str, object] | None = None) -> dict[str, object]:
    return rules if rules is not None else _rules()


def _keyword_regex(rules: dict[str, object] | None = None) -> re.Pattern[str]:
    if rules is None:
        return _keyword_regex_default()
    return re.compile("|".join(rules["include_keyword_patterns"]), re.IGNORECASE)  # type: ignore[index]


@lru_cache(maxsize=1)
def _keyword_regex_default() -> re.Pattern[str]:
    return re.compile("|".join(_rules()["include_keyword_patterns"]), re.IGNORECASE)  # type: ignore[index]


def _exclude_regex(rules: dict[str, object] | None = None) -> re.Pattern[str]:
    if rules is None:
        return _exclude_regex_default()
    return re.compile("|".join(rules["exclude_keyword_patterns"]), re.IGNORECASE)  # type: ignore[index]


@lru_cache(maxsize=1)
def _exclude_regex_default() -> re.Pattern[str]:
    return re.compile("|".join(_rules()["exclude_keyword_patterns"]), re.IGNORECASE)  # type: ignore[index]


def _near_miss_regex(rules: dict[str, object] | None = None) -> re.Pattern[str]:
    if rules is None:
        return _near_miss_regex_default()
    return re.compile("|".join(rules["near_miss_keyword_patterns"]), re.IGNORECASE)  # type: ignore[index]


@lru_cache(maxsize=1)
def _near_miss_regex_default() -> re.Pattern[str]:
    return re.compile("|".join(_rules()["near_miss_keyword_patterns"]), re.IGNORECASE)  # type: ignore[index]


def _keyword_hits(text: str, regex: re.Pattern[str]) -> list[str]:
    """Collect matched keyword spans; use finditer so alternation never yields empty captures."""
    reasons: list[str] = []
    for m in regex.finditer(text):
        token = m.group(0)
        if token and f"kw:{token}" not in reasons:
            reasons.append(f"kw:{token}")
    return reasons


def _cpv_inclusion_reasons(cpv_text: str, rules: dict[str, object] | None = None) -> list[str]:
    reasons: list[str] = []
    resolved = _get_rules(rules)
    for cpv in parse_cpv_codes(cpv_text):
        digits = cpv.split("-")[0]
        if any(digits.startswith(prefix) for prefix in resolved["include_cpv_prefixes"]):  # type: ignore[index]
            r = f"cpv:{cpv}"
            if r not in reasons:
                reasons.append(r)
    return reasons


def _cpv_exclusion_reasons(cpv_text: str, rules: dict[str, object] | None = None) -> list[str]:
    reasons: list[str] = []
    resolved = _get_rules(rules)
    for cpv in parse_cpv_codes(cpv_text):
        digits = cpv.split("-")[0]
        if any(digits.startswith(prefix) for prefix in resolved["exclude_cpv_prefixes"]):  # type: ignore[index]
            r = f"exclude_cpv:{cpv}"
            if r not in reasons:
                reasons.append(r)
    return reasons


def _cpv_near_miss_reasons(cpv_text: str, rules: dict[str, object] | None = None) -> list[str]:
    reasons: list[str] = []
    resolved = _get_rules(rules)
    for cpv in parse_cpv_codes(cpv_text):
        digits = cpv.split("-")[0]
        if any(digits.startswith(prefix) for prefix in resolved["near_miss_cpv_prefixes"]):  # type: ignore[index]
            r = f"near_cpv:{cpv}"
            if r not in reasons:
                reasons.append(r)
    return reasons


def _exclude_keyword_hits(text: str, regex: re.Pattern[str]) -> list[str]:
    reasons: list[str] = []
    for m in regex.finditer(text):
        token = m.group(0)
        if token and f"exclude_kw:{token}" not in reasons:
            reasons.append(f"exclude_kw:{token}")
    return reasons


def classify_software_broad(
    record: dict[str, str], *, rules: dict[str, object] | None = None
) -> tuple[bool, list[str]]:
    """
    Return whether the row is software/IT-related (broad) and match reasons.

    Reasons use ``kw:`` / ``cpv:`` prefixes so exports and QC files stay
    consistent with the legacy script.
    """
    text = _combined_text(record)
    regex = _keyword_regex(rules)
    reasons = _keyword_hits(text, regex)
    reasons.extend(
        r
        for r in _cpv_inclusion_reasons(record.get("kodi_cpv_raw", ""), rules)
        if r not in reasons
    )
    return (len(reasons) > 0), reasons


def mixed_it_bundle_signal(
    record: dict[str, str], *, rules: dict[str, object] | None = None
) -> tuple[bool, list[str]]:
    """
    Detect bundled tenders that mix IT/software relevance with hardware-repair signals.

    These rows are review-worthy and should not be silently ignored in strict-like flows.
    """
    broad_ok, broad_reasons = classify_software_broad(record, rules=rules)
    excluded_ok, excluded_reasons = hardware_repair_exclusion_signals(record, rules=rules)
    if broad_ok and excluded_ok:
        return True, [*broad_reasons, *excluded_reasons]
    return False, []


def hardware_repair_exclusion_signals(
    record: dict[str, str], *, rules: dict[str, object] | None = None
) -> tuple[bool, list[str]]:
    """
    Hardware-repair / maintenance signals used for the strict filter.

    Exposed for validation invariants; same rules as legacy ``should_exclude``.
    """
    text = _combined_text(record)
    reasons = _exclude_keyword_hits(text, _exclude_regex(rules))
    for r in _cpv_exclusion_reasons(record.get("kodi_cpv_raw", ""), rules):
        if r not in reasons:
            reasons.append(r)
    return (len(reasons) > 0), reasons


def classify_software_strict(
    record: dict[str, str],
    *,
    rules: dict[str, object] | None = None,
) -> tuple[bool, list[str], list[str]]:
    """
    Strict software set: broad match minus hardware-repair style rows.

    Returns
    -------
    (accepted, broad_reasons, excluded_reasons)

    - If not broad: ``(False, [], [])``.
    - If broad but excluded from strict: ``(False, broad_reasons, excluded_reasons)``.
    - If broad and accepted: ``(True, broad_reasons, [])``.
    """
    broad_ok, broad_reasons = classify_software_broad(record, rules=rules)
    if not broad_ok:
        return False, [], []

    excluded_ok, excluded_reasons = hardware_repair_exclusion_signals(record, rules=rules)
    if excluded_ok:
        return False, broad_reasons, excluded_reasons

    return True, broad_reasons, []


def validate_classification_invariants(record: dict[str, str]) -> list[str]:
    """
    Return human-readable invariant violations for a single row (empty if OK).

    Used by ``export_registry.py validate`` sanity checks.
    """
    violations: list[str] = []
    strict_ok, _broad_r, excl_r = classify_software_strict(record)
    broad_ok, _ = classify_software_broad(record)
    ex_sig, _ = hardware_repair_exclusion_signals(record)

    if strict_ok and not broad_ok:
        violations.append("strict True but broad False")
    if strict_ok and ex_sig:
        violations.append("strict True but hardware-exclusion signals fired")
    if not strict_ok and broad_ok and ex_sig and not excl_r:
        violations.append("excluded from strict but excluded_reasons empty")

    return violations


def classify_near_miss(
    record: dict[str, str], *, rules: dict[str, object] | None = None
) -> tuple[bool, list[str]]:
    """
    Rows close to software relevance but not strict-accepted.

    - Include mixed IT bundles (broad + hardware-repair signals).
    - Include weak proximity signals when broad rules do not fire.
    """
    strict_ok, _broad_reasons, _excluded = classify_software_strict(record, rules=rules)
    if strict_ok:
        return False, []

    mixed_ok, mixed_reasons = mixed_it_bundle_signal(record, rules=rules)
    if mixed_ok:
        return True, [f"mixed_it_bundle:{r}" for r in mixed_reasons]

    broad_ok, _ = classify_software_broad(record, rules=rules)
    if broad_ok:
        return False, []

    text = _combined_text(record)
    reasons = [f"near_kw:{m.group(0)}" for m in _near_miss_regex(rules).finditer(text)]
    for r in _cpv_near_miss_reasons(record.get("kodi_cpv_raw", ""), rules):
        if r not in reasons:
            reasons.append(r)

    deduped: list[str] = []
    for r in reasons:
        if r not in deduped:
            deduped.append(r)
    return (len(deduped) > 0), deduped


def _score_reason_entries(reasons: list[str], weight: int) -> list[tuple[str, int]]:
    return [(reason, weight) for reason in reasons]


def _confidence_from_score(score: int) -> ConfidenceTier:
    scoring = _rules()["scoring"]
    thresholds = scoring["confidence_thresholds"]
    if score >= int(thresholds["high"]):
        return "high"
    if score >= int(thresholds["medium"]):
        return "medium"
    return "low"


def classify_software_scored(
    record: dict[str, str], *, rules: dict[str, object] | None = None
) -> dict[str, object]:
    """
    Deterministic score + confidence tiers for triage prioritization.

    Backward compatibility:
    - broad/strict/near_miss booleans and reasons are still computed from existing rules.
    """
    broad_ok, broad_reasons = classify_software_broad(record, rules=rules)
    strict_ok, _, strict_excluded_reasons = classify_software_strict(record, rules=rules)
    mixed_ok, mixed_reasons = mixed_it_bundle_signal(record, rules=rules)
    near_ok, near_reasons = classify_near_miss(record, rules=rules)
    exclusion_ok, exclusion_reasons = hardware_repair_exclusion_signals(record, rules=rules)

    resolved = _get_rules(rules)
    scoring = resolved["scoring"]  # type: ignore[index]
    weights = scoring["weights"]
    scale = scoring["scale"]
    top_signal_count = int(scoring.get("top_signal_count", 3))

    include_kw_reasons = [r for r in broad_reasons if r.startswith("kw:")]
    include_cpv_reasons = [r for r in broad_reasons if r.startswith("cpv:")]
    exclude_kw_reasons = [r for r in exclusion_reasons if r.startswith("exclude_kw:")]
    exclude_cpv_reasons = [r for r in exclusion_reasons if r.startswith("exclude_cpv:")]

    near_kw_reasons = [r for r in near_reasons if r.startswith("near_kw:")]
    near_cpv_reasons = [r for r in near_reasons if r.startswith("near_cpv:")]
    mixed_signal_reasons = [r for r in near_reasons if r.startswith("mixed_it_bundle:")]

    signal_entries: list[tuple[str, int]] = []
    summary_entries: list[tuple[str, int]] = []
    if broad_ok:
        bonus = int(weights["broad_bonus"])
        signal_entries.append(("status:broad", bonus))
        summary_entries.append(("status:broad", bonus))
    if strict_ok:
        bonus = int(weights["strict_bonus"])
        signal_entries.append(("status:strict", bonus))
        summary_entries.append(("status:strict", bonus))
    if mixed_ok:
        bonus = int(weights["mixed_bundle_bonus"])
        signal_entries.append(("status:mixed_it_bundle", bonus))
        summary_entries.append(("status:mixed_it_bundle", bonus))

    signal_entries.extend(
        _score_reason_entries(include_kw_reasons, int(weights["include_keyword_hit"]))
    )
    if include_kw_reasons:
        summary_entries.append(
            ("include_kw_hits", len(include_kw_reasons) * int(weights["include_keyword_hit"]))
        )
    signal_entries.extend(
        _score_reason_entries(include_cpv_reasons, int(weights["include_cpv_hit"]))
    )
    if include_cpv_reasons:
        summary_entries.append(
            ("include_cpv_hits", len(include_cpv_reasons) * int(weights["include_cpv_hit"]))
        )
    signal_entries.extend(
        _score_reason_entries(exclude_kw_reasons, int(weights["exclude_keyword_hit"]))
    )
    if exclude_kw_reasons:
        summary_entries.append(
            ("exclude_kw_hits", len(exclude_kw_reasons) * int(weights["exclude_keyword_hit"]))
        )
    signal_entries.extend(
        _score_reason_entries(exclude_cpv_reasons, int(weights["exclude_cpv_hit"]))
    )
    if exclude_cpv_reasons:
        summary_entries.append(
            ("exclude_cpv_hits", len(exclude_cpv_reasons) * int(weights["exclude_cpv_hit"]))
        )
    signal_entries.extend(
        _score_reason_entries(near_kw_reasons, int(weights["near_keyword_hit"]))
    )
    if near_kw_reasons:
        summary_entries.append(
            ("near_kw_hits", len(near_kw_reasons) * int(weights["near_keyword_hit"]))
        )
    signal_entries.extend(
        _score_reason_entries(near_cpv_reasons, int(weights["near_cpv_hit"]))
    )
    if near_cpv_reasons:
        summary_entries.append(
            ("near_cpv_hits", len(near_cpv_reasons) * int(weights["near_cpv_hit"]))
        )
    # mixed near-miss indicators should still contribute if present in near-miss mode.
    signal_entries.extend(
        _score_reason_entries(mixed_signal_reasons, int(weights["mixed_bundle_bonus"]))
    )
    if mixed_signal_reasons:
        summary_entries.append(
            ("mixed_near_hits", len(mixed_signal_reasons) * int(weights["mixed_bundle_bonus"]))
        )

    raw_score = sum(weight for _signal, weight in signal_entries)
    min_score = int(scale["min"])
    max_score = int(scale["max"])
    score = max(min_score, min(max_score, raw_score))
    confidence = _confidence_from_score(score)

    sorted_top = sorted(
        summary_entries,
        key=lambda item: (abs(item[1]), item[1], item[0]),
        reverse=True,
    )
    top_signals = [f"{signal}({weight:+d})" for signal, weight in sorted_top[:top_signal_count]]

    return {
        "score": score,
        "confidence": confidence,
        "top_signals": top_signals,
        "broad_ok": broad_ok,
        "broad_reasons": broad_reasons,
        "strict_ok": strict_ok,
        "strict_excluded_reasons": strict_excluded_reasons,
        "near_miss_ok": near_ok,
        "near_miss_reasons": near_reasons,
        "mixed_it_bundle": mixed_ok,
        "mixed_reasons": mixed_reasons,
        "hardware_exclusion_ok": exclusion_ok,
    }


def classifier_snapshot(record: dict[str, str]) -> dict[str, object]:
    scored = classify_software_scored(record)
    return {
        "score": int(scored["score"]),
        "confidence": str(scored["confidence"]),
        "top_signals": list(scored["top_signals"]),
        "broad_ok": bool(scored["broad_ok"]),
        "strict_ok": bool(scored["strict_ok"]),
        "near_miss_ok": bool(scored["near_miss_ok"]),
        "reasons": {
            "broad": list(scored["broad_reasons"]),
            "strict_excluded": list(scored["strict_excluded_reasons"]),
            "near_miss": list(scored["near_miss_reasons"]),
            "mixed": list(scored["mixed_reasons"]),
        },
    }
