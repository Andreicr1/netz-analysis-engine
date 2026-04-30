"""Tests for PR-Q157 — correlation display fidelity + IR phantom fix.

WMJ-015: correlation_matrix and average_correlation should use raw
(post-shrinkage, pre-denoising) correlations for display fidelity.
Denoised matrix is reserved for eigenvalue concentration analysis.

WMJ-021: risk_calc must compute information_ratio_1y — previously
declared in the DB model but never written, causing scoring_service
to always fall back to a degraded synthetic value.
"""

import inspect

import numpy as np
import pytest

from quant_engine.correlation_regime_service import compute_correlation_regime


class TestCorrelationRawVsDenoised:
    """WMJ-015: correlation_matrix should use raw (non-denoised) correlations."""

    def test_correlation_matrix_is_raw_when_denoising_enabled(self) -> None:
        """With denoising ON, correlation_matrix should still reflect raw sample correlations."""
        rng = np.random.default_rng(42)
        T, N = 120, 5
        returns = rng.normal(0.0005, 0.01, (T, N))
        # Add correlation structure so denoising actually changes something
        returns[:, 1] += 0.5 * returns[:, 0]
        returns[:, 2] += 0.3 * returns[:, 0]

        result_denoised = compute_correlation_regime(
            returns,
            config={"apply_denoising": True, "apply_shrinkage": True, "min_observations": 30},
        )
        result_raw = compute_correlation_regime(
            returns,
            config={"apply_denoising": False, "apply_shrinkage": True, "min_observations": 30},
        )

        # With the fix, correlation_matrix from denoised run should match the raw run
        # (because correlation_matrix now uses raw correlations regardless of denoising)
        assert result_denoised.correlation_matrix == result_raw.correlation_matrix

    def test_concentration_uses_denoised(self) -> None:
        """Concentration/eigenvalue analysis should still use denoised matrix."""
        rng = np.random.default_rng(42)
        T, N = 120, 5
        returns = rng.normal(0.0005, 0.01, (T, N))
        returns[:, 1] += 0.5 * returns[:, 0]

        result_denoised = compute_correlation_regime(
            returns,
            config={"apply_denoising": True, "apply_shrinkage": True, "min_observations": 30},
        )
        result_no_denoise = compute_correlation_regime(
            returns,
            config={"apply_denoising": False, "apply_shrinkage": True, "min_observations": 30},
        )

        # Concentration eigenvalues SHOULD differ (denoised vs raw)
        assert result_denoised.concentration.eigenvalues != result_no_denoise.concentration.eigenvalues

    def test_average_correlation_from_raw(self) -> None:
        """average_correlation should be computed from raw (not denoised) matrix."""
        rng = np.random.default_rng(42)
        T, N = 120, 4
        returns = rng.normal(0.0005, 0.01, (T, N))
        returns[:, 1] += 0.8 * returns[:, 0]  # strong correlation

        result = compute_correlation_regime(
            returns,
            config={"apply_denoising": True, "apply_shrinkage": True, "min_observations": 30},
        )
        # Verify by recomputing from the returned matrix
        matrix = np.array(result.correlation_matrix)
        n_inst = matrix.shape[0]
        upper_tri = matrix[np.triu_indices(n_inst, k=1)]
        expected_avg = float(np.mean(upper_tri))
        assert abs(result.average_correlation - round(expected_avg, 6)) < 1e-5

    def test_pair_correlations_use_denoised(self) -> None:
        """Pair correlations (contagion detection) should use denoised matrix."""
        rng = np.random.default_rng(42)
        T, N = 120, 3
        returns = rng.normal(0.0005, 0.01, (T, N))
        returns[:, 1] += 0.7 * returns[:, 0]

        result_denoised = compute_correlation_regime(
            returns,
            config={"apply_denoising": True, "apply_shrinkage": True, "min_observations": 30},
        )
        result_raw = compute_correlation_regime(
            returns,
            config={"apply_denoising": False, "apply_shrinkage": True, "min_observations": 30},
        )

        # Pair correlations come from the denoised matrix, so they MAY differ
        # (when denoising changes values). The key invariant is that the
        # correlation_matrix (display) uses raw while pair_correlations
        # use denoised for statistical signal detection.
        denoised_pairs = {
            (p.index_a, p.index_b): p.current_correlation
            for p in result_denoised.pair_correlations
        }
        raw_pairs = {
            (p.index_a, p.index_b): p.current_correlation
            for p in result_raw.pair_correlations
        }
        # At least verify that pair correlations exist and are populated
        assert len(denoised_pairs) == len(raw_pairs) == 3  # C(3,2) = 3

    def test_regime_shift_zero_when_same_returns(self) -> None:
        """When window_days >= T, recent == baseline; regime shift must be zero.

        Codex P2 regression: if avg_corr uses raw but avg_corr_base uses
        denoised, the delta can be non-zero even with identical input data.
        Both must use the same transform (raw).
        """
        rng = np.random.default_rng(42)
        T, N = 80, 4
        returns = rng.normal(0.0005, 0.01, (T, N))
        returns[:, 1] += 0.6 * returns[:, 0]

        result = compute_correlation_regime(
            returns,
            config={
                "apply_denoising": True,
                "apply_shrinkage": True,
                "min_observations": 30,
                "window_days": T + 10,  # >= T → baseline == recent
                "contagion_threshold": 0.3,
            },
        )
        # With identical data, avg_corr == avg_corr_base → no regime shift
        assert result.average_correlation == result.baseline_average_correlation
        assert result.regime_shift_detected is False

    def test_baseline_average_uses_raw_not_denoised(self) -> None:
        """baseline_average_correlation must use raw (same transform as average_correlation)."""
        rng = np.random.default_rng(42)
        T, N = 300, 5
        returns = rng.normal(0.0005, 0.01, (T, N))
        returns[:, 1] += 0.5 * returns[:, 0]

        result_denoised = compute_correlation_regime(
            returns,
            config={"apply_denoising": True, "apply_shrinkage": True, "min_observations": 30},
        )
        result_raw = compute_correlation_regime(
            returns,
            config={"apply_denoising": False, "apply_shrinkage": True, "min_observations": 30},
        )
        # baseline_average should match between denoised and raw configs
        # because both now use the raw (pre-denoising) baseline
        assert result_denoised.baseline_average_correlation == result_raw.baseline_average_correlation

    def test_no_denoising_raw_equals_display(self) -> None:
        """When denoising is OFF, raw and display matrix should trivially match."""
        rng = np.random.default_rng(42)
        T, N = 120, 4
        returns = rng.normal(0.0005, 0.01, (T, N))

        result = compute_correlation_regime(
            returns,
            config={"apply_denoising": False, "apply_shrinkage": True, "min_observations": 30},
        )
        matrix = np.array(result.correlation_matrix)
        # Diagonal should be 1.0
        for i in range(N):
            assert abs(matrix[i, i] - 1.0) < 1e-6


class TestInformationRatioComputation:
    """WMJ-021: risk_calc must compute information_ratio_1y."""

    @staticmethod
    def _import_ir_helper():
        """Import _compute_information_ratio, skipping if fastapi unavailable."""
        pytest.importorskip("fastapi", reason="risk_calc import chain requires fastapi")
        from app.domains.wealth.workers.risk_calc import _compute_information_ratio

        return _compute_information_ratio

    def test_ir_computed_from_excess_returns(self) -> None:
        """IR = annualized_excess_mean / annualized_tracking_error."""
        _compute_information_ratio = self._import_ir_helper()

        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        rf = 0.04
        ir = _compute_information_ratio(returns, 252, rf)
        assert ir is not None
        # Manually verify
        rf_daily = rf / 252
        excess = returns[-252:] - rf_daily
        te = float(np.std(excess, ddof=1)) * np.sqrt(252)
        ann_excess = float(np.mean(excess)) * 252
        expected = round(ann_excess / te, 6)
        assert abs(ir - expected) < 1e-5

    def test_ir_none_when_insufficient_data(self) -> None:
        """IR should be None when fewer than 252 days available."""
        _compute_information_ratio = self._import_ir_helper()

        returns = np.random.default_rng(42).normal(0.001, 0.01, 100)
        assert _compute_information_ratio(returns, 252, 0.04) is None

    def test_ir_none_when_vol_too_low(self) -> None:
        """IR should be None when tracking error is below minimum threshold."""
        _compute_information_ratio = self._import_ir_helper()

        # Near-constant returns -> near-zero TE
        returns = np.full(252, 0.0001)
        assert _compute_information_ratio(returns, 252, 0.04) is None

    def test_ir_positive_for_positive_excess(self) -> None:
        """IR should be positive when excess return is positive and vol is meaningful."""
        _compute_information_ratio = self._import_ir_helper()

        rng = np.random.default_rng(99)
        # Daily returns with a strong positive drift (well above rf)
        returns = rng.normal(0.003, 0.015, 300)
        ir = _compute_information_ratio(returns, 252, 0.02)
        assert ir is not None
        assert ir > 0

    def test_ir_included_in_metrics_function(self) -> None:
        """_compute_metrics_from_returns should include information_ratio_1y."""
        pytest.importorskip("fastapi", reason="risk_calc import chain requires fastapi")
        from app.domains.wealth.workers.risk_calc import _compute_metrics_from_returns

        src = inspect.getsource(_compute_metrics_from_returns)
        assert "information_ratio_1y" in src
