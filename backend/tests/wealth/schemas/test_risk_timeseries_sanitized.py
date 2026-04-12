"""Tests for the RiskTimeseriesOut sanitise retrofit.

Phase 2 Session C commit 2 — audit §C.2 flagged this schema as
leaking raw ``volatility_garch`` and regime enum strings to the wire.
These tests lock in the sanitised shape.
"""
from __future__ import annotations

from datetime import date

from app.domains.wealth.schemas.risk_timeseries import RiskTimeseriesOut


def _make_payload() -> RiskTimeseriesOut:
    return RiskTimeseriesOut(
        instrument_id="00000000-0000-0000-0000-000000000001",
        ticker="SPY",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 12, 31),
        drawdown=[{"time": "2024-06-01", "value": -3.5}],
        volatility_garch=[{"time": "2024-06-01", "value": 14.2}],
        regime_prob=[
            {"time": "2024-06-01", "value": 0.75, "regime": "RISK_ON"},
            {"time": "2024-07-01", "value": 0.60, "regime": "RISK_OFF"},
            {"time": "2024-08-01", "value": 0.10, "regime": "CRISIS"},
        ],
    )


def test_volatility_garch_wire_key_is_conditional_volatility() -> None:
    payload = _make_payload()
    dumped = payload.model_dump(by_alias=True)
    assert "conditional_volatility" in dumped
    assert "volatility_garch" not in dumped
    assert dumped["conditional_volatility"] == [
        {"time": "2024-06-01", "value": 14.2},
    ]


def test_internal_field_still_accessible_as_volatility_garch() -> None:
    """Python-side code (tests, routes) keeps using the stable name."""
    payload = _make_payload()
    assert payload.volatility_garch == [{"time": "2024-06-01", "value": 14.2}]


def test_regime_prob_enums_translated_to_tri_state() -> None:
    payload = _make_payload()
    dumped = payload.model_dump(by_alias=True)
    regimes = [p["regime"] for p in dumped["regime_prob"]]
    assert regimes == ["Expansion", "Cautious", "Stress"]


def test_model_dump_json_has_no_banned_jargon() -> None:
    """Full-payload string grep — no raw jargon substrings may appear."""
    payload = _make_payload()
    json_str = payload.model_dump_json(by_alias=True)
    banned = [
        "volatility_garch",
        "RISK_ON",
        "RISK_OFF",
        "CRISIS",
        "EXPANSION",
        "NEUTRAL",
    ]
    for token in banned:
        assert token not in json_str, f"Banned jargon {token!r} leaked: {json_str}"


def test_unknown_regime_passes_through_unchanged() -> None:
    """New backend regime states must remain visible until labelled."""
    payload = RiskTimeseriesOut(
        instrument_id="00000000-0000-0000-0000-000000000001",
        ticker=None,
        from_date=date(2024, 1, 1),
        to_date=date(2024, 12, 31),
        drawdown=[],
        volatility_garch=[],
        regime_prob=[{"time": "2024-06-01", "value": 0.5, "regime": "STAGFLATION"}],
    )
    dumped = payload.model_dump(by_alias=True)
    assert dumped["regime_prob"][0]["regime"] == "STAGFLATION"
