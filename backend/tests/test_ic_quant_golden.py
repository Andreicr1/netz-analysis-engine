"""Golden-value tests for ic_quant_engine functions.

Captures exact outputs of _build_sensitivity_2d(), _build_sensitivity_3d_summary(),
and _build_deterministic_scenarios() for known inputs BEFORE refactoring.
These tests verify that extracted modules produce identical outputs.

Use numpy.testing.assert_allclose(rtol=1e-6) for float comparisons.
"""

from __future__ import annotations

import pytest

from vertical_engines.credit.ic_quant_engine import (
    _build_deterministic_scenarios,
    _build_sensitivity_2d,
    _build_sensitivity_3d_summary,
)

# ──────────────────────────────────────────────────────────────────
#  _build_sensitivity_2d golden values
# ──────────────────────────────────────────────────────────────────


class TestSensitivity2DGolden:
    """Golden values for 2D sensitivity grid (default_rate × recovery_rate)."""

    def test_normal_base_return(self) -> None:
        """Normal case: base_return_pct=8.5%."""
        grid = _build_sensitivity_2d(8.5, [])
        assert len(grid) == 16  # 4 default × 4 recovery

        # Spot-check corners
        # dr=1.0, rr=80.0 → loss=1.0*(1-0.8)=0.2 → net=8.3
        assert grid[0]["default_rate_pct"] == 1.0
        assert grid[0]["recovery_rate_pct"] == 80.0
        assert grid[0]["loss_impact_pct"] == pytest.approx(0.2, abs=1e-4)
        assert grid[0]["net_return_pct"] == pytest.approx(8.3, abs=1e-4)

        # dr=8.0, rr=35.0 → loss=8.0*(1-0.35)=5.2 → net=3.3
        assert grid[-1]["default_rate_pct"] == 8.0
        assert grid[-1]["recovery_rate_pct"] == 35.0
        assert grid[-1]["loss_impact_pct"] == pytest.approx(5.2, abs=1e-4)
        assert grid[-1]["net_return_pct"] == pytest.approx(3.3, abs=1e-4)

    def test_low_base_return(self) -> None:
        """Low base return where some cells go negative."""
        grid = _build_sensitivity_2d(2.0, [])
        assert len(grid) == 16

        # dr=8.0, rr=35.0 → loss=5.2 → net=-3.2
        last = grid[-1]
        assert last["net_return_pct"] == pytest.approx(-3.2, abs=1e-4)

    def test_none_base_return(self) -> None:
        """None base return returns empty grid."""
        assert _build_sensitivity_2d(None, []) == []

    def test_zero_base_return(self) -> None:
        """Zero base return — all net returns are negative or zero."""
        grid = _build_sensitivity_2d(0.0, [])
        assert len(grid) == 16
        for cell in grid:
            assert cell["net_return_pct"] <= 0.0


# ──────────────────────────────────────────────────────────────────
#  _build_sensitivity_3d_summary golden values
# ──────────────────────────────────────────────────────────────────


class TestSensitivity3DGolden:
    """Golden values for 3D summary (+ rate shocks)."""

    def test_normal_3d_summary(self) -> None:
        """Normal case with base_return=8.5%."""
        grid_2d = _build_sensitivity_2d(8.5, [])
        summary = _build_sensitivity_3d_summary(8.5, grid_2d)

        assert "top_fragile_combinations" in summary
        assert "break_even_thresholds" in summary
        assert "dominant_driver" in summary
        assert summary["rate_shocks_bps"] == [0, 100, 200]

        # 3 shocks × 16 cells = 48 total cells
        top_fragile = summary["top_fragile_combinations"]
        assert len(top_fragile) == 5
        # First fragile cell should be worst case: highest shock, highest default, lowest recovery
        assert top_fragile[0]["rate_shock_bps"] == 200
        assert top_fragile[0]["default_rate_pct"] == 8.0
        assert top_fragile[0]["recovery_rate_pct"] == 35.0

        # Dominant driver with 8.5% base: default_rate has wider range
        assert summary["dominant_driver"] in ("default_rate", "balanced", "recovery_rate")

    def test_low_return_has_break_even(self) -> None:
        """Low return should find break-even point."""
        grid_2d = _build_sensitivity_2d(3.0, [])
        summary = _build_sensitivity_3d_summary(3.0, grid_2d)

        assert summary["break_even_thresholds"] != {}
        be = summary["break_even_thresholds"]
        assert "note" in be

    def test_high_return_no_break_even(self) -> None:
        """High return may not have break-even."""
        grid_2d = _build_sensitivity_2d(15.0, [])
        summary = _build_sensitivity_3d_summary(15.0, grid_2d)

        # At 15% base, even worst case (dr=8, rr=35, shock=200bps):
        # 15 - 5.2 - 2.0 = 7.8 > 0 → no break-even
        assert summary["break_even_thresholds"] == {}

    def test_none_inputs(self) -> None:
        """None/empty inputs return empty dict."""
        assert _build_sensitivity_3d_summary(None, []) == {}
        assert _build_sensitivity_3d_summary(8.5, []) == {}


# ──────────────────────────────────────────────────────────────────
#  _build_deterministic_scenarios golden values
# ──────────────────────────────────────────────────────────────────


class TestScenariosGolden:
    """Golden values for deterministic Base/Downside/Severe scenarios."""

    def test_with_credit_metrics(self) -> None:
        """Scenarios with actual credit metrics (not proxy)."""
        scenarios, flags = _build_deterministic_scenarios(
            base_return_pct=8.5,
            risks=[],
            credit_metrics={"defaultRatePct": 2.0, "recoveryRatePct": 65.0},
            concentration_profile=None,
            liquidity_hooks=None,
        )
        assert len(scenarios) == 3
        assert [s["scenario_name"] for s in scenarios] == ["Base", "Downside", "Severe"]

        # Base uses actual credit metrics
        base = scenarios[0]
        assert base["loss_rate_pct"] == 2.0
        assert base["recovery_rate_pct"] == 65.0
        assert base["inputs_used"]["loss_rate_source"] == "CREDIT_METRICS"
        assert base["inputs_used"]["recovery_rate_source"] == "CREDIT_METRICS"

        # Downside/Severe use proxy
        ds = scenarios[1]
        assert ds["inputs_used"]["loss_rate_source"] == "PROXY_FROM_SEVERITY"
        assert ds["loss_rate_pct"] == 3.0  # from _SCENARIO_PROXY
        assert ds["recovery_rate_pct"] == 55.0

        sv = scenarios[2]
        assert sv["loss_rate_pct"] == 7.0
        assert sv["recovery_rate_pct"] == 40.0

        # No proxy flags when Base has credit metrics
        assert not any("PROXY_FROM_SEVERITY:loss_rate:Base" in f for f in flags)

    def test_without_credit_metrics_proxy_mode(self) -> None:
        """All scenarios use proxy when no credit metrics provided."""
        scenarios, flags = _build_deterministic_scenarios(
            base_return_pct=8.5,
            risks=[],
            credit_metrics=None,
        )
        assert len(scenarios) == 3

        base = scenarios[0]
        assert base["loss_rate_pct"] == 1.0  # _SCENARIO_PROXY["Base"]["loss_rate"]
        assert base["recovery_rate_pct"] == 70.0
        assert base["inputs_used"]["loss_rate_source"] == "PROXY_FROM_SEVERITY"

        assert "PROXY_FROM_SEVERITY:loss_rate:Base" in flags
        assert "PROXY_FROM_SEVERITY:recovery_rate:Base" in flags

    def test_concentration_adjustment(self) -> None:
        """High concentration adds 2pp to loss rate."""
        scenarios, flags = _build_deterministic_scenarios(
            base_return_pct=8.5,
            risks=[],
            credit_metrics={"defaultRatePct": 2.0, "recoveryRatePct": 65.0},
            concentration_profile={"top_single_exposure_pct": 85.0},
        )
        # Base: loss = 2.0 + 2.0 = 4.0
        assert scenarios[0]["loss_rate_pct"] == pytest.approx(4.0)
        assert any("CONCENTRATION_ADJ" in f for f in flags)

    def test_none_base_return(self) -> None:
        """None base return returns empty with SKIPPED flag."""
        scenarios, flags = _build_deterministic_scenarios(
            base_return_pct=None,
            risks=[],
        )
        assert scenarios == []
        assert "SCENARIO_SKIPPED_NO_BASE_RETURN" in flags

    def test_liquidity_hooks(self) -> None:
        """Lockup months are passed through."""
        scenarios, _ = _build_deterministic_scenarios(
            base_return_pct=8.5,
            risks=[],
            liquidity_hooks={"lockup_months": 24},
        )
        for s in scenarios:
            assert s["liquidity_delay_months"] == 24

    def test_net_return_calculation(self) -> None:
        """Verify exact net return math."""
        scenarios, _ = _build_deterministic_scenarios(
            base_return_pct=10.0,
            risks=[],
            credit_metrics={"defaultRatePct": 5.0, "recoveryRatePct": 50.0},
        )
        base = scenarios[0]
        # loss_impact = 5.0 * (1 - 50/100) = 2.5
        # net = 10.0 - 2.5 = 7.5
        assert base["expected_net_return_pct"] == pytest.approx(7.5, abs=1e-4)
