"""Underwriting derivation — pure deterministic functions.

Error contract: raises-on-failure (pure deterministic).
Standard exceptions for truly exceptional cases.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def derive_risk_band(analysis: dict[str, Any]) -> str:
    """Derive risk band from structured analysis risk factors.

    Rule:
      - >= 1 HIGH -> HIGH
      - >= 2 MEDIUM -> MEDIUM
      - Otherwise -> LOW
    """
    risks = analysis.get("riskFactors", [])
    if not isinstance(risks, list):
        risks = []

    high_count = sum(
        1 for r in risks
        if isinstance(r, dict) and (r.get("severity") or "").upper() == "HIGH"
    )
    medium_count = sum(
        1 for r in risks
        if isinstance(r, dict) and (r.get("severity") or "").upper() == "MEDIUM"
    )

    if high_count >= 1:
        return "HIGH"
    if medium_count >= 2:
        return "MEDIUM"
    return "LOW"


def confidence_to_level(score: float) -> str:
    """Map a 0.0-1.0 confidence score to HIGH / MEDIUM / LOW."""
    if score >= 0.70:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def compute_evidence_pack_hash(evidence_pack: dict[str, Any]) -> str:
    """Compute a stable SHA-256 hash of the evidence pack JSON."""
    canonical = json.dumps(evidence_pack, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
