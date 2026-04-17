"""Integration tests for Phase A construction estimator (PR-A1).

End-to-end wiring of compute_fund_level_inputs using an in-memory synthetic
market. The DB layer is stubbed so these run without a Postgres instance —
PR-A3 adds the fundamental factor model and PR-A4 adds the live 20-fund
integration against instruments_universe.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.domains.wealth.services.quant_queries import (
    COV_LOOKBACK_DAYS_5Y,
    KAPPA_ERROR_THRESHOLD,
    RISK_AVERSION_INSTITUTIONAL_DEFAULT,
    FundLevelInputs,
    IllConditionedCovarianceError,
    compute_fund_level_inputs,
)


def _build_synthetic_market(
    n_funds: int = 20,
    n_days: int = COV_LOOKBACK_DAYS_5Y,
    seed: int = 2026,
    vol: float = 0.01,
    factor_loading: float = 0.6,
) -> tuple[list[uuid.UUID], dict[str, dict[date, float]]]:
    """Generate a well-conditioned synthetic universe with one common factor.

    Returns (instrument_ids, fund_returns) compatible with _fetch_returns_by_type.
    """
    rng = np.random.default_rng(seed)
    common = rng.standard_normal(n_days) * vol
    idio = rng.standard_normal((n_days, n_funds)) * vol
    raw = factor_loading * common[:, None] + np.sqrt(1 - factor_loading**2) * idio

    ids = [uuid.uuid4() for _ in range(n_funds)]
    start = date(2021, 4, 14)
    dates = [start + timedelta(days=i) for i in range(n_days)]

    fund_returns: dict[str, dict[date, float]] = {}
    for col, iid in enumerate(ids):
        fund_returns[str(iid)] = {d: float(raw[i, col]) for i, d in enumerate(dates)}
    return ids, fund_returns


@pytest.mark.asyncio
async def test_compute_fund_level_inputs_happy_path_20_fund_synthetic() -> None:
    """20 funds × 5Y synthetic data returns a well-conditioned FundLevelInputs."""
    ids, returns = _build_synthetic_market(n_funds=20)
    db = AsyncMock()

    with patch(
        "app.domains.wealth.services.quant_queries._fetch_returns_by_type",
        new=AsyncMock(return_value=(returns, "log")),
    ), patch(
        "app.domains.wealth.services.quant_queries._fetch_return_horizons",
        new=AsyncMock(return_value={
            str(iid): {"10y": 0.08, "5y": 0.07} for iid in ids
        }),
    ), patch(
        "app.domains.wealth.services.quant_queries.fetch_strategic_weights_for_funds",
        new=AsyncMock(return_value=np.full(20, 1 / 20)),
    ), patch(
        "app.domains.wealth.services.quant_queries._maybe_regime_condition_cov",
        return_value=None,
    ):
        result = await compute_fund_level_inputs(
            db, ids, profile="balanced", as_of_date=date(2026, 4, 14),
        )

    assert isinstance(result, FundLevelInputs)
    assert len(result.available_ids) == 20
    assert result.cov_matrix.shape == (20, 20)
    assert len(result.expected_returns) == 20
    assert result.condition_number < KAPPA_ERROR_THRESHOLD
    assert result.condition_number < 1e3  # synthetic market is well-conditioned
    assert result.kappa_warning_triggered is False
    assert result.kappa_error_triggered is False
    assert result.risk_aversion_gamma == RISK_AVERSION_INSTITUTIONAL_DEFAULT
    assert result.risk_aversion_source == "institutional_default"
    assert result.used_return_type == "log"
    assert result.prior_weights_used == pytest.approx({"10y": 0.5, "5y": 0.3, "eq": 0.2})
    assert result.n_funds_by_history == {"10y+": 20, "5y+": 0, "1y_only": 0}
    assert result.skewness.shape == (20,)
    assert result.excess_kurtosis.shape == (20,)
    # PSD
    assert np.linalg.eigvalsh(result.cov_matrix).min() >= 0
    # Annualized cov diagonal should be roughly (vol * sqrt(252))² = 0.01² * 252 ≈ 0.0252
    diag = np.diag(result.cov_matrix)
    assert np.all(diag > 0)
    assert 0.01 < diag.mean() < 0.06


@pytest.mark.asyncio
async def test_compute_fund_level_inputs_collinear_funds_raises() -> None:
    """Pathologically rank-deficient series must trip the kappa error guard.

    PR-A17.1 raised KAPPA_FALLBACK_THRESHOLD from 5e4 to 1e5. The previous
    rank-3-in-R^4 fixture produced kappa post-Ledoit-Wolf that was tolerable
    on the new ladder (decision='sample', no raise). Strengthen the fixture
    to rank-1-in-R^4 (all series exact duplicates of series 0) so kappa
    exceeds the pathological ceiling (1e6) even after shrinkage.
    """
    rng = np.random.default_rng(11)
    n_days = 1260
    ids = [uuid.uuid4() for _ in range(4)]
    start = date(2021, 4, 14)
    dates = [start + timedelta(days=i) for i in range(n_days)]
    returns: dict[str, dict[date, float]] = {}
    # Rank-1: every fund is an exact copy of the first series.
    base_series = rng.standard_normal(n_days) * 0.01
    for iid in ids:
        returns[str(iid)] = {d: float(base_series[i]) for i, d in enumerate(dates)}

    db = AsyncMock()
    with patch(
        "app.domains.wealth.services.quant_queries._fetch_returns_by_type",
        new=AsyncMock(return_value=(returns, "log")),
    ), patch(
        "app.domains.wealth.services.quant_queries.fetch_strategic_weights_for_funds",
        new=AsyncMock(return_value=np.full(4, 0.25)),
    ), patch(
        "app.domains.wealth.services.quant_queries._maybe_regime_condition_cov",
        return_value=None,
    ):
        with pytest.raises(IllConditionedCovarianceError):
            await compute_fund_level_inputs(
                db, ids, mu_prior="equilibrium", profile="balanced",
                as_of_date=date(2026, 4, 14),
            )


@pytest.mark.asyncio
async def test_compute_fund_level_inputs_insufficient_data_raises_value_error() -> None:
    """< MIN_OBSERVATIONS aligned trading days → ValueError."""
    ids = [uuid.uuid4() for _ in range(3)]
    start = date(2025, 1, 1)
    short = {
        str(iid): {start + timedelta(days=i): 0.001 + 0.0001 * i for i in range(50)}
        for iid in ids
    }
    db = AsyncMock()
    with patch(
        "app.domains.wealth.services.quant_queries._fetch_returns_by_type",
        new=AsyncMock(return_value=(short, "log")),
    ), patch(
        "app.domains.wealth.services.quant_queries._maybe_regime_condition_cov",
        return_value=None,
    ):
        with pytest.raises(ValueError, match="Insufficient aligned"):
            await compute_fund_level_inputs(
                db, ids, mu_prior="equilibrium",
                as_of_date=date(2026, 4, 14),
            )


@pytest.mark.asyncio
async def test_compute_fund_level_inputs_historical_1y_mode_does_not_call_thbb() -> None:
    """Legacy caller passes mu_prior='historical_1y' → skips THBB fetch."""
    ids, returns = _build_synthetic_market(n_funds=5)
    db = AsyncMock()

    thbb_mock = AsyncMock(return_value={})
    with patch(
        "app.domains.wealth.services.quant_queries._fetch_returns_by_type",
        new=AsyncMock(return_value=(returns, "log")),
    ), patch(
        "app.domains.wealth.services.quant_queries._fetch_return_horizons",
        new=thbb_mock,
    ), patch(
        "app.domains.wealth.services.quant_queries._maybe_regime_condition_cov",
        return_value=None,
    ):
        result = await compute_fund_level_inputs(
            db, ids, mu_prior="historical_1y",
            as_of_date=date(2026, 4, 14),
        )

    thbb_mock.assert_not_awaited()
    assert result.prior_weights_used == {"10y": 0.0, "5y": 0.0, "eq": 0.0}
    assert result.n_funds_by_history["1y_only"] == 5
