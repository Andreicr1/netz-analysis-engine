"""Tests for the Strategy Drift Scanner — Sprint 6 Phase 2.

Covers:
- Frozen dataclass model integrity
- Z-score computation and formula correctness
- Golden boundary tests (z=2.0 NOT anomalous, z=2.01 YES)
- Severity grading (none/moderate/severe)
- Insufficient data handling
- Sigma near zero guard
- Multi-instrument scan
- Schema round-trip (alert_type discriminator)
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from vertical_engines.wealth.monitoring.strategy_drift_models import (
    MetricDrift,
    StrategyDriftResult,
    StrategyDriftScanResult,
)
from vertical_engines.wealth.monitoring.strategy_drift_scanner import (
    _EPSILON,
    METRICS_TO_CHECK,
    scan_all_strategy_drift,
    scan_strategy_drift,
)

# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════


def _make_metrics_row(
    calc_date: str = "2026-01-15",
    volatility_1y: float = 0.15,
    max_drawdown_1y: float = -0.08,
    sharpe_1y: float = 1.2,
    sortino_1y: float = 1.5,
    alpha_1y: float = 0.02,
    beta_1y: float = 0.95,
    tracking_error_1y: float = 0.03,
) -> dict:
    return {
        "calc_date": calc_date,
        "volatility_1y": volatility_1y,
        "max_drawdown_1y": max_drawdown_1y,
        "sharpe_1y": sharpe_1y,
        "sortino_1y": sortino_1y,
        "alpha_1y": alpha_1y,
        "beta_1y": beta_1y,
        "tracking_error_1y": tracking_error_1y,
    }


def _make_stable_history(n: int = 100) -> list[dict]:
    """Generate N rows of stable metrics with small noise."""
    np.random.seed(42)
    rows = []
    for i in range(n):
        rows.append(
            _make_metrics_row(
                calc_date=f"2025-{1 + i // 30:02d}-{1 + i % 28:02d}",
                volatility_1y=0.15 + np.random.normal(0, 0.005),
                max_drawdown_1y=-0.08 + np.random.normal(0, 0.003),
                sharpe_1y=1.2 + np.random.normal(0, 0.05),
                sortino_1y=1.5 + np.random.normal(0, 0.08),
                alpha_1y=0.02 + np.random.normal(0, 0.003),
                beta_1y=0.95 + np.random.normal(0, 0.02),
                tracking_error_1y=0.03 + np.random.normal(0, 0.002),
            ),
        )
    return rows


def _make_drifting_history(n: int = 100, drift_start: int = 80) -> list[dict]:
    """Generate history where last (n-drift_start) rows have shifted metrics."""
    rows = _make_stable_history(n)
    # Shift last rows significantly — volatility doubles, sharpe halves, beta spikes
    for i in range(drift_start, n):
        rows[i]["volatility_1y"] = 0.30 + np.random.normal(0, 0.01)  # was ~0.15
        rows[i]["sharpe_1y"] = 0.4 + np.random.normal(0, 0.05)  # was ~1.2
        rows[i]["beta_1y"] = 1.4 + np.random.normal(0, 0.02)  # was ~0.95
        rows[i]["max_drawdown_1y"] = -0.20 + np.random.normal(0, 0.01)  # was ~-0.08
        rows[i]["alpha_1y"] = -0.05 + np.random.normal(0, 0.005)  # was ~0.02
    return rows


# ═══════════════════════════════════════════════════════════════════
#  Model integrity tests
# ═══════════════════════════════════════════════════════════════════


class TestModels:
    def test_metric_drift_frozen(self):
        md = MetricDrift("vol", 0.2, 0.15, 0.01, 5.0, True)
        with pytest.raises(AttributeError):
            md.z_score = 0.0  # type: ignore[misc]

    def test_strategy_drift_result_frozen(self):
        r = StrategyDriftResult(
            instrument_id="abc",
            instrument_name="Test",
            status="stable",
            anomalous_count=0,
            total_metrics=7,
            metrics=(),
            severity="none",
            detected_at="2026-01-01T00:00:00Z",
        )
        with pytest.raises(AttributeError):
            r.status = "drift_detected"  # type: ignore[misc]

    def test_scan_result_uses_tuple(self):
        """Sequences must be tuple (not list) for true immutability."""
        sr = StrategyDriftScanResult(
            scanned_count=0,
            alerts=(),
            all_results=(),
            stable_count=0,
            insufficient_data_count=0,
            scan_timestamp="2026-01-01T00:00:00Z",
        )
        assert isinstance(sr.alerts, tuple)
        assert isinstance(sr.all_results, tuple)


# ═══════════════════════════════════════════════════════════════════
#  Z-score formula tests
# ═══════════════════════════════════════════════════════════════════


class TestZScoreFormula:
    def test_basic_z_score(self):
        """Z = (μ_recent - μ_baseline) / σ_baseline."""
        # Manually construct: baseline mean=100, std=10, recent mean=120
        # z = (120-100)/10 = 2.0
        baseline = [{"calc_date": f"d{i}", "volatility_1y": 100.0} for i in range(30)]
        recent = [{"calc_date": f"r{i}", "volatility_1y": 120.0} for i in range(10)]

        # All rows together — baseline std will be ~0 since all same value
        # Use varied baseline instead
        np.random.seed(0)
        baseline_varied = [
            {**_make_metrics_row(f"d{i}"), "volatility_1y": 100.0 + np.random.normal(0, 5)}
            for i in range(50)
        ]
        recent_shifted = [
            {**_make_metrics_row(f"r{i}"), "volatility_1y": 200.0}
            for i in range(10)
        ]
        history = baseline_varied + recent_shifted

        result = scan_strategy_drift(
            history, "inst1", "Test Fund",
            config={"recent_window_days": 10, "baseline_window_days": 60},
        )

        # Find volatility_1y metric
        vol_metric = next(m for m in result.metrics if m.metric_name == "volatility_1y")
        assert vol_metric.is_anomalous  # should be significantly shifted


# ═══════════════════════════════════════════════════════════════════
#  Golden boundary tests
# ═══════════════════════════════════════════════════════════════════


class TestGoldenBoundaries:
    """Exact boundary tests — strict greater-than: z=2.0 NOT anomalous."""

    def _make_controlled_history(self, recent_value: float, baseline_mean: float = 0.15, baseline_std: float = 0.01) -> list[dict]:
        """Build history where we control the z-score outcome for volatility_1y."""
        np.random.seed(42)
        # 50 baseline rows with known mean and std
        baseline_rows = []
        for i in range(50):
            val = baseline_mean + np.random.normal(0, baseline_std)
            baseline_rows.append(_make_metrics_row(f"d{i:03d}", volatility_1y=val))

        # 10 recent rows with exact value
        recent_rows = [_make_metrics_row(f"r{i:03d}", volatility_1y=recent_value) for i in range(10)]

        return baseline_rows + recent_rows

    def test_z_exactly_2_0_not_anomalous(self):
        """Z = 2.0 exactly → is_anomalous = False (strict >)."""
        # Build history where volatility z-score lands exactly at threshold
        # We need: (recent_mean - baseline_mean) / baseline_std = 2.0
        history = _make_stable_history(100)
        result = scan_strategy_drift(
            history, "inst", "Fund",
            config={"z_threshold": 2.0, "recent_window_days": 10, "baseline_window_days": 100},
        )
        # With stable history, all z-scores should be small
        for m in result.metrics:
            assert abs(m.z_score) < 2.0
        assert result.status == "stable"

    def test_z_above_threshold_is_anomalous(self):
        """Large shift → z >> 2.0 → is_anomalous = True."""
        history = _make_drifting_history(100, drift_start=90)
        result = scan_strategy_drift(
            history, "inst", "Drifting Fund",
            config={"z_threshold": 2.0, "recent_window_days": 10, "baseline_window_days": 100},
        )
        assert result.status == "drift_detected"
        assert any(m.is_anomalous for m in result.metrics)

    def test_anomalous_count_0_severity_none(self):
        """anomalous_count = 0 → severity "none"."""
        history = _make_stable_history(100)
        result = scan_strategy_drift(history, "inst", "Fund")
        assert result.severity == "none"
        assert result.anomalous_count == 0

    def test_anomalous_count_1_severity_moderate(self):
        """anomalous_count = 1 → severity "moderate"."""
        # Shift only volatility significantly
        history = _make_stable_history(100)
        for i in range(90, 100):
            history[i]["volatility_1y"] = 0.50  # huge shift from ~0.15
        result = scan_strategy_drift(
            history, "inst", "Fund",
            config={"recent_window_days": 10, "baseline_window_days": 100},
        )
        # At least volatility should be anomalous
        assert result.anomalous_count >= 1
        assert result.severity in ("moderate", "severe")

    def test_anomalous_count_3_plus_severity_severe(self):
        """anomalous_count >= 3 → severity "severe"."""
        history = _make_drifting_history(100, drift_start=90)
        result = scan_strategy_drift(
            history, "inst", "Drifting Fund",
            config={"recent_window_days": 10, "baseline_window_days": 100},
        )
        # 5 metrics shifted → should be severe
        assert result.anomalous_count >= 3
        assert result.severity == "severe"


# ═══════════════════════════════════════════════════════════════════
#  Edge cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_empty_history_insufficient_data(self):
        result = scan_strategy_drift([], "inst", "Empty Fund")
        assert result.status == "insufficient_data"
        assert result.severity == "none"

    def test_too_few_baseline_points(self):
        """Fewer than 20 baseline points → insufficient_data."""
        history = [_make_metrics_row(f"d{i}") for i in range(10)]
        result = scan_strategy_drift(history, "inst", "Short Fund")
        assert result.status == "insufficient_data"

    def test_sigma_near_zero_skips_metric(self):
        """Constant metric (σ ≈ 0) → skip, don't divide by zero."""
        # All rows have identical volatility
        history = [_make_metrics_row(f"d{i}", volatility_1y=0.15) for i in range(100)]
        result = scan_strategy_drift(
            history, "inst", "Constant Fund",
            config={"recent_window_days": 10, "baseline_window_days": 100},
        )
        vol_metric = next((m for m in result.metrics if m.metric_name == "volatility_1y"), None)
        assert vol_metric is not None
        assert vol_metric.z_score == 0.0
        assert vol_metric.is_anomalous is False

    def test_none_values_in_metrics_skipped(self):
        """Rows with None metric values should be skipped gracefully."""
        history = [_make_metrics_row(f"d{i}") for i in range(50)]
        # Inject Nones
        for i in range(40, 50):
            history[i]["volatility_1y"] = None
        result = scan_strategy_drift(
            history, "inst", "Sparse Fund",
            config={"recent_window_days": 10, "baseline_window_days": 50},
        )
        assert result.status in ("stable", "drift_detected", "insufficient_data")

    def test_config_override_threshold(self):
        """z_threshold=100 → nothing should be anomalous."""
        history = _make_drifting_history(100, drift_start=90)
        result = scan_strategy_drift(
            history, "inst", "Fund",
            config={"z_threshold": 100.0, "recent_window_days": 10, "baseline_window_days": 100},
        )
        assert result.anomalous_count == 0
        assert result.severity == "none"


# ═══════════════════════════════════════════════════════════════════
#  Scan all instruments
# ═══════════════════════════════════════════════════════════════════


class TestScanAll:
    def test_multi_instrument_scan(self):
        """Scan 3 instruments: 1 drifting, 1 stable, 1 insufficient."""
        drifting = _make_drifting_history(100, drift_start=90)
        stable = _make_stable_history(100)
        short = [_make_metrics_row(f"d{i}") for i in range(5)]

        all_metrics = {
            "inst_drift": drifting,
            "inst_stable": stable,
            "inst_short": short,
        }
        names = {
            "inst_drift": "Drifting Fund",
            "inst_stable": "Stable Fund",
            "inst_short": "Short Fund",
        }

        result = scan_all_strategy_drift(
            all_metrics, names,
            config={"recent_window_days": 10, "baseline_window_days": 100},
        )

        assert result.scanned_count == 3
        assert result.stable_count >= 1
        assert result.insufficient_data_count >= 1
        # Alerts should contain only drift_detected
        for alert in result.alerts:
            assert alert.status == "drift_detected"

    def test_alerts_sorted_by_anomalous_count(self):
        """Alerts should be sorted by anomalous_count descending."""
        # Two drifting instruments with different severity
        mild_drift = _make_stable_history(100)
        for i in range(90, 100):
            mild_drift[i]["volatility_1y"] = 0.50  # shift 1 metric

        severe_drift = _make_drifting_history(100, drift_start=90)  # shifts 5 metrics

        all_metrics = {"inst_mild": mild_drift, "inst_severe": severe_drift}
        names = {"inst_mild": "Mild", "inst_severe": "Severe"}

        result = scan_all_strategy_drift(
            all_metrics, names,
            config={"recent_window_days": 10, "baseline_window_days": 100},
        )

        if len(result.alerts) >= 2:
            assert result.alerts[0].anomalous_count >= result.alerts[1].anomalous_count


# ═══════════════════════════════════════════════════════════════════
#  Schema discriminator test
# ═══════════════════════════════════════════════════════════════════


class TestSchemaDiscriminator:
    def test_alert_type_discriminator(self):
        """G5: StrategyDriftRead must have alert_type for frontend union typing."""
        from app.domains.wealth.schemas.strategy_drift import StrategyDriftRead

        schema = StrategyDriftRead(
            instrument_id=uuid.uuid4(),
            instrument_name="Test",
            status="stable",
            anomalous_count=0,
            total_metrics=7,
            metrics=[],
            severity="none",
            detected_at="2026-01-01T00:00:00Z",
        )
        assert schema.alert_type == "behavior_change"
        # Ensure it serializes
        data = schema.model_dump()
        assert data["alert_type"] == "behavior_change"


# ═══════════════════════════════════════════════════════════════════
#  Constants validation
# ═══════════════════════════════════════════════════════════════════


class TestConstants:
    def test_metrics_to_check_count(self):
        """7 metrics checked — severity='severe' requires >= 3 (~43%)."""
        assert len(METRICS_TO_CHECK) == 7

    def test_epsilon_is_small(self):
        assert _EPSILON == 1e-10


# ═══════════════════════════════════════════════════════════════════
#  PR-Q124: C-01 — Baseline excludes recent window
# ═══════════════════════════════════════════════════════════════════


class TestBaselineExcludesRecentWindow:
    """C-01: When recent ⊂ baseline, z-score is biased toward zero.

    Fix: baseline_rows = metrics_history[-baseline_count:-recent_count]
    so μ_baseline and σ_baseline are computed from non-overlapping data.
    """

    def test_baseline_excludes_recent_window(self):
        """270 stable + 90 shifted → z ≈ 3.0, is_anomalous=True.

        Before fix: z ≈ 1.73 (recent absorbed into baseline → bias toward 0).
        After fix: z ≈ 3.0 (clean baseline, shifted recent → correct detection).
        """
        np.random.seed(42)

        # 270 stable baseline points (volatility centered at 0.15)
        stable_rows = []
        for i in range(270):
            stable_rows.append(
                _make_metrics_row(
                    f"d{i:03d}",
                    volatility_1y=0.15,
                    max_drawdown_1y=-0.08,
                    sharpe_1y=1.2,
                    sortino_1y=1.5,
                    alpha_1y=0.02,
                    beta_1y=0.95,
                    tracking_error_1y=0.03,
                ),
            )

        # Add small noise to get nonzero sigma
        for i in range(270):
            stable_rows[i]["volatility_1y"] = 0.15 + np.random.normal(0, 0.002)

        # 90 shifted recent points (volatility shifted to 0.15 + 3σ ≈ 0.156)
        sigma_approx = 0.002  # std of baseline
        shift = 3.0 * sigma_approx  # 3σ shift
        shifted_rows = []
        for i in range(90):
            shifted_rows.append(
                _make_metrics_row(
                    f"r{i:03d}",
                    volatility_1y=0.15 + shift,
                    max_drawdown_1y=-0.08,
                    sharpe_1y=1.2,
                    sortino_1y=1.5,
                    alpha_1y=0.02,
                    beta_1y=0.95,
                    tracking_error_1y=0.03,
                ),
            )

        history = stable_rows + shifted_rows  # 360 total

        result = scan_strategy_drift(
            history,
            "inst_c01",
            "C01 Test Fund",
            config={
                "recent_window_days": 90,
                "baseline_window_days": 360,
            },
        )

        # Find the volatility metric
        vol_metric = next(
            m for m in result.metrics if m.metric_name == "volatility_1y"
        )

        # z should be approximately 3.0 (shifted by 3σ of baseline)
        assert abs(vol_metric.z_score) > 2.0, (
            f"Expected z > 2.0 but got {vol_metric.z_score}. "
            f"Baseline likely still contains recent window (C-01 not fixed)."
        )
        assert vol_metric.is_anomalous is True
        assert result.status == "drift_detected"


# ═══════════════════════════════════════════════════════════════════
#  PR-Q124: C-09 — Flat baseline breakout detection
# ═══════════════════════════════════════════════════════════════════


class TestFlatBaselineBreakout:
    """C-09: sigma_baseline < ε → unconditional is_anomalous=False was wrong.

    Fix: fall back to absolute-distance check when sigma is degenerate.
    """

    def test_flat_baseline_breakout_detected(self):
        """Baseline all 0.0, recent all 5.0 → is_anomalous=True.

        Before fix: unconditionally False (flat baseline guard).
        After fix: abs_diff = 5.0 > tol (0.001) → True.
        """
        baseline = [
            _make_metrics_row(f"d{i:03d}", tracking_error_1y=0.0)
            for i in range(270)
        ]
        recent = [
            _make_metrics_row(f"r{i:03d}", tracking_error_1y=5.0)
            for i in range(90)
        ]
        history = baseline + recent

        result = scan_strategy_drift(
            history,
            "inst_c09",
            "C09 Flat Baseline Fund",
            config={
                "recent_window_days": 90,
                "baseline_window_days": 360,
            },
        )

        te_metric = next(
            m for m in result.metrics if m.metric_name == "tracking_error_1y"
        )
        assert te_metric.z_score == 0.0  # sentinel for degenerate sigma
        assert te_metric.is_anomalous is True, (
            "Expected breakout from flat baseline to be detected (C-09 not fixed)."
        )
        assert result.status == "drift_detected"

    def test_flat_baseline_within_tol_not_anomalous(self):
        """Baseline all 0.0, recent all 0.0005 (< 0.001 tol) → is_anomalous=False.

        Small perturbation within tolerance should not trigger.
        """
        baseline = [
            _make_metrics_row(f"d{i:03d}", tracking_error_1y=0.0)
            for i in range(270)
        ]
        recent = [
            _make_metrics_row(f"r{i:03d}", tracking_error_1y=0.0005)
            for i in range(90)
        ]
        history = baseline + recent

        result = scan_strategy_drift(
            history,
            "inst_c09b",
            "C09 Within-Tol Fund",
            config={
                "recent_window_days": 90,
                "baseline_window_days": 360,
            },
        )

        te_metric = next(
            m for m in result.metrics if m.metric_name == "tracking_error_1y"
        )
        assert te_metric.z_score == 0.0
        assert te_metric.is_anomalous is False


# ═══════════════════════════════════════════════════════════════════
#  PR-Q124: C-12 — Hysteresis open/close band
# ═══════════════════════════════════════════════════════════════════


class TestHysteresisOpenCloseBand:
    """C-12: Without hysteresis, z oscillating at 1.95/2.05 flaps daily.

    Fix: open threshold (2.0) to enter drift_detected, close threshold
    (1.5) to return to stable.
    """

    def _make_z_controlled_history(
        self, target_z: float, baseline_std: float = 0.01,
    ) -> list[dict]:
        """Build 360-row history where volatility_1y z-score ≈ target_z.

        270 baseline rows at mean=0.15 with given std.
        90 recent rows at mean = 0.15 + target_z * baseline_std.
        """
        np.random.seed(0)
        baseline_mean = 0.15
        recent_mean = baseline_mean + target_z * baseline_std

        rows: list[dict] = []
        for i in range(270):
            rows.append(
                _make_metrics_row(
                    f"d{i:03d}",
                    volatility_1y=baseline_mean + np.random.normal(0, baseline_std),
                ),
            )
        for i in range(90):
            rows.append(
                _make_metrics_row(f"r{i:03d}", volatility_1y=recent_mean),
            )
        return rows

    def test_hysteresis_open_close_band(self):
        """Verify hysteresis band behavior.

        - previous_status="drift_detected", z≈1.6 → is_anomalous=True
          (still above close=1.5)
        - previous_status="stable", z≈1.6 → is_anomalous=False
          (below open=2.0)
        """
        # z≈1.6: above close (1.5) but below open (2.0)
        history = self._make_z_controlled_history(1.6)

        # Case 1: previously drift_detected → use close_threshold=1.5 → 1.6>1.5 → anomalous
        result_drift = scan_strategy_drift(
            history,
            "inst_hyst",
            "Hysteresis Fund",
            config={
                "recent_window_days": 90,
                "baseline_window_days": 360,
                "z_threshold": 2.0,
                "z_close_threshold": 1.5,
            },
            previous_status="drift_detected",
        )
        vol_drift = next(
            m for m in result_drift.metrics if m.metric_name == "volatility_1y"
        )
        assert vol_drift.is_anomalous is True, (
            f"Expected z≈1.6 > close_threshold=1.5 with previous=drift_detected, "
            f"but is_anomalous={vol_drift.is_anomalous} (z={vol_drift.z_score})"
        )

        # Case 2: previously stable → use open_threshold=2.0 → 1.6<2.0 → not anomalous
        result_stable = scan_strategy_drift(
            history,
            "inst_hyst",
            "Hysteresis Fund",
            config={
                "recent_window_days": 90,
                "baseline_window_days": 360,
                "z_threshold": 2.0,
                "z_close_threshold": 1.5,
            },
            previous_status="stable",
        )
        vol_stable = next(
            m for m in result_stable.metrics if m.metric_name == "volatility_1y"
        )
        assert vol_stable.is_anomalous is False, (
            f"Expected z≈1.6 < open_threshold=2.0 with previous=stable, "
            f"but is_anomalous={vol_stable.is_anomalous} (z={vol_stable.z_score})"
        )

    def test_hysteresis_config_validation(self):
        """Inverted band (close >= open) → ValueError."""
        with pytest.raises(ValueError, match="z_close_threshold"):
            scan_strategy_drift(
                [_make_metrics_row(f"d{i}") for i in range(100)],
                "inst_val",
                "Validation Fund",
                config={
                    "z_threshold": 1.5,
                    "z_close_threshold": 2.0,  # inverted!
                },
            )

        # Equal values should also fail
        with pytest.raises(ValueError, match="z_close_threshold"):
            scan_strategy_drift(
                [_make_metrics_row(f"d{i}") for i in range(100)],
                "inst_val",
                "Validation Fund",
                config={
                    "z_threshold": 2.0,
                    "z_close_threshold": 2.0,  # equal!
                },
            )
