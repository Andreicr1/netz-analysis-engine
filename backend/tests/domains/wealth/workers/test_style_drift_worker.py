"""Style drift worker — gate-logic tests via the pure-compute helper.

The worker's DB-side glue (advisory lock, persist, fund-name lookup)
lives behind asyncpg and is exercised by the dev smoke run. These
tests pin the per-CIK decision logic that determines which CIKs get
a drift signal and which are skipped.
"""
from __future__ import annotations

from datetime import date

from app.domains.wealth.services.style_drift_analyzer import (
    StyleDriftResult,
)
from app.domains.wealth.workers.style_drift_worker import (
    _process_holdings_quarters,
)


def _holding(asset_class, pct, sector="CORP", isin="US0378331005"):
    return {
        "asset_class": asset_class,
        "pct_of_nav": pct,
        "sector": sector,
        "isin": isin,
        "currency": "USD",
        "report_date": date(2026, 3, 31),
    }


def _quarter(d: date, asset_class="EC", pct=100, sector="CORP"):
    """Build a holdings list tagged with a single report_date."""
    h = _holding(asset_class, pct, sector=sector)
    h["report_date"] = d
    return [h]


class TestGates:
    def test_too_few_quarters_returns_insufficient(self):
        # Only 3 quarters total → below _MIN_QUARTERS_REQUIRED=5.
        quarters = {
            date(2026, 3, 31): _quarter(date(2026, 3, 31)),
            date(2025, 12, 31): _quarter(date(2025, 12, 31)),
            date(2025, 9, 30): _quarter(date(2025, 9, 30)),
        }
        out = _process_holdings_quarters(quarters, cik="123")
        assert out == "insufficient_data"

    def test_low_coverage_current_quarter_skipped(self):
        """Current quarter has total pct_of_nav < 70 → low coverage,
        skipped before drift is computed."""
        quarters: dict = {}
        for q in [date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30),
                  date(2025, 6, 30), date(2025, 3, 31)]:
            h = _holding("EC", 50)  # only 50% NAV — low coverage
            h["report_date"] = q
            quarters[q] = [h]
        out = _process_holdings_quarters(quarters, cik="123")
        assert out == "skipped_low_coverage"

    def test_trust_cik_aggregation_incoherent_current(self):
        """Current quarter shows 3 dominant buckets (equity + FI +
        cash all >30%) — coherence gate rejects."""
        cur_dt = date(2026, 3, 31)
        cur_holdings = [
            {**_holding("EC", 35), "report_date": cur_dt},
            {**_holding("DBT", 35), "report_date": cur_dt},
            {**_holding("ST", 35), "report_date": cur_dt},
        ]
        quarters = {cur_dt: cur_holdings}
        for q in [date(2025, 12, 31), date(2025, 9, 30),
                  date(2025, 6, 30), date(2025, 3, 31)]:
            quarters[q] = _quarter(q)
        out = _process_holdings_quarters(quarters, cik="123")
        assert out == "skipped_incoherent"


class TestSuccessPath:
    def test_stable_fund_yields_drift_result_with_severity_none(self):
        # 5 identical quarters of 100% equity. Drift = 0.
        quarters = {
            d: _quarter(d) for d in [
                date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30),
                date(2025, 6, 30), date(2025, 3, 31),
            ]
        }
        out = _process_holdings_quarters(quarters, cik="123")
        assert isinstance(out, StyleDriftResult)
        assert out.severity == "none"
        assert out.status == "stable"
        assert out.composite_drift == 0.0
        assert out.historical_window_quarters == 4

    def test_severe_shift_detected(self):
        """Current quarter is 100% government bonds; historical was
        100% equity. Asset-mix drift maxes out, severity=severe."""
        cur_dt = date(2026, 3, 31)
        cur_holdings = [
            {**_holding("UST", 95, sector="UST"), "report_date": cur_dt},
            {**_holding("ST", 5), "report_date": cur_dt},
        ]
        quarters = {cur_dt: cur_holdings}
        for q in [date(2025, 12, 31), date(2025, 9, 30),
                  date(2025, 6, 30), date(2025, 3, 31)]:
            quarters[q] = _quarter(q)  # 100% equity historical
        out = _process_holdings_quarters(quarters, cik="123")
        assert isinstance(out, StyleDriftResult)
        assert out.severity == "severe"
        assert out.status == "drift_detected"
        # Asset mix and FI subtype should be the top drivers.
        assert "asset_mix" in out.drivers[:2]
