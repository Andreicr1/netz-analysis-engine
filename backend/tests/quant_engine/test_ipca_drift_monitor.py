"""Tests for IPCA gamma drift monitor (PR-Q35 F01: Procrustes alignment)."""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.ipca.drift_monitor import compute_gamma_drift


class TestProcrustesAlignment:
    """PR-Q35 F01: drift must be invariant under orthogonal rotation / sign flip."""

    def test_sign_flip_produces_zero_drift(self):
        """Pure sign flip is a valid IPCA equivalence — drift must be 0.0, not 2.0."""
        rng = np.random.default_rng(42)
        gamma_old = rng.normal(0.0, 1.0, size=(10, 3))
        gamma_new = -gamma_old

        drift = compute_gamma_drift(gamma_old, gamma_new)

        assert drift == pytest.approx(0.0, abs=1e-10), (
            f"Sign flip should produce drift=0.0 (Procrustes-aligned), got {drift}. "
            f"If ~2.0, F01 Procrustes alignment was not applied."
        )

    def test_orthogonal_rotation_produces_zero_drift(self):
        """Arbitrary orthogonal rotation is a valid IPCA equivalence — drift must be 0.0."""
        rng = np.random.default_rng(42)
        gamma_old = rng.normal(0.0, 1.0, size=(10, 3))

        # Random orthogonal matrix via QR decomposition
        Q, _ = np.linalg.qr(rng.normal(0.0, 1.0, size=(3, 3)))
        gamma_new = gamma_old @ Q

        drift = compute_gamma_drift(gamma_old, gamma_new)

        assert drift == pytest.approx(0.0, abs=1e-10), (
            f"Orthogonal rotation should produce drift=0.0, got {drift}"
        )

    def test_real_drift_still_detected(self):
        """A non-rotational change must still be detected as drift."""
        rng = np.random.default_rng(42)
        gamma_old = rng.normal(0.0, 1.0, size=(10, 3))
        # Add genuine perturbation (not orthogonal)
        gamma_new = gamma_old + rng.normal(0.0, 0.5, size=(10, 3))

        drift = compute_gamma_drift(gamma_old, gamma_new)

        # Drift should be substantial (> threshold) but not 0
        assert drift > 0.1, f"Real drift not detected: {drift}"

    def test_identical_matrices_zero_drift(self):
        """gamma_new = gamma_old must produce drift=0.0."""
        rng = np.random.default_rng(42)
        gamma = rng.normal(0.0, 1.0, size=(10, 3))

        drift = compute_gamma_drift(gamma, gamma.copy())

        assert drift == pytest.approx(0.0, abs=1e-10)

    def test_shape_mismatch_raises(self):
        """Backward-compat: shape mismatch still raises ValueError."""
        gamma_old = np.zeros((10, 3))
        gamma_new = np.zeros((10, 4))

        with pytest.raises(ValueError, match="Shape mismatch"):
            compute_gamma_drift(gamma_old, gamma_new)

    def test_zero_norm_old_returns_zero(self):
        """Backward-compat: norm_old < 1e-12 returns 0.0 unchanged."""
        gamma_old = np.zeros((10, 3))
        gamma_new = np.ones((10, 3))

        drift = compute_gamma_drift(gamma_old, gamma_new)

        assert drift == 0.0
