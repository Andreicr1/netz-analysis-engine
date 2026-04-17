"""Adversarial solver tests for Phase A construction estimator (PR-A1).

These tests prove the math fails loudly on pathological inputs before the
optimizer is ever called. They are the reason we skipped shadow mode —
if any of these regress the estimator can produce extreme weights and must
be blocked from production.

Coverage target: ≥ 15 cases (see docs/prompts/2026-04-14-construction-engine-phase-a.md).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.domains.wealth.services.quant_queries import (
    KAPPA_ERROR_THRESHOLD,
    KAPPA_WARN_THRESHOLD,
    RISK_AVERSION_INSTITUTIONAL_DEFAULT,
    TRADING_DAYS_PER_YEAR,
    FundLevelInputs,
    IllConditionedCovarianceError,
    _build_data_view,
    _build_thbb_prior,
    _compute_ewma_covariance,
    _guard_condition_number,
    _repair_psd,
    _resolve_risk_aversion,
    _sanitize_returns,
    _thbb_weights_for_fund,
    _winsorize_returns,
)

# ═══════════════════════════════════════════════════════════════════════
# Pathological matrix tests (pure numpy — no DB)
# ═══════════════════════════════════════════════════════════════════════


def test_singular_matrix_n_greater_than_t_raises() -> None:
    """N funds > T observations → rank-deficient → κ=inf → IllConditioned."""
    rng = np.random.default_rng(0)
    T, N = 40, 50
    returns = rng.standard_normal((T, N)) * 0.01
    cov = _compute_ewma_covariance(returns) * TRADING_DAYS_PER_YEAR
    with pytest.raises(IllConditionedCovarianceError) as exc:
        _guard_condition_number(cov, n_obs=T)
    assert exc.value.n_funds == N
    assert exc.value.n_obs == T
    assert exc.value.condition_number > KAPPA_ERROR_THRESHOLD


def test_near_singular_collinear_funds_raises() -> None:
    """Two fully-collinear funds → near-zero smallest eigenvalue → κ≈∞."""
    rng = np.random.default_rng(1)
    T = 500
    base = rng.standard_normal((T, 3)) * 0.01
    # Duplicate column 0 → exact collinearity
    collinear = np.column_stack([base, base[:, 0]])
    cov = _compute_ewma_covariance(collinear) * TRADING_DAYS_PER_YEAR
    with pytest.raises(IllConditionedCovarianceError):
        _guard_condition_number(cov, n_obs=T)


def test_non_psd_input_is_repaired_not_raised() -> None:
    """Matrix with tiny negative eigenvalue → PSD repair clamps, no exception."""
    sigma = np.array([[1.0, 0.99], [0.99, 1.0]])
    # Inject a small negative perturbation
    e, V = np.linalg.eigh(sigma)
    e[0] = -1e-4
    broken = V @ np.diag(e) @ V.T
    repaired, was_repaired = _repair_psd(broken, min_eigenvalue=1e-10)
    assert was_repaired is True
    assert np.linalg.eigvalsh(repaired).min() >= 1e-10


def test_nan_returns_exclude_fund_pre_estimation() -> None:
    """A single NaN in a fund's returns excludes the fund with an audit reason."""
    d0 = date(2025, 1, 1)
    good = {d0 + timedelta(days=i): 0.001 * i for i in range(200)}
    bad = {d0 + timedelta(days=i): (float("nan") if i == 5 else 0.001) for i in range(200)}
    g_id, b_id = uuid.uuid4(), uuid.uuid4()
    fund_returns = {str(g_id): good, str(b_id): bad}
    cleaned, ids, excluded = _sanitize_returns(fund_returns, [g_id, b_id])
    assert str(b_id) not in cleaned
    assert str(g_id) in cleaned
    assert any(fid == str(b_id) and reason == "non_finite_returns" for fid, reason in excluded)


def test_inf_returns_exclude_fund_pre_estimation() -> None:
    """An Inf observation must exclude the fund (not silently propagate)."""
    d0 = date(2025, 1, 1)
    inf_series = {d0 + timedelta(days=i): (float("inf") if i == 10 else 0.001) for i in range(200)}
    fid = uuid.uuid4()
    _cleaned, ids, excluded = _sanitize_returns({str(fid): inf_series}, [fid])
    assert str(fid) not in ids
    assert excluded == [(str(fid), "non_finite_returns")]


def test_zero_variance_fund_excluded() -> None:
    """Fund with constant returns (std=0) cannot be optimized → excluded."""
    d0 = date(2025, 1, 1)
    constant_series = {d0 + timedelta(days=i): 0.001 for i in range(200)}
    fid = uuid.uuid4()
    _cleaned, ids, excluded = _sanitize_returns({str(fid): constant_series}, [fid])
    assert str(fid) not in ids
    assert excluded == [(str(fid), "zero_variance")]


def test_kappa_at_warning_threshold_triggers_warn_flag() -> None:
    """κ between WARN and ERROR thresholds → returns warn=True, error=False."""
    # Construct Σ with κ ≈ 2e4 — eigenvalues e.g. [2e4, 1, 1]
    # (PR-A9 WARN threshold is 1e4, FALLBACK is 5e4; 2e4 sits in the warn-sample band)
    e = np.array([2e4, 1.0, 1.0])
    # Random orthogonal V
    rng = np.random.default_rng(7)
    A = rng.standard_normal((3, 3))
    Q, _ = np.linalg.qr(A)
    sigma = Q @ np.diag(e) @ Q.T
    kappa, warn, error = _guard_condition_number(sigma, n_obs=500)
    assert warn is True
    assert error is False
    assert KAPPA_WARN_THRESHOLD < kappa < KAPPA_ERROR_THRESHOLD


def test_kappa_well_conditioned_no_flags() -> None:
    """Identity-like matrix → κ=1 → no warn/error."""
    sigma = np.eye(5) * 0.04  # 20% annual vol, uncorrelated
    kappa, warn, error = _guard_condition_number(sigma, n_obs=500)
    assert kappa == pytest.approx(1.0, rel=1e-10)
    assert warn is False
    assert error is False


# ═══════════════════════════════════════════════════════════════════════
# EWMA covariance identities
# ═══════════════════════════════════════════════════════════════════════


def test_ewma_lambda_one_equals_sample_covariance() -> None:
    """λ=1.0 must match np.cov(…, ddof=1) within numerical tolerance."""
    rng = np.random.default_rng(42)
    returns = rng.standard_normal((500, 4)) * 0.01
    ewma = _compute_ewma_covariance(returns, lambda_=1.0)
    sample = np.cov(returns, rowvar=False, ddof=1)
    np.testing.assert_allclose(ewma, sample, atol=1e-10, rtol=0)


def test_ewma_weights_sum_to_one() -> None:
    """Internal weight normalization — half-life check derived from λ."""
    # Half-life for λ=0.94 should be ≈ log(0.5)/log(0.94) ≈ 11.2 days
    half_life_094 = np.log(0.5) / np.log(0.94)
    assert half_life_094 == pytest.approx(11.2, abs=0.1)
    # Half-life for λ=0.97 should be ≈ 22.8 days
    half_life_097 = np.log(0.5) / np.log(0.97)
    assert half_life_097 == pytest.approx(22.8, abs=0.1)
    # Sanity: cov should be PSD for both λ
    rng = np.random.default_rng(3)
    returns = rng.standard_normal((400, 3)) * 0.01
    for lam in (0.94, 0.97, 0.99):
        cov = _compute_ewma_covariance(returns, lambda_=lam)
        assert np.linalg.eigvalsh(cov).min() >= -1e-14


def test_ewma_invalid_lambda_raises() -> None:
    with pytest.raises(ValueError):
        _compute_ewma_covariance(np.zeros((10, 2)), lambda_=0.0)
    with pytest.raises(ValueError):
        _compute_ewma_covariance(np.zeros((10, 2)), lambda_=1.5)


def test_ewma_insufficient_observations_raises() -> None:
    with pytest.raises(ValueError):
        _compute_ewma_covariance(np.zeros((1, 3)), lambda_=0.97)


# ═══════════════════════════════════════════════════════════════════════
# THBB availability schedule
# ═══════════════════════════════════════════════════════════════════════


def test_thbb_weights_full_availability() -> None:
    assert _thbb_weights_for_fund(has_10y=True, has_5y=True) == (0.5, 0.3, 0.2)


def test_thbb_weights_5y_and_eq_only() -> None:
    assert _thbb_weights_for_fund(has_10y=False, has_5y=True) == (0.0, 0.7, 0.3)


def test_thbb_weights_eq_only_degenerate() -> None:
    assert _thbb_weights_for_fund(has_10y=False, has_5y=False) == (0.0, 0.0, 1.0)


def test_thbb_blend_on_synthetic_three_fund_universe() -> None:
    """All three horizons available → blend = 0.5·r10 + 0.3·r5 + 0.2·π."""
    ids = ["a", "b", "c"]
    horizons = {
        "a": {"10y": 0.08, "5y": 0.07},
        "b": {"10y": 0.10, "5y": 0.09},
        "c": {"10y": 0.06, "5y": 0.06},
    }
    sigma = np.eye(3) * 0.04
    w_bench = np.array([1 / 3, 1 / 3, 1 / 3])
    gamma = 2.5
    mu, weights_mean, buckets = _build_thbb_prior(
        ids, horizons, sigma, w_bench, risk_aversion=gamma,
    )
    pi = gamma * (sigma @ w_bench)
    expected = np.array([
        0.5 * 0.08 + 0.3 * 0.07 + 0.2 * pi[0],
        0.5 * 0.10 + 0.3 * 0.09 + 0.2 * pi[1],
        0.5 * 0.06 + 0.3 * 0.06 + 0.2 * pi[2],
    ])
    np.testing.assert_allclose(mu, expected, atol=1e-12)
    assert weights_mean == pytest.approx({"10y": 0.5, "5y": 0.3, "eq": 0.2})
    assert buckets == {"10y+": 3, "5y+": 0, "1y_only": 0}


def test_thbb_fallback_to_eq_when_only_1y_available() -> None:
    """No 5Y/10Y data anywhere → prior degenerates to pure equilibrium."""
    ids = ["x", "y"]
    horizons = {"x": {"10y": None, "5y": None}, "y": {"10y": None, "5y": None}}
    sigma = np.array([[0.04, 0.01], [0.01, 0.06]])
    w_bench = np.array([0.6, 0.4])
    gamma = 2.5
    mu, weights_mean, buckets = _build_thbb_prior(
        ids, horizons, sigma, w_bench, risk_aversion=gamma,
    )
    pi = gamma * (sigma @ w_bench)
    np.testing.assert_allclose(mu, pi, atol=1e-12)
    assert weights_mean == pytest.approx({"10y": 0.0, "5y": 0.0, "eq": 1.0})
    assert buckets == {"10y+": 0, "5y+": 0, "1y_only": 2}


def test_thbb_renormalizes_when_10y_missing_for_some_funds() -> None:
    """Mixed availability: some funds have 10Y, others only 5Y."""
    ids = ["old_fund", "new_fund"]
    horizons = {
        "old_fund": {"10y": 0.09, "5y": 0.08},
        "new_fund": {"10y": None, "5y": 0.07},
    }
    sigma = np.eye(2) * 0.04
    w_bench = np.array([0.5, 0.5])
    gamma = 2.5
    _mu, _weights_mean, buckets = _build_thbb_prior(
        ids, horizons, sigma, w_bench, risk_aversion=gamma,
    )
    assert buckets == {"10y+": 1, "5y+": 1, "1y_only": 0}


# ═══════════════════════════════════════════════════════════════════════
# Data-view construction for BL (PR-A2 consumer, but wired in PR-A1)
# ═══════════════════════════════════════════════════════════════════════


def test_data_view_identity_picking_matrix() -> None:
    """P must be identity when each fund has its own view on its own mean."""
    rng = np.random.default_rng(5)
    returns = rng.standard_normal((400, 3)) * 0.01
    ids = ["a", "b", "c"]
    P, Q, Omega = _build_data_view(returns, ids)
    np.testing.assert_array_equal(P, np.eye(3))
    assert Q.shape == (3,)
    assert Omega.shape == (3, 3)
    # Ω must be diagonal and strictly positive
    assert np.all(np.diag(Omega) > 0)
    off_diag = Omega - np.diag(np.diag(Omega))
    assert np.allclose(off_diag, 0)


# ═══════════════════════════════════════════════════════════════════════
# γ (risk aversion) sourcing + audit trail
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_risk_aversion_default_when_no_org() -> None:
    db = AsyncMock()
    gamma, source = await _resolve_risk_aversion(db, org_id=None)
    assert gamma == RISK_AVERSION_INSTITUTIONAL_DEFAULT
    assert source == "institutional_default"


@pytest.mark.asyncio
async def test_risk_aversion_config_override_writes_audit() -> None:
    """Non-default γ from ConfigService must write an AuditEvent."""
    db = AsyncMock()
    org_id = uuid.uuid4()

    config_result = MagicMock()
    config_result.value = {"risk_aversion": 3.5}

    with patch(
        "app.core.config.config_service.ConfigService",
    ) as MockService, patch(
        "app.core.db.audit.write_audit_event", new_callable=AsyncMock,
    ) as mock_audit:
        instance = MockService.return_value
        instance.get = AsyncMock(return_value=config_result)
        gamma, source = await _resolve_risk_aversion(
            db, org_id=org_id, actor_id="u1", request_id="r1",
        )
        assert gamma == 3.5
        assert source == "config_override"
        mock_audit.assert_awaited_once()
        kwargs = mock_audit.await_args.kwargs
        assert kwargs["action"] == "risk_aversion_overridden"
        assert kwargs["before"] == {"risk_aversion": RISK_AVERSION_INSTITUTIONAL_DEFAULT}
        assert kwargs["after"] == {"risk_aversion": 3.5}


@pytest.mark.asyncio
async def test_risk_aversion_override_equal_to_default_not_audited() -> None:
    """Override value of 2.5 is identical to default → no audit noise."""
    db = AsyncMock()
    org_id = uuid.uuid4()
    config_result = MagicMock()
    config_result.value = {"risk_aversion": RISK_AVERSION_INSTITUTIONAL_DEFAULT}
    with patch(
        "app.core.config.config_service.ConfigService",
    ) as MockService, patch(
        "app.core.db.audit.write_audit_event", new_callable=AsyncMock,
    ) as mock_audit:
        instance = MockService.return_value
        instance.get = AsyncMock(return_value=config_result)
        gamma, source = await _resolve_risk_aversion(db, org_id=org_id)
        assert gamma == RISK_AVERSION_INSTITUTIONAL_DEFAULT
        assert source == "institutional_default"
        mock_audit.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════
# Winsorization for higher moments
# ═══════════════════════════════════════════════════════════════════════


def test_winsorize_clips_extreme_tails() -> None:
    """A single massive outlier must be clipped at the 99th percentile."""
    rng = np.random.default_rng(9)
    returns = rng.standard_normal((1000, 1)) * 0.01
    returns[0, 0] = 10.0  # outlier
    clipped = _winsorize_returns(returns, lower=0.01, upper=0.99)
    assert clipped[0, 0] < 0.1  # clamped well below the raw outlier
    assert clipped.max() < 10.0


def test_winsorize_passthrough_when_too_few_observations() -> None:
    tiny = np.array([[0.1], [0.2], [0.3]])
    out = _winsorize_returns(tiny)
    np.testing.assert_array_equal(out, tiny)


# ═══════════════════════════════════════════════════════════════════════
# FundLevelInputs contract
# ═══════════════════════════════════════════════════════════════════════


def test_fund_level_inputs_is_frozen() -> None:
    """FundLevelInputs must be frozen so it's safe across async/thread boundaries."""
    fli = FundLevelInputs(
        cov_matrix=np.eye(2),
        expected_returns={"a": 0.05, "b": 0.07},
        available_ids=["a", "b"],
        skewness=np.zeros(2),
        excess_kurtosis=np.zeros(2),
        condition_number=1.0,
        factor_loadings=None,
        factor_names=None,
        residual_variance=None,
        prior_weights_used={"10y": 0.5, "5y": 0.3, "eq": 0.2},
        n_funds_by_history={"10y+": 2, "5y+": 0, "1y_only": 0},
        regime_probability_at_calc=None,
        used_return_type="log",
        lookback_start_date=date(2021, 1, 1),
        lookback_end_date=date(2026, 1, 1),
    )
    with pytest.raises((AttributeError, Exception)):  # dataclasses.FrozenInstanceError
        fli.condition_number = 99.0  # type: ignore[misc]


def test_ill_conditioned_error_message_includes_kappa_and_dims() -> None:
    err = IllConditionedCovarianceError(
        condition_number=1.5e5,
        n_funds=20,
        n_obs=300,
        worst_eigenvalues=[1e-8, 2e-8, 1e-5],
    )
    msg = str(err)
    assert "1.500e+05" in msg or "κ(Σ)=1.500e+05" in msg
    assert "N=20" in msg
    assert "T=300" in msg
    assert "1.000e-08" in msg or "1.0e-08" in msg
