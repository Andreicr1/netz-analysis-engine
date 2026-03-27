"""Tests for parametric stress testing (BL-10)."""

import numpy as np

from vertical_engines.wealth.model_portfolio.stress_scenarios import (
    PRESET_SCENARIOS,
    StressScenarioResult,
    run_stress_scenario,
)


class TestRunStressScenario:
    """Unit tests for parametric stress scenario engine."""

    def test_basic_impact_calculation(self):
        weights = {"na_equity_large": 0.6, "fi_treasury": 0.4}
        shocks = {"na_equity_large": -0.38, "fi_treasury": 0.06}

        result = run_stress_scenario(weights, shocks, None, "gfc_2008")

        assert isinstance(result, StressScenarioResult)
        expected_impact = 0.6 * (-0.38) + 0.4 * 0.06
        assert abs(result.nav_impact_pct - expected_impact) < 1e-5
        assert result.worst_block == "na_equity_large"
        assert result.best_block == "fi_treasury"

    def test_missing_block_in_shocks_zero_impact(self):
        """Blocks not in shocks dict should have zero impact."""
        weights = {"na_equity_large": 0.5, "alt_gold": 0.5}
        shocks = {"na_equity_large": -0.10}

        result = run_stress_scenario(weights, shocks, None, "custom")

        assert result.block_impacts["alt_gold"] == 0.0
        assert abs(result.nav_impact_pct - (-0.05)) < 1e-5

    def test_preset_scenarios_exist(self):
        """All 4 preset scenarios should exist."""
        assert "gfc_2008" in PRESET_SCENARIOS
        assert "covid_2020" in PRESET_SCENARIOS
        assert "taper_2013" in PRESET_SCENARIOS
        assert "rate_shock_200bps" in PRESET_SCENARIOS

    def test_preset_gfc_negative_impact_for_equity_heavy(self):
        weights = {"na_equity_large": 0.8, "fi_treasury": 0.2}
        shocks = PRESET_SCENARIOS["gfc_2008"]

        result = run_stress_scenario(weights, shocks, None, "gfc_2008")

        assert result.nav_impact_pct < 0  # equity-heavy should lose money in GFC

    def test_with_historical_returns(self):
        """When historical returns are provided, cvar_stressed should be computed."""
        rng = np.random.default_rng(42)
        historical = rng.normal(0.0003, 0.015, 252)
        weights = {"na_equity_large": 0.5, "fi_treasury": 0.5}
        shocks = {"na_equity_large": -0.20, "fi_treasury": 0.05}

        result = run_stress_scenario(weights, shocks, historical, "custom")

        assert result.cvar_stressed is not None

    def test_without_historical_returns(self):
        """Without historical returns, cvar_stressed should be None."""
        weights = {"na_equity_large": 1.0}
        shocks = {"na_equity_large": -0.30}

        result = run_stress_scenario(weights, shocks, None, "custom")

        assert result.cvar_stressed is None

    def test_empty_portfolio(self):
        """Empty portfolio should have zero impact."""
        result = run_stress_scenario({}, {"na_equity_large": -0.5}, None, "custom")

        assert result.nav_impact_pct == 0.0
        assert result.worst_block is None
        assert result.best_block is None
