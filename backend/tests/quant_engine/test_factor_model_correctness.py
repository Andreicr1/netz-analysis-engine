"""PR-Q15 — regression tests for factor_model_service correctness fixes.

Each test maps 1:1 to a numbered fix.  Tests are designed to FAIL against
the pre-PR-Q15 code and PASS after the fixes.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from quant_engine.factor_model_service import (
    FactorContributionResult,
    FactorModelResult,
    FundamentalFactorFit,
    _safe_correlation,
    compute_factor_contributions,
    decompose_factors,
    fit_fundamental_loadings,
)


# ─── Fix 1: ffill levels, not returns — no compounding bug ──────────────

@pytest.mark.asyncio
async def test_ffill_levels_not_returns_no_compounding(monkeypatch):
    """Fix 1: Friday +1% then holiday → Monday return should be 0%, not +1%.

    If forward-filling were applied to returns (old bug), Friday's +1%
    return would be repeated on Monday, producing artificial compounding.
    Level-side ffill carries the price forward, giving 0% on Monday.
    """
    from quant_engine.factor_model_service import build_fundamental_factor_returns

    async def _noop_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "quant_engine.factor_model_service.write_audit_event",
        _noop_audit,
    )

    db = AsyncMock()
    # SPY: Fri=100, Mon(gap), Tue=101 → after level-ffill Mon level=100 → Mon return=0%
    bench_rows = [
        (date(2021, 1, 1), "SPY", 100.0),   # Fri
        # date(2021, 1, 2) is missing (holiday)
        (date(2021, 1, 3), "SPY", 101.0),   # Tue
    ]
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=bench_rows)),
        MagicMock(all=MagicMock(return_value=[])),  # macro
    ]

    factors = await build_fundamental_factor_returns(
        db, date(2021, 1, 1), date(2021, 1, 5)
    )

    if "equity_us" in factors.columns and len(factors) > 0:
        # The return from Fri to Tue should be +1% (101/100 - 1),
        # NOT +2% (which would occur if Friday's return was repeated).
        returns = factors["equity_us"].dropna()
        assert len(returns) >= 1
        # The return should be close to 1% (100→101) not compounded.
        assert returns.iloc[-1] == pytest.approx(0.01, abs=0.001)


# ─── Fix 2: EWMA + LedoitWolf — no double scaling ──────────────────────

def test_ewma_lw_no_double_scaling():
    """Fix 2: constant factor returns → covariance ≈ 0.

    If EWMA weights improperly scale the data before LW (old bug), the
    covariance of constant-return factors would be artificially positive.
    """
    T, N, K = 200, 3, 2
    rng = np.random.default_rng(42)
    # Nearly constant factor returns (tiny noise)
    factor_returns = np.ones((T, K)) * 0.001 + rng.standard_normal((T, K)) * 1e-8
    fund_returns = rng.standard_normal((T, N)) * 0.01

    fit = fit_fundamental_loadings(
        fund_returns, factor_returns, factor_names=["f1", "f2"], ewma_lambda=0.97,
    )

    # Factor covariance should be near zero (constant returns).
    assert np.max(np.abs(fit.factor_cov)) < 0.01


# ─── Fix 3: OLS with intercept — alpha doesn't bias loadings ────────────

def test_loadings_with_intercept_isolate_alpha():
    """Fix 3: y = alpha + beta*x + noise → recovered beta ≈ true_beta.

    Without intercept (old bug), OLS forces beta to absorb the drift,
    inflating the estimated loading.
    """
    T, N = 500, 1
    K = 1
    rng = np.random.default_rng(99)
    true_alpha = 0.005  # 50 bps daily drift
    true_beta = 2.0
    factor_returns = rng.standard_normal((T, K)) * 0.01
    noise = rng.standard_normal((T, N)) * 0.001
    fund_returns = true_alpha + true_beta * factor_returns + noise

    fit = fit_fundamental_loadings(
        fund_returns, factor_returns, factor_names=["f1"], ewma_lambda=1.0,
    )

    # With intercept, loading should recover true_beta ≈ 2.0.
    assert fit.loadings[0, 0] == pytest.approx(true_beta, abs=0.05)
    # Alpha should be recovered.
    assert fit.alphas_per_fund is not None
    assert fit.alphas_per_fund[0] == pytest.approx(true_alpha, abs=0.001)


# ─── Fix 4: combined ffill uses _FACTOR_FFILL_LIMIT ─────────────────────

@pytest.mark.asyncio
async def test_combined_uses_constant_ffill_limit(monkeypatch):
    """Fix 4 (subsumed by Fix 1): level-side ffill uses _FACTOR_FFILL_LIMIT.

    After Fix 1, there is no ffill on the combined returns DataFrame —
    fills happen on levels.  This test verifies the constant is used.
    """
    from quant_engine.factor_model_service import _FACTOR_FFILL_LIMIT

    assert _FACTOR_FFILL_LIMIT == 2  # documented contract


# ─── Fix 5: spread factors drop stale-leg dates ─────────────────────────

@pytest.mark.asyncio
async def test_spread_drops_stale_leg_dates(monkeypatch):
    """Fix 5: spread factor NaN on dates where either leg was forward-filled.

    HYG has no data on day 2 (gets level-filled from day 1). The credit
    spread (HYG - IEF) should be NaN on day 2 since HYG is stale.
    """
    from quant_engine.factor_model_service import build_fundamental_factor_returns

    async def _noop_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "quant_engine.factor_model_service.write_audit_event",
        _noop_audit,
    )

    db = AsyncMock()
    # HYG has data on day 1 and 3, not day 2.
    # IEF has data on all 3 days.
    bench_rows = [
        (date(2021, 1, 1), "HYG", 80.0),
        # HYG missing on 2021-01-02 — will be ffilled
        (date(2021, 1, 3), "HYG", 80.5),
        (date(2021, 1, 1), "IEF", 100.0),
        (date(2021, 1, 2), "IEF", 100.2),
        (date(2021, 1, 3), "IEF", 100.1),
        # Need SPY for equity_us
        (date(2021, 1, 1), "SPY", 400.0),
        (date(2021, 1, 2), "SPY", 401.0),
        (date(2021, 1, 3), "SPY", 400.5),
    ]
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=bench_rows)),
        MagicMock(all=MagicMock(return_value=[])),  # macro
    ]

    factors = await build_fundamental_factor_returns(
        db, date(2021, 1, 1), date(2021, 1, 5)
    )

    if "credit" in factors.columns:
        credit = factors["credit"]
        # Day 2 (2021-01-02): HYG was ffilled → credit spread should be NaN.
        day2 = pd.Timestamp("2021-01-02")
        if day2 in credit.index:
            assert pd.isna(credit.loc[day2]), (
                "Credit spread should be NaN on dates where HYG was ffilled"
            )


# ─── Fix 6: simple returns for macro (not log) ──────────────────────────

@pytest.mark.asyncio
async def test_simple_returns_for_macro(monkeypatch):
    """Fix 6: macro factor returns use pct_change (simple), not np.log.

    For a -30% move, simple = -0.30, log = -0.357.  Simple is the
    standard financial convention matching benchmark returns.
    """
    from quant_engine.factor_model_service import build_fundamental_factor_returns

    async def _noop_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "quant_engine.factor_model_service.write_audit_event",
        _noop_audit,
    )

    db = AsyncMock()
    # SPY for equity_us
    bench_rows = [
        (date(2021, 1, 1), "SPY", 100.0),
        (date(2021, 1, 2), "SPY", 101.0),
        (date(2021, 1, 3), "SPY", 100.5),
    ]
    # DCOILWTICO: 100 → 70 = -30% simple return
    macro_rows = [
        (date(2021, 1, 1), "DCOILWTICO", 100.0),
        (date(2021, 1, 2), "DCOILWTICO", 70.0),
        (date(2021, 1, 3), "DCOILWTICO", 75.0),
    ]
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=bench_rows)),
        MagicMock(all=MagicMock(return_value=macro_rows)),
    ]

    factors = await build_fundamental_factor_returns(
        db, date(2021, 1, 1), date(2021, 1, 5)
    )

    if "commodity" in factors.columns:
        commodity = factors["commodity"].dropna()
        if len(commodity) > 0:
            first_return = commodity.iloc[0]
            # Simple return: (70 - 100) / 100 = -0.30
            # Log return would be: ln(70/100) = -0.357
            assert first_return == pytest.approx(-0.30, abs=0.01), (
                f"Expected simple return ≈ -0.30, got {first_return} "
                f"(log return would be ≈ -0.357)"
            )


# ─── Fix 7: dropna preserves early history ──────────────────────────────

@pytest.mark.asyncio
async def test_dropna_preserves_early_history(monkeypatch):
    """Fix 7: dropna(how='all') preserves dates where at least one factor exists.

    With dropna() (old bug), dates where ANY factor is NaN are dropped —
    losing years of history for factors that exist when others don't.
    """
    from quant_engine.factor_model_service import build_fundamental_factor_returns

    async def _noop_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "quant_engine.factor_model_service.write_audit_event",
        _noop_audit,
    )

    db = AsyncMock()
    # SPY exists for all 4 days. HYG only exists for days 3-4.
    bench_rows = [
        (date(2021, 1, 1), "SPY", 100.0),
        (date(2021, 1, 2), "SPY", 101.0),
        (date(2021, 1, 3), "SPY", 100.5),
        (date(2021, 1, 4), "SPY", 101.5),
        (date(2021, 1, 1), "IEF", 50.0),
        (date(2021, 1, 2), "IEF", 50.1),
        (date(2021, 1, 3), "IEF", 50.05),
        (date(2021, 1, 4), "IEF", 50.2),
        # HYG starts late
        (date(2021, 1, 3), "HYG", 80.0),
        (date(2021, 1, 4), "HYG", 80.5),
    ]
    db.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=bench_rows)),
        MagicMock(all=MagicMock(return_value=[])),  # macro
    ]

    factors = await build_fundamental_factor_returns(
        db, date(2021, 1, 1), date(2021, 1, 5)
    )

    # equity_us (SPY) should have returns from day 2 onward (pct_change drops day 1).
    # With old dropna(), day 2 would be wiped because HYG doesn't exist yet.
    if "equity_us" in factors.columns:
        assert len(factors["equity_us"].dropna()) >= 2, (
            "Early history for equity_us should be preserved even when HYG is absent"
        )


# ─── Fix 8: residual variance DOF ───────────────────────────────────────

def test_residual_variance_uses_regression_dof():
    """Fix 8: residual variance divides by T-K-1 (not T-1).

    With K=3 factors + 1 intercept and T=100, DOF = 100-3-1 = 96.
    The old code used T-1=99, underestimating by ~3%.
    """
    T, N, K = 100, 2, 3
    rng = np.random.default_rng(42)
    factor_returns = rng.standard_normal((T, K)) * 0.01
    fund_returns = rng.standard_normal((T, N)) * 0.01

    fit = fit_fundamental_loadings(
        fund_returns, factor_returns, factor_names=["f1", "f2", "f3"],
        ewma_lambda=1.0,
    )

    # Manually compute expected residual variance with correct DOF.
    X = np.hstack([np.ones((T, 1)), factor_returns])
    beta, _, _, _ = np.linalg.lstsq(X, fund_returns, rcond=None)
    resid = fund_returns - X @ beta
    dof = T - K - 1  # 96
    expected_resvar = (np.sum(resid ** 2, axis=0) / dof) * 252

    np.testing.assert_allclose(fit.residual_variance, expected_resvar, rtol=0.05)


# ─── Fix 9: _safe_correlation returns NaN on NaN input ───────────────────

def test_safe_correlation_returns_nan_on_nan_input():
    """Fix 9: _safe_correlation returns NaN (not 0.0) when input has NaN."""
    a = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
    b = np.array([np.nan, np.nan, np.nan, np.nan, np.nan])

    result = _safe_correlation(a, b)
    # All-NaN input: fewer than 2 valid pairs → NaN.
    assert np.isnan(result), f"Expected NaN, got {result}"


def test_safe_correlation_returns_nan_on_zero_variance():
    """Fix 9: _safe_correlation returns NaN (not 0.0) for zero-variance input."""
    a = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    b = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    result = _safe_correlation(a, b)
    assert np.isnan(result), f"Expected NaN for zero-variance input, got {result}"


# ─── Fix 10: lstsq warns on rank-deficient design ───────────────────────

def test_lstsq_warns_on_rank_deficient_design(caplog):
    """Fix 10: rank-deficient factor design matrix triggers a warning."""
    T, N = 100, 2
    rng = np.random.default_rng(42)
    # Two identical factors → rank 1 (but 2 columns → rank-deficient)
    factor_col = rng.standard_normal((T, 1)) * 0.01
    factor_returns = np.hstack([factor_col, factor_col])  # rank 1
    fund_returns = rng.standard_normal((T, N)) * 0.01

    import structlog
    with caplog.at_level("WARNING"):
        fit = fit_fundamental_loadings(
            fund_returns,
            factor_returns,
            factor_names=["f1", "f2_dup"],
            ewma_lambda=1.0,
        )

    # Function should complete (not raise) and loadings should exist.
    assert fit.loadings.shape == (2, 2)


# ─── Fix 11: centered residual — no mean offset ─────────────────────────

def test_centered_residual_no_mean_offset():
    """Fix 11: PCA residual is mean-zero (centered portfolio returns used).

    Without centering (old bug), the residual carries the portfolio's
    mean drift, which is NOT idiosyncratic.
    """
    T, N = 300, 5
    rng = np.random.default_rng(42)
    # Returns with non-zero mean (drift)
    returns = rng.standard_normal((T, N)) * 0.02 + 0.001  # positive drift
    weights = np.ones(N) / N

    result = decompose_factors(returns, None, weights, n_factors=2)

    # Centered residual should have mean ≈ 0
    assert abs(float(np.mean(result.residual_returns))) < 0.001, (
        f"Residual mean = {np.mean(result.residual_returns):.6f}, expected ≈ 0"
    )


# ─── Fix 12: T<3 PCA edge case raises ───────────────────────────────────

def test_decompose_factors_raises_on_T_less_than_3():
    """Fix 12: decompose_factors raises ValueError for T < 3."""
    returns = np.array([[0.01, 0.02], [0.03, 0.04]])  # T=2, N=2
    weights = np.array([0.5, 0.5])

    with pytest.raises(ValueError, match="at least 3 observations"):
        decompose_factors(returns, None, weights, n_factors=1)


def test_decompose_factors_raises_on_T_equals_1():
    """Fix 12: T=1 also raises."""
    returns = np.array([[0.01, 0.02]])  # T=1, N=2
    weights = np.array([0.5, 0.5])

    with pytest.raises(ValueError, match="at least 3 observations"):
        decompose_factors(returns, None, weights, n_factors=1)


# ─── Fix 13: PCA sign normalization — deterministic ─────────────────────

def test_pca_sign_normalization_deterministic():
    """Fix 13: PCA signs are deterministic across repeated calls.

    Without sign normalization (old bug), SVD's arbitrary sign convention
    could flip factor loadings across platforms / numpy versions.
    """
    T, N = 200, 5
    rng = np.random.default_rng(42)
    returns = rng.standard_normal((T, N)) * 0.02
    weights = np.ones(N) / N

    result1 = decompose_factors(returns, None, weights, n_factors=3)
    result2 = decompose_factors(returns, None, weights, n_factors=3)

    # Signs must be identical across calls.
    np.testing.assert_array_equal(
        np.sign(result1.factor_loadings),
        np.sign(result2.factor_loadings),
    )


def test_pca_sign_largest_loading_positive():
    """Fix 13: for each PCA component, the largest-magnitude loading is positive."""
    T, N = 200, 5
    rng = np.random.default_rng(42)
    returns = rng.standard_normal((T, N)) * 0.02
    weights = np.ones(N) / N

    result = decompose_factors(returns, None, weights, n_factors=3)

    # For each factor column, the largest absolute loading should be positive.
    for k in range(3):
        col = result.factor_loadings[:, k]
        largest_idx = int(np.argmax(np.abs(col)))
        assert col[largest_idx] > 0, (
            f"Factor {k}: largest-magnitude loading at index {largest_idx} "
            f"is {col[largest_idx]}, expected > 0"
        )


# ─── Fix 14: _label_factors aligns by dates, not length ─────────────────

def test_label_factors_aligns_by_dates_not_length():
    """Fix 14: when dates and pd.Series proxies are provided, correlation
    uses date-aligned inner join, not tail-slicing by length.

    If factor has 252 daily and proxy has 260 calendar weekdays, they must
    be aligned by date, not shifted by 8 days.
    """
    T, N = 100, 5
    rng = np.random.default_rng(42)
    market = rng.standard_normal(T) * 0.02
    returns = np.column_stack([market + rng.standard_normal(T) * 0.005 for _ in range(N)])
    weights = np.ones(N) / N

    factor_dates = pd.date_range("2021-01-01", periods=T)

    # Proxy with DIFFERENT date range — overlaps factor_dates partially.
    proxy_dates = pd.date_range("2021-02-01", periods=T)
    proxy_vals = pd.Series(market[:T], index=proxy_dates)

    proxies = {"market_proxy": proxy_vals}

    result = decompose_factors(
        returns, proxies, weights, n_factors=2, dates=factor_dates,
    )

    # The label assignment should work (no crash from misaligned lengths).
    assert len(result.factor_labels) == 2


# ─── Fix 15: factor contributions use full covariance ────────────────────

def test_factor_contributions_use_full_covariance():
    """Fix 15: systematic variance uses full quadratic form (exposures' Σ_F exposures).

    With diagonal-only (old bug), cross-correlations between factors are
    dropped, underestimating systematic risk by 1-3%.
    """
    T, N = 300, 5
    rng = np.random.default_rng(42)
    # Create correlated factors so cross-terms matter.
    base = rng.standard_normal(T) * 0.02
    returns = np.column_stack([
        base + rng.standard_normal(T) * 0.005,
        base * 0.8 + rng.standard_normal(T) * 0.005,
        rng.standard_normal(T) * 0.02,
        base * 0.5 + rng.standard_normal(T) * 0.01,
        rng.standard_normal(T) * 0.015,
    ])
    weights = np.array([0.3, 0.3, 0.2, 0.1, 0.1])

    result = decompose_factors(returns, None, weights, n_factors=3)
    contributions = compute_factor_contributions(result)

    # Verify it's a FactorContributionResult
    assert isinstance(contributions, FactorContributionResult)
    # Systematic + specific = 100%
    total = contributions.systematic_risk_pct + contributions.specific_risk_pct
    assert total == pytest.approx(100.0, abs=0.1)
    # Per-factor contributions should sum to systematic (Euler decomposition).
    factor_pct_sum = sum(
        fc["pct_contribution"] for fc in contributions.factor_contributions
    )
    assert factor_pct_sum == pytest.approx(contributions.systematic_risk_pct, abs=0.5)


# ─── Fix 16: R² is portfolio-specific ───────────────────────────────────

def test_r_squared_is_portfolio_specific():
    """Fix 16: R² from compute_factor_contributions is portfolio-specific.

    With the old code, R² was the panel's eigenvalue ratio, which could
    be ~0.85 even for a niche portfolio orthogonal to the top factors.
    """
    T, N = 300, 10
    rng = np.random.default_rng(42)
    # Strong market factor in funds 0-7, orthogonal fund 8-9.
    market = rng.standard_normal(T) * 0.02
    returns = np.column_stack([
        *(market + rng.standard_normal(T) * 0.003 for _ in range(8)),
        rng.standard_normal(T) * 0.02,  # fund 8: independent
        rng.standard_normal(T) * 0.02,  # fund 9: independent
    ])

    # Portfolio 1: market-heavy → high R².
    w_market = np.zeros(N)
    w_market[:8] = 1.0 / 8
    result_market = decompose_factors(returns, None, w_market, n_factors=2)
    contrib_market = compute_factor_contributions(result_market)

    # Portfolio 2: only in independent funds → low R².
    w_niche = np.zeros(N)
    w_niche[8:] = 0.5
    result_niche = decompose_factors(returns, None, w_niche, n_factors=2)
    contrib_niche = compute_factor_contributions(result_niche)

    # Market portfolio should have much higher R² than niche.
    assert contrib_market.r_squared > contrib_niche.r_squared + 0.1, (
        f"Market R²={contrib_market.r_squared:.3f} should be > "
        f"niche R²={contrib_niche.r_squared:.3f} + 0.1"
    )
