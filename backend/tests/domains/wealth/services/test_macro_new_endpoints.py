"""Unit tests for new macro endpoints.

These tests do not hit the DB. They cover schema serialization and small helper logic.
"""

import datetime

import pytest

from app.domains.wealth.schemas.macro import (
    CbCalendarResponse,
    CbEvent,
    CrossAssetPoint,
    CrossAssetResponse,
    RegimeTrailPoint,
    RegimeTrailResponse,
)


def test_cross_asset_point_schema() -> None:
    p = CrossAssetPoint(
        symbol="DGS10",
        name="US 10Y",
        sector="RATES",
        last_value=4.32,
        change_pct=-0.021,
        unit="%",
        sparkline=[4.10, 4.15, 4.20, 4.32],
    )
    assert p.sector == "RATES"
    assert p.last_value == pytest.approx(4.32)
    assert len(p.sparkline) == 4


def test_cross_asset_response_empty() -> None:
    r = CrossAssetResponse()
    assert r.assets == []
    assert r.as_of_date is None


def test_regime_trail_point_schema() -> None:
    p = RegimeTrailPoint(
        as_of_date=datetime.date(2025, 1, 15),
        g=0.42,
        i=-0.18,
        stress=35.0,
    )
    assert -1.0 <= p.g <= 1.0
    assert -1.0 <= p.i <= 1.0


def test_regime_trail_response_empty() -> None:
    r = RegimeTrailResponse()
    assert r.points == []
    assert r.region == "US"


def test_score_to_gi_conversion() -> None:
    """Percentile 0-100 -> [-1, +1]: 50 -> 0, 100 -> 1, 0 -> -1."""

    def _to_gi(score: float) -> float:
        return (score / 100.0) * 2.0 - 1.0

    assert _to_gi(50) == pytest.approx(0.0)
    assert _to_gi(100) == pytest.approx(1.0)
    assert _to_gi(0) == pytest.approx(-1.0)


def test_cb_event_schema() -> None:
    ev = CbEvent(
        central_bank="Fed",
        meeting_date=datetime.date(2026, 5, 7),
        current_rate_pct=4.50,
        expected_change_bps=-25,
    )
    assert ev.central_bank == "Fed"
    assert ev.expected_change_bps == -25
    assert ev.importance == "HIGH"


def test_cb_calendar_response_empty() -> None:
    r = CbCalendarResponse()
    assert r.events == []
