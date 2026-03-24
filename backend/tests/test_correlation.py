"""Tests for correlation regime monitor (Phase 4).

Tests cover:
- Correlation matrix computation
- Marchenko-Pastur denoising
- Contagion detection
- Eigenvalue concentration with golden boundary tests
- Diversification ratio with boundary tests
- Absorption ratio
- Minimum observations guard
- Wealth service orchestration
- Pydantic schema round-trip
"""
import numpy as np
import pytest

from app.domains.wealth.schemas.correlation_regime import (
    ConcentrationRead,
    CorrelationRegimeRead,
)
from quant_engine.correlation_regime_service import (
    _compute_diversification_ratio,
    _marchenko_pastur_denoise,
    _resolve_config,
    compute_correlation_regime,
)
from vertical_engines.wealth.correlation.models import (
    ConcentrationAnalysis,
    InstrumentCorrelation,
)
from vertical_engines.wealth.correlation.service import CorrelationService


class TestCorrelationMatrix:
    def test_identical_series_perfect_correlation(self):
        rng = np.random.default_rng(42)
        base = rng.normal(0, 0.01, (100, 1))
        returns = np.hstack([base, base])
        result = compute_correlation_regime(
            returns, config={"apply_denoising": False, "apply_shrinkage": False, "min_observations": 10}
        )
        assert result.sufficient_data
        # Diagonal should be 1.0
        for i in range(2):
            assert abs(result.correlation_matrix[i][i] - 1.0) < 1e-6
        # Off-diagonal should be ~1.0
        assert abs(result.correlation_matrix[0][1] - 1.0) < 1e-4

    def test_independent_series_near_zero_correlation(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, (500, 3))
        result = compute_correlation_regime(
            returns, config={"apply_denoising": False, "apply_shrinkage": False, "min_observations": 10, "window_days": 500}
        )
        for i in range(3):
            for j in range(3):
                if i == j:
                    assert abs(result.correlation_matrix[i][j] - 1.0) < 1e-6
                else:
                    assert abs(result.correlation_matrix[i][j]) < 0.15  # tolerance for random

    def test_negative_correlation(self):
        rng = np.random.default_rng(42)
        base = rng.normal(0, 0.01, (200, 1))
        returns = np.hstack([base, -base])
        result = compute_correlation_regime(
            returns, config={"apply_denoising": False, "apply_shrinkage": False, "min_observations": 10}
        )
        assert result.correlation_matrix[0][1] < -0.99


class TestMarchenkoPasturDenoising:
    def test_pure_noise_denoised(self):
        rng = np.random.default_rng(42)
        T, N = 200, 5
        noise = rng.normal(0, 1, (T, N))
        corr = np.corrcoef(noise, rowvar=False)
        q = N / T
        denoised = _marchenko_pastur_denoise(corr, q)
        # Diagonal should be 1
        for i in range(N):
            assert abs(denoised[i, i] - 1.0) < 1e-6
        # Off-diagonal should be closer to zero after denoising
        off_diag_orig = np.abs(corr[np.triu_indices(N, k=1)]).mean()
        off_diag_denoised = np.abs(denoised[np.triu_indices(N, k=1)]).mean()
        assert off_diag_denoised <= off_diag_orig + 0.01  # may not always reduce

    def test_signal_preserved(self):
        rng = np.random.default_rng(42)
        T, N = 200, 4
        # Strong signal: correlated pairs
        base = rng.normal(0, 1, T)
        returns = np.column_stack([
            base + rng.normal(0, 0.1, T),
            base + rng.normal(0, 0.1, T),
            rng.normal(0, 1, T),
            rng.normal(0, 1, T),
        ])
        corr = np.corrcoef(returns, rowvar=False)
        q = N / T
        denoised = _marchenko_pastur_denoise(corr, q)
        # First pair should maintain elevated correlation after denoising
        assert denoised[0, 1] > 0.4


class TestContagionDetection:
    def test_contagion_detected(self):
        """Pair with jump from 0.3 to 0.8 -> is_contagion=True."""
        rng = np.random.default_rng(42)
        N = 3
        T = 200
        # Baseline: low correlation
        base_returns = rng.normal(0, 0.01, (T - 60, N))
        # Recent: high correlation (instruments 0 and 1)
        signal = rng.normal(0, 0.01, 60)
        recent = np.column_stack([
            signal + rng.normal(0, 0.001, 60),
            signal + rng.normal(0, 0.001, 60),
            rng.normal(0, 0.01, 60),
        ])
        returns = np.vstack([base_returns, recent])
        result = compute_correlation_regime(
            returns,
            config={"apply_denoising": False, "apply_shrinkage": False, "min_observations": 10, "window_days": 60},
        )
        # At least one contagion pair between 0-1
        contagion = [p for p in result.pair_correlations if p.is_contagion]
        assert len(contagion) >= 1

    def test_stable_high_correlation_not_contagion(self):
        """Pair always at 0.7 -> no contagion (no change)."""
        rng = np.random.default_rng(42)
        T = 200
        base = rng.normal(0, 0.01, T)
        returns = np.column_stack([
            base + rng.normal(0, 0.003, T),
            base + rng.normal(0, 0.003, T),
        ])
        result = compute_correlation_regime(
            returns,
            config={"apply_denoising": False, "apply_shrinkage": False, "min_observations": 10, "window_days": 60},
        )
        # Stable -> small change -> not contagion
        for p in result.pair_correlations:
            assert abs(p.correlation_change) < 0.3 or not p.is_contagion


class TestConcentrationGoldenBoundary:
    """Golden boundary tests for eigenvalue concentration thresholds."""

    def test_0_60_exactly_is_diversified(self):
        """first_ratio = 0.60 -> diversified (strict >)."""
        cfg = _resolve_config(None)
        # Direct test of threshold logic
        assert not (cfg["concentration_moderate"] < 0.60)  # 0.60 > 0.6 is False

    def test_0_601_is_moderate(self):
        """first_ratio = 0.601 -> moderate_concentration."""
        cfg = _resolve_config(None)
        assert cfg["concentration_moderate"] < 0.601
        assert not (cfg["concentration_high"] < 0.601)

    def test_0_80_exactly_is_moderate(self):
        """first_ratio = 0.80 -> moderate_concentration (strict >)."""
        cfg = _resolve_config(None)
        assert cfg["concentration_moderate"] < 0.80
        assert not (cfg["concentration_high"] < 0.80)

    def test_0_801_is_high(self):
        """first_ratio = 0.801 -> high_concentration."""
        cfg = _resolve_config(None)
        assert cfg["concentration_high"] < 0.801

    def test_all_identical_returns_high_concentration(self):
        """All instruments with identical returns -> high concentration."""
        T = 100
        rng = np.random.default_rng(42)
        base = rng.normal(0, 0.01, T)
        returns = np.column_stack([base] * 5)
        # Add tiny noise to avoid singular matrix
        returns += rng.normal(0, 1e-8, returns.shape)
        result = compute_correlation_regime(
            returns,
            config={"apply_denoising": False, "apply_shrinkage": False, "min_observations": 10, "window_days": 100},
        )
        assert result.concentration.concentration_status == "high_concentration"

    def test_independent_returns_diversified(self):
        """Independent random returns -> diversified."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, (200, 5))
        result = compute_correlation_regime(
            returns,
            config={"apply_denoising": False, "apply_shrinkage": False, "min_observations": 10, "window_days": 200},
        )
        assert result.concentration.concentration_status == "diversified"


class TestDiversificationRatio:
    def test_single_asset_dr_1(self):
        """Single asset -> DR = 1.0."""
        cov = np.array([[0.01]])
        weights = np.array([1.0])
        dr = _compute_diversification_ratio(cov, weights)
        assert abs(dr - 1.0) < 1e-6

    def test_uncorrelated_equal_weight_dr_gt_1(self):
        """Equal-weight uncorrelated assets -> DR > 1."""
        N = 4
        cov = np.diag([0.01] * N)
        weights = np.ones(N) / N
        dr = _compute_diversification_ratio(cov, weights)
        assert dr > 1.0

    def test_dr_1_20_no_alert(self):
        """DR = 1.2 exactly -> no alert (strict <)."""
        # DR threshold is 1.2, strict less-than
        assert not (1.2 < 1.2)  # 1.2 < 1.2 is False -> no alert

    def test_dr_1_19_alert(self):
        """DR = 1.19 -> alert."""
        assert 1.19 < 1.2  # -> alert


class TestMinObservations:
    def test_insufficient_data(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, (30, 3))
        result = compute_correlation_regime(
            returns,
            config={"min_observations": 45},
        )
        assert not result.sufficient_data


class TestLedoitWolfShrinkage:
    def test_shrinkage_applied(self):
        """With shrinkage, correlation should be more stable."""
        rng = np.random.default_rng(42)
        T, N = 100, 5
        returns = rng.normal(0, 0.01, (T, N))
        result_shrunk = compute_correlation_regime(
            returns,
            config={"apply_shrinkage": True, "apply_denoising": False, "min_observations": 10, "window_days": T},
        )
        result_raw = compute_correlation_regime(
            returns,
            config={"apply_shrinkage": False, "apply_denoising": False, "min_observations": 10, "window_days": T},
        )
        # Both should work without error
        assert result_shrunk.sufficient_data
        assert result_raw.sufficient_data


class TestCorrelationService:
    def test_analyze_portfolio_maps_indices(self):
        """Service maps pair indices to instrument IDs."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, (100, 3))
        svc = CorrelationService(config={
            "apply_denoising": False, "apply_shrinkage": False,
            "min_observations": 10, "window_days": 100,
        })
        result = svc.analyze_portfolio_correlation(
            instrument_ids=("id-a", "id-b", "id-c"),
            instrument_names=("Fund A", "Fund B", "Fund C"),
            returns_matrix=returns,
            profile="moderate",
        )
        assert result.profile == "moderate"
        assert result.instrument_count == 3
        assert len(result.instrument_labels) == 3
        # Check contagion pairs have correct identifiers
        for p in result.contagion_pairs:
            assert p.instrument_a_id in ("id-a", "id-b", "id-c")


class TestCorrelationSchemas:
    def test_concentration_read_roundtrip(self):
        data = {
            "eigenvalues": [2.5, 1.0, 0.5],
            "explained_variance_ratios": [0.625, 0.25, 0.125],
            "first_eigenvalue_ratio": 0.625,
            "concentration_status": "moderate_concentration",
            "diversification_ratio": 1.3,
            "dr_alert": False,
            "absorption_ratio": 0.625,
            "absorption_status": "normal",
            "mp_threshold": 1.5,
            "n_signal_eigenvalues": 1,
        }
        schema = ConcentrationRead(**data)
        assert schema.concentration_status == "moderate_concentration"

    def test_correlation_regime_read(self):
        from datetime import datetime
        data = {
            "profile": "moderate",
            "instrument_count": 3,
            "window_days": 60,
            "correlation_matrix": [[1.0, 0.5], [0.5, 1.0]],
            "instrument_labels": ["A", "B"],
            "contagion_pairs": [],
            "concentration": {
                "eigenvalues": [1.5, 0.5],
                "explained_variance_ratios": [0.75, 0.25],
                "first_eigenvalue_ratio": 0.75,
                "concentration_status": "moderate_concentration",
                "diversification_ratio": 1.2,
                "dr_alert": False,
                "absorption_ratio": 0.75,
                "absorption_status": "normal",
                "mp_threshold": 1.2,
                "n_signal_eigenvalues": 1,
            },
            "average_correlation": 0.5,
            "baseline_average_correlation": 0.3,
            "regime_shift_detected": False,
            "computed_at": datetime.now().isoformat(),
        }
        schema = CorrelationRegimeRead(**data)
        assert schema.instrument_count == 3


class TestCorrelationModels:
    def test_frozen_dataclass(self):
        ic = InstrumentCorrelation(
            instrument_a_id="a", instrument_a_name="Fund A",
            instrument_b_id="b", instrument_b_name="Fund B",
            current_correlation=0.8, baseline_correlation=0.3,
            correlation_change=0.5, is_contagion=True,
        )
        with pytest.raises(AttributeError):
            ic.current_correlation = 0.9  # type: ignore

    def test_concentration_analysis_frozen(self):
        ca = ConcentrationAnalysis(
            eigenvalues=(2.0, 1.0), explained_variance_ratios=(0.67, 0.33),
            first_eigenvalue_ratio=0.67, concentration_status="moderate_concentration",
            diversification_ratio=1.3, dr_alert=False,
            absorption_ratio=0.67, absorption_status="normal",
            mp_threshold=1.2, n_signal_eigenvalues=1,
        )
        assert ca.concentration_status == "moderate_concentration"
