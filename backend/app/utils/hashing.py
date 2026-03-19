"""Deterministic hashing utilities for quant reproducibility."""
from __future__ import annotations

import hashlib
from datetime import date


def compute_input_hash(values: list[float]) -> str:
    """SHA-256 hex digest of a list of floats, for cache-key / audit trail."""
    payload = ",".join(f"{v:.10f}" for v in values)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def derive_seed(profile: str, calc_date: date) -> int:
    """Deterministic seed from profile + date for reproducible optimization."""
    payload = f"{profile}:{calc_date.isoformat()}"
    digest = hashlib.sha256(payload.encode()).digest()
    return int.from_bytes(digest[:4], "big")
