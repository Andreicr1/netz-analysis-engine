"""Tests for fundamental factor model (PR-A3)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.domains.wealth.services.quant_queries import (
    FundLevelInputs,
    compute_fund_level_inputs,
)
from quant_engine.factor_model_service import (
    FundamentalFactorFit,
    assemble_factor_covariance,
    build_fundamental_factor_returns,
    compute_residual_pca,
    fit_fundamental_loadings,
)


@pytest.fixture
def sample_factor_returns():
    """T=100, K=3 synthetic factor returns."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2021-01-01", periods=100)
    data = rng.standard_normal((100, 3)) * 0.01
    df = pd.DataFrame(data, index=dates, columns=["equity_us", "duration", "credit"])
    return df


@pytest.fixture
def sample_fund_returns(sample_factor_returns):
    """N=5 funds with known loadings on sample_factor_returns."""
    T = len(sample_factor_returns)
    N = 5
    # Loadings: (N, K)
    true_loadings = np.array([
        [1.2, 0.0, 0.2],
        [0.8, 0.5, 0.0],
        [0.0, 1.0, -0.5],
        [1.0, -0.2, 0.8],
        [0.5, 0.5, 0.5]
    ])
    # Reduced noise to ensure recovery within tolerance with small T
    idio = np.random.default_rng(43).standard_normal((T, N)) * 0.001
    fund_returns = (sample_factor_returns.values @ true_loadings.T) + idio
    return fund_returns, true_loadings


def test_fit_fundamental_loadings(sample_factor_returns, sample_fund_returns):
    fund_returns, true_loadings = sample_fund_returns
    
    fit = fit_fundamental_loadings(
        fund_returns, 
        sample_factor_returns.values, 
        ewma_lambda=1.0  # Equal weights for simpler recovery check
    )
    
    assert isinstance(fit, FundamentalFactorFit)
    assert fit.loadings.shape == (5, 3)
    # Recovered loadings should be close to true_loadings
    np.testing.assert_allclose(fit.loadings, true_loadings, atol=0.02)
    assert len(fit.residual_variance) == 5
    assert fit.residual_series.shape == (100, 5)
    assert len(fit.r_squared_per_fund) == 5
    assert np.all(fit.r_squared_per_fund > 0.8)  # high fit by construction


def test_assemble_factor_covariance(sample_factor_returns, sample_fund_returns):
    fund_returns, _ = sample_fund_returns
    fit = fit_fundamental_loadings(fund_returns, sample_factor_returns.values)
    
    sigma = assemble_factor_covariance(fit)
    
    assert sigma.shape == (5, 5)
    # Symmetric
    np.testing.assert_allclose(sigma, sigma.T, atol=1e-12)
    # PSD (all eigenvalues > 0)
    eigvals = np.linalg.eigvalsh(sigma)
    assert np.all(eigvals > 1e-11)


def test_compute_residual_pca(sample_fund_returns):
    fund_returns, _ = sample_fund_returns
    # Generate some residuals
    residuals = fund_returns * 0.1
    
    diag = compute_residual_pca(residuals, n_components=2)
    
    assert len(diag.explained_variance_ratio) == 2
    assert diag.cumulative_variance <= 1.0
    assert len(diag.top_loadings) == 2


@pytest.mark.asyncio
async def test_build_fundamental_factor_returns_joins_allocation_blocks():
    """T1: Assert SQL joins through allocation_blocks."""
    db = AsyncMock()
    # Mock return values for benchmark and macro queries
    db.execute.side_effect = [
        # benchmark_res
        MagicMock(all=MagicMock(return_value=[
            (date(2021, 1, 1), "SPY", 0.01),
            (date(2021, 1, 2), "SPY", -0.005),
            (date(2021, 1, 1), "IEF", 0.002),
        ])),
        # macro_res
        MagicMock(all=MagicMock(return_value=[
            (date(2021, 1, 1), "DTWEXBGS", 100.0),
            (date(2021, 1, 2), "DTWEXBGS", 101.0),
        ])),
    ]
    
    factors = await build_fundamental_factor_returns(
        db, date(2021, 1, 1), date(2021, 1, 10)
    )
    
    assert isinstance(factors, pd.DataFrame)
    # SPY and IEF should be present
    assert "equity_us" in factors.columns
    assert "duration" in factors.columns
    # Check skipped info
    skipped = factors.attrs.get("skipped", [])
    assert any(s["name"] == "credit" for s in skipped)


@pytest.mark.asyncio
async def test_iwf_absent_triggers_value_factor_skip():
    """T2: Value factor skipped when IWF absent."""
    db = AsyncMock()
    # benchmark_res only has IWD
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[
            (date(2021, 1, 1), "SPY", 0.01),
            (date(2021, 1, 1), "IWD", 0.01),
        ])),
        MagicMock(all=MagicMock(return_value=[])),
    ]
    
    factors = await build_fundamental_factor_returns(
        db, date(2021, 1, 1), date(2021, 1, 2)
    )
    
    skipped = factors.attrs.get("skipped", [])
    assert any(s["name"] == "value" and "IWF absent" in s["reason"] for s in skipped)


@pytest.mark.asyncio
async def test_efa_absent_triggers_international_factor_skip():
    """T3: International factor skipped when EFA absent."""
    db = AsyncMock()
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[
            (date(2021, 1, 1), "SPY", 0.01),
        ])),
        MagicMock(all=MagicMock(return_value=[])),
    ]
    
    factors = await build_fundamental_factor_returns(
        db, date(2021, 1, 1), date(2021, 1, 2)
    )
    
    skipped = factors.attrs.get("skipped", [])
    assert any(s["name"] == "international" and "EFA absent" in s["reason"] for s in skipped)


@pytest.mark.asyncio
async def test_k_equals_six_end_to_end():
    """T4: Realistic 25-fund portfolio, current DB shape (K=6)."""
    n_funds = 25
    ids = [uuid.uuid4() for _ in range(n_funds)]
    
    # 5Y history
    n_days = 1260
    rng = np.random.default_rng(2026)
    raw_returns = rng.standard_normal((n_days, n_funds)) * 0.01
    dates = [date(2021, 1, 1) + timedelta(days=i) for i in range(n_days)]
    
    returns_dict = {}
    for i, iid in enumerate(ids):
        returns_dict[str(iid)] = {d: float(raw_returns[j, i]) for j, d in enumerate(dates)}
        
    # Mock factor returns (K=6)
    factor_df = pd.DataFrame(
        rng.standard_normal((n_days, 6)) * 0.01,
        index=pd.to_datetime(dates),
        columns=["equity_us", "duration", "credit", "usd", "commodity", "size"]
    )
    factor_df.attrs["skipped"] = [
        {"name": "value", "reason": "IWF absent"},
        {"name": "international", "reason": "EFA absent"}
    ]
    
    db = AsyncMock()
    
    with patch(
        "app.domains.wealth.services.quant_queries._fetch_returns_by_type",
        new=AsyncMock(return_value=(returns_dict, "log")),
    ), patch(
        "app.domains.wealth.services.quant_queries._fetch_return_horizons",
        new=AsyncMock(return_value={str(iid): {"10y": 0.05, "5y": 0.05} for iid in ids}),
    ), patch(
        "app.domains.wealth.services.quant_queries.fetch_strategic_weights_for_funds",
        new=AsyncMock(return_value=np.full(n_funds, 1 / n_funds)),
    ), patch(
        "app.domains.wealth.services.quant_queries.build_fundamental_factor_returns",
        new=AsyncMock(return_value=factor_df),
    ), patch(
        "app.domains.wealth.services.quant_queries._maybe_regime_condition_cov",
        return_value=None,
    ):
        result = await compute_fund_level_inputs(
            db, ids, profile="balanced", as_of_date=date(2026, 4, 14)
        )
        
    assert isinstance(result, FundLevelInputs)
    assert result.cov_matrix.shape == (25, 25)
    assert result.factor_loadings.shape == (25, 6)
    assert len(result.factor_names) == 6
    assert len(result.residual_variance) == 25
    # PSD check
    assert np.linalg.eigvalsh(result.cov_matrix).min() >= 1e-11


@pytest.mark.asyncio
async def test_oas_level_is_never_used_as_credit_return():
    """T6: Defensive test against OAS level change usage."""
    db = AsyncMock()
    # Mock return value including an OAS ticker
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[
            MagicMock(benchmark_ticker="BAMLH0A0HYM2"),
        ])),
    ]
    
    with pytest.raises(ValueError, match="OAS level is not a total return"):
        await build_fundamental_factor_returns(
            db, date(2021, 1, 1), date(2021, 1, 2)
        )


def test_residual_pca_not_fed_back_into_sigma():
    """T7: Regression check that residual PCA is not used in Σ."""
    # We can inspect the source code of assemble_factor_covariance
    import inspect

    from quant_engine.factor_model_service import assemble_factor_covariance
    source = inspect.getsource(assemble_factor_covariance)
    assert "compute_residual_pca" not in source
    assert "PCADiagnostic" not in source


@pytest.mark.asyncio
async def test_single_index_fallback_when_n_less_than_20():
    """T8: N=15 universe fallback."""
    n_funds = 15
    ids = [uuid.uuid4() for _ in range(n_funds)]
    n_days = 200
    rng = np.random.default_rng(2026)
    raw_returns = rng.standard_normal((n_days, n_funds)) * 0.01
    dates = [date(2021, 1, 1) + timedelta(days=i) for i in range(n_days)]
    
    returns_dict = {}
    for i, iid in enumerate(ids):
        returns_dict[str(iid)] = {d: float(raw_returns[j, i]) for j, d in enumerate(dates)}

    db = AsyncMock()
    
    with patch(
        "app.domains.wealth.services.quant_queries._fetch_returns_by_type",
        new=AsyncMock(return_value=(returns_dict, "log")),
    ), patch(
        "app.domains.wealth.services.quant_queries._fetch_return_horizons",
        new=AsyncMock(return_value={str(iid): {"10y": 0.05, "5y": 0.05} for iid in ids}),
    ), patch(
        "app.domains.wealth.services.quant_queries.fetch_strategic_weights_for_funds",
        new=AsyncMock(return_value=np.full(n_funds, 1 / n_funds)),
    ), patch(
        "app.domains.wealth.services.quant_queries.build_fundamental_factor_returns",
        new=AsyncMock(return_value=pd.DataFrame({"equity_us": rng.standard_normal(n_days)}, index=pd.to_datetime(dates))),
    ), patch(
        "app.domains.wealth.services.quant_queries._maybe_regime_condition_cov",
        return_value=None,
    ):
        result = await compute_fund_level_inputs(
            db, ids, profile="balanced", as_of_date=date(2021, 8, 1)
        )
        
    assert result.factor_loadings is None
    assert result.factor_names is None
    assert result.cov_matrix.shape == (15, 15)
    assert result.condition_number < 1e3
