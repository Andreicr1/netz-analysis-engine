"""Watchlist Monitoring Engine domain models.

Frozen dataclasses for cross-boundary safety. These are NOT ORM models --
ORM models live in backend/app/domains/wealth/models/.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TransitionAlert:
    """Alert generated when a watchlisted instrument changes screening outcome."""

    instrument_id: uuid.UUID
    instrument_name: str
    previous_outcome: str  # "watchlist"
    new_outcome: str  # "pass" | "fail" | "watchlist"
    direction: str  # "improvement" | "deterioration" | "stable"
    message: str
    detected_at: datetime


@dataclass(frozen=True, slots=True)
class WatchlistRunResult:
    """Aggregate result of a watchlist monitoring run."""

    run_id: uuid.UUID
    organization_id: str
    total_screened: int
    improvements: int
    deteriorations: int
    stable: int
    alerts: tuple[TransitionAlert, ...]
    completed_at: datetime
