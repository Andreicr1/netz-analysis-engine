"""Multi-view Black-Litterman tests (PR-A2).

Covers compute_bl_posterior_multi_view — the new entry point that stacks
heterogeneous views (data view + IC views) into a single BL posterior solve.

Acceptance per docs/prompts/2026-04-14-construction-engine-phase-a.md:
- single stacked view yields the same posterior as the canonical one-view solve
- two stacked views combine correctly (posterior between prior and both views)
- confidence=0.999 and confidence=1.0 both converge numerically (Ω regularization)
- a very high-Ω view (low confidence) leaves the posterior near the prior
"""

from __future__ import annotations

import numpy as np

from quant_engine.black_litterman_service import (
    REG_OMEGA_EPS_FACTOR,
    TAU_PHASE_A,
    View,
    compute_bl_posterior_multi_view,
)

# ═══════════════════════════════════════════════════════════════════════
# Analytic reference: single-view canonical BL posterior
# ═══════════════════════════════════════════════════════════════════════


def _canonical_bl_single_view(
    mu_prior: np.ndarray,
    sigma: np.ndarray,
    P: np.ndarray,
    Q: np.ndarray,
    Omega: np.ndarray,
    tau: float,
) -> np.ndarray:
    """Textbook BL posterior formula — direct inv-based reference for tests."""
    tau_sigma_inv = np.linalg.inv(tau * sigma)
    Omega_inv = np.linalg.inv(Omega)
    M = tau_sigma_inv + P.T @ Omega_inv @ P
    rhs = tau_sigma_inv @ mu_prior + P.T @ Omega_inv @ Q
    return np.linalg.solve(M, rhs)


# ═══════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════


def test_empty_views_returns_prior_unchanged() -> None:
    mu_prior = np.array([0.08, 0.06, 0.05])
    sigma = np.eye(3) * 0.04
    result = compute_bl_posterior_multi_view(mu_prior, sigma, views=[], tau=TAU_PHASE_A)
    np.testing.assert_allclose(result, mu_prior, atol=1e-12)


def test_single_view_matches_canonical_bl_formula() -> None:
    """One stacked View must match the canonical inv-based BL posterior."""
    rng = np.random.default_rng(7)
    N = 4
    mu_prior = np.array([0.07, 0.09, 0.05, 0.08])
    A = rng.standard_normal((N, N)) * 0.05
    sigma = A @ A.T + np.eye(N) * 0.04  # PSD

    P = np.eye(1, N, k=2)  # view on asset index 2
    Q = np.array([0.12])
    Omega = np.array([[0.001]])
    tau = TAU_PHASE_A

    view = View(P=P, Q=Q, Omega=Omega, source="ic_view", confidence=0.9)
    got = compute_bl_posterior_multi_view(mu_prior, sigma, [view], tau=tau)

    expected = _canonical_bl_single_view(mu_prior, sigma, P, Q, Omega, tau)
    # Ω regularization adds a tiny eps; posterior should match within that noise.
    np.testing.assert_allclose(got, expected, atol=1e-5, rtol=1e-5)


def test_two_stacked_views_produce_intermediate_posterior() -> None:
    """Posterior lies between prior and both views for two moderate-confidence views."""
    N = 3
    mu_prior = np.array([0.05, 0.05, 0.05])
    sigma = np.eye(N) * 0.04

    # View 1: asset 0 = 10%, moderate certainty
    v1 = View(
        P=np.array([[1.0, 0.0, 0.0]]),
        Q=np.array([0.10]),
        Omega=np.array([[0.001]]),
        source="ic_view", confidence=0.7,
    )
    # View 2: asset 1 = 12%, moderate certainty
    v2 = View(
        P=np.array([[0.0, 1.0, 0.0]]),
        Q=np.array([0.12]),
        Omega=np.array([[0.001]]),
        source="ic_view", confidence=0.7,
    )
    post = compute_bl_posterior_multi_view(mu_prior, sigma, [v1, v2], tau=TAU_PHASE_A)

    # Posterior for asset 0 lies strictly between prior (0.05) and view (0.10)
    assert 0.05 < post[0] < 0.10
    # Posterior for asset 1 lies strictly between prior (0.05) and view (0.12)
    assert 0.05 < post[1] < 0.12
    # Asset 2 has no view → stays close to prior (diagonal Σ means no cross-term pull)
    assert abs(post[2] - 0.05) < 1e-3


def test_very_high_omega_view_leaves_posterior_near_prior() -> None:
    """A data view with huge Ω (near-zero confidence) must barely move the prior."""
    N = 2
    mu_prior = np.array([0.05, 0.07])
    sigma = np.eye(N) * 0.04

    v_weak = View(
        P=np.eye(N),
        Q=np.array([0.20, 0.20]),
        Omega=np.eye(N) * 1e6,  # absurdly weak view
        source="data_view", confidence=None,
    )
    post = compute_bl_posterior_multi_view(mu_prior, sigma, [v_weak], tau=TAU_PHASE_A)
    np.testing.assert_allclose(post, mu_prior, atol=1e-3)


def test_confidence_0999_posterior_near_view() -> None:
    """Confidence=0.999 (tiny-but-nonzero Ω) must nearly match the view exactly."""
    N = 2
    mu_prior = np.array([0.05, 0.07])
    sigma = np.eye(N) * 0.04
    tau = TAU_PHASE_A

    # Idzorek Ω at confidence=0.999: Ω ≈ prior_var · (0.001/0.999)
    P = np.eye(1, N, k=0)
    prior_var = float(P @ (tau * sigma) @ P.T)
    omega_ii = prior_var * (1 - 0.999) / 0.999
    view = View(
        P=P, Q=np.array([0.15]), Omega=np.array([[omega_ii]]),
        source="ic_view", confidence=0.999,
    )
    post = compute_bl_posterior_multi_view(mu_prior, sigma, [view], tau=tau)
    assert abs(post[0] - 0.15) < 5e-3
    # Asset 1 unaffected (diagonal sigma)
    assert abs(post[1] - 0.07) < 1e-3


def test_confidence_100_omega_zero_regularization_solves_cleanly() -> None:
    """Confidence=1.0 → Ω_ii=0 must not raise LinAlgError (Ω regularization)."""
    N = 3
    mu_prior = np.array([0.05, 0.06, 0.07])
    sigma = np.eye(N) * 0.04

    view = View(
        P=np.array([[1.0, 0.0, 0.0]]),
        Q=np.array([0.20]),
        Omega=np.array([[0.0]]),  # certainty-1.0 → singular pre-reg
        source="ic_view", confidence=1.0,
    )
    post = compute_bl_posterior_multi_view(mu_prior, sigma, [view], tau=TAU_PHASE_A)
    assert np.all(np.isfinite(post))
    # Certain view should dominate asset 0; tolerance looser because of eps
    assert abs(post[0] - 0.20) < 1e-2


def test_confidence_0999_and_100_both_converge_within_same_range() -> None:
    """Adjacent confidences (0.999 vs 1.0) must produce nearby posteriors."""
    N = 2
    mu_prior = np.array([0.05, 0.07])
    sigma = np.eye(N) * 0.04
    tau = TAU_PHASE_A

    P = np.array([[1.0, 0.0]])
    prior_var = float(P @ (tau * sigma) @ P.T)
    omega_999 = prior_var * (1 - 0.999) / 0.999

    v_999 = View(
        P=P, Q=np.array([0.15]), Omega=np.array([[omega_999]]),
        source="ic_view", confidence=0.999,
    )
    v_100 = View(
        P=P, Q=np.array([0.15]), Omega=np.array([[0.0]]),
        source="ic_view", confidence=1.0,
    )
    post_999 = compute_bl_posterior_multi_view(mu_prior, sigma, [v_999], tau=tau)
    post_100 = compute_bl_posterior_multi_view(mu_prior, sigma, [v_100], tau=tau)
    np.testing.assert_allclose(post_999, post_100, atol=5e-3)


def test_data_view_plus_ic_view_stack_correctly() -> None:
    """Mixing a data view (identity P) and an IC view (single row) stacks as block_diag Ω."""
    N = 3
    mu_prior = np.array([0.05, 0.06, 0.07])
    sigma = np.eye(N) * 0.04
    tau = TAU_PHASE_A

    # Data view: each asset has its own view on its own mean with moderate Ω
    data_view = View(
        P=np.eye(N),
        Q=np.array([0.04, 0.08, 0.06]),
        Omega=np.eye(N) * 0.005,
        source="data_view", confidence=None,
    )
    # IC view: analyst believes asset 1 > asset 2 by 3%
    ic_view = View(
        P=np.array([[0.0, 1.0, -1.0]]),
        Q=np.array([0.03]),
        Omega=np.array([[0.001]]),
        source="ic_view", confidence=0.8,
    )
    post = compute_bl_posterior_multi_view(
        mu_prior, sigma, [data_view, ic_view], tau=tau,
    )
    assert np.all(np.isfinite(post))
    # Asset 0 pulled toward data view (0.04, down from 0.05)
    assert post[0] < 0.05
    # IC relative view pushes asset 1 up and asset 2 down relative to their data views
    assert post[1] > post[2]


def test_tau_fixed_at_phase_a_default() -> None:
    """TAU_PHASE_A must remain 0.05 — regime-conditional τ is Phase B."""
    assert TAU_PHASE_A == 0.05


def test_omega_regularization_epsilon_scale_aware() -> None:
    """Large-magnitude Ω gets proportionally larger eps — not a fixed 1e-8."""
    N = 2
    mu_prior = np.zeros(N)
    sigma = np.eye(N) * 0.04

    big_omega_view = View(
        P=np.eye(N),
        Q=np.array([0.02, 0.02]),
        Omega=np.eye(N) * 1e3,
        source="data_view", confidence=None,
    )
    # Should not raise; eps is trace-scaled so huge Ω doesn't dwarf eps.
    post = compute_bl_posterior_multi_view(
        mu_prior, sigma, [big_omega_view], tau=TAU_PHASE_A,
    )
    assert np.all(np.isfinite(post))
    # Sanity on the constant
    assert REG_OMEGA_EPS_FACTOR == 1e-8


def test_relative_view_shifts_spread_between_assets() -> None:
    """A relative view (long A, short B) must widen the A-B spread in posterior."""
    N = 3
    mu_prior = np.array([0.06, 0.06, 0.06])
    sigma = np.eye(N) * 0.04

    rel_view = View(
        P=np.array([[1.0, -1.0, 0.0]]),
        Q=np.array([0.05]),  # A should beat B by 5%
        Omega=np.array([[0.0005]]),
        source="ic_view", confidence=0.9,
    )
    post = compute_bl_posterior_multi_view(mu_prior, sigma, [rel_view], tau=TAU_PHASE_A)
    # A-B spread must move toward +0.05
    spread = post[0] - post[1]
    assert 0.0 < spread <= 0.05 + 1e-6
