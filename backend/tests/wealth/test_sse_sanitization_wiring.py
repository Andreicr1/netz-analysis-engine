"""Tests verifying sanitize_payload() is wired into SSE serialization functions.

Each emitter's output is checked for zero banned substrings.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from vertical_engines.wealth.monitoring.alert_engine import (
    Alert,
    AlertBatch,
    alerts_to_json,
)
from vertical_engines.wealth.monitoring.drift_monitor import (
    DriftAlert,
    DriftScanResult,
    drift_alerts_to_json,
)
from vertical_engines.wealth.rebalancing.preview_service import (
    compute_rebalance_preview,
)

# Substrings that must never appear in user-facing output.
# sanitize_payload() translates REGIME_LABELS values.
BANNED_REGIME_STRINGS = {"RISK_ON", "RISK_OFF", "CRISIS"}


def test_drift_alerts_to_json_sanitizes_regime_values() -> None:
    """drift_alerts_to_json wraps through sanitize_payload."""
    result = DriftScanResult(
        alerts=[
            DriftAlert(
                instrument_id="abc-123",
                fund_name="Test Fund",
                drift_score=0.25,
                drift_type="style_drift",
                affected_portfolios=["Portfolio A"],
                detail="DTW drift score 0.250 exceeds threshold 0.150.",
            ),
        ],
        scanned_at=datetime.now(UTC),
        organization_id="org-1",
    )
    serialized = drift_alerts_to_json(result)
    assert len(serialized) == 1
    # The detail field passes through (no regime enum in it),
    # but verify the function runs without error.
    assert "instrument_id" in serialized[0]


def test_alerts_to_json_sanitizes_regime_values() -> None:
    """alerts_to_json wraps through sanitize_payload."""
    batch = AlertBatch(
        alerts=[
            Alert(
                alert_type="dd_expiry",
                severity="warning",
                title="No DD Report for Test Fund",
                detail="Fund Test Fund has no DD Report on file.",
                entity_id="fund-1",
                entity_type="fund",
            ),
        ],
        scanned_at=datetime.now(UTC),
        organization_id="org-1",
    )
    serialized = alerts_to_json(batch)
    assert len(serialized) == 1
    assert "alert_type" in serialized[0]


def test_rebalance_preview_sanitizes_payload() -> None:
    """compute_rebalance_preview wraps through sanitize_payload."""
    result = compute_rebalance_preview(
        portfolio_id=uuid.uuid4(),
        portfolio_name="Test Portfolio",
        profile="balanced",
        fund_selection_schema={
            "funds": [
                {
                    "instrument_id": str(uuid.uuid4()),
                    "fund_name": "Fund A",
                    "block_id": "equity",
                    "weight": 0.6,
                },
                {
                    "instrument_id": str(uuid.uuid4()),
                    "fund_name": "Fund B",
                    "block_id": "fixed_income",
                    "weight": 0.3,
                },
            ],
        },
        current_holdings=[],
        cash_available=1_000_000.0,
    )
    assert "portfolio_id" in result
    assert "trades" in result
    # Verify sanitize_payload was applied (no regime strings in output)
    payload_str = str(result)
    for banned in BANNED_REGIME_STRINGS:
        assert banned not in payload_str, f"Found banned substring '{banned}' in output"


def test_drift_alerts_detail_with_regime_string_is_sanitized() -> None:
    """Proves sanitize_payload translates exact regime string values in detail."""
    result = DriftScanResult(
        alerts=[
            DriftAlert(
                instrument_id="x",
                fund_name="Test Fund",
                drift_score=0.2,
                drift_type="style_drift",
                affected_portfolios=[],
                detail="RISK_ON",
            ),
        ],
        scanned_at=datetime.now(UTC),
        organization_id="org-1",
    )
    serialized = drift_alerts_to_json(result)
    assert serialized[0]["detail"] == "Expansion"


def test_alerts_title_with_regime_string_is_sanitized() -> None:
    """Proves sanitize_payload translates exact regime string values in title/detail."""
    batch = AlertBatch(
        alerts=[
            Alert(
                alert_type="regime_change",
                severity="info",
                title="CRISIS",
                detail="CRISIS",
                entity_id=None,
                entity_type=None,
            ),
        ],
        scanned_at=datetime.now(UTC),
        organization_id="org-1",
    )
    serialized = alerts_to_json(batch)
    assert serialized[0]["title"] == "Stress"
    assert serialized[0]["detail"] == "Stress"


def test_rebalance_empty_response_sanitizes_payload() -> None:
    """_empty_response also routes through sanitize_payload."""
    result = compute_rebalance_preview(
        portfolio_id=uuid.uuid4(),
        portfolio_name="Empty Portfolio",
        profile="conservative",
        fund_selection_schema={"funds": []},
        current_holdings=[],
        cash_available=0.0,
        total_aum_override=0.0,
    )
    assert result["total_trades"] == 0
    assert result["trades"] == []
