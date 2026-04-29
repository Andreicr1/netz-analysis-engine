"""Tests for parametric stress testing (BL-10)."""

import numpy as np

from quant_engine.cvar_service import compute_cvar_from_returns
from vertical_engines.wealth.model_portfolio.stress_scenarios import (
    PRESET_SCENARIOS,
    StressScenarioResult,
    apply_idiosyncratic_dispersion,
    run_stress_scenario,
    run_stress_scenario_fund_level,
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

    def test_stressed_cvar_materially_different_from_unstressed(self):
        """PR-Q112 (S10 C-05): stressed CVaR must reflect the scenario shock.

        The old implementation divided nav_impact by T, diluting a -38%
        GFC shock to ~-0.15%/day across 252 observations — producing
        stressed CVaR indistinguishable from unstressed.  The fix appends
        the shock as a single extreme observation so it properly impacts
        the CVaR_95 tail.
        """
        rng = np.random.default_rng(42)
        returns = rng.normal(0.0004, 0.01, 252)
        base_cvar, _ = compute_cvar_from_returns(returns, confidence=0.95)

        # 100% equity portfolio hit by GFC -38% shock
        result = run_stress_scenario(
            {"equity": 1.0}, {"equity": -0.38}, returns, "gfc"
        )

        assert result.cvar_stressed is not None
        # Stressed CVaR should be materially worse (at least 10% more negative)
        assert result.cvar_stressed < base_cvar * 1.10


class TestIdiosyncraticDispersion:
    """C-13: per-fund RNG seed produces distinct shocks per fund."""

    def test_dispersion_produces_different_shocks_per_fund(self):
        """Same base seed + different fund_ids must yield distinct residuals."""
        import hashlib

        base_seed = 42
        block_shock = -0.38
        fund_vol = 0.15

        shocks: dict[str, float] = {}
        for fid in ["fund_a", "fund_b", "fund_c"]:
            fund_hash = int(hashlib.md5(fid.encode()).hexdigest()[:8], 16)
            fund_seed = (base_seed + fund_hash) & 0xFFFFFFFF
            shocks[fid] = apply_idiosyncratic_dispersion(
                block_shock=block_shock,
                fund_volatility=fund_vol,
                seed=fund_seed,
            )

        assert len(set(shocks.values())) == 3, (
            f"Expected 3 distinct shocks but got {shocks}"
        )

    def test_fund_level_scenario_produces_distinct_per_fund_shocks(self):
        """run_stress_scenario_fund_level must not produce identical impacts."""
        fund_ids = ["fund_a", "fund_b", "fund_c"]
        fund_weights = {fid: 1.0 / 3 for fid in fund_ids}
        fund_blocks = {fid: "na_equity_large" for fid in fund_ids}
        fund_vols = {fid: 0.15 for fid in fund_ids}
        shocks = {"na_equity_large": -0.38}

        result = run_stress_scenario_fund_level(
            fund_weights=fund_weights,
            fund_blocks=fund_blocks,
            fund_volatilities=fund_vols,
            shocks=shocks,
            seed=42,
        )

        # NAV impact must differ from naive (all-identical) calculation
        naive_impact = sum(w * (-0.38) for w in fund_weights.values())
        assert result.nav_impact_pct != round(naive_impact, 6), (
            "Fund-level shocks should differ from block-level due to dispersion"
        )

    def test_dispersion_deterministic_for_same_fund(self):
        """Same fund_id + same base seed must produce identical results."""
        import hashlib

        base_seed = 99
        fund_id = "fund_x"
        fund_hash = int(hashlib.md5(fund_id.encode()).hexdigest()[:8], 16)
        fund_seed = (base_seed + fund_hash) & 0xFFFFFFFF

        s1 = apply_idiosyncratic_dispersion(
            block_shock=-0.20, fund_volatility=0.12, seed=fund_seed,
        )
        s2 = apply_idiosyncratic_dispersion(
            block_shock=-0.20, fund_volatility=0.12, seed=fund_seed,
        )
        assert s1 == s2
