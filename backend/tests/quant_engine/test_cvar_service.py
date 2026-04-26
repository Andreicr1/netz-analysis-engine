"""PR-Q13 — CVaR service correctness regression tests.

Each test targets a specific fix from the PR-Q13 spec. Tests are designed
to fail against the pre-fix code and pass against the post-fix code.
"""

import math

import numpy as np
import pytest

from quant_engine.cvar_service import (
    check_breach_status,
    classify_trigger_status,
    compute_cvar,
    compute_cvar_from_returns,
    compute_regime_cvar_audited,
    get_cvar_utilization,
)

# ── Fix 1 — Parametric sign convention (return-space) ────────────────────

def test_parametric_returns_negative_for_losses() -> None:
    """Parametric CVaR/VaR must be negative for a loss-dominated distribution."""
    rng = np.random.default_rng(42)
    # Negative-mean distribution: mostly losses.
    returns = rng.normal(loc=-0.02, scale=0.05, size=500)
    result = compute_cvar(returns, confidence=0.95, method="parametric")
    # Both VaR and CVaR should be negative (return-space: losses are negative).
    assert result.var < 0, f"VaR should be negative for losses, got {result.var}"
    assert result.cvar < 0, f"CVaR should be negative for losses, got {result.cvar}"
    # CVaR should be more negative (worse) than VaR.
    assert result.cvar < result.var, (
        f"CVaR ({result.cvar}) should be <= VaR ({result.var})"
    )


# ── Fix 2 — EVT loss-space → return-space ────────────────────────────────

def test_evt_pot_returns_negative_for_losses() -> None:
    """EVT/POT CVaR/VaR must be negative (return-space) for loss distributions."""
    rng = np.random.default_rng(42)
    # Generate enough data with a fat left tail for EVT to fit.
    returns = rng.normal(loc=-0.001, scale=0.02, size=1000)
    result = compute_cvar(returns, confidence=0.95, method="evt_pot")
    if result.degraded:
        pytest.skip(f"EVT degraded: {result.degraded_reason}")
    assert result.var < 0, f"EVT VaR should be negative, got {result.var}"
    assert result.cvar < 0, f"EVT CVaR should be negative, got {result.cvar}"
    assert result.cvar <= result.var, (
        f"EVT CVaR ({result.cvar}) should be <= VaR ({result.var})"
    )


# ── Fix 3 — Utilization clamps gains to zero ─────────────────────────────

def test_utilization_clamps_gain_to_zero() -> None:
    """A positive cvar_current (gain in worst case) should yield 0% utilization."""
    # cvar_current = +0.05 (gain), limit = -0.08 (loss limit).
    util = get_cvar_utilization(cvar_current=0.05, cvar_limit=-0.08)
    assert util == 0.0, f"Gain should yield 0% utilization, got {util}"


# ── Fix 4 — Zero / positive cvar_limit raises ────────────────────────────

def test_get_cvar_utilization_raises_on_zero_limit() -> None:
    """cvar_limit=0 is a config error and must raise, not silently return 0."""
    with pytest.raises(ValueError, match="must be negative"):
        get_cvar_utilization(cvar_current=-0.05, cvar_limit=0.0)


def test_get_cvar_utilization_raises_on_positive_limit() -> None:
    """cvar_limit>0 is a sign-convention error and must raise."""
    with pytest.raises(ValueError, match="must be negative"):
        get_cvar_utilization(cvar_current=-0.05, cvar_limit=0.08)


# ── Fixes 5 + 10 — Insufficient observations return NaN + degraded ───────

def test_compute_cvar_returns_nan_when_insufficient_obs() -> None:
    """< 5 observations must return NaN with degraded=True, not optimistic 0.0."""
    returns = np.array([-0.01, -0.02, 0.01])
    result = compute_cvar(returns, confidence=0.95, method="historical")
    assert math.isnan(result.cvar), f"Expected NaN cvar, got {result.cvar}"
    assert math.isnan(result.var), f"Expected NaN var, got {result.var}"
    assert result.degraded is True
    assert "insufficient_obs" in (result.degraded_reason or "")

    # Also test parametric path (Fix 10).
    result_p = compute_cvar(returns, confidence=0.95, method="parametric")
    assert math.isnan(result_p.cvar)
    assert result_p.degraded is True


# ── Fix 6 — regime_probs validation ──────────────────────────────────────

def test_compute_regime_cvar_raises_on_invalid_probs() -> None:
    """Regime probs as percentages (0-100) must raise, not silently compute."""
    rng = np.random.default_rng(42)
    returns = rng.normal(loc=0, scale=0.02, size=120)
    # Probs as percentages (40, 60, 80...) instead of [0, 1].
    regime_probs = rng.uniform(20, 90, size=120)
    with pytest.raises(ValueError, match="must be in \\[0, 1\\]"):
        compute_regime_cvar_audited(returns, regime_probs)


# ── Fix 7 — Unconditional fallback uses full history ─────────────────────

def test_regime_unconditional_fallback_uses_full_history() -> None:
    """When regime probs are shorter than returns and stress obs < 30,
    the unconditional fallback must use the full 120m returns, not the
    truncated 24m alignment slice."""
    rng = np.random.default_rng(42)
    full_returns = rng.normal(loc=-0.005, scale=0.04, size=120)
    # Only 24 months of regime data — all low-stress (< 0.5).
    regime_probs = rng.uniform(0.0, 0.3, size=24)

    result = compute_regime_cvar_audited(full_returns, regime_probs)

    # Should be unconditional fallback.
    assert result.is_conditional is False
    assert "insufficient_stress_obs_fallback_to_unconditional" in result.audit_note
    # n_total_obs should reflect the FULL original history.
    assert result.n_total_obs == 120, (
        f"Expected n_total_obs=120 (full history), got {result.n_total_obs}"
    )

    # The CVaR value should match compute_cvar_from_returns on full 120m.
    expected_cvar, _ = compute_cvar_from_returns(full_returns, 0.95)
    assert abs(result.value - expected_cvar) < 1e-10, (
        f"CVaR {result.value} != expected {expected_cvar} from full history"
    )


# ── Fix 8 — VaR index for small samples ──────────────────────────────────

def test_var_index_for_small_samples() -> None:
    """n=20, conf=0.95: tail_count=ceil(1.0)=1, so var=sorted[0] (the worst)."""
    rng = np.random.default_rng(42)
    returns = rng.normal(loc=0, scale=0.02, size=20)
    sorted_returns = np.sort(returns)

    cvar, var = compute_cvar_from_returns(returns, confidence=0.95)

    # With 20 obs at 95%, tail_count = ceil(20 * 0.05) = ceil(1.0) = 1.
    # VaR = sorted[0] (the single worst return).
    assert var == float(sorted_returns[0]), (
        f"VaR should be sorted[0]={sorted_returns[0]}, got {var}"
    )
    # CVaR = mean(sorted[:1]) = sorted[0] (same as VaR for single-obs tail).
    assert cvar == float(sorted_returns[0])


# ── Fix 9 — Parametric sigma uses ddof=1 ─────────────────────────────────

def test_parametric_sigma_uses_ddof_one() -> None:
    """Parametric path must use sample std (ddof=1), not population std (ddof=0)."""
    rng = np.random.default_rng(42)
    # Small sample where ddof=0 vs ddof=1 difference is material (~4.3% for n=12).
    returns = rng.normal(loc=0.001, scale=0.03, size=12)

    result = compute_cvar(returns, confidence=0.95, method="parametric")

    # Compute expected with ddof=1 (sample std).
    from scipy.stats import norm
    mu = float(np.mean(returns))
    sigma_sample = float(np.std(returns, ddof=1))
    z = norm.ppf(0.05)
    expected_var = mu + z * sigma_sample

    assert abs(result.var - expected_var) < 1e-10, (
        f"VaR {result.var} doesn't match ddof=1 expected {expected_var}"
    )

    # Verify it does NOT match ddof=0.
    sigma_pop = float(np.std(returns, ddof=0))
    wrong_var = mu + z * sigma_pop
    assert abs(result.var - wrong_var) > 1e-6, (
        "VaR should NOT match population std (ddof=0)"
    )


# ── Fix 11 — Breach float comparison with epsilon ────────────────────────

def test_classify_trigger_status_handles_float_drift() -> None:
    """Utilization at exactly 100.0 + tiny float drift should NOT trigger breach."""
    # Simulate floating-point drift: 100.0 + 1e-10 (well within epsilon).
    status = classify_trigger_status(
        utilization_pct=100.0 + 1e-10,
        consecutive_days=10,
        breach_consecutive_days=5,
    )
    # Should be "warning" (100% utilization is at the boundary, not a breach).
    assert status == "warning", f"Expected 'warning' at boundary, got '{status}'"

    # But clearly above the threshold should still trigger breach.
    status_above = classify_trigger_status(
        utilization_pct=100.001,
        consecutive_days=10,
        breach_consecutive_days=5,
    )
    assert status_above == "breach", (
        f"Expected 'breach' at 100.001%, got '{status_above}'"
    )


# ── Fix 12 — NaN cvar_current surfaces degraded BreachStatus ─────────────

def test_check_breach_status_returns_degraded_on_nan_cvar() -> None:
    """NaN cvar_current (from insufficient obs) must return trigger_status='degraded'."""
    result = check_breach_status(
        profile="conservative",
        cvar_current=float("nan"),
        consecutive_breach_days=3,
    )
    assert result.trigger_status == "degraded"
    assert result.consecutive_breach_days == 0  # reset when degraded
    assert math.isnan(result.cvar_utilized_pct)
    assert math.isnan(result.cvar_current)


# ── Fix 13 — check_breach_status uses epsilon for consecutive counter ─────

def test_check_breach_status_uses_breach_epsilon_at_boundary() -> None:
    """Utilization at 100 + tiny float drift should NOT increment consecutive days.

    cvar_current / cvar_limit * 100 lands at ~100.0000005 due to float math.
    Both the counter (Fix 13) and classify_trigger_status (Fix 11) must agree
    this is NOT a breach.
    """
    # Construct values where ratio is just barely above 100% due to float drift.
    # cvar_limit = -0.08, cvar_current = -0.08 * (1 + 5e-9) ≈ -0.0800000004
    cvar_limit = -0.08
    cvar_current = cvar_limit * (1.0 + 5e-9)  # tiny overshoot

    result = check_breach_status(
        profile="conservative",
        cvar_current=cvar_current,
        consecutive_breach_days=4,
        config={
            "conservative": {
                "cvar": {
                    "window_months": 12,
                    "confidence": 0.95,
                    "limit": cvar_limit,
                    "warning_pct": 0.80,
                    "breach_days": 5,
                },
            },
        },
    )
    # Counter should NOT increment — the overshoot is within epsilon.
    assert result.consecutive_breach_days == 0, (
        f"Expected counter reset at boundary, got {result.consecutive_breach_days}"
    )
    # Status should be warning (utilization ≈ 100%), not breach.
    assert result.trigger_status == "warning"


# ─── PR-Q31 F03 ────────────────────────────────────────────────────────────


def test_compute_cvar_filters_inf_consistent_with_tail_var():
    """PR-Q31 F03: ±Inf must be filtered out, matching tail_var_service / garch_service convention.

    Pre-fix: ~np.isnan() lets ±Inf survive, producing nan/inf CVaR silently.
    Post-fix: np.isfinite() drops them; CVaR computed over the finite subset.
    """
    # 40 finite returns + 2 Inf rows that must be filtered
    returns = np.concatenate([
        np.array([0.01, 0.02, -0.03, 0.05] * 10),  # 40 finite obs
        np.array([np.inf, -np.inf]),
    ])

    result = compute_cvar(returns, confidence=0.95, method="historical")

    assert np.isfinite(result.cvar), f"CVaR should be finite, got {result.cvar}"
    assert np.isfinite(result.var), f"VaR should be finite, got {result.var}"
    # n_obs reflects finite-filtered count (40), not nan-filtered (would be 42)
    assert result.n_obs == 40


# ── PR-Q32 F01 — Exact RU empirical estimator ────────────────────────────


def test_compute_cvar_from_returns_matches_exact_ru_formula():
    """PR-Q32 F01: compute_cvar_from_returns uses exact RU empirical estimator.

    Reference: T=5 returns with alpha=0.7 (target tail mass = 1.5). Pre-fix
    used ceil(5 * 0.3) = 2 tail items, averaging 2 of the worst returns. Post-fix
    uses the exact RU formula matching the LP minimum.
    """
    # Returns: [0.05, 0.04, 0.03, -0.02, -0.10] (T=5)
    # Losses: [-0.05, -0.04, -0.03, 0.02, 0.10]
    # confidence=0.7 → quantile(losses, 0.7, "higher") = 0.02 (3rd-worst loss)
    # u = max(losses - 0.02, 0) = [0, 0, 0, 0, 0.08]
    # cvar_loss = 0.02 + 0.08 / (0.3 * 5) = 0.02 + 0.0533 = 0.0733
    # Returns negated: cvar = -0.0733, var = -0.02
    returns = np.array([0.05, 0.04, 0.03, -0.02, -0.10])
    cvar, var = compute_cvar_from_returns(returns, confidence=0.7)

    assert cvar == pytest.approx(-0.0733, abs=1e-3)
    assert var == pytest.approx(-0.02, abs=1e-9)
