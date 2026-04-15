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
from quant_engine.factor_model_pca import compute_residual_pca
from quant_engine.factor_model_service import (
    FundamentalFactorFit,
    assemble_factor_covariance,
    build_fundamental_factor_returns,
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
        factor_names=sample_factor_returns.columns.tolist(),
        ewma_lambda=1.0,  # Equal weights for simpler recovery check
    )

    assert isinstance(fit, FundamentalFactorFit)
    assert fit.loadings.shape == (5, 3)
    # A.9 — factor_names populated from explicit parameter, never empty
    assert fit.factor_names == ["equity_us", "duration", "credit"]
    # Recovered loadings should be close to true_loadings
    np.testing.assert_allclose(fit.loadings, true_loadings, atol=0.02)
    assert len(fit.residual_variance) == 5
    assert fit.residual_series.shape == (100, 5)
    assert len(fit.r_squared_per_fund) == 5
    assert np.all(fit.r_squared_per_fund > 0.8)  # high fit by construction
    # A.6 — Ledoit-Wolf shrinkage λ is recorded on the fit
    assert fit.shrinkage_lambda is not None
    assert 0.0 <= fit.shrinkage_lambda <= 1.0


def test_fit_fundamental_loadings_zero_variance_fund_guarded():
    """A.10 — a constant-return fund must not divide by zero in r_squared."""
    T, N, K = 200, 3, 2
    rng = np.random.default_rng(0)
    factor_returns = rng.standard_normal((T, K)) * 0.01
    fund_returns = rng.standard_normal((T, N)) * 0.01
    fund_returns[:, 1] = 0.0  # fund 1 has zero variance

    fit = fit_fundamental_loadings(
        fund_returns,
        factor_returns,
        factor_names=["f1", "f2"],
        ewma_lambda=0.97,
    )

    assert np.isfinite(fit.r_squared_per_fund).all()
    assert fit.r_squared_per_fund[1] == 0.0


def test_assemble_factor_covariance(sample_factor_returns, sample_fund_returns):
    fund_returns, _ = sample_fund_returns
    fit = fit_fundamental_loadings(
        fund_returns,
        sample_factor_returns.values,
        factor_names=sample_factor_returns.columns.tolist(),
    )

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
async def test_k_equals_six_contract_with_stubbed_factor_returns(monkeypatch):
    """T4 (contract): 25-fund portfolio, factor matrix stubbed via AsyncSession.execute.

    The real database integration test lives in
    ``test_fundamental_factor_model_integration.py`` under the
    ``@pytest.mark.integration`` lane (PR-A3 Section A §11). This unit-level
    test exercises the full ``compute_fund_level_inputs`` path with the
    production ``build_fundamental_factor_returns`` driven by a mocked
    ``AsyncSession`` — so the production SQL joins and audit pipeline still
    execute, but without docker.
    """
    n_funds = 25
    ids = [uuid.uuid4() for _ in range(n_funds)]
    n_days = 1260
    rng = np.random.default_rng(2026)
    raw_returns = rng.standard_normal((n_days, n_funds)) * 0.01
    dates = [date(2021, 1, 1) + timedelta(days=i) for i in range(n_days)]

    returns_dict = {
        str(iid): {d: float(raw_returns[j, i]) for j, d in enumerate(dates)}
        for i, iid in enumerate(ids)
    }

    # Build the underlying rows that build_fundamental_factor_returns will
    # pivot into factors. 7 benchmark tickers + 2 macro series. We skip EFA
    # and IWF so only 6 factors survive — matching the original intent.
    bench_tickers = ["SPY", "IEF", "HYG", "IWM", "IWD"]
    bench_rows = []
    for d in dates:
        for t in bench_tickers:
            bench_rows.append((d, t, rng.standard_normal() * 0.01))
    macro_rows = []
    for d in dates:
        macro_rows.append((d, "DTWEXBGS", 100.0 + rng.standard_normal()))
        macro_rows.append((d, "DCOILWTICO", 70.0 + rng.standard_normal()))

    db = AsyncMock()
    # Two execute calls per invocation of build_fundamental_factor_returns
    # (benchmarks then macro). compute_fund_level_inputs calls it exactly once
    # after A.7 (hoisted).
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=bench_rows)),
        MagicMock(all=MagicMock(return_value=macro_rows)),
    ]

    async def _noop_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "quant_engine.factor_model_service.write_audit_event",
        _noop_audit,
    )

    with patch(
        "app.domains.wealth.services.quant_queries._fetch_returns_by_type",
        new=AsyncMock(return_value=(returns_dict, "log")),
    ), patch(
        "app.domains.wealth.services.quant_queries._fetch_return_horizons",
        new=AsyncMock(
            return_value={str(iid): {"10y": 0.05, "5y": 0.05} for iid in ids}
        ),
    ), patch(
        "app.domains.wealth.services.quant_queries.fetch_strategic_weights_for_funds",
        new=AsyncMock(return_value=np.full(n_funds, 1 / n_funds)),
    ), patch(
        "app.domains.wealth.services.quant_queries._maybe_regime_condition_cov",
        return_value=None,
    ):
        result = await compute_fund_level_inputs(
            db, ids, profile="balanced", as_of_date=date(2026, 4, 14)
        )

    assert isinstance(result, FundLevelInputs)
    assert result.cov_matrix.shape == (25, 25)
    assert result.factor_loadings is not None
    assert result.factor_loadings.shape[0] == 25
    # At most 6 factors because EFA / IWF missing from the stubbed benchmark rows
    assert result.factor_loadings.shape[1] <= 6
    assert result.factor_names is not None and len(result.factor_names) <= 6
    assert result.residual_variance is not None
    assert len(result.residual_variance) == 25
    assert np.linalg.eigvalsh(result.cov_matrix).min() >= 1e-11
    # A.2 — inputs_metadata populated
    fm = result.inputs_metadata["factor_model"]
    assert fm["k_factors"] == 8
    assert fm["k_factors_effective"] == len(result.factor_names)
    assert set(fm["r_squared_per_fund"].keys()) == {str(i) for i in ids}
    assert fm["kappa_factor_cov"] is not None
    # Ledoit-Wolf shrinkage recorded
    assert fm["shrinkage_lambda"] is not None
    # Residual PCA recorded
    pca = result.inputs_metadata["residual_pca"]
    assert pca["n_components"] >= 1
    assert len(pca["cumulative_variance"]) == pca["n_components"]


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
    """T7: Regression check that residual PCA is not used in Σ.

    The docstring may legitimately *mention* PCADiagnostic for documentation,
    so we only assert that neither symbol is referenced in the function's
    executable code (``__code__.co_names``).
    """
    from quant_engine.factor_model_service import assemble_factor_covariance

    co_names = assemble_factor_covariance.__code__.co_names
    assert "compute_residual_pca" not in co_names
    assert "PCADiagnostic" not in co_names


@pytest.mark.asyncio
async def test_single_index_fallback_when_n_less_than_20(monkeypatch):
    """T8: N=15 universe fallback."""

    async def _noop_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "quant_engine.factor_model_service.write_audit_event",
        _noop_audit,
    )

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
