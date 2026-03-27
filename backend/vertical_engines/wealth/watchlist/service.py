"""Watchlist service — entry point for watchlist transition detection.

Reuses ScreenerService.screen_instrument() for re-screening.
Compares new outcomes against previous screening results to detect transitions.
Session injection pattern: caller provides db session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from vertical_engines.wealth.screener.service import ScreenerService
from vertical_engines.wealth.watchlist.models import TransitionAlert
from vertical_engines.wealth.watchlist.transition_detector import detect_transition

logger = structlog.get_logger(__name__)


class WatchlistService:
    """Detects screening outcome transitions for watchlisted instruments."""

    def __init__(
        self,
        screener: ScreenerService,
    ) -> None:
        self._screener = screener

    def check_transitions(
        self,
        instruments: list[dict[str, Any]],
        previous_outcomes: dict[uuid.UUID, str],
    ) -> list[TransitionAlert]:
        """Re-screen instruments and detect transitions.

        Pure logic — no DB access. Caller provides instrument dicts and
        previous outcomes.

        Args:
            instruments: List of dicts with instrument_id, instrument_type,
                        attributes, block_id, and name.
            previous_outcomes: Map of instrument_id -> previous overall_status.

        Returns:
            List of TransitionAlert for non-stable transitions.

        """
        alerts: list[TransitionAlert] = []
        now = datetime.now(UTC)

        for inst in instruments:
            instrument_id = inst["instrument_id"]
            instrument_name = inst.get("name", str(instrument_id))
            previous_outcome = previous_outcomes.get(instrument_id, "watchlist")

            try:
                result = self._screener.screen_instrument(
                    instrument_id=instrument_id,
                    instrument_type=inst["instrument_type"],
                    attributes=inst.get("attributes", {}),
                    block_id=inst.get("block_id"),
                )
            except Exception:
                logger.warning(
                    "watchlist_screen_failed",
                    instrument_id=str(instrument_id),
                    exc_info=True,
                )
                continue

            direction, message = detect_transition(previous_outcome, result.overall_status)

            if direction != "stable":
                alerts.append(
                    TransitionAlert(
                        instrument_id=instrument_id,
                        instrument_name=instrument_name,
                        previous_outcome=previous_outcome,
                        new_outcome=result.overall_status,
                        direction=direction,
                        message=message,
                        detected_at=now,
                    ),
                )

        return alerts
