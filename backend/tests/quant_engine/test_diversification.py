"""Tests for ``quant_engine.diversification_service``.

Covers §2 validation list from
``docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md`` and the
acceptance gates in the PR-Q2 prompt.
"""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.diversification_service import (
    ENBResult,
    effective_number_of_bets,
)


def _rng(seed: int = 0) -> np.random.Generator:
    return np.random.default_rng(seed)


def test_uniform_rc_recovers_k():
    """Σ_f = I_K and p_f = 1_K / √K → every RC_k = 1/K → N_ent = K."""
    K = 5
    Sigma_f = np.eye(K)
    # Pick w, B such that p_f = B^T w = ones(K) / sqrt(K)
    N = K
    B = np.eye(N)  # loadings = identity
    w = np.ones(K) / np.sqrt(K)

    result = effective_number_of_bets(w, B, Sigma_f, method="both")

    assert result.degraded is False
    assert result.n_factors == K
    np.testing.assert_allclose(result.risk_contributions, np.full(K, 1.0 / K), atol=1e-10)
    assert abs(result.enb_entropy - float(K)) < 1e-6
    # With Σ_f = I, torsion = I → MT ENB = entropy ENB
    assert result.enb_minimum_torsion is not None
    assert abs(result.enb_minimum_torsion - float(K)) < 1e-6


def test_degenerate_single_factor_concentration():
    """All mass loaded onto one factor → N_ent → 1."""
    K = 4
    Sigma_f = np.eye(K)
    B = np.zeros((3, K))
    B[0, 0] = 1.0  # asset 0 exposed only to factor 0
    w = np.array([1.0, 0.0, 0.0])

    result = effective_number_of_bets(w, B, Sigma_f, method="entropy")

    assert result.degraded is False
    # Exactly one RC = 1, others = 0 → entropy 0 → exp(0) = 1
    assert abs(result.enb_entropy - 1.0) < 1e-10
    assert result.enb_minimum_torsion is None  # method="entropy"


def test_mt_greater_or_equal_entropy_correlated_factors():
    """For correlated factors, MT ENB ≥ entropy ENB (Meucci property)."""
    rng = _rng(42)
    K = 4
    # Build a correlated factor covariance
    A = rng.standard_normal((K, K))
    Sigma_f = A @ A.T + 0.1 * np.eye(K)

    N = 6
    B = rng.standard_normal((N, K))
    w = rng.dirichlet(np.ones(N))

    result = effective_number_of_bets(w, B, Sigma_f, method="both")

    assert result.degraded is False
    assert result.enb_minimum_torsion is not None
    # Allow tiny numerical slack
    assert result.enb_minimum_torsion >= result.enb_entropy - 1e-6


@pytest.mark.parametrize("N,K", [(100, 5), (10, 5), (5, 20)])
def test_shape_coverage(N: int, K: int):
    """Runs cleanly across fat, square, and wide loading matrices."""
    rng = _rng(7)
    A = rng.standard_normal((K, K))
    Sigma_f = A @ A.T + 0.05 * np.eye(K)
    B = rng.standard_normal((N, K))
    w = rng.standard_normal(N)

    result = effective_number_of_bets(w, B, Sigma_f, method="both")

    if result.degraded:
        # Only acceptable when zero portfolio variance slipped through
        assert result.degraded_reason is not None
        return
    assert isinstance(result, ENBResult)
    assert result.n_factors == K
    assert result.risk_contributions.shape == (K,)
    assert result.factor_exposures.shape == (K,)
    # Entropy ENB bounded by K
    assert 1.0 - 1e-6 <= result.enb_entropy <= K + 1e-6


def test_non_psd_sigma_f_degrades():
    """Non-PSD factor covariance → degraded=True, reason factor_cov_not_psd."""
    K = 3
    Sigma_f = np.eye(K)
    Sigma_f[0, 0] = -1.0  # forces a negative eigenvalue
    B = np.eye(K)
    w = np.ones(K)

    result = effective_number_of_bets(w, B, Sigma_f)

    assert result.degraded is True
    assert result.degraded_reason == "factor_cov_not_psd"
    assert np.isnan(result.enb_entropy)


def test_nan_weights_degrades():
    K = 3
    Sigma_f = np.eye(K)
    B = np.eye(K)
    w = np.array([1.0, np.nan, 0.5])

    result = effective_number_of_bets(w, B, Sigma_f)

    assert result.degraded is True
    assert result.degraded_reason == "nan_in_inputs"


def test_k_equals_one_edge():
    """Single factor → ENB identically 1.0 for both methods."""
    N = 4
    B = np.ones((N, 1))
    Sigma_f = np.array([[0.04]])
    w = np.array([0.25, 0.25, 0.25, 0.25])

    result = effective_number_of_bets(w, B, Sigma_f, method="both")

    assert result.degraded is False
    assert result.n_factors == 1
    assert result.enb_entropy == pytest.approx(1.0)
    assert result.enb_minimum_torsion == pytest.approx(1.0)


def test_method_parameter_output_presence():
    """method controls which fields are populated:

    - "entropy" → enb_minimum_torsion is None
    - "minimum_torsion" → enb_minimum_torsion is a float (entropy always computed too)
    - "both" → both are floats
    """
    rng = _rng(11)
    K = 3
    A = rng.standard_normal((K, K))
    Sigma_f = A @ A.T + 0.1 * np.eye(K)
    B = rng.standard_normal((5, K))
    w = rng.dirichlet(np.ones(5))

    r_ent = effective_number_of_bets(w, B, Sigma_f, method="entropy")
    r_mt = effective_number_of_bets(w, B, Sigma_f, method="minimum_torsion")
    r_both = effective_number_of_bets(w, B, Sigma_f, method="both")

    assert r_ent.enb_minimum_torsion is None
    assert isinstance(r_ent.enb_entropy, float)

    assert r_mt.enb_minimum_torsion is not None
    assert isinstance(r_mt.enb_minimum_torsion, float)

    assert r_both.enb_entropy == pytest.approx(r_ent.enb_entropy)
    assert r_both.enb_minimum_torsion is not None
    assert r_both.enb_minimum_torsion == pytest.approx(r_mt.enb_minimum_torsion)


def test_risk_contributions_sum_to_one():
    """Euler decomposition invariant: Σ RC_k = 1 for any valid input."""
    rng = _rng(99)
    K = 6
    A = rng.standard_normal((K, K))
    Sigma_f = A @ A.T + 0.2 * np.eye(K)
    B = rng.standard_normal((10, K))
    w = rng.standard_normal(10)

    result = effective_number_of_bets(w, B, Sigma_f, method="both")

    assert result.degraded is False
    assert abs(result.risk_contributions.sum() - 1.0) < 1e-10


def test_scale_invariance_of_weights():
    """Scaling weights by λ ≠ 0 leaves RC (and ENB) unchanged."""
    rng = _rng(3)
    K = 4
    A = rng.standard_normal((K, K))
    Sigma_f = A @ A.T + 0.1 * np.eye(K)
    B = rng.standard_normal((8, K))
    w = rng.standard_normal(8)

    base = effective_number_of_bets(w, B, Sigma_f, method="both")
    scaled = effective_number_of_bets(2.5 * w, B, Sigma_f, method="both")

    assert not base.degraded and not scaled.degraded
    np.testing.assert_allclose(
        base.risk_contributions, scaled.risk_contributions, atol=1e-10
    )
    assert base.enb_entropy == pytest.approx(scaled.enb_entropy)
    assert scaled.enb_minimum_torsion is not None
    assert base.enb_minimum_torsion == pytest.approx(scaled.enb_minimum_torsion)


def test_shape_mismatch_degrades():
    """Inconsistent loadings/weights shape → degraded with explicit reason."""
    Sigma_f = np.eye(3)
    B = np.zeros((4, 3))
    w = np.ones(5)  # mismatched N

    result = effective_number_of_bets(w, B, Sigma_f)

    assert result.degraded is True
    assert result.degraded_reason == "loadings_weights_shape_mismatch"


def test_pure_function_no_input_mutation():
    """Service must not mutate caller-provided arrays."""
    K = 3
    Sigma_f = np.eye(K) * 0.04
    B = np.eye(K)
    w = np.array([0.3, 0.4, 0.3])

    w_before = w.copy()
    B_before = B.copy()
    S_before = Sigma_f.copy()

    effective_number_of_bets(w, B, Sigma_f, method="both")

    np.testing.assert_array_equal(w, w_before)
    np.testing.assert_array_equal(B, B_before)
    np.testing.assert_array_equal(Sigma_f, S_before)
