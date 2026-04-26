"""Tests for POT + GPD Extreme Value Theory (EVT) risk estimation."""

from dataclasses import asdict

import numpy as np
import pytest
from scipy.stats import genpareto

from quant_engine.evt.pot_gpd import LMOMENTS_AVAILABLE, extreme_var_evt


def test_gpd_synthetic_recovery():
    """Test 1: GPD synthetic xi=0.3, beta=0.02, T=2000: recover params (MLE)."""
    xi_true = 0.3
    beta_true = 0.02
    T = 2000
    
    # Generate GPD samples
    samples = genpareto.rvs(xi_true, scale=beta_true, size=T, random_state=42)
    
    # u = 0.05, 10% of total losses
    # Total losses N=20000, n_u=2000
    u = 0.05
    bulk = np.random.uniform(0, u, 18000)
    losses = np.concatenate([bulk, samples + u])
    returns = -losses
    
    res = extreme_var_evt(returns)
    
    assert res.fit.method == "mle"
    assert res.fit.converged
    # Within reasonable tolerance for T=2000
    assert pytest.approx(res.fit.xi, abs=0.1) == xi_true
    assert pytest.approx(res.fit.beta, abs=0.005) == beta_true


def test_gpd_exponential_tail():
    """Test 2: GPD synthetic xi=0 (exponential tail): xi_hat approx 0."""
    beta_true = 0.02
    T = 2000
    samples = np.random.exponential(beta_true, size=T)
    u = 0.05
    losses = np.concatenate([np.random.uniform(0, u, 8000), samples + u])
    returns = -losses
    
    res = extreme_var_evt(returns)
    assert abs(res.fit.xi) < 0.1


def test_infinite_mean_tail(monkeypatch):
    """Test 3: Infinite-mean xi=1.1 synthetic -> CVaR=NaN + degraded."""
    # Force MLE and L-moments to return xi >= 1.0
    from scipy.stats import genpareto

    from quant_engine.evt import pot_gpd
    
    def mock_fit_mle(*args, **kwargs):
        return 1.1, 0.0, 0.02
        
    def mock_fit_lm(*args, **kwargs):
        return 1.1, 0.02, True  # PR-Q30: 3-tuple including converged=True

    monkeypatch.setattr(genpareto, "fit", mock_fit_mle)
    if pot_gpd.LMOMENTS_AVAILABLE:
        monkeypatch.setattr(pot_gpd, "_fit_gpd_lmoments", mock_fit_lm)
    
    # We still need enough data to pass the initial checks
    losses = np.linspace(0.01, 0.10, 500)
    returns = -losses
    
    res = extreme_var_evt(returns)
    assert np.isnan(res.cvar_99)
    assert res.degraded
    assert res.degraded_reason == "infinite_mean_tail"


def test_insufficient_exceedances():
    """Test 4: N=15 exceedances -> fallback to normal or degraded."""
    # Force a case where we have enough losses but not enough exceedances
    # losses = 20 values, 90% quantile is at index 18, so 2 exceedances.
    losses = np.linspace(0.001, 0.10, 20)
    returns = -losses
    res = extreme_var_evt(returns)
    assert res.fit.method == "fallback_normal"
    assert res.degraded
    assert res.degraded_reason == "insufficient_exceedances"


def test_boundary_20_exceedances():
    """Test 5: Exactly 20 excesses -> boundary OK."""
    # N_losses = 200, 90% quantile leaves 20 excesses
    losses = np.concatenate([np.linspace(0.001, 0.05, 180), np.linspace(0.051, 0.10, 20)])
    returns = -losses
    
    res = extreme_var_evt(returns)
    assert res.fit.n_exceedances >= 20
    assert not res.degraded


def test_ground_truth_simple():
    """Test 6: Manual verification of VaR formula."""
    # xi=0, beta=0.01, u=0.05, n_u=100, N=1000
    # VaR_99 = u + beta * log((n_u/N) / (1-q))
    # VaR_99 = 0.05 + 0.01 * log(0.1 / 0.01) = 0.05 + 0.01 * log(10) approx 0.05 + 0.023 = 0.073
    T_tail = 100
    samples = np.random.exponential(0.01, size=T_tail)
    u = 0.05
    bulk = np.linspace(0, u, 900)
    losses = np.concatenate([bulk, samples + u])
    returns = -losses
    
    res = extreme_var_evt(returns)
    expected_var_99 = u + 0.01 * np.log((100/1000) / (0.01))
    assert pytest.approx(res.var_99, abs=0.01) == expected_var_99


@pytest.mark.skipif(
    not LMOMENTS_AVAILABLE,
    reason="lmoments3 not installed; test requires L-moments fallback to be available",
)
def test_mle_failure_fallback_lmoments(monkeypatch):
    """Test 7: MLE failure path -> L-moments fallback invoked."""
    from scipy.stats import genpareto
    
    def mock_fit(*args, **kwargs):
        raise ValueError("MLE failed")
        
    monkeypatch.setattr(genpareto, "fit", mock_fit)
    
    returns = np.random.laplace(0, 0.02, 1000)
    res = extreme_var_evt(returns)
    
    # If lmoments3 is installed, it should use it. Otherwise fallback_normal.
    assert res.fit.method in ("lmoments", "fallback_normal")


def test_hill_sanity_triggers(monkeypatch):
    """Test 9: Hill sanity triggers when xi_MLE far from xi_Hill."""
    # We need xi_mle > 0.1 to trigger the check
    from scipy.stats import genpareto
    def mock_fit_mle(*args, **kwargs):
        # returns (shape, loc, scale)
        return 0.3, 0.0, 0.02
        
    monkeypatch.setattr(genpareto, "fit", mock_fit_mle)
    
    from quant_engine.evt import pot_gpd
    def mock_hill(*args, **kwargs):
        return 5.0 # Very different from 0.3
        
    monkeypatch.setattr(pot_gpd, "compute_hill_estimator", mock_hill)
    
    losses = np.linspace(0.01, 0.10, 500)
    returns = -losses
    
    res = extreme_var_evt(returns)
    assert res.degraded
    assert res.degraded_reason == "hill_estimator_divergence"


def test_threshold_quantile_retry():
    """Test 10: Threshold 90% default, switch to 85% when <20 excess."""
    # N_losses = 100. 90% -> 10 excesses (<20). 85% -> 15 excesses (>=15).
    losses = np.concatenate([np.linspace(0.001, 0.05, 85), np.linspace(0.051, 0.10, 15)])
    returns = -losses
    
    res = extreme_var_evt(returns)
    assert res.fit.n_exceedances == 15 # Switched to 85%


def test_nan_handling():
    """Test 11: Returns contain NaN -> stripped before fit."""
    returns = np.random.laplace(0, 0.02, 1000)
    returns[::10] = np.nan
    res = extreme_var_evt(returns)
    assert not np.isnan(res.var_99)


def test_no_losses():
    """Test 12: All positive returns -> insufficient losses."""
    returns = np.random.uniform(0.01, 0.05, 100)
    res = extreme_var_evt(returns)
    assert res.degraded
    assert res.degraded_reason == "insufficient_losses"


def test_monotonic_quantiles():
    """Test 13: Monotonic quantiles: var_99 < var_995 < var_999."""
    returns = np.random.laplace(0, 0.02, 5000)
    res = extreme_var_evt(returns)
    
    assert res.var_99 < res.var_995 < res.var_999
    assert res.cvar_99 < res.cvar_995 < res.cvar_999


def test_cvar_geq_var():
    """Test 14: CVaR >= VaR at same quantile."""
    returns = np.random.laplace(0, 0.02, 5000)
    res = extreme_var_evt(returns)
    
    assert res.cvar_99 >= res.var_99
    assert res.cvar_995 >= res.var_995
    assert res.cvar_999 >= res.var_999


def test_tail_heaviness_mapping():
    """Test 15: Tail heaviness qualitative mapping."""
    from vertical_engines.wealth.dd_report.chapters import _map_tail_heaviness
    
    assert _map_tail_heaviness(-0.1) == "Light"
    assert _map_tail_heaviness(0.05) == "Normal"
    assert _map_tail_heaviness(0.3) == "Heavy"
    assert _map_tail_heaviness(0.6) == "Extreme"
    assert _map_tail_heaviness(None) is None


@pytest.mark.asyncio
async def test_global_risk_metrics_worker_integration(monkeypatch):
    """Test 16: global_risk_metrics worker populates 3 new cols (integration mock)."""
    # This test mocks the database and return fetching to verify the worker logic
    # including the new EVT metrics.
    pass # Placeholder for complex mock


def test_idempotence():
    """Test 17: Idempotence: same returns -> same result."""
    returns = np.random.laplace(0, 0.02, 1000)
    res1 = extreme_var_evt(returns)
    res2 = extreme_var_evt(returns)
    assert res1.var_99 == res2.var_99
    assert res1.fit.xi == res2.fit.xi


def test_fit_serializable():
    """Test 18: Fit object serializable (dataclass to dict)."""
    returns = np.random.laplace(0, 0.02, 1000)
    res = extreme_var_evt(returns)
    d = asdict(res)
    assert isinstance(d, dict)
    assert d["fit"]["xi"] == res.fit.xi


def test_cvar_service_evt_integration():
    """Test 19: cvar_service.compute_cvar works with evt_pot method."""
    from quant_engine.cvar_service import compute_cvar
    returns = np.random.laplace(0, 0.02, 1000)

    res = compute_cvar(returns, method="evt_pot", confidence=0.99)
    assert res.method == "evt_pot"
    # PR-Q13 Fix 2: compute_cvar now returns return-space (negative = loss).
    assert res.cvar < 0
    assert res.evt_xi is not None


def test_quantile_results_populated_for_requested_quantiles():
    """Test 20 (PR-Q14): quantile_results dict carries every requested quantile.

    Pre-PR-Q14 the constructor only populated legacy fields keyed by
    "var_990", "var_995", "var_999". Any other quantile (e.g. 0.95)
    silently fell back to 0.0 because the constructor's results.get()
    looked up a key that was never written. The dict-based lookup keeps
    arbitrary quantiles available to consumers.
    """
    returns = np.random.default_rng(42).laplace(0, 0.02, 1000)
    res = extreme_var_evt(returns, quantiles=(0.95, 0.99, 0.999))

    assert set(res.quantile_results.keys()) == {0.95, 0.99, 0.999}
    var_95, cvar_95 = res.quantile_results[0.95]
    var_99, cvar_99 = res.quantile_results[0.99]
    assert var_95 > 0 and cvar_95 > 0  # non-zero for risky data
    assert cvar_99 >= cvar_95  # higher confidence → larger tail


def test_compute_cvar_evt_default_confidence_no_longer_zeroes():
    """Test 21 (PR-Q14): compute_cvar(method='evt_pot', confidence=0.95)
    now returns real EVT-derived CVaR, not silent (0.0, 0.0).

    Pre-PR-Q14 the else branch in cvar_service mapped 0.95 to res.var_99
    which was never populated (extreme_var_evt was called with
    quantiles=(0.95,) only), so cvar=var=0.0 was returned silently.
    """
    from quant_engine.cvar_service import compute_cvar

    returns = np.random.default_rng(7).laplace(0, 0.02, 1000)
    res = compute_cvar(returns, method="evt_pot", confidence=0.95)
    assert res.method == "evt_pot"
    assert res.confidence == 0.95
    if not res.degraded:
        # PR-Q13 Fix 2: compute_cvar now returns return-space (negative = loss).
        assert res.cvar < 0, "EVT 0.95 returned zero — Q14 fix regressed"
        assert res.var < 0


def test_risk_calc_evt_consumers_unaffected_by_q14():
    """Test 22 (PR-Q14): risk_calc.py consumes legacy var_99/var_999 fields
    directly; those must still be populated when 0.99/0.999 are passed."""
    returns = np.random.default_rng(11).laplace(0, 0.02, 1000)
    res = extreme_var_evt(returns, quantiles=(0.99, 0.999))

    # Legacy fields still populated when matching quantiles requested.
    assert res.var_99 > 0
    assert res.cvar_99 > 0
    assert res.var_999 > 0
    assert res.cvar_999 > 0
    # And the new dict mirrors them.
    assert res.quantile_results[0.99] == (res.var_99, res.cvar_99)
    assert res.quantile_results[0.999] == (res.var_999, res.cvar_999)


def test_lmoments_fallback_does_not_silently_swap_to_exponential(monkeypatch):
    """PR-Q30 F02: when MLE produces xi>=0.9 AND L-moments raises exception,
    code must NOT silently replace heavy-tail with exponential xi=0.

    Setup: MLE returns xi=0.9 (heavy tail). _fit_gpd_lmoments mocked to return
    (0.0, 1.0, False) — simulating the package raising and the fallback firing.
    Caller must observe lm_converged=False and KEEP the MLE estimate xi=0.9.
    """
    from scipy.stats import genpareto

    from quant_engine.evt import pot_gpd

    def mock_fit_mle(*args, **kwargs):
        return 0.9, 0.0, 0.02

    def mock_fit_lm_failed(*args, **kwargs):
        # Simulates the except block returning the fallback tuple
        return 0.0, 1.0, False

    monkeypatch.setattr(genpareto, "fit", mock_fit_mle)
    if pot_gpd.LMOMENTS_AVAILABLE:
        monkeypatch.setattr(pot_gpd, "_fit_gpd_lmoments", mock_fit_lm_failed)

    # Synthesize losses with sufficient excesses
    losses = np.concatenate([np.linspace(0.001, 0.05, 180), np.linspace(0.051, 0.10, 50)])
    returns = -losses

    res = extreme_var_evt(returns)

    # CRITICAL ASSERTION: xi must remain at MLE's heavy-tail estimate (>= 0.5),
    # NOT silently swapped to exponential 0.0.
    assert res.fit.xi >= 0.5, (
        f"Heavy-tail estimate {res.fit.xi} silently swapped to exponential "
        f"despite L-moments fallback failure (xi=0.9 MLE was correct)."
    )
    # method should be "mle" since L-moments failed
    assert res.fit.method == "mle"


def test_lmoments_fallback_succeeds_when_lmoments_returns_valid_xi(monkeypatch):
    """PR-Q30 F02 paired test: when MLE has xi>=0.9 AND _fit_gpd_lmoments
    returns a valid xi<1.0 with converged=True, the swap is intentional and
    the result should reflect the L-moments estimate.

    This is the COMPLEMENT of test_lmoments_fallback_does_not_silently_swap...
    to ensure we did not over-correct.
    """
    from scipy.stats import genpareto

    from quant_engine.evt import pot_gpd

    if not pot_gpd.LMOMENTS_AVAILABLE:
        pytest.skip("lmoments3 not installed in this environment")

    def mock_fit_mle(*args, **kwargs):
        return 0.95, 0.0, 0.02  # MLE heavy-tail near boundary

    def mock_fit_lm_ok(*args, **kwargs):
        return 0.4, 0.05, True  # L-moments converges with milder estimate

    monkeypatch.setattr(genpareto, "fit", mock_fit_mle)
    monkeypatch.setattr(pot_gpd, "_fit_gpd_lmoments", mock_fit_lm_ok)

    losses = np.concatenate([np.linspace(0.001, 0.05, 180), np.linspace(0.051, 0.10, 50)])
    returns = -losses

    res = extreme_var_evt(returns)

    # When L-moments converges legitimately, result should reflect it
    assert res.fit.method == "lmoments"
    assert res.fit.xi == pytest.approx(0.4, abs=0.01)


def test_lmoments_gpa_sign_convention_matches_scipy():
    """PR-Q30 F06: lmoments3 GPA fit must return xi with same sign as scipy genpareto.

    Both scipy.stats.genpareto.fit (`c` parameter) and lmoments3.distr.gpa.lmom_fit
    (`paras['c']`) should follow the Pickands-Balkema-de Haan convention:
    positive shape = heavy tail. If a future package upgrade flips this, this
    test will fail and the orchestrator's CI will catch it.

    The current sign convention is verified against synthetic heavy-tail data:
    we generate samples from genpareto(c=0.5) and assert both estimators recover
    a positive shape parameter.
    """
    from scipy.stats import genpareto

    from quant_engine.evt.pot_gpd import LMOMENTS_AVAILABLE, _fit_gpd_lmoments, _fit_gpd_mle

    if not LMOMENTS_AVAILABLE:
        pytest.skip("lmoments3 not installed in this environment")

    # Synthesize heavy-tail GPD samples: xi=0.5, beta=1.0, threshold u=0
    rng = np.random.default_rng(42)
    samples = genpareto(c=0.5, scale=1.0).rvs(size=2000, random_state=rng)
    excesses = samples[samples > 0]  # POT step — keep only positive excesses

    # MLE estimate
    xi_mle, beta_mle, mle_converged = _fit_gpd_mle(excesses)

    # L-moments estimate
    xi_lm, beta_lm, lm_converged = _fit_gpd_lmoments(excesses)

    # Both should converge for this clean synthetic
    assert mle_converged, "MLE should converge on clean synthetic GPD samples"
    assert lm_converged, "L-moments should converge on clean synthetic GPD samples"

    # Both should agree on sign convention: heavy tail → positive xi
    assert xi_mle > 0.1, f"MLE xi={xi_mle} should reflect heavy tail (>0.1) for c=0.5 input"
    assert xi_lm > 0.1, (
        f"L-moments xi={xi_lm} should reflect heavy tail (>0.1) for c=0.5 input. "
        f"If this fails, the sign convention of lmoments3.distr.gpa has changed "
        f"and the L-moments fallback path in pot_gpd.py silently inverts the "
        f"shape parameter."
    )

    # And approximately agree (within reasonable noise)
    assert abs(xi_mle - xi_lm) < 0.25, (
        f"MLE xi={xi_mle} and L-moments xi={xi_lm} disagree materially. "
        f"This may indicate a sign convention drift, scale parameter divergence, "
        f"or a package version incompatibility."
    )


# ─── PR-Q31 F03 ────────────────────────────────────────────────────────────


def test_extreme_var_evt_filters_inf_consistent_with_sibling_modules():
    """PR-Q31 F03: ±Inf must be filtered before EVT POT to avoid undefined excesses.

    Pre-fix: ~np.isnan() lets ±Inf survive; np.quantile on losses with +inf
    returns inf as the threshold, producing degenerate excesses.
    Post-fix: np.isfinite() drops them; EVT runs cleanly on finite subset.
    """
    # Sufficient finite returns to drive POT + 2 Inf rows
    rng = np.random.default_rng(42)
    finite_returns = rng.normal(0.0, 0.02, size=500)
    returns = np.concatenate([finite_returns, np.array([np.inf, -np.inf])])

    res = extreme_var_evt(returns)

    # Result should not be degraded due to Inf survival (it may be degraded
    # for legitimate POT reasons, but not because of Inf in the input)
    assert np.isfinite(res.fit.u), f"Threshold u should be finite, got {res.fit.u}"
    assert np.isfinite(res.var_99) or res.degraded, (
        f"VaR_99 should be finite when not degraded; got {res.var_99}, degraded={res.degraded}"
    )


# ─── PR-Q31 F05 ────────────────────────────────────────────────────────────


def test_evt_non_convergence_sets_degraded_reason(monkeypatch):
    """PR-Q31 F05: when both MLE and L-moments fail, degraded_reason must be set
    to 'gpd_fit_did_not_converge', not None.
    """
    from quant_engine.evt import pot_gpd

    def mock_fit_mle(*args, **kwargs):
        raise ValueError("synthetic MLE failure")

    def mock_fit_lm_failed(*args, **kwargs):
        return 0.0, 1.0, False  # post-PR-Q30 3-tuple, lm_converged=False

    monkeypatch.setattr(genpareto, "fit", mock_fit_mle)
    if pot_gpd.LMOMENTS_AVAILABLE:
        monkeypatch.setattr(pot_gpd, "_fit_gpd_lmoments", mock_fit_lm_failed)

    # Generate enough data to reach the convergence-check branch
    losses = np.concatenate([np.linspace(0.001, 0.05, 180), np.linspace(0.051, 0.10, 50)])
    returns = -losses

    res = extreme_var_evt(returns)

    assert res.degraded is True
    assert res.degraded_reason == "gpd_fit_did_not_converge"
