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
def _rules() -> dict[str, list[str]]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


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


@lru_cache(maxsize=1)
def _keyword_regex() -> re.Pattern[str]:
    return re.compile("|".join(_rules()["include_keyword_patterns"]), re.IGNORECASE)


@lru_cache(maxsize=1)
def _exclude_regex() -> re.Pattern[str]:
    return re.compile("|".join(_rules()["exclude_keyword_patterns"]), re.IGNORECASE)


@lru_cache(maxsize=1)
def _near_miss_regex() -> re.Pattern[str]:
    return re.compile("|".join(_rules()["near_miss_keyword_patterns"]), re.IGNORECASE)


def _keyword_hits(text: str, regex: re.Pattern[str]) -> list[str]:
    """Collect matched keyword spans; use finditer so alternation never yields empty captures."""
    reasons: list[str] = []
    for m in regex.finditer(text):
        token = m.group(0)
        if token and f"kw:{token}" not in reasons:
            reasons.append(f"kw:{token}")
    return reasons


def _cpv_inclusion_reasons(cpv_text: str) -> list[str]:
    reasons: list[str] = []
    for cpv in parse_cpv_codes(cpv_text):
        digits = cpv.split("-")[0]
        if any(digits.startswith(prefix) for prefix in _rules()["include_cpv_prefixes"]):
            r = f"cpv:{cpv}"
            if r not in reasons:
                reasons.append(r)
    return reasons


def _cpv_exclusion_reasons(cpv_text: str) -> list[str]:
    reasons: list[str] = []
    for cpv in parse_cpv_codes(cpv_text):
        digits = cpv.split("-")[0]
        if any(digits.startswith(prefix) for prefix in _rules()["exclude_cpv_prefixes"]):
            r = f"exclude_cpv:{cpv}"
            if r not in reasons:
                reasons.append(r)
    return reasons


def _cpv_near_miss_reasons(cpv_text: str) -> list[str]:
    reasons: list[str] = []
    for cpv in parse_cpv_codes(cpv_text):
        digits = cpv.split("-")[0]
        if any(digits.startswith(prefix) for prefix in _rules()["near_miss_cpv_prefixes"]):
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


def classify_software_broad(record: dict[str, str]) -> tuple[bool, list[str]]:
    """
    Return whether the row is software/IT-related (broad) and match reasons.

    Reasons use ``kw:`` / ``cpv:`` prefixes so exports and QC files stay
    consistent with the legacy script.
    """
    text = _combined_text(record)
    regex = _keyword_regex()
    reasons = _keyword_hits(text, regex)
    reasons.extend(r for r in _cpv_inclusion_reasons(record.get("kodi_cpv_raw", "")) if r not in reasons)
    return (len(reasons) > 0), reasons


def mixed_it_bundle_signal(record: dict[str, str]) -> tuple[bool, list[str]]:
    """
    Detect bundled tenders that mix IT/software relevance with hardware-repair signals.

    These rows are review-worthy and should not be silently ignored in strict-like flows.
    """
    broad_ok, broad_reasons = classify_software_broad(record)
    excluded_ok, excluded_reasons = hardware_repair_exclusion_signals(record)
    if broad_ok and excluded_ok:
        return True, [*broad_reasons, *excluded_reasons]
    return False, []


def hardware_repair_exclusion_signals(record: dict[str, str]) -> tuple[bool, list[str]]:
    """
    Hardware-repair / maintenance signals used for the strict filter.

    Exposed for validation invariants; same rules as legacy ``should_exclude``.
    """
    text = _combined_text(record)
    reasons = _exclude_keyword_hits(text, _exclude_regex())
    for r in _cpv_exclusion_reasons(record.get("kodi_cpv_raw", "")):
        if r not in reasons:
            reasons.append(r)
    return (len(reasons) > 0), reasons


def classify_software_strict(
    record: dict[str, str],
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
    broad_ok, broad_reasons = classify_software_broad(record)
    if not broad_ok:
        return False, [], []

    excluded_ok, excluded_reasons = hardware_repair_exclusion_signals(record)
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


def classify_near_miss(record: dict[str, str]) -> tuple[bool, list[str]]:
    """
    Rows close to software relevance but not strict-accepted.

    - Include mixed IT bundles (broad + hardware-repair signals).
    - Include weak proximity signals when broad rules do not fire.
    """
    strict_ok, _broad_reasons, _excluded = classify_software_strict(record)
    if strict_ok:
        return False, []

    mixed_ok, mixed_reasons = mixed_it_bundle_signal(record)
    if mixed_ok:
        return True, [f"mixed_it_bundle:{r}" for r in mixed_reasons]

    broad_ok, _ = classify_software_broad(record)
    if broad_ok:
        return False, []

    text = _combined_text(record)
    reasons = [f"near_kw:{m.group(0)}" for m in _near_miss_regex().finditer(text)]
    for r in _cpv_near_miss_reasons(record.get("kodi_cpv_raw", "")):
        if r not in reasons:
            reasons.append(r)

    deduped: list[str] = []
    for r in reasons:
        if r not in deduped:
            deduped.append(r)
    return (len(deduped) > 0), deduped
