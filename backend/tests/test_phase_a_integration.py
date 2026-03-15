"""Integration tests for Phase A: Credit Engine Quant Architecture Parity.

Tests extracted modules, new services, and decoupled components.
Uses differential testing (new vs old produces same output) and
unit tests for new capabilities.
"""

from __future__ import annotations

import numpy as np
import pytest

# ──────────────────────────────────────────────────────────────────
#  credit_sensitivity — differential tests (same output as before)
# ──────────────────────────────────────────────────────────────────


class TestCreditSensitivityIntegration:
    """Verify extracted credit_sensitivity produces identical output."""

    def test_2d_grid_via_extracted_module(self) -> None:
        from vertical_engines.credit.credit_sensitivity import build_sensitivity_2d

        grid = build_sensitivity_2d(8.5, [])
        assert len(grid) == 16
        # Same spot checks as golden tests
        assert grid[0]["net_return_pct"] == pytest.approx(8.3, abs=1e-4)
        assert grid[-1]["net_return_pct"] == pytest.approx(3.3, abs=1e-4)

    def test_3d_summary_via_extracted_module(self) -> None:
        from vertical_engines.credit.credit_sensitivity import (
            build_sensitivity_2d,
            build_sensitivity_3d_summary,
        )

        grid_2d = build_sensitivity_2d(8.5, [])
        summary = build_sensitivity_3d_summary(8.5, grid_2d)
        assert len(summary["top_fragile_combinations"]) == 5
        assert summary["dominant_driver"] in ("default_rate", "balanced", "recovery_rate")

    def test_ic_quant_engine_delegates_correctly(self) -> None:
        """ic_quant_engine's _build_sensitivity_2d should delegate to extracted module."""
        from vertical_engines.credit.ic_quant_engine import _build_sensitivity_2d

        grid = _build_sensitivity_2d(8.5, [])
        assert len(grid) == 16
        assert grid[0]["default_rate_pct"] == 1.0


# ──────────────────────────────────────────────────────────────────
#  credit_scenarios — differential tests
# ──────────────────────────────────────────────────────────────────


class TestCreditScenariosIntegration:
    """Verify extracted credit_scenarios produces identical output."""

    def test_scenarios_via_extracted_module(self) -> None:
        from vertical_engines.credit.credit_scenarios import build_deterministic_scenarios

        scenarios, flags = build_deterministic_scenarios(
            base_return_pct=8.5,
            risks=[],
            credit_metrics={"defaultRatePct": 2.0, "recoveryRatePct": 65.0},
        )
        assert len(scenarios) == 3
        assert scenarios[0]["scenario_name"] == "Base"
        assert scenarios[0]["loss_rate_pct"] == 2.0

    def test_ic_quant_engine_delegates_correctly(self) -> None:
        from vertical_engines.credit.ic_quant_engine import _build_deterministic_scenarios

        scenarios, flags = _build_deterministic_scenarios(
            base_return_pct=8.5,
            risks=[],
        )
        assert len(scenarios) == 3


# ──────────────────────────────────────────────────────────────────
#  fred_service — unit tests (mocked FRED API)
# ──────────────────────────────────────────────────────────────────


class TestFredService:
    """Unit tests for FredService (no actual FRED API calls)."""

    def test_token_bucket_rate_limiter(self) -> None:
        from quant_engine.fred_service import TokenBucketRateLimiter

        limiter = TokenBucketRateLimiter(max_tokens=3, refill_rate=100.0)
        # Should be able to acquire 3 tokens immediately (burst)
        for _ in range(3):
            limiter.acquire()

    def test_parse_fred_value_valid(self) -> None:
        from quant_engine.fred_service import parse_fred_value

        assert parse_fred_value("3.14") == pytest.approx(3.14)
        assert parse_fred_value("0") == 0.0
        assert parse_fred_value("-1.5") == pytest.approx(-1.5)

    def test_parse_fred_value_missing(self) -> None:
        from quant_engine.fred_service import parse_fred_value

        assert parse_fred_value(".") is None
        assert parse_fred_value("#N/A") is None
        assert parse_fred_value("") is None
        assert parse_fred_value("NaN") is None

    def test_parse_fred_value_invalid(self) -> None:
        from quant_engine.fred_service import parse_fred_value

        assert parse_fred_value("not_a_number") is None

    def test_apply_transform_yoy_pct(self) -> None:
        from quant_engine.fred_service import apply_transform

        obs = [
            {"date": "2026-01-01", "value": "110.0"},
            {"date": "2025-07-01", "value": "105.0"},
            {"date": "2025-01-01", "value": "100.0"},
        ]
        result = apply_transform("TEST", obs, "yoy_pct")
        assert result["latest"] == 110.0
        assert result["delta_12m_pct"] is not None
        assert result["trend_direction"] in ("rising", "falling", "stable")

    def test_apply_transform_empty(self) -> None:
        from quant_engine.fred_service import apply_transform

        result = apply_transform("TEST", [], None)
        assert result["latest"] is None
        assert result["series"] == []

    def test_apply_transform_mom_delta(self) -> None:
        from quant_engine.fred_service import apply_transform

        obs = [
            {"date": "2026-02-01", "value": "155000"},
            {"date": "2026-01-01", "value": "150000"},
        ]
        result = apply_transform("PAYEMS", obs, "mom_delta")
        assert result["transform_result"] == 5000.0

    def test_fred_service_init_requires_api_key(self) -> None:
        from quant_engine.fred_service import FredService

        with pytest.raises(ValueError, match="FRED API key must be provided"):
            FredService("")


# ──────────────────────────────────────────────────────────────────
#  stress_severity_service — unit tests
# ──────────────────────────────────────────────────────────────────


class TestStressSeverityService:
    """Unit tests for configurable stress severity scoring."""

    def test_empty_snapshot(self) -> None:
        from quant_engine.stress_severity_service import compute_stress_severity

        result = compute_stress_severity({})
        assert result.level == "none"
        assert result.score == 0.0
        assert result.triggers == []

    def test_severe_stress(self) -> None:
        from quant_engine.stress_severity_service import compute_stress_severity

        result = compute_stress_severity({
            "recession_flag": True,
            "financial_conditions_index": 1.5,
            "yield_curve_2s10s": -0.80,
            "baa_spread": 4.0,
            "hy_spread_proxy": 10.0,
            "real_estate_national": {"CSUSHPINSA": {"delta_12m_pct": -8.0}},
            "mortgage": {"DRSFRMACBS": {"latest": 6.0}},
            "credit_quality": {"DRALACBN": {"latest": 4.0}},
        })
        assert result.level == "severe"
        assert result.score == 100.0

    def test_config_injection(self) -> None:
        from quant_engine.stress_severity_service import compute_stress_severity

        # Custom config with no dimensions → no stress
        result = compute_stress_severity(
            {"recession_flag": True},
            config={"stress_severity": {"dimensions": []}},
        )
        assert result.level == "none"
        assert result.score == 0.0

    def test_sub_dimensions_present(self) -> None:
        from quant_engine.stress_severity_service import compute_stress_severity

        result = compute_stress_severity({"recession_flag": True})
        assert "recession" in result.sub_dimensions
        assert result.sub_dimensions["recession"] == "severe"


# ──────────────────────────────────────────────────────────────────
#  regime_service — decoupled tests
# ──────────────────────────────────────────────────────────────────


class TestRegimeDecoupled:
    """Verify regime_service works with shared models and plausibility bounds."""

    def test_classify_regime_risk_on(self) -> None:
        from quant_engine.regime_service import classify_regime_multi_signal

        regime, reasons = classify_regime_multi_signal(vix=15.0, yield_curve_spread=1.0, cpi_yoy=2.0)
        assert regime == "RISK_ON"

    def test_classify_regime_crisis(self) -> None:
        from quant_engine.regime_service import classify_regime_multi_signal

        regime, reasons = classify_regime_multi_signal(vix=40.0, yield_curve_spread=-0.5, cpi_yoy=2.0)
        assert regime == "CRISIS"

    def test_classify_regime_inflation(self) -> None:
        from quant_engine.regime_service import classify_regime_multi_signal

        regime, reasons = classify_regime_multi_signal(vix=20.0, yield_curve_spread=1.0, cpi_yoy=5.0)
        assert regime == "INFLATION"

    def test_plausibility_rejects_extreme_vix(self) -> None:
        from quant_engine.regime_service import classify_regime_multi_signal

        # VIX=300 is physically impossible → rejected, falls through to RISK_ON
        regime, reasons = classify_regime_multi_signal(vix=300.0, yield_curve_spread=1.0, cpi_yoy=2.0)
        assert regime == "RISK_ON"
        assert "no stress signals triggered" in reasons.get("decision", "")

    def test_plausibility_rejects_extreme_cpi(self) -> None:
        from quant_engine.regime_service import classify_regime_multi_signal

        # CPI=50% is implausible → rejected
        regime, reasons = classify_regime_multi_signal(vix=20.0, yield_curve_spread=1.0, cpi_yoy=50.0)
        assert regime == "RISK_ON"


# ──────────────────────────────────────────────────────────────────
#  credit_backtest — unit tests
# ──────────────────────────────────────────────────────────────────


class TestCreditBacktest:
    """Unit tests for credit PD/LGD backtest service."""

    def _make_synthetic_data(self, n_obs: int = 200, default_rate: float = 0.1) -> "BacktestInput":
        from vertical_engines.credit.credit_backtest import BacktestInput

        rng = np.random.default_rng(42)
        n_defaults = int(n_obs * default_rate)
        labels = np.zeros(n_obs)
        labels[:n_defaults] = 1
        rng.shuffle(labels)

        features = rng.normal(size=(n_obs, 5))
        # Make defaulted loans have slightly higher values in feature 0
        features[labels == 1, 0] += 1.0

        recovery = rng.uniform(0.2, 0.8, size=n_obs)
        vintages = rng.choice([2020, 2021, 2022, 2023, 2024], size=n_obs)

        return BacktestInput(
            features=features,
            default_labels=labels,
            recovery_rates=recovery,
            vintage_years=vintages,
        )

    def test_backtest_completes(self) -> None:
        from vertical_engines.credit.credit_backtest import backtest_pd_model

        inp = self._make_synthetic_data(n_obs=200)
        result = backtest_pd_model(inp)

        assert result.status == "complete"
        assert result.pd_auc_roc > 0.5  # should discriminate better than random
        assert 0.0 <= result.pd_brier <= 1.0
        assert result.lgd_mae >= 0.0
        assert result.cv_folds >= 2
        assert result.sample_size == 200
        assert result.n_defaults == 20

    def test_backtest_insufficient_data(self) -> None:
        from vertical_engines.credit.credit_backtest import BacktestInput, backtest_pd_model

        inp = BacktestInput(
            features=np.random.randn(30, 3),
            default_labels=np.array([1, 0] * 15),
            recovery_rates=np.random.uniform(0, 1, 30),
            vintage_years=np.full(30, 2024),
        )
        result = backtest_pd_model(inp)
        assert result.status == "insufficient_data"

    def test_backtest_rejects_nan_features(self) -> None:
        from vertical_engines.credit.credit_backtest import BacktestInput, backtest_pd_model

        features = np.random.randn(200, 3)
        features[10, 1] = np.nan
        inp = BacktestInput(
            features=features,
            default_labels=np.zeros(200),
            recovery_rates=np.random.uniform(0, 1, 200),
            vintage_years=np.full(200, 2024),
        )
        result = backtest_pd_model(inp)
        assert result.status == "insufficient_data"

    def test_backtest_rejects_non_binary_labels(self) -> None:
        from vertical_engines.credit.credit_backtest import BacktestInput, backtest_pd_model

        inp = BacktestInput(
            features=np.random.randn(200, 3),
            default_labels=np.full(200, 2),  # invalid: not 0/1
            recovery_rates=np.random.uniform(0, 1, 200),
            vintage_years=np.full(200, 2024),
        )
        result = backtest_pd_model(inp)
        assert result.status == "insufficient_data"

    def test_vintage_cohort_analysis(self) -> None:
        from vertical_engines.credit.credit_backtest import backtest_pd_model

        inp = self._make_synthetic_data(n_obs=200)
        result = backtest_pd_model(inp)

        assert len(result.vintage_cohorts) > 0
        for year, cohort in result.vintage_cohorts.items():
            assert "count" in cohort
            assert "default_rate" in cohort
            assert "avg_recovery" in cohort

    def test_temporal_cv_strategy(self) -> None:
        from vertical_engines.credit.credit_backtest import CVStrategy, backtest_pd_model

        inp = self._make_synthetic_data(n_obs=200)
        inp.cv_strategy = CVStrategy.TEMPORAL
        result = backtest_pd_model(inp)

        assert result.status == "complete"
        assert result.cv_strategy == "temporal"


# ──────────────────────────────────────────────────────────────────
#  Shared models — import verification
# ──────────────────────────────────────────────────────────────────


class TestSharedModels:
    """Verify shared models are importable and backward-compatible."""

    def test_macro_data_from_shared(self) -> None:
        from app.shared.models import MacroData

        assert MacroData.__tablename__ == "macro_data"

    def test_macro_snapshot_from_shared(self) -> None:
        from app.shared.models import MacroSnapshot

        assert MacroSnapshot.__tablename__ == "macro_snapshots"

    def test_backward_compat_macro_data(self) -> None:
        from app.domains.wealth.models.macro import MacroData

        assert MacroData.__tablename__ == "macro_data"

    def test_backward_compat_macro_snapshot(self) -> None:
        from app.domains.credit.modules.ai.models import MacroSnapshot

        assert MacroSnapshot.__tablename__ == "macro_snapshots"

    def test_regime_read_from_shared(self) -> None:
        from app.shared.schemas import RegimeRead

        r = RegimeRead(regime="RISK_ON")
        assert r.regime == "RISK_ON"

    def test_stress_severity_result(self) -> None:
        from app.shared.schemas import StressSeverityResult

        r = StressSeverityResult(score=50.0, level="moderate", triggers=["test"])
        assert r.score == 50.0
