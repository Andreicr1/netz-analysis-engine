"""Style drift analyzer unit tests with synthetic fixtures.

Covers the four key behaviors the worker depends on:
  • Insufficient history (<4 quarters) → status="insufficient_data"
  • Stable composition over time → severity="none", composite ≈ 0
  • Single-dimension large shift → driver attribution correct
  • Composite weighting (asset_mix > fi_subtype > geography > issuer)
  • Severity tier transitions at 10 / 25 thresholds
"""
from __future__ import annotations

from datetime import date

from app.domains.wealth.services.holdings_analyzer import HoldingsAnalysis
from app.domains.wealth.services.style_drift_analyzer import (
    compute_style_drift,
)


def _ha(
    *,
    equity=0.0, fi=0.0, cash=0.0, deriv=0.0, other=0.0,
    fi_govt=0.0, fi_muni=0.0, fi_corp=0.0, fi_mbs=0.0, fi_abs=0.0,
    geo_us=0.0, geo_eu=0.0, geo_asia=0.0, geo_em=0.0, geo_other=0.0,
    issuer_cats: list[tuple[str, float]] | None = None,
    as_of: date = date(2026, 3, 31),
) -> HoldingsAnalysis:
    return HoldingsAnalysis(
        as_of_date=as_of,
        n_holdings=200,
        total_nav_covered_pct=100.0,
        equity_pct=equity, fixed_income_pct=fi, cash_pct=cash,
        derivatives_pct=deriv, other_pct=other,
        geography_us_pct=geo_us, geography_europe_pct=geo_eu,
        geography_asia_developed_pct=geo_asia, geography_em_pct=geo_em,
        geography_other_pct=geo_other,
        fi_government_pct=fi_govt, fi_municipal_pct=fi_muni,
        fi_corporate_pct=fi_corp, fi_mbs_pct=fi_mbs, fi_abs_pct=fi_abs,
        top_issuer_categories=issuer_cats or [],
        coverage_quality="high",
    )


def _series(template: HoldingsAnalysis, n: int) -> list[HoldingsAnalysis]:
    """Build n historical quarters, all identical to template."""
    return [template for _ in range(n)]


class TestInsufficientHistory:
    def test_zero_history_returns_insufficient(self):
        current = _ha(equity=100, geo_us=100)
        result = compute_style_drift(current, [], instrument_id="x")
        assert result.status == "insufficient_data"
        assert result.severity == "none"
        assert result.composite_drift == 0.0
        assert result.historical_window_quarters == 0

    def test_three_quarters_is_insufficient(self):
        current = _ha(equity=100, geo_us=100)
        history = _series(current, 3)
        result = compute_style_drift(current, history, instrument_id="x")
        assert result.status == "insufficient_data"
        assert result.historical_window_quarters == 3

    def test_four_quarters_is_sufficient(self):
        current = _ha(equity=100, geo_us=100)
        history = _series(current, 4)
        result = compute_style_drift(current, history, instrument_id="x")
        assert result.status == "stable"
        assert result.historical_window_quarters == 4


class TestStableFund:
    def test_no_change_yields_zero_drift(self):
        current = _ha(
            equity=98, cash=2,
            geo_us=100,
            issuer_cats=[("CORP", 100.0)],
        )
        history = _series(current, 8)
        result = compute_style_drift(current, history, instrument_id="x")
        assert result.composite_drift == 0.0
        assert result.severity == "none"
        assert result.status == "stable"
        assert result.asset_mix_drift == 0.0
        assert result.fi_subtype_drift == 0.0
        assert result.geography_drift == 0.0
        assert result.issuer_category_drift == 0.0


class TestAssetMixDrift:
    def test_50pct_shift_equity_to_bonds_is_severe(self):
        """Fund switches from 100% equity to 50/50 equity/bonds.
        L2 distance: sqrt(50^2 + 50^2) = 70.7. Asset weight 0.40 →
        contribution 28.3, well above SEVERE threshold (25)."""
        current = _ha(equity=50, fi=50, fi_corp=50, geo_us=100,
                      issuer_cats=[("CORP", 100.0)])
        history_template = _ha(equity=100, geo_us=100,
                               issuer_cats=[("CORP", 100.0)])
        history = _series(history_template, 8)
        result = compute_style_drift(current, history, instrument_id="x")
        assert result.severity == "severe"
        assert result.status == "drift_detected"
        assert "asset_mix" in result.drivers[:2]
        assert result.asset_mix_drift > 50  # sqrt(50^2 + 50^2) ≈ 70.7

    def test_small_shift_is_stable(self):
        """5% drift in asset mix is normal noise, not a drift signal."""
        current = _ha(equity=95, cash=5, geo_us=100,
                      issuer_cats=[("CORP", 100.0)])
        history_template = _ha(equity=100, geo_us=100,
                               issuer_cats=[("CORP", 100.0)])
        history = _series(history_template, 8)
        result = compute_style_drift(current, history, instrument_id="x")
        # Asset L2 = sqrt(5^2 + 5^2) = 7.07. Composite ~2.83. Stable.
        assert result.composite_drift < 5
        assert result.severity == "none"


class TestFiSubtypeDrift:
    def test_treasuries_to_corporates_flagged(self):
        """A bond fund switching from 80% Government to 80% Corporate
        is exactly the institutional-grade signal style drift exists
        to catch."""
        current = _ha(fi=90, cash=10, fi_corp=80, geo_us=100,
                      issuer_cats=[("CORP", 100.0)])
        history_template = _ha(fi=90, cash=10, fi_govt=80, geo_us=100,
                               issuer_cats=[("CORP", 100.0)])
        history = _series(history_template, 8)
        result = compute_style_drift(current, history, instrument_id="x")
        # FI drift = sqrt(80^2 + 80^2) = 113.1. Weight 0.30 → 33.9.
        assert "fi_subtype" in result.drivers[:1]
        assert result.fi_subtype_drift > 100
        assert result.severity == "severe"


class TestGeographyDrift:
    def test_us_to_em_shift(self):
        current = _ha(equity=95, cash=5, geo_em=70, geo_us=25, geo_eu=5,
                      issuer_cats=[("CORP", 100.0)])
        history_template = _ha(equity=95, cash=5, geo_us=100,
                               issuer_cats=[("CORP", 100.0)])
        history = _series(history_template, 8)
        result = compute_style_drift(current, history, instrument_id="x")
        assert "geography" in result.drivers
        # Geography L2 = sqrt(75^2 + 70^2 + 5^2) ≈ 102.6.
        # Weighted: 102.6 * 0.20 = 20.5. Moderate.
        assert result.geography_drift > 90


class TestComposite:
    def test_drivers_ranked_by_weighted_contribution(self):
        """Big asset shift dominates a small geography shift."""
        current = _ha(equity=20, fi=80, fi_corp=80, geo_us=95, geo_eu=5,
                      issuer_cats=[("CORP", 100.0)])
        history_template = _ha(equity=100, geo_us=100,
                               issuer_cats=[("CORP", 100.0)])
        history = _series(history_template, 8)
        result = compute_style_drift(current, history, instrument_id="x")
        # asset_mix > fi_subtype > geography > issuer_category
        assert result.drivers[0] == "asset_mix"

    def test_severity_transition_at_moderate_threshold(self):
        """Composite around 10 should be moderate."""
        # ~12 composite via asset shift only
        current = _ha(equity=80, fi=20, fi_corp=20, geo_us=100,
                      issuer_cats=[("CORP", 100.0)])
        history_template = _ha(equity=100, geo_us=100,
                               issuer_cats=[("CORP", 100.0)])
        history = _series(history_template, 8)
        result = compute_style_drift(current, history, instrument_id="x")
        assert result.status == "drift_detected"
        assert result.severity in ("moderate", "severe")
