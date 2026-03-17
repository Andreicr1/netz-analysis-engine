"""Mandate Fit Engine domain models.

Frozen dataclasses for cross-boundary safety. These are NOT ORM models --
ORM models live in backend/app/domains/wealth/models/.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """Client investment profile for mandate fit evaluation."""

    risk_bucket: str  # "conservative" | "moderate" | "aggressive"
    esg_required: bool
    domicile_restrictions: tuple[str, ...]  # ISO country codes to EXCLUDE
    max_redemption_days: int | None  # max acceptable redemption notice (days)
    currency_restrictions: tuple[str, ...]  # allowed currencies (empty = no restriction)


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    """Result of evaluating a single mandate constraint."""

    constraint: str
    passed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class MandateFitResult:
    """Mandate fit evaluation for a single instrument."""

    instrument_id: uuid.UUID
    instrument_name: str
    eligible: bool
    suitability_score: float  # 0.0-1.0
    constraint_results: tuple[ConstraintResult, ...]
    disqualifying_reasons: tuple[str, ...]  # non-empty if not eligible


@dataclass(frozen=True, slots=True)
class MandateFitRunResult:
    """Aggregate result of mandate fit evaluation across instruments."""

    total_evaluated: int
    eligible_count: int
    ineligible_count: int
    results: tuple[MandateFitResult, ...]
