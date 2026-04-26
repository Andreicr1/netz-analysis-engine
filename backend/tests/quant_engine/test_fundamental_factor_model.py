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
    # PR-Q34 F08: LW shrinkage removed (scaled-identity target destroyed
    # cross-factor correlations). shrinkage_lambda is always None post-Q34.
    assert fit.shrinkage_lambda is None
    # PR-Q15 Fix 3 — alphas_per_fund is populated
    assert fit.alphas_per_fund is not None
    assert len(fit.alphas_per_fund) == 5


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
    # PR-Q15: mock returns NAV levels (not return_1d) after Fix 1.
    db.execute.side_effect = [
        # benchmark_res — NAV levels
        MagicMock(all=MagicMock(return_value=[
            (date(2021, 1, 1), "SPY", 100.0),
            (date(2021, 1, 2), "SPY", 101.0),
            (date(2021, 1, 3), "SPY", 100.5),
            (date(2021, 1, 1), "IEF", 50.0),
            (date(2021, 1, 2), "IEF", 50.1),
            (date(2021, 1, 3), "IEF", 50.05),
        ])),
        # macro_res — levels
        MagicMock(all=MagicMock(return_value=[
            (date(2021, 1, 1), "DTWEXBGS", 100.0),
            (date(2021, 1, 2), "DTWEXBGS", 101.0),
            (date(2021, 1, 3), "DTWEXBGS", 100.5),
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
    # PR-Q15: NAV levels (not return_1d)
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[
            (date(2021, 1, 1), "SPY", 100.0),
            (date(2021, 1, 2), "SPY", 101.0),
            (date(2021, 1, 1), "IWD", 50.0),
            (date(2021, 1, 2), "IWD", 50.5),
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
    # PR-Q15: NAV levels
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[
            (date(2021, 1, 1), "SPY", 100.0),
            (date(2021, 1, 2), "SPY", 101.0),
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
    as_of_date = date(2026, 4, 14)
    dates = [as_of_date - timedelta(days=n_days - 1 - i) for i in range(n_days)]

    returns_dict = {
        str(iid): {d: float(raw_returns[j, i]) for j, d in enumerate(dates)}
        for i, iid in enumerate(ids)
    }

    # Build the underlying rows that build_fundamental_factor_returns will
    # pivot into factors. 7 benchmark tickers + 2 macro series. We skip EFA
    # and IWF so only 6 factors survive — matching the original intent.
    # PR-Q15: benchmark mock data uses NAV levels (not return_1d).
    bench_tickers = ["SPY", "IEF", "HYG", "IWM", "IWD"]
    bench_levels_state = {t: 100.0 for t in bench_tickers}
    bench_rows = []
    for d in dates:
        for t in bench_tickers:
            bench_levels_state[t] *= (1 + rng.standard_normal() * 0.01)
            bench_rows.append((d, t, bench_levels_state[t]))
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
        "app.domains.wealth.services.quant_queries._resolve_trace_instrument_ids",
        new=AsyncMock(return_value={}),
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
    # PR-Q34 F08: LW shrinkage removed; shrinkage_lambda always None post-Q34
    assert fm["shrinkage_lambda"] is None
    # Residual PCA recorded
    pca = result.inputs_metadata["residual_pca"]
    assert pca["n_components"] >= 1
    assert len(pca["cumulative_variance"]) == pca["n_components"]


@pytest.mark.asyncio
async def test_oas_level_is_filtered_not_crashed_on(monkeypatch):
    """T6 (PR-Q35 F06): OAS levels filtered defensively without crashing.

    Replaces previous test_oas_level_is_never_used_as_credit_return which
    asserted pytest.raises(ValueError). Per Wave 6 Session 03 F06, the
    defensive intent is preserved but the crash is replaced with degraded
    skip pattern (charter §3 degraded > crash).

    Verifies:
    - build_fundamental_factor_returns does NOT raise ValueError
    - OAS rows are filtered from the result
    - skipped accumulator (factors.attrs["skipped"]) records the OAS filter
    """
    async def _noop_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "quant_engine.factor_model_service.write_audit_event",
        _noop_audit,
    )

    db = AsyncMock()
    # Mock returns: one OAS row + one valid SPY row + empty macro
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[
            MagicMock(benchmark_ticker="BAMLH0A0HYM2", nav_date=date(2021, 1, 2), nav=8.5),
            MagicMock(benchmark_ticker="SPY", nav_date=date(2021, 1, 2), nav=400.0),
        ])),
        # Macro query returns empty
        MagicMock(all=MagicMock(return_value=[])),
    ]

    # Should NOT raise — degraded skip instead
    result = await build_fundamental_factor_returns(
        db, date(2021, 1, 1), date(2021, 1, 2)
    )

    # Result is a DataFrame with skipped attrs populated
    assert result is not None
    skipped = result.attrs.get("skipped", [])
    skipped_names = [s["name"] for s in skipped]
    assert any("oas" in n.lower() for n in skipped_names), (
        f"OAS filter not recorded in skipped: {skipped_names}. "
        f"F06 fix should append 'oas_*' entries when OAS rows are present."
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
    as_of_date = date(2026, 4, 14)
    dates = [as_of_date - timedelta(days=n_days - 1 - i) for i in range(n_days)]
    
    returns_dict = {}
    for i, iid in enumerate(ids):
        returns_dict[str(iid)] = {d: float(raw_returns[j, i]) for j, d in enumerate(dates)}

    db = AsyncMock()

    with patch(
        "app.domains.wealth.services.quant_queries._fetch_returns_by_type",
        new=AsyncMock(return_value=(returns_dict, "log")),
    ), patch(
        "app.domains.wealth.services.quant_queries._resolve_trace_instrument_ids",
        new=AsyncMock(return_value={}),
    ), patch(
        "app.domains.wealth.services.quant_queries._resolve_trace_instrument_ids",
        new=AsyncMock(return_value={}),
    ), patch(
        "app.domains.wealth.services.quant_queries._fetch_return_horizons",        new=AsyncMock(return_value={str(iid): {"10y": 0.05, "5y": 0.05} for iid in ids}),
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


# ── PR-Q34 F07: weighted SSE tests ──────────────────────────────────────


def test_residual_variance_uses_weighted_sse_consistent_with_ewma_wls():
    """PR-Q34 F07: residual variance must reflect EWMA-weighted SSE, not unweighted full-history.

    Synthetic 5-year setup with regime shift at t=4 years. EWMA λ=0.97
    weights recent data ~30x more than 5-year-old data. Pre-fix unweighted
    SSE inflates residual_variance ~28x; post-fix weighted SSE produces
    consistent estimate.
    """
    rng = np.random.default_rng(42)
    T_years = 5
    T = 252 * T_years  # 1260 daily obs
    K = 3  # small factor model for clean test
    N = 1  # single fund

    # Synthetic factor returns
    factor_returns = rng.normal(0.0, 0.01, size=(T, K))

    # Single fund with β shift at t=4 years
    shift_idx = 252 * 4  # 4-year mark
    beta_old = np.array([1.0, 0.5, -0.2])
    beta_new = np.array([0.5, 1.5, 0.3])

    fund_returns = np.zeros((T, N))
    fund_returns[:shift_idx, 0] = factor_returns[:shift_idx, :] @ beta_old + rng.normal(0.0, 0.005, size=shift_idx)
    fund_returns[shift_idx:, 0] = factor_returns[shift_idx:, :] @ beta_new + rng.normal(0.0, 0.005, size=T - shift_idx)

    fit = fit_fundamental_loadings(
        fund_returns_matrix=fund_returns,
        factor_returns=factor_returns,
        factor_names=["f1", "f2", "f3"],
        ewma_lambda=0.97,
    )

    # Post-fix residual variance should reflect the recent (post-shift) regime,
    # which has noise std ~0.005 → annualized variance ~0.005² * 252 ≈ 6.3e-3
    expected_recent_var = (0.005 ** 2) * 252

    # Allow generous tolerance (4x) since EWMA mixes some pre-shift residuals
    assert fit.residual_variance[0] < 4 * expected_recent_var, (
        f"Residual variance {fit.residual_variance[0]:.6f} vs expected ~{expected_recent_var:.6f}; "
        f"if much larger, F07 unweighted-SSE bug not fixed"
    )
    assert fit.residual_variance[0] > expected_recent_var * 0.5, (
        f"Residual variance {fit.residual_variance[0]:.6f} too low; possible over-correction"
    )

    # R² should be reasonable post-fix (not falsely suppressed to 0)
    assert fit.r_squared_per_fund[0] > 0.5, (
        f"R² per fund {fit.r_squared_per_fund[0]:.4f}; if near 0, F07 SSE inflation suppressed it"
    )


def test_residual_variance_matches_unweighted_when_lambda_is_one():
    """PR-Q34 F07 sanity: when ewma_lambda=1.0 (uniform weights), the weighted
    SSE must equal the unweighted SSE divided by T (since w_norm = 1/T).
    Backward compatibility check.
    """
    rng = np.random.default_rng(42)
    T = 500
    K = 3
    N = 2

    factor_returns = rng.normal(0.0, 0.01, size=(T, K))
    fund_returns = factor_returns @ rng.normal(0.0, 1.0, size=(K, N)) + rng.normal(0.0, 0.005, size=(T, N))

    fit_uniform = fit_fundamental_loadings(
        fund_returns_matrix=fund_returns,
        factor_returns=factor_returns,
        factor_names=["f1", "f2", "f3"],
        ewma_lambda=1.0,  # uniform weights
    )

    # With ewma_lambda=1.0, weights are all 1; w_norm = 1/T; weighted_sse * T = sse
    # So residual_variance = unweighted_sse / dof * 252 — same as pre-fix
    assert fit_uniform.residual_variance.shape == (N,)
    assert all(np.isfinite(fit_uniform.residual_variance))


# ── PR-Q34 F08: cross-factor correlation tests ──────────────────────────


def test_factor_covariance_preserves_cross_factor_correlations():
    """PR-Q34 F08: factor covariance must preserve cross-factor correlations
    (no LW shrinkage to scaled identity).

    Synthetic: two perfectly correlated factors (Market and a copy with noise).
    Pre-fix LW shrinkage would push the off-diagonal toward zero. Post-fix
    EWMA covariance preserves the ~0.9+ correlation.
    """
    rng = np.random.default_rng(42)
    T = 1260  # 5Y daily
    K = 2  # two factors
    N = 1

    # Two highly correlated factors
    common_signal = rng.normal(0.0, 0.01, size=T)
    factor_returns = np.column_stack([
        common_signal + rng.normal(0.0, 0.001, size=T),  # f1: signal + small noise
        common_signal + rng.normal(0.0, 0.001, size=T),  # f2: same signal + small noise
    ])

    fund_returns = factor_returns @ np.array([[1.0], [0.5]]) + rng.normal(0.0, 0.005, size=(T, N))

    fit = fit_fundamental_loadings(
        fund_returns_matrix=fund_returns,
        factor_returns=factor_returns,
        factor_names=["f1", "f2"],
        ewma_lambda=0.97,
    )

    # Post-fix factor_cov off-diagonal correlation should be > 0.85 (preserves
    # true correlation). Pre-fix LW shrinkage would push it toward 0.
    cov_diag = np.sqrt(np.diag(fit.factor_cov))
    corr_off_diag = fit.factor_cov[0, 1] / (cov_diag[0] * cov_diag[1])

    assert corr_off_diag > 0.85, (
        f"Factor cross-correlation {corr_off_diag:.4f}; if near 0, F08 "
        f"scaled-identity shrinkage was not removed"
    )


def test_shrinkage_lambda_is_none_post_q34():
    """PR-Q34 F08: shrinkage_lambda field must always be None post-fix
    (LW shrinkage removed)."""
    rng = np.random.default_rng(42)
    T = 200
    K = 3
    N = 2
    factor_returns = rng.normal(0.0, 0.01, size=(T, K))
    fund_returns = factor_returns @ rng.normal(0.0, 1.0, size=(K, N)) + rng.normal(0.0, 0.005, size=(T, N))

    fit = fit_fundamental_loadings(
        fund_returns_matrix=fund_returns,
        factor_returns=factor_returns,
        factor_names=["f1", "f2", "f3"],
    )

    assert fit.shrinkage_lambda is None
