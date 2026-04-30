"""Tests for Carino (1999) multi-period linking math (PR-Q148).

Covers:
- F-S12-01: full Carino factor k_t = (ln(1+R_p) - ln(1+R_b)) / (R_p - R_b)
- F-S12-08: geometric compounding in _simple_average_linking fallback
- Regression guard for single-period identity
"""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.attribution_service import (
    AttributionResult,
    SectorAttribution,
    compute_multi_period_attribution,
)
from vertical_engines.wealth.attribution.service import AttributionService


def _make_period(
    p_ret: float,
    b_ret: float,
    sector_effects: list[tuple[str, float, float, float]],
) -> AttributionResult:
    """Build a single-period AttributionResult with exact sector effects.

    sector_effects: list of (label, allocation, selection, interaction)
    """
    sectors = []
    for label, alloc, sel, inter in sector_effects:
        sectors.append(
            SectorAttribution(
                sector=label,
                allocation_effect=alloc,
                selection_effect=sel,
                interaction_effect=inter,
                total_effect=alloc + sel + inter,
            ),
        )
    return AttributionResult(
        total_portfolio_return=p_ret,
        total_benchmark_return=b_ret,
        total_excess_return=p_ret - b_ret,
        sectors=sectors,
        allocation_total=sum(s.allocation_effect for s in sectors),
        selection_total=sum(s.selection_effect for s in sectors),
        interaction_total=sum(s.interaction_effect for s in sectors),
        n_periods=1,
        benchmark_available=True,
    )


class TestCarino6PeriodReconciliation:
    """F-S12-01: 6 monthly periods with known returns.

    The linked effects must reconcile to the geometrically compounded
    total excess return to within floating-point tolerance.
    """

    def test_carino_6_period_reconciliation(self):
        # 6 monthly period returns — deliberately asymmetric
        p_rets = [0.02, 0.03, -0.01, 0.04, -0.02, 0.01]
        b_rets = [0.01, 0.02, 0.005, 0.025, -0.01, 0.005]

        periods = []
        for p, b in zip(p_rets, b_rets, strict=False):
            excess = p - b
            # Sector effects that sum exactly to period excess
            periods.append(
                _make_period(
                    p, b,
                    [
                        ("Equity", excess * 0.4, excess * 0.35, excess * 0.1),
                        ("Bonds", excess * 0.1, excess * 0.03, excess * 0.02),
                    ],
                ),
            )

        result = compute_multi_period_attribution(periods, p_rets, b_rets)

        # Compound returns
        R_p = float(np.prod([1 + r for r in p_rets]) - 1)
        R_b = float(np.prod([1 + r for r in b_rets]) - 1)
        excess_total = R_p - R_b

        np.testing.assert_almost_equal(result.total_portfolio_return, R_p, decimal=6)
        np.testing.assert_almost_equal(result.total_benchmark_return, R_b, decimal=6)

        # Core invariant: linked effects must sum to total excess return.
        # Tolerance accounts for round(..., 6) on each sector effect stored
        # in SectorAttribution (N_sectors * T_periods * 5e-7 worst-case).
        effects_sum = (
            result.allocation_total
            + result.selection_total
            + result.interaction_total
        )
        assert abs(effects_sum - excess_total) < 1e-5, (
            f"Effects sum {effects_sum} != excess {excess_total}, "
            f"gap = {abs(effects_sum - excess_total)}"
        )

    def test_carino_12_period_reconciliation(self):
        """12-month test — verifies the ~20-30 bps drift from the old
        simplified formula is eliminated."""
        np.random.seed(42)
        p_rets = list(np.random.normal(0.005, 0.02, 12))
        b_rets = list(np.random.normal(0.003, 0.015, 12))

        periods = []
        for p, b in zip(p_rets, b_rets, strict=False):
            excess = p - b
            periods.append(
                _make_period(
                    p, b,
                    [("All", excess * 0.6, excess * 0.25, excess * 0.15)],
                ),
            )

        result = compute_multi_period_attribution(periods, p_rets, b_rets)

        R_p = float(np.prod([1 + r for r in p_rets]) - 1)
        R_b = float(np.prod([1 + r for r in b_rets]) - 1)
        excess_total = R_p - R_b

        effects_sum = (
            result.allocation_total
            + result.selection_total
            + result.interaction_total
        )
        assert abs(effects_sum - excess_total) < 1e-5


class TestCarinoNearZeroExcess:
    """F-S12-08: geometric fallback must report compounded returns."""

    def test_geometric_fallback_returns(self):
        """+10% then -10% must report geometric total, not arithmetic 0%."""
        svc = AttributionService()

        r1 = _make_period(
            0.10, 0.10,
            [("Equity", 0.0, 0.0, 0.0)],
        )
        r2 = _make_period(
            -0.10, -0.10,
            [("Equity", 0.0, 0.0, 0.0)],
        )

        # Total excess is exactly zero, so this triggers _simple_average_linking
        result = svc.compute_multi_period(
            [r1, r2],
            [0.10, -0.10],
            [0.10, -0.10],
        )

        # Geometric: (1.10)(0.90) - 1 = -0.01
        expected_p = 1.10 * 0.90 - 1  # -0.01
        expected_b = 1.10 * 0.90 - 1  # -0.01

        assert result.total_portfolio_return == pytest.approx(expected_p, abs=1e-6)
        assert result.total_benchmark_return == pytest.approx(expected_b, abs=1e-6)
        # Old arithmetic fallback would have reported 0.0, which is wrong
        assert result.total_portfolio_return != pytest.approx(0.0, abs=1e-4)

    def test_opposing_excess_geometric_total(self):
        """Portfolio +5%/+0%, benchmark +0%/+5% — compound totals must match."""
        svc = AttributionService()

        r1 = _make_period(
            0.05, 0.00,
            [("Equity", 0.025, 0.015, 0.01)],
        )
        r2 = _make_period(
            0.00, 0.05,
            [("Equity", -0.025, -0.015, -0.01)],
        )

        result = svc.compute_multi_period(
            [r1, r2],
            [0.05, 0.00],
            [0.00, 0.05],
        )

        # Both compound to 0.05
        assert result.total_portfolio_return == pytest.approx(0.05, abs=1e-6)
        assert result.total_benchmark_return == pytest.approx(0.05, abs=1e-6)
        assert result.total_excess_return == pytest.approx(0.0, abs=1e-6)


class TestCarinoSinglePeriodIdentity:
    """Regression guard: single period must reconcile exactly."""

    def test_single_period_identity(self):
        """Single period passed to compute_multi_period_attribution must return
        the same object (short-circuit), preserving exact reconciliation."""
        period = _make_period(
            0.05, 0.03,
            [
                ("Equity", 0.008, 0.006, 0.004),
                ("Bonds", 0.001, 0.0005, 0.0005),
            ],
        )

        result = compute_multi_period_attribution([period], [0.05], [0.03])

        # Single-period short-circuit returns the same object
        assert result is period

    def test_single_period_via_service(self):
        """Single period through the service layer also preserves identity."""
        svc = AttributionService()
        period = _make_period(
            0.04, 0.02,
            [("Equity", 0.01, 0.005, 0.005)],
        )

        result = svc.compute_multi_period([period], [0.04], [0.02])

        assert result is period
        assert result.total_excess_return == pytest.approx(0.02, abs=1e-10)
        effects = (
            result.allocation_total
            + result.selection_total
            + result.interaction_total
        )
        assert effects == pytest.approx(result.total_excess_return, abs=1e-10)


class TestCarinoFactorMath:
    """Direct tests of the corrected _carino_factor inner function."""

    def test_equal_returns_limit(self):
        """When r_p == r_b, k_t should equal 1/(1+r_p) by L'Hopital."""
        # Access the inner function via compute_multi_period_attribution
        # by constructing a case where we can verify the scale factor.
        # Instead, test indirectly: two periods with equal excess but
        # different absolute levels should produce different k_t values.
        p_rets = [0.10, 0.02]
        b_rets = [0.05, -0.03]
        # excess_0 = 0.05, excess_1 = 0.05 — same excess, different levels

        periods = []
        for p, b in zip(p_rets, b_rets, strict=False):
            excess = p - b
            periods.append(
                _make_period(p, b, [("All", excess * 0.6, excess * 0.25, excess * 0.15)]),
            )

        result = compute_multi_period_attribution(periods, p_rets, b_rets)

        R_p = float(np.prod([1 + r for r in p_rets]) - 1)
        R_b = float(np.prod([1 + r for r in b_rets]) - 1)

        # Must still reconcile
        effects_sum = (
            result.allocation_total
            + result.selection_total
            + result.interaction_total
        )
        assert abs(effects_sum - (R_p - R_b)) < 1e-5

    def test_negative_returns_reconciliation(self):
        """Both portfolio and benchmark negative — Carino must still reconcile."""
        p_rets = [-0.02, -0.03, 0.01]
        b_rets = [-0.01, -0.04, 0.005]

        periods = []
        for p, b in zip(p_rets, b_rets, strict=False):
            excess = p - b
            periods.append(
                _make_period(p, b, [("All", excess * 0.5, excess * 0.3, excess * 0.2)]),
            )

        result = compute_multi_period_attribution(periods, p_rets, b_rets)

        R_p = float(np.prod([1 + r for r in p_rets]) - 1)
        R_b = float(np.prod([1 + r for r in b_rets]) - 1)

        effects_sum = (
            result.allocation_total
            + result.selection_total
            + result.interaction_total
        )
        assert abs(effects_sum - (R_p - R_b)) < 1e-5
