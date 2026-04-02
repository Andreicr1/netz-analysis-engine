"""Screener engine domain models.

Frozen dataclasses for cross-boundary safety. These are NOT ORM models —
ORM models live in backend/app/domains/wealth/models/.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CriterionResult:
    """Result of evaluating a single screening criterion."""

    criterion: str
    expected: str
    actual: str
    passed: bool
    layer: int


@dataclass(frozen=True, slots=True)
class InstrumentScreeningResult:
    """Full screening outcome for one instrument."""

    instrument_id: uuid.UUID
    instrument_type: str
    overall_status: str  # PASS | FAIL | WATCHLIST
    score: float | None
    failed_at_layer: int | None
    layer_results: list[CriterionResult]
    required_analysis_type: str  # dd_report | bond_brief | none

    @property
    def layer_results_dict(self) -> list[dict[str, object]]:
        """Serialize layer_results for JSONB storage."""
        return [
            {
                "criterion": r.criterion,
                "expected": r.expected,
                "actual": r.actual,
                "passed": r.passed,
                "layer": r.layer,
            }
            for r in self.layer_results
        ]


@dataclass(frozen=True, slots=True)
class ScreeningRunResult:
    """Aggregate result of a screening run."""

    run_id: uuid.UUID
    organization_id: uuid.UUID
    run_type: str
    instrument_count: int
    config_hash: str
    results: list[InstrumentScreeningResult] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
