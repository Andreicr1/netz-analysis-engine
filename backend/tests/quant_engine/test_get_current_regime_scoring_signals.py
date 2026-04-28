"""Codex catch #8 — has_scoring_signal filter (PR-Q74).

get_current_regime must gate on _REGIME_SCORING_INPUTS (financial + slow
signals), not on ANY non-None input. cpi_yoy alone is an INFLATION override
input that doesn't independently score the stress dimension — admitting it
would force classify_regime_multi_signal's internal RISK_OFF default instead
of letting the caller fallback to a richer source.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quant_engine.regime_service import _REGIME_SCORING_INPUTS


@pytest.mark.asyncio
async def test_cpi_only_does_not_admit_classification():
    """If only cpi_yoy is fresh, get_current_regime falls through to caller
    fallback instead of forcing classify's internal RISK_OFF default."""
    # All scoring signals None, only cpi_yoy present
    fake_inputs = {field: None for field in _REGIME_SCORING_INPUTS}
    fake_inputs["cpi_yoy"] = 3.5

    with (
        patch(
            "quant_engine.regime_service.build_regime_inputs",
            new_callable=AsyncMock,
            return_value=fake_inputs,
        ),
        patch(
            "quant_engine.regime_service.classify_regime_multi_signal",
        ) as mock_classify,
    ):
        from quant_engine.regime_service import get_current_regime

        db = AsyncMock()
        result = await get_current_regime(db, fallback_regime="RISK_ON")

    mock_classify.assert_not_called()
    assert result.regime == "RISK_ON"  # caller-supplied fallback


@pytest.mark.asyncio
async def test_vix_alone_admits_classification():
    """One scoring signal (vix) → classify is invoked."""
    fake_inputs = {field: None for field in _REGIME_SCORING_INPUTS}
    fake_inputs["cpi_yoy"] = None
    fake_inputs["vix"] = 25.0

    with (
        patch(
            "quant_engine.regime_service.build_regime_inputs",
            new_callable=AsyncMock,
            return_value=fake_inputs,
        ),
        patch(
            "quant_engine.regime_service.classify_regime_multi_signal",
            return_value=("RISK_OFF", {"decision": "test"}, []),
        ) as mock_classify,
    ):
        from quant_engine.regime_service import get_current_regime

        # `as_of_row = (await db.execute(stmt)).scalar_one_or_none()` —
        # db.execute is an awaitable returning a Result-like object whose
        # scalar_one_or_none() is sync.
        result_obj = MagicMock()
        result_obj.scalar_one_or_none.return_value = date(2026, 4, 28)
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_obj)

        result = await get_current_regime(db, fallback_regime="RISK_ON")

    mock_classify.assert_called_once()
    assert result.regime == "RISK_OFF"


@pytest.mark.asyncio
async def test_all_signals_missing_falls_back():
    """Total absence → caller fallback (no internal default forced)."""
    fake_inputs = {field: None for field in _REGIME_SCORING_INPUTS}
    fake_inputs["cpi_yoy"] = None

    with (
        patch(
            "quant_engine.regime_service.build_regime_inputs",
            new_callable=AsyncMock,
            return_value=fake_inputs,
        ),
        patch(
            "quant_engine.regime_service.classify_regime_multi_signal",
        ) as mock_classify,
    ):
        from quant_engine.regime_service import get_current_regime

        db = AsyncMock()
        result = await get_current_regime(db, fallback_regime="RISK_OFF")

    mock_classify.assert_not_called()
    assert result.regime == "RISK_OFF"


def test_regime_scoring_inputs_matches_classify_signature():
    """_REGIME_SCORING_INPUTS must match the fields that classify_regime_multi_signal
    actually scores (all params except cpi_yoy and thresholds/config)."""
    expected = {
        "vix", "hy_oas", "energy_shock", "yield_curve_spread",
        "dxy_zscore", "baa_spread", "fed_funds_delta_6m",
        "cfnai", "icsa_zscore", "sahm_rule", "credit_impulse", "permits_roc",
    }
    assert expected == _REGIME_SCORING_INPUTS
