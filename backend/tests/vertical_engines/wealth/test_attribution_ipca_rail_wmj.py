"""WMJ-013 / WMJ-014 hardening tests for the IPCA attribution rail.

1. test_load_ipca_fit_propagates_degraded_flag
2. test_ipca_rail_marks_degraded_when_fit_degraded
3. test_ipca_dates_none_marks_degraded
4. test_ipca_option_a_uses_regression_r2_as_confidence
5. test_ipca_result_includes_residual
6. test_ipca_option_a_dates_none_marks_degraded
7. test_ipca_serialization_round_trip_with_new_fields
"""
from __future__ import annotations

from collections import namedtuple
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from quant_engine.ipca.fit import IPCAFit
from vertical_engines.wealth.attribution.ipca_rail import (
    _run_ipca_rail_option_a,
    load_latest_ipca_fit,
    run_ipca_rail,
)
from vertical_engines.wealth.attribution.models import AttributionRequest, IPCAResult
from vertical_engines.wealth.attribution.service import (
    _deserialize_result,
    _serialize_result,
)

# ---------------------------------------------------------------------------
# Helpers (shared with test_attribution_ipca_rail_unit.py patterns)
# ---------------------------------------------------------------------------

_RefRow = namedtuple("_RefRow", ["ref_period"])
_CSRow = namedtuple("_CSRow", [
    "instrument_id", "size", "value", "momentum",
    "quality", "investment", "profitability",
])
_HRow = namedtuple("_HRow", ["pct_of_nav", "instrument_id"])
_NavRow = namedtuple("_NavRow", ["month", "nav_eom"])


class _FakeResult:
    """Minimal mock for sqlalchemy CursorResult."""

    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


def _mock_cik(padded: str | None):
    from data_providers.identity.resolver import CikIdentity
    if padded is None:
        return CikIdentity(padded=None, unpadded=None)
    unpadded = padded.lstrip("0") or "0"
    return CikIdentity(padded=padded, unpadded=unpadded)


def _make_request(**overrides) -> AttributionRequest:
    defaults = dict(
        fund_instrument_id=uuid4(),
        asof=date(2026, 4, 19),
        fund_asset_class="Equity",
        fund_cik="0001234567",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 4, 19),
    )
    defaults.update(overrides)
    return AttributionRequest(**defaults)


_SENTINEL = object()


def _make_fit(
    oos_r_squared: float = 0.03,
    K: int = 6,
    degraded: bool = False,
    degraded_reason: str | None = None,
    dates: pd.DatetimeIndex | None | object = _SENTINEL,
) -> IPCAFit:
    n_periods = 30
    if dates is _SENTINEL:
        dates = pd.date_range("2024-01-31", periods=n_periods, freq="ME")
    return IPCAFit(
        gamma=np.eye(K, dtype=np.float64),
        factor_returns=np.random.default_rng(42).standard_normal((K, n_periods)),
        K=K,
        intercept=False,
        r_squared=0.5,
        oos_r_squared=oos_r_squared,
        converged=True,
        n_iterations=50,
        dates=dates,
        degraded=degraded,
        degraded_reason=degraded_reason,
    )


def _nav_rows_spanning_2024_to_2026():
    """Generate NAV rows spanning 2024-01 through 2026-04 (enough for regression)."""
    rows = []
    for year in (2023, 2024, 2025):
        for m in range(1, 13):
            rows.append(_NavRow(month=date(year, m, 1), nav_eom=100.0 + year * 0.01 + m * 0.5))
    for m in range(1, 5):
        rows.append(_NavRow(month=date(2026, m, 1), nav_eom=120.0 + m * 0.3))
    return rows


# ---------------------------------------------------------------------------
# WMJ-013: degraded flag propagation from DB → IPCAFit → IPCAResult
# ---------------------------------------------------------------------------


_FitRow = namedtuple("_FitRow", [
    "k_factors", "gamma_loadings", "factor_returns",
    "oos_r_squared", "converged", "n_iterations",
    "degraded", "degraded_reason",
])


@pytest.mark.asyncio
async def test_load_ipca_fit_propagates_degraded_flag():
    """1. load_latest_ipca_fit propagates degraded/degraded_reason from DB row."""
    K = 3
    gamma = np.eye(K).tolist()
    factor_returns_dict = {
        "dates": ["2024-01-31", "2024-02-28"],
        "values": np.random.default_rng(1).standard_normal((K, 2)).tolist(),
    }
    row = _FitRow(
        k_factors=K,
        gamma_loadings=gamma,
        factor_returns=factor_returns_dict,
        oos_r_squared=0.03,
        converged=True,
        n_iterations=50,
        degraded=True,
        degraded_reason="insufficient_dates_40_lt_72",
    )

    async def mock_execute(stmt, params=None):
        return _FakeResult([row])

    db = AsyncMock()
    db.execute = mock_execute

    fit = await load_latest_ipca_fit(db, "Equity")
    assert fit is not None
    assert fit.degraded is True
    assert fit.degraded_reason == "insufficient_dates_40_lt_72"


@pytest.mark.asyncio
async def test_load_ipca_fit_defaults_degraded_false():
    """1b. When DB row has degraded=None, IPCAFit defaults to False."""
    K = 3
    gamma = np.eye(K).tolist()
    factor_returns_dict = {
        "dates": ["2024-01-31", "2024-02-28"],
        "values": np.random.default_rng(1).standard_normal((K, 2)).tolist(),
    }
    row = _FitRow(
        k_factors=K,
        gamma_loadings=gamma,
        factor_returns=factor_returns_dict,
        oos_r_squared=0.05,
        converged=True,
        n_iterations=50,
        degraded=None,
        degraded_reason=None,
    )

    async def mock_execute(stmt, params=None):
        return _FakeResult([row])

    db = AsyncMock()
    db.execute = mock_execute

    fit = await load_latest_ipca_fit(db, "Equity")
    assert fit is not None
    assert fit.degraded is False
    assert fit.degraded_reason is None


# ---------------------------------------------------------------------------
# WMJ-013: degraded fit → degraded IPCAResult (Option B path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ipca_rail_marks_degraded_when_fit_degraded():
    """2. A degraded fit produces a degraded IPCAResult (not None)."""
    fit = _make_fit(
        oos_r_squared=0.03,
        degraded=True,
        degraded_reason="insufficient_dates_40_lt_72",
    )
    req = _make_request()
    fund_id = req.fund_instrument_id

    ref_date = date(2026, 3, 31)
    cs_rows = [
        _CSRow(instrument_id=fund_id, size=1.0, value=1.0, momentum=1.0,
               quality=1.0, investment=1.0, profitability=1.0),
    ]
    h_rows = [_HRow(pct_of_nav=10.0, instrument_id=fund_id)]

    call_count = 0

    async def mock_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _FakeResult([_RefRow(ref_period=ref_date)])
        elif call_count == 2:
            return _FakeResult(cs_rows)
        elif call_count == 3:
            return _FakeResult(h_rows)
        return _FakeResult([])

    db = AsyncMock()
    db.execute = mock_execute

    _P = "vertical_engines.wealth.attribution.ipca_rail"
    with patch(f"{_P}.load_latest_ipca_fit", return_value=fit), \
         patch(f"{_P}.resolve_cik", new=AsyncMock(return_value=_mock_cik("0001234567"))), \
         patch(f"{_P}.latest_period_for_cik", return_value=date(2026, 3, 31)), \
         patch(f"{_P}._estimate_alpha_fixed_beta", new=AsyncMock(return_value=0.001)):
        result = await run_ipca_rail(req, db)

    assert result is not None, "Degraded fit should produce a result, not None"
    assert result.degraded is True
    assert "insufficient_dates" in result.degraded_reason


# ---------------------------------------------------------------------------
# WMJ-014C: fit.dates=None → degraded with full_matrix_fallback reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ipca_dates_none_marks_degraded():
    """3. fit.dates=None → result marked degraded with full_matrix_fallback."""
    fit = _make_fit(oos_r_squared=0.03, dates=None)
    req = _make_request()
    fund_id = req.fund_instrument_id

    ref_date = date(2026, 3, 31)
    cs_rows = [
        _CSRow(instrument_id=fund_id, size=1.0, value=1.0, momentum=1.0,
               quality=1.0, investment=1.0, profitability=1.0),
    ]
    h_rows = [_HRow(pct_of_nav=10.0, instrument_id=fund_id)]

    call_count = 0

    async def mock_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _FakeResult([_RefRow(ref_period=ref_date)])
        elif call_count == 2:
            return _FakeResult(cs_rows)
        elif call_count == 3:
            return _FakeResult(h_rows)
        return _FakeResult([])

    db = AsyncMock()
    db.execute = mock_execute

    _P = "vertical_engines.wealth.attribution.ipca_rail"
    with patch(f"{_P}.load_latest_ipca_fit", return_value=fit), \
         patch(f"{_P}.resolve_cik", new=AsyncMock(return_value=_mock_cik("0001234567"))), \
         patch(f"{_P}.latest_period_for_cik", return_value=date(2026, 3, 31)), \
         patch(f"{_P}._estimate_alpha_fixed_beta", new=AsyncMock(return_value=0.0)):
        result = await run_ipca_rail(req, db)

    assert result is not None, "dates=None should produce a degraded result, not None"
    assert result.degraded is True
    assert "ipca_dates_unavailable_full_matrix_fallback" in result.degraded_reason


# ---------------------------------------------------------------------------
# WMJ-014A: Option A uses regression R² as confidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ipca_option_a_uses_regression_r2_as_confidence():
    """4. Option A confidence = OLS regression R², not universe OOS R²."""
    fit = _make_fit(oos_r_squared=0.03, K=4)
    # Rebuild fit with known K=4 gamma
    fit = IPCAFit(
        gamma=fit.gamma[:, :4],
        factor_returns=np.random.default_rng(99).standard_normal((4, 30)),
        K=4,
        intercept=False,
        r_squared=0.5,
        oos_r_squared=0.03,
        converged=True,
        n_iterations=50,
        dates=pd.date_range("2024-01-31", periods=30, freq="ME"),
    )

    req = _make_request()
    nav_rows = _nav_rows_spanning_2024_to_2026()

    async def mock_execute(stmt, params=None):
        return _FakeResult(nav_rows)

    db = AsyncMock()
    db.execute = mock_execute

    result = await _run_ipca_rail_option_a(req, db, fit)
    assert result is not None, "Option A returned None"
    # Confidence must be the regression R², not the universe OOS R² (0.03).
    # OLS R² on synthetic data is typically much higher than 0.03.
    # The key assertion is that confidence != fit.oos_r_squared
    assert result.confidence != fit.oos_r_squared, (
        f"Confidence {result.confidence} matches universe OOS R² {fit.oos_r_squared} — "
        "should be regression R² instead"
    )
    # Regression R² is between 0 and 1
    assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# WMJ-014B: residual field populated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ipca_result_includes_residual():
    """5. IPCAResult.residual is populated and approximately zero for Option B."""
    fit = _make_fit(oos_r_squared=0.03, K=6)
    req = _make_request()
    fund_id = req.fund_instrument_id

    ref_date = date(2026, 3, 31)
    cs_rows = [
        _CSRow(instrument_id=fund_id, size=1.0, value=1.0, momentum=1.0,
               quality=1.0, investment=1.0, profitability=1.0),
    ]
    h_rows = [_HRow(pct_of_nav=10.0, instrument_id=fund_id)]

    call_count = 0

    async def mock_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _FakeResult([_RefRow(ref_period=ref_date)])
        elif call_count == 2:
            return _FakeResult(cs_rows)
        elif call_count == 3:
            return _FakeResult(h_rows)
        return _FakeResult([])

    db = AsyncMock()
    db.execute = mock_execute

    _P = "vertical_engines.wealth.attribution.ipca_rail"
    with patch(f"{_P}.load_latest_ipca_fit", return_value=fit), \
         patch(f"{_P}.resolve_cik", new=AsyncMock(return_value=_mock_cik("0001234567"))), \
         patch(f"{_P}.latest_period_for_cik", return_value=date(2026, 3, 31)), \
         patch(f"{_P}._estimate_alpha_fixed_beta", new=AsyncMock(return_value=0.001)):
        result = await run_ipca_rail(req, db)

    assert result is not None, "Expected IPCA result"
    assert result.residual is not None, "residual must be populated"
    # For Option B, residual = sum(beta_k * f_k_mean) + alpha - (beta' f_t_mean + alpha)
    # This is mathematically zero because contribution_per_factor = beta * f_t_mean.
    assert abs(result.residual) < 1e-10, (
        f"Residual {result.residual} is not near zero for a well-decomposed model"
    )


# ---------------------------------------------------------------------------
# WMJ-014C: Option A with dates=None → degraded result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ipca_option_a_dates_none_marks_degraded():
    """6. Option A with fit.dates=None produces degraded result."""
    K = 4
    fit = IPCAFit(
        gamma=np.eye(6, K, dtype=np.float64),
        factor_returns=np.random.default_rng(77).standard_normal((K, 30)),
        K=K,
        intercept=False,
        r_squared=0.5,
        oos_r_squared=0.03,
        converged=True,
        n_iterations=50,
        dates=None,  # <-- dates unavailable
    )

    req = _make_request()
    nav_rows = _nav_rows_spanning_2024_to_2026()

    async def mock_execute(stmt, params=None):
        return _FakeResult(nav_rows)

    db = AsyncMock()
    db.execute = mock_execute

    result = await _run_ipca_rail_option_a(req, db, fit)
    assert result is not None, "Option A with dates=None should produce a degraded result"
    assert result.degraded is True
    assert "ipca_dates_unavailable_full_matrix_fallback" in result.degraded_reason


# ---------------------------------------------------------------------------
# Serialization round-trip with new fields
# ---------------------------------------------------------------------------


def test_ipca_serialization_round_trip_with_new_fields():
    """7. IPCA result with degraded/residual fields survives serialize→deserialize."""
    from vertical_engines.wealth.attribution.models import (
        FundAttributionResult,
        RailBadge,
    )

    fund_id = uuid4()
    ipca = IPCAResult(
        factor_names=["Size", "Value", "Momentum"],
        factor_exposures=[0.1, 0.2, 0.3],
        factor_returns_contribution=[0.01, 0.02, 0.03],
        alpha=0.005,
        confidence=0.65,
        degraded=True,
        degraded_reason="insufficient_dates_40_lt_72",
        residual=-0.0001,
    )
    original = FundAttributionResult(
        fund_instrument_id=fund_id,
        asof=date(2026, 4, 19),
        badge=RailBadge.RAIL_IPCA,
        ipca=ipca,
        metadata={"n_factors": "3"},
    )

    serialized = _serialize_result(original)
    restored = _deserialize_result(serialized)

    assert restored.badge == RailBadge.RAIL_IPCA
    assert restored.ipca is not None
    assert restored.ipca.degraded is True
    assert restored.ipca.degraded_reason == "insufficient_dates_40_lt_72"
    assert restored.ipca.residual is not None
    assert abs(restored.ipca.residual - (-0.0001)) < 1e-10
    assert restored.ipca.factor_names == ["Size", "Value", "Momentum"]
    assert abs(restored.ipca.alpha - 0.005) < 1e-10
    assert abs(restored.ipca.confidence - 0.65) < 1e-10
