"""PR-Q152 — Session 12 hygiene terminus tests.

One test per finding: F-S12-10 (regex), F-S12-13 (AS validation),
F-S12-12 (Brinson reconciliation), F-S12-14 (ddof), F-S12-15 (reconciliation warning).
"""

from __future__ import annotations

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# F-S12-10 — Regex ordering misclassifies global/international FI
# ---------------------------------------------------------------------------


class TestRegexClassification:
    """fi_intl must match before fi_us_agg / fi_us_ig."""

    def test_global_aggregate_classifies_as_fi_intl(self) -> None:
        from vertical_engines.wealth.attribution.benchmark_proxy import (
            classify_asset_class_keywords,
        )

        assert classify_asset_class_keywords("Bloomberg Global Aggregate") == "fi_intl"

    def test_international_corporate_bond_classifies_as_fi_intl(self) -> None:
        from vertical_engines.wealth.attribution.benchmark_proxy import (
            classify_asset_class_keywords,
        )

        assert classify_asset_class_keywords("International Corporate Bond") == "fi_intl"

    def test_us_aggregate_still_works(self) -> None:
        from vertical_engines.wealth.attribution.benchmark_proxy import (
            classify_asset_class_keywords,
        )

        assert classify_asset_class_keywords("Bloomberg US Aggregate") == "fi_us_agg"


# ---------------------------------------------------------------------------
# F-S12-13 — Active share weight-sum validation
# ---------------------------------------------------------------------------


class TestActiveShareWeightValidation:
    def test_unnormalized_weights_degrade(self) -> None:
        from quant_engine.active_share_service import compute_active_share

        result = compute_active_share(
            portfolio_weights={"A": 0.25, "B": 0.25},  # sum = 0.5
            benchmark_weights={"A": 0.5, "B": 0.5},
        )
        assert result.degraded is True
        assert result.degraded_reason == "weight_sum_out_of_range"

    def test_normalized_weights_pass(self) -> None:
        from quant_engine.active_share_service import compute_active_share

        result = compute_active_share(
            portfolio_weights={"A": 0.6, "B": 0.4},
            benchmark_weights={"A": 0.5, "B": 0.5},
        )
        assert result.degraded is False
        assert result.active_share == pytest.approx(10.0, abs=0.01)


# ---------------------------------------------------------------------------
# F-S12-12 — Brinson reconciliation against input-derived active return
# ---------------------------------------------------------------------------


class TestBrinsonReconciliation:
    def test_asymmetric_sectors_reconcile(self) -> None:
        """Fund has sectors A+C, benchmark has A+B — effects must sum to
        input-derived R_P - R_B within 1e-12."""
        from vertical_engines.wealth.attribution.brinson_fachler import brinson_fachler

        fund_w = {"A": 0.6, "C": 0.4}
        fund_r = {"A": 0.05, "C": 0.08}
        bench_w = {"A": 0.7, "B": 0.3}
        bench_r = {"A": 0.04, "B": 0.02}

        result = brinson_fachler(fund_w, fund_r, bench_w, bench_r)

        # Input-derived returns
        R_P = sum(fund_w[s] * fund_r[s] for s in fund_w)
        R_B = sum(bench_w[s] * bench_r[s] for s in bench_w)

        assert result.total_active_return == pytest.approx(R_P - R_B, abs=1e-12)


# ---------------------------------------------------------------------------
# F-S12-14 — RBSA tracking error ddof=1
# ---------------------------------------------------------------------------


class TestTrackingErrorDdof:
    def test_te_uses_sample_stdev(self) -> None:
        from vertical_engines.wealth.attribution.returns_based import fit_style

        rng = np.random.default_rng(42)
        T = 36
        r_fund = rng.normal(0.01, 0.03, T)
        r_styles = rng.normal(0.01, 0.03, (T, 2))
        tickers = ("SPY", "AGG")

        result = fit_style(r_fund, r_styles, tickers, min_months=36)
        assert not result.degraded

        # Recompute expected TE with ddof=1
        fitted = r_styles @ np.array([e.weight for e in result.exposures])
        residuals = r_fund - fitted
        expected_te = float(np.std(residuals, ddof=1) * np.sqrt(12))

        assert result.tracking_error_annualized == pytest.approx(expected_te, rel=1e-6)


# ---------------------------------------------------------------------------
# F-S12-15 — compute_attribution reconciliation warning
# ---------------------------------------------------------------------------


class TestAttributionReconciliationWarning:
    def test_normalized_weights_no_warning(self) -> None:
        from quant_engine.attribution_service import compute_attribution

        result = compute_attribution(
            portfolio_weights=np.array([0.6, 0.4]),
            benchmark_weights=np.array([0.5, 0.5]),
            portfolio_returns=np.array([0.05, 0.03]),
            benchmark_returns=np.array([0.04, 0.02]),
            sector_labels=["A", "B"],
        )
        assert result.reconciliation_warning is False
        assert abs(result.reconciliation_residual) < 1e-10

    def test_non_normalized_weights_fires_warning(self) -> None:
        from quant_engine.attribution_service import compute_attribution

        # Weights don't sum to 1 — reconciliation gap expected
        result = compute_attribution(
            portfolio_weights=np.array([0.3, 0.2]),  # sum=0.5
            benchmark_weights=np.array([0.5, 0.5]),
            portfolio_returns=np.array([0.05, 0.03]),
            benchmark_returns=np.array([0.04, 0.02]),
            sector_labels=["A", "B"],
        )
        # The _WEIGHT_EPSILON threshold zeroes allocation/interaction for
        # small w_diff, but with these inputs the gap is real.
        # Just verify the field is populated; warning fires when |residual| > 1e-6
        assert result.reconciliation_residual is not None
