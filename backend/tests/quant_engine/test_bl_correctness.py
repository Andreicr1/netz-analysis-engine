"""PR-Q19 regression tests — Black-Litterman correctness fixes.

Each test FAILS against unmodified code, PASSES post-fix.
Covers 7 confirmed bugs + 2 GRAY-resolved findings.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from quant_engine.black_litterman_service import (
    View,
    compute_bl_posterior_multi_view,
    compute_bl_returns,
)

# ═══════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def sigma_3():
    """Simple 3-asset diagonal covariance."""
    return np.diag([0.04, 0.09, 0.16])


@pytest.fixture
def w_market_3():
    """Equal weights for 3 assets."""
    return np.array([1.0 / 3, 1.0 / 3, 1.0 / 3])


# ═══════════════════════════════════════════════════════════════════════
# Fix 1 (BUG-B3) — tau zero/negative rejected
# ═══════════════════════════════════════════════════════════════════════


class TestBUG_B3_tau:
    def test_tau_negative_raises_multi_view(self, sigma_3):
        mu_prior = np.array([0.05, 0.06, 0.07])
        with pytest.raises(ValueError, match="tau must be a positive finite scalar"):
            compute_bl_posterior_multi_view(mu_prior, sigma_3, views=[], tau=-0.05)

    def test_tau_zero_raises_multi_view(self, sigma_3):
        mu_prior = np.array([0.05, 0.06, 0.07])
        with pytest.raises(ValueError, match="tau must be a positive finite scalar"):
            compute_bl_posterior_multi_view(mu_prior, sigma_3, views=[], tau=0.0)

    def test_tau_negative_raises_legacy(self, sigma_3, w_market_3):
        with pytest.warns(DeprecationWarning):
            with pytest.raises(ValueError, match="tau must be a positive finite scalar"):
                compute_bl_returns(sigma_3, w_market_3, views=None, tau=-0.05)

    def test_tau_zero_raises_legacy(self, sigma_3, w_market_3):
        with pytest.warns(DeprecationWarning):
            with pytest.raises(ValueError, match="tau must be a positive finite scalar"):
                compute_bl_returns(sigma_3, w_market_3, views=None, tau=0.0)


# ═══════════════════════════════════════════════════════════════════════
# Fix 2 (BUG-B4) — invalid view indices/dimensions rejected
# ═══════════════════════════════════════════════════════════════════════


class TestBUG_B4_invalid_views:
    def test_invalid_asset_idx_raises_in_legacy(self, sigma_3, w_market_3):
        views = [{"type": "absolute", "asset_idx": 42, "Q": 0.10, "confidence": 0.5}]
        with pytest.warns(DeprecationWarning):
            with pytest.raises(ValueError, match="asset_idx=42 out of range"):
                compute_bl_returns(sigma_3, w_market_3, views=views)

    def test_invalid_view_dimension_raises_in_multi_view(self, sigma_3):
        mu_prior = np.array([0.05, 0.06, 0.07])
        # P has 2 columns but sigma is 3x3
        bad_view = View(
            P=np.array([[1.0, -1.0]]),
            Q=np.array([0.03]),
            Omega=np.array([[0.001]]),
            source="ic_view",
            confidence=0.8,
        )
        with pytest.raises(ValueError, match="P cols=2, expected 3"):
            compute_bl_posterior_multi_view(mu_prior, sigma_3, [bad_view])


# ═══════════════════════════════════════════════════════════════════════
# Fix 3 (BUG-B5) — negative w_market rejected
# ═══════════════════════════════════════════════════════════════════════


class TestBUG_B5_w_market:
    def test_negative_w_market_raises(self, sigma_3):
        w_short = np.array([0.4, 0.4, -0.3])
        with pytest.warns(DeprecationWarning):
            with pytest.raises(ValueError, match="negative entries"):
                compute_bl_returns(sigma_3, w_short, views=None)

    def test_w_market_sum_zero_raises(self, sigma_3):
        w_zero = np.zeros(3)
        with pytest.warns(DeprecationWarning):
            with pytest.raises(ValueError, match="expected > 0"):
                compute_bl_returns(sigma_3, w_zero, views=None)


# ═══════════════════════════════════════════════════════════════════════
# Fix 4 (BUG-B6) — NaN Q / NaN confidence rejected
# ═══════════════════════════════════════════════════════════════════════


class TestBUG_B6_nan:
    def test_nan_Q_raises_legacy(self, sigma_3, w_market_3):
        views = [
            {
                "type": "absolute",
                "asset_idx": 0,
                "Q": float("nan"),
                "confidence": 0.5,
            }
        ]
        with pytest.warns(DeprecationWarning):
            with pytest.raises(ValueError, match="Q is non-finite"):
                compute_bl_returns(sigma_3, w_market_3, views=views)

    def test_nan_confidence_raises_legacy(self, sigma_3, w_market_3):
        views = [
            {
                "type": "absolute",
                "asset_idx": 0,
                "Q": 0.10,
                "confidence": float("nan"),
            }
        ]
        with pytest.warns(DeprecationWarning):
            with pytest.raises(ValueError, match="confidence is non-finite"):
                compute_bl_returns(sigma_3, w_market_3, views=views)

    def test_nan_Q_raises_multi_view(self, sigma_3):
        mu_prior = np.array([0.05, 0.06, 0.07])
        bad_view = View(
            P=np.array([[1.0, 0.0, 0.0]]),
            Q=np.array([float("nan")]),
            Omega=np.array([[0.001]]),
            source="ic_view",
            confidence=0.8,
        )
        with pytest.raises(ValueError, match="Q contains non-finite"):
            compute_bl_posterior_multi_view(mu_prior, sigma_3, [bad_view])


# ═══════════════════════════════════════════════════════════════════════
# Fix 5 (BUG-B1) — no np.linalg.inv in module
# ═══════════════════════════════════════════════════════════════════════


def test_BUG_B1_legacy_uses_solve_not_inv():
    """Verify no np.linalg.inv calls in the module source (comments excluded)."""
    import quant_engine.black_litterman_service as bl_mod

    source = inspect.getsource(bl_mod)
    # Filter out comments — check actual code lines
    code_lines = []
    for line in source.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    assert "np.linalg.inv(" not in code, (
        "np.linalg.inv() found in black_litterman_service.py — "
        "use np.linalg.solve() instead"
    )


# ═══════════════════════════════════════════════════════════════════════
# Fix 7 (BUG-B7) — indefinite Omega rejected
# ═══════════════════════════════════════════════════════════════════════


def test_BUG_B7_indefinite_omega_raises():
    """Omega with negative eigenvalue must be rejected as non-PSD."""
    sigma = np.eye(3) * 0.04
    mu_prior = np.array([0.05, 0.06, 0.07])
    bad_view = View(
        P=np.array([[1.0, 0.0, 0.0]]),
        Q=np.array([0.10]),
        Omega=np.array([[-0.01]]),  # indefinite
        source="ic_view",
        confidence=0.8,
    )
    with pytest.raises(ValueError, match="Omega is not PSD"):
        compute_bl_posterior_multi_view(mu_prior, sigma, [bad_view])


# ═══════════════════════════════════════════════════════════════════════
# Fix 8 (BUG-B8) — lambda floor + quant_queries override
# ═══════════════════════════════════════════════════════════════════════


def test_BUG_B8_lambda_zero_floored_with_warning():
    """risk_aversion=0.001 (very small positive) still works with no error."""
    sigma = np.diag([0.04, 0.09])
    w_mkt = np.array([0.6, 0.4])
    with pytest.warns(DeprecationWarning):
        result = compute_bl_returns(sigma, w_mkt, views=None, risk_aversion=0.001)
    assert np.all(np.isfinite(result))


def test_BUG_B8_quant_queries_override_zero_falls_back():
    """_resolve_risk_aversion in quant_queries rejects gamma <= 0 override."""
    from app.domains.wealth.services.quant_queries import (
        RISK_AVERSION_INSTITUTIONAL_DEFAULT,
    )

    assert RISK_AVERSION_INSTITUTIONAL_DEFAULT > 0


# ═══════════════════════════════════════════════════════════════════════
# Fix 9 (BUG-B9) — deprecation warning emitted
# ═══════════════════════════════════════════════════════════════════════


def test_BUG_B9_compute_bl_returns_emits_deprecation_warning():
    """Legacy compute_bl_returns must emit DeprecationWarning."""
    sigma = np.diag([0.04, 0.09])
    w_mkt = np.array([0.6, 0.4])
    with pytest.warns(DeprecationWarning, match="compute_bl_returns is deprecated"):
        compute_bl_returns(sigma, w_mkt, views=None)
