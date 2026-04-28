#!/usr/bin/env python3
"""Canonical source_hash for tender deduplication."""

from __future__ import annotations

import hashlib

from registry_parse import normalize_text

# Unambiguous field separator (not expected in normalized procurement text)
_SEP = "\x1e"


def compute_source_hash(row: dict[str, str]) -> str:
    """SHA-256 over normalized stable fields (hex digest, deterministic)."""
    parts = [
        normalize_text(row.get("objekti_procedurave", "")),
        normalize_text(row.get("autoriteti_kontraktues", "")),
        normalize_text(row.get("data_publikimit", "")),
        normalize_text(row.get("ora_publikimit", "")),
        normalize_text(row.get("fondi_limit_raw", "")),
        normalize_text(row.get("kodi_cpv_raw", "")),
    ]
    payload = _SEP.join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
