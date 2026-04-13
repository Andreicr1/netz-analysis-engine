"""Tests for quant_engine/taa_band_service.py — TAA band clamping + EMA smoothing.

Proves:
1. IPS invariant: effective bands ALWAYS within IPS bounds
2. EMA smoothing convergence (halflife=5, 95% in ~22 days)
3. Max daily shift cap prevents whipsaw
4. Per-block disaggregation preserves proportions
5. Fallback to static IPS when taa_enabled=False or no regime state
6. Backward compatibility: disabled TAA = identical to current static behavior
7. Degenerate band handling (regime outside IPS)
"""

from __future__ import annotations

import math

import pytest

from quant_engine.optimizer_service import BlockConstraint
from quant_engine.taa_band_service import (
    DEFAULT_TAA_BANDS,
    _disaggregate_centers_to_blocks,
    compute_effective_band,
    extract_stress_score,
    get_regime_centers_for_regime,
    resolve_effective_bands,
    smooth_regime_centers,
)

# ---------------------------------------------------------------------------
#  Shared fixtures
# ---------------------------------------------------------------------------

MODERATE_ALLOCATIONS = [
    {"block_id": "na_equity_large",   "target_weight": 0.19, "min_weight": 0.14, "max_weight": 0.28},
    {"block_id": "na_equity_growth",  "target_weight": 0.08, "min_weight": 0.04, "max_weight": 0.14},
    {"block_id": "na_equity_value",   "target_weight": 0.08, "min_weight": 0.04, "max_weight": 0.14},
    {"block_id": "dm_europe_equity",  "target_weight": 0.08, "min_weight": 0.03, "max_weight": 0.14},
    {"block_id": "em_equity",         "target_weight": 0.07, "min_weight": 0.02, "max_weight": 0.12},
    {"block_id": "fi_aggregate",      "target_weight": 0.15, "min_weight": 0.10, "max_weight": 0.25},
    {"block_id": "fi_ig_corporate",   "target_weight": 0.10, "min_weight": 0.05, "max_weight": 0.18},
    {"block_id": "fi_high_yield",     "target_weight": 0.08, "min_weight": 0.03, "max_weight": 0.13},
    {"block_id": "alt_real_estate",   "target_weight": 0.06, "min_weight": 0.02, "max_weight": 0.10},
    {"block_id": "alt_commodities",   "target_weight": 0.06, "min_weight": 0.02, "max_weight": 0.10},
    {"block_id": "cash",              "target_weight": 0.05, "min_weight": 0.02, "max_weight": 0.15},
]

BLOCK_ASSET_CLASSES = {
    "na_equity_large": "equity",
    "na_equity_growth": "equity",
    "na_equity_value": "equity",
    "dm_europe_equity": "equity",
    "em_equity": "equity",
    "fi_aggregate": "fixed_income",
    "fi_ig_corporate": "fixed_income",
    "fi_high_yield": "fixed_income",
    "alt_real_estate": "alternatives",
    "alt_commodities": "alternatives",
    "cash": "cash",
}


def _make_regime_state(regime: str = "RISK_OFF") -> dict:
    """Build a minimal taa_regime_state dict."""
    centers = get_regime_centers_for_regime(regime)
    return {
        "raw_regime": regime,
        "stress_score": 35.0,
        "smoothed_centers": centers,
        "effective_bands": {},
    }


# ---------------------------------------------------------------------------
#  1. IPS Invariant (the CORE safety property)
# ---------------------------------------------------------------------------


class TestIPSInvariant:
    """The IPS invariant MUST hold for every possible input combination.

    effective_min >= ips_min AND effective_max <= ips_max
    """

    @pytest.mark.parametrize("ips_min,ips_max,regime_center,half_width", [
        # Normal: regime band fits inside IPS
        (0.15, 0.55, 0.35, 0.08),
        # Regime band wider than IPS
        (0.20, 0.30, 0.25, 0.15),
        # Regime center below IPS min
        (0.15, 0.55, 0.10, 0.05),
        # Regime center above IPS max
        (0.15, 0.55, 0.60, 0.05),
        # Very narrow IPS
        (0.20, 0.21, 0.30, 0.08),
        # Very wide regime band
        (0.10, 0.60, 0.35, 0.30),
        # Edge: IPS min == IPS max (degenerate point constraint)
        (0.25, 0.25, 0.35, 0.08),
        # Zero half-width (point constraint from regime)
        (0.10, 0.50, 0.30, 0.00),
    ])
    def test_ips_invariant_holds(self, ips_min, ips_max, regime_center, half_width):
        eff_min, eff_max = compute_effective_band(ips_min, ips_max, regime_center, half_width)

        assert eff_min >= ips_min - 1e-9, (
            f"IPS VIOLATION: eff_min={eff_min} < ips_min={ips_min}"
        )
        assert eff_max <= ips_max + 1e-9, (
            f"IPS VIOLATION: eff_max={eff_max} > ips_max={ips_max}"
        )
        assert eff_min <= eff_max + 1e-9, (
            f"INVALID BAND: eff_min={eff_min} > eff_max={eff_max}"
        )

    def test_normal_intersection(self):
        """Regime band [0.27, 0.43] intersected with IPS [0.15, 0.55] = [0.27, 0.43]."""
        eff_min, eff_max = compute_effective_band(0.15, 0.55, 0.35, 0.08)
        assert abs(eff_min - 0.27) < 1e-9
        assert abs(eff_max - 0.43) < 1e-9

    def test_regime_below_ips(self):
        """Regime center 0.10 with half_width 0.05 → band [0.05, 0.15].
        IPS [0.15, 0.55]. Clamp: effective = [0.15, 0.25] (push up to IPS min).
        """
        eff_min, eff_max = compute_effective_band(0.15, 0.55, 0.10, 0.05)
        assert eff_min >= 0.15
        assert eff_max <= 0.55

    def test_regime_above_ips(self):
        """Regime center 0.60 above IPS max 0.55 → clamp to upper IPS edge."""
        eff_min, eff_max = compute_effective_band(0.15, 0.55, 0.60, 0.05)
        assert eff_max <= 0.55
        assert eff_min >= 0.15


# ---------------------------------------------------------------------------
#  2. EMA Smoothing Convergence
# ---------------------------------------------------------------------------


class TestEMASmoothing:
    """EMA with halflife=5 should converge to target within 95% in ~22 days."""

    def test_first_run_returns_current(self):
        """No previous smoothed → returns current centers directly."""
        centers = {"equity": 0.52, "fixed_income": 0.30}
        result = smooth_regime_centers(centers, None)
        assert result == centers

    def test_ema_halflife_convergence(self):
        """After 5 days of constant target, should be ~50% converged."""
        target = {"equity": 0.38}
        initial = {"equity": 0.52}
        current = initial

        for _ in range(5):
            current = smooth_regime_centers(target, current, halflife_days=5, max_daily_shift=1.0)

        # After one halflife, ~50% of the gap should be closed
        gap_initial = 0.52 - 0.38
        gap_after = current["equity"] - 0.38
        convergence = 1 - (gap_after / gap_initial)
        assert abs(convergence - 0.5) < 0.05, f"Expected ~50% convergence, got {convergence:.1%}"

    def test_ema_full_convergence(self):
        """After 22 days of constant target, should be >95% converged."""
        target = {"equity": 0.38}
        current = {"equity": 0.52}

        for _ in range(22):
            current = smooth_regime_centers(target, current, halflife_days=5, max_daily_shift=1.0)

        gap = abs(current["equity"] - 0.38)
        convergence = 1 - (gap / 0.14)
        assert convergence > 0.95, f"Expected >95% convergence after 22 days, got {convergence:.1%}"

    def test_max_daily_shift_cap(self):
        """Single-day shift should not exceed max_daily_shift_pct."""
        target = {"equity": 0.25}  # CRISIS: big shift from 0.52
        current = {"equity": 0.52}
        max_shift = 0.03

        result = smooth_regime_centers(target, current, halflife_days=5, max_daily_shift=max_shift)
        delta = abs(result["equity"] - current["equity"])
        assert delta <= max_shift + 1e-9, (
            f"Daily shift {delta:.4f} exceeds cap {max_shift}"
        )

    def test_multi_asset_class_smoothing(self):
        """All asset classes are smoothed independently."""
        target = {"equity": 0.25, "fixed_income": 0.35, "cash": 0.25}
        current = {"equity": 0.52, "fixed_income": 0.30, "cash": 0.06}

        result = smooth_regime_centers(target, current, halflife_days=5, max_daily_shift=0.03)
        # Equity should decrease, FI should increase, cash should increase
        assert result["equity"] < current["equity"]
        assert result["fixed_income"] > current["fixed_income"]
        assert result["cash"] > current["cash"]

    def test_no_shift_when_at_target(self):
        """If already at target, smoothing produces no movement."""
        target = {"equity": 0.52}
        result = smooth_regime_centers(target, {"equity": 0.52}, halflife_days=5, max_daily_shift=0.03)
        assert abs(result["equity"] - 0.52) < 1e-9


# ---------------------------------------------------------------------------
#  3. Per-block Disaggregation
# ---------------------------------------------------------------------------


class TestDisaggregation:
    def test_preserves_block_proportions(self):
        """Block's share of asset class should be preserved in disaggregation."""
        blocks = [
            {"block_id": "na_equity_large",  "asset_class": "equity", "target_weight": 0.19},
            {"block_id": "na_equity_growth", "asset_class": "equity", "target_weight": 0.08},
            {"block_id": "em_equity",        "asset_class": "equity", "target_weight": 0.07},
        ]
        centers = {"equity": 0.38}
        half_widths = {"equity": 0.08}

        result = _disaggregate_centers_to_blocks(centers, blocks, half_widths)

        # na_equity_large has 19/34 of equity → center = 0.38 * 19/34
        total_eq = 0.19 + 0.08 + 0.07
        expected_large_center = 0.38 * (0.19 / total_eq)
        assert abs(result["na_equity_large"][0] - expected_large_center) < 1e-6

    def test_block_centers_sum_to_asset_class_center(self):
        """Per-block centers within an asset class should sum to the asset class center."""
        blocks = [
            {"block_id": "fi_aggregate",    "asset_class": "fixed_income", "target_weight": 0.15},
            {"block_id": "fi_ig_corporate", "asset_class": "fixed_income", "target_weight": 0.10},
            {"block_id": "fi_high_yield",   "asset_class": "fixed_income", "target_weight": 0.08},
        ]
        centers = {"fixed_income": 0.36}
        half_widths = {"fixed_income": 0.06}

        result = _disaggregate_centers_to_blocks(centers, blocks, half_widths)

        center_sum = sum(c for c, _ in result.values())
        assert abs(center_sum - 0.36) < 1e-6


# ---------------------------------------------------------------------------
#  4. Fallback to static IPS bounds
# ---------------------------------------------------------------------------


class TestFallbackToStatic:
    """When TAA is disabled or no regime state exists, constraints MUST be identical
    to the current static behavior (lines 1851-1858 of model_portfolios.py pre-TAA).
    """

    def _static_constraints(self):
        """Reproduce the exact current behavior."""
        return [
            BlockConstraint(
                block_id=a["block_id"],
                min_weight=a["min_weight"],
                max_weight=a["max_weight"],
            )
            for a in MODERATE_ALLOCATIONS
        ]

    def test_taa_disabled_produces_static_constraints(self):
        """taa_enabled=False → identical to current static behavior."""
        constraints, provenance = resolve_effective_bands(
            allocations=MODERATE_ALLOCATIONS,
            block_asset_classes=BLOCK_ASSET_CLASSES,
            taa_regime_state=_make_regime_state("RISK_OFF"),
            taa_enabled=False,
        )

        static = self._static_constraints()
        assert len(constraints) == len(static)
        for c, s in zip(constraints, static, strict=True):
            assert c.block_id == s.block_id
            assert c.min_weight == s.min_weight
            assert c.max_weight == s.max_weight

        assert provenance["enabled"] is False
        assert provenance["reason"] == "disabled"

    def test_no_regime_state_produces_static_constraints(self):
        """taa_regime_state=None → identical to current static behavior."""
        constraints, provenance = resolve_effective_bands(
            allocations=MODERATE_ALLOCATIONS,
            block_asset_classes=BLOCK_ASSET_CLASSES,
            taa_regime_state=None,
            taa_enabled=True,
        )

        static = self._static_constraints()
        assert len(constraints) == len(static)
        for c, s in zip(constraints, static, strict=True):
            assert c.block_id == s.block_id
            assert c.min_weight == s.min_weight
            assert c.max_weight == s.max_weight

        assert provenance["enabled"] is False
        assert provenance["reason"] == "no_regime_state"


# ---------------------------------------------------------------------------
#  5. resolve_effective_bands integration
# ---------------------------------------------------------------------------


class TestResolveEffectiveBands:
    def test_risk_off_tightens_equity_bands(self):
        """RISK_OFF regime should produce lower equity band centers than RISK_ON."""
        risk_on_state = _make_regime_state("RISK_ON")
        risk_off_state = _make_regime_state("RISK_OFF")

        on_constraints, _ = resolve_effective_bands(
            MODERATE_ALLOCATIONS, BLOCK_ASSET_CLASSES, risk_on_state,
        )
        off_constraints, _ = resolve_effective_bands(
            MODERATE_ALLOCATIONS, BLOCK_ASSET_CLASSES, risk_off_state,
        )

        # Find equity block constraints
        on_equity = [c for c in on_constraints if BLOCK_ASSET_CLASSES.get(c.block_id) == "equity"]
        off_equity = [c for c in off_constraints if BLOCK_ASSET_CLASSES.get(c.block_id) == "equity"]

        # RISK_OFF equity max should be lower than RISK_ON equity max
        on_eq_max = sum(c.max_weight for c in on_equity)
        off_eq_max = sum(c.max_weight for c in off_equity)
        assert off_eq_max < on_eq_max, "RISK_OFF should tighten equity bands"

    def test_crisis_increases_cash_band(self):
        """CRISIS regime should give cash more room than RISK_ON."""
        risk_on_state = _make_regime_state("RISK_ON")
        crisis_state = _make_regime_state("CRISIS")

        on_constraints, _ = resolve_effective_bands(
            MODERATE_ALLOCATIONS, BLOCK_ASSET_CLASSES, risk_on_state,
        )
        crisis_constraints, _ = resolve_effective_bands(
            MODERATE_ALLOCATIONS, BLOCK_ASSET_CLASSES, crisis_state,
        )

        on_cash = next(c for c in on_constraints if c.block_id == "cash")
        crisis_cash = next(c for c in crisis_constraints if c.block_id == "cash")
        assert crisis_cash.max_weight >= on_cash.max_weight

    def test_all_constraints_respect_ips(self):
        """Every block constraint should be within IPS bounds for all regimes."""
        ips_bounds = {a["block_id"]: (a["min_weight"], a["max_weight"]) for a in MODERATE_ALLOCATIONS}

        for regime in ["RISK_ON", "RISK_OFF", "INFLATION", "CRISIS"]:
            state = _make_regime_state(regime)
            constraints, _ = resolve_effective_bands(
                MODERATE_ALLOCATIONS, BLOCK_ASSET_CLASSES, state,
            )
            for c in constraints:
                ips_min, ips_max = ips_bounds[c.block_id]
                assert c.min_weight >= ips_min - 1e-9, (
                    f"{regime}/{c.block_id}: min {c.min_weight} < IPS min {ips_min}"
                )
                assert c.max_weight <= ips_max + 1e-9, (
                    f"{regime}/{c.block_id}: max {c.max_weight} > IPS max {ips_max}"
                )

    def test_provenance_populated(self):
        """TAA provenance should have all required fields."""
        state = _make_regime_state("RISK_OFF")
        _, provenance = resolve_effective_bands(
            MODERATE_ALLOCATIONS, BLOCK_ASSET_CLASSES, state,
        )

        assert provenance["enabled"] is True
        assert provenance["raw_regime"] == "RISK_OFF"
        assert "smoothed_centers" in provenance
        assert "effective_bands" in provenance
        assert isinstance(provenance["ips_clamps_applied"], list)


# ---------------------------------------------------------------------------
#  6. Config center sum validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_default_centers_sum_to_one(self):
        """Each regime's centers in DEFAULT_TAA_BANDS must sum to 1.0."""
        for regime, bands in DEFAULT_TAA_BANDS["regime_bands"].items():
            total = sum(cfg["center"] for cfg in bands.values())
            assert abs(total - 1.0) < 0.01, (
                f"Regime {regime} centers sum to {total}, expected 1.0"
            )


# ---------------------------------------------------------------------------
#  7. Stress score extraction
# ---------------------------------------------------------------------------


class TestStressScoreExtraction:
    def test_normal_format(self):
        assert extract_stress_score({"composite_stress": "38.2/100 (8 signals)"}) == 38.2

    def test_integer_score(self):
        assert extract_stress_score({"composite_stress": "75/100 (6 signals)"}) == 75.0

    def test_missing_key(self):
        assert extract_stress_score({}) is None

    def test_malformed(self):
        assert extract_stress_score({"composite_stress": "no score here"}) is None


# ---------------------------------------------------------------------------
#  8. get_regime_centers_for_regime
# ---------------------------------------------------------------------------


class TestRegimeCenters:
    def test_risk_on_centers(self):
        centers = get_regime_centers_for_regime("RISK_ON")
        assert abs(centers["equity"] - 0.52) < 1e-6
        assert abs(centers["cash"] - 0.06) < 1e-6

    def test_crisis_centers(self):
        centers = get_regime_centers_for_regime("CRISIS")
        assert abs(centers["equity"] - 0.25) < 1e-6
        assert abs(centers["cash"] - 0.25) < 1e-6

    def test_unknown_regime_falls_back_to_risk_on(self):
        """Unknown regime should fall back to RISK_ON."""
        centers = get_regime_centers_for_regime("UNKNOWN_REGIME")
        risk_on = get_regime_centers_for_regime("RISK_ON")
        assert centers == risk_on


# ---------------------------------------------------------------------------
#  9. EMA mathematical proof — halflife=5 alpha derivation
# ---------------------------------------------------------------------------


class TestEMAMathematicalProperties:
    """Proves the EMA formula alpha = 1 - exp(-ln(2) / halflife) is correct."""

    def test_alpha_at_halflife_5(self):
        """Alpha should be ~0.1294 for halflife=5."""
        alpha = 1 - math.exp(-math.log(2) / 5)
        assert abs(alpha - 0.12944) < 0.001

    def test_halflife_property(self):
        """After exactly `halflife` steps, (1-alpha)^halflife should be 0.5.

        This means 50% of the gap is closed in `halflife` steps.
        """
        halflife = 5
        alpha = 1 - math.exp(-math.log(2) / halflife)
        remaining = (1 - alpha) ** halflife
        assert abs(remaining - 0.5) < 1e-6, f"Expected 0.5, got {remaining}"

    def test_95_percent_convergence_steps(self):
        """95% convergence should occur in ~3.32 * halflife steps.

        For halflife=5: 3.32 * 5 = 16.6 → ~17 steps for 95%.
        More conservatively, ~22 steps for >95%.
        """
        halflife = 5
        alpha = 1 - math.exp(-math.log(2) / halflife)
        # Find number of steps for 95% convergence
        steps_for_95 = math.log(0.05) / math.log(1 - alpha)
        assert 15 < steps_for_95 < 25, f"Expected 15-25 steps, got {steps_for_95}"
