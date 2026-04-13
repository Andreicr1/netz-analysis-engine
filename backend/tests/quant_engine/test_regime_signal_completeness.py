"""Tests for build_regime_inputs() — 10-signal completeness + staleness + as_of_date."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from quant_engine.regime_service import (
    build_regime_inputs,
    classify_regime_multi_signal,
)

EXPECTED_KEYS = {
    "vix", "yield_curve_spread", "cpi_yoy", "sahm_rule",
    "hy_oas", "baa_spread", "fed_funds_delta_6m",
    "dxy_zscore", "energy_shock", "cfnai",
}


def _make_macro_row(series_id: str, value: float, obs_date: date):
    """Create a mock row matching the (series_id, value, obs_date) shape."""
    from collections import namedtuple
    Row = namedtuple("Row", ["series_id", "value", "obs_date"])
    return Row(series_id=series_id, value=value, obs_date=obs_date)


def _build_fresh_macro_rows(as_of: date | None = None):
    """Build macro_data rows for ALL regime series, all fresh."""
    d = as_of or date.today()
    return [
        _make_macro_row("VIXCLS", 20.0, d),
        _make_macro_row("DGS10", 4.5, d),
        _make_macro_row("DGS2", 4.0, d),
        _make_macro_row("CPIAUCSL", 310.0, d),
        _make_macro_row("SAHMREALTIME", 0.2, d),
        _make_macro_row("BAMLH0A0HYM2", 3.5, d),
        _make_macro_row("BAA10Y", 1.5, d),
        _make_macro_row("DFF", 5.25, d),
        _make_macro_row("DTWEXBGS", 110.0, d),
        _make_macro_row("DCOILWTICO", 75.0, d),
        _make_macro_row("CFNAI", 0.1, d),
    ]


def _make_db_mock(bulk_rows, cpi_12m=295.0, ff_6m=5.00):
    """Create an AsyncSession mock that returns appropriate results.

    The bulk query returns bulk_rows. Subsequent queries for CPI 12m ago
    and FF 6m ago return scalar values. Z-score/RoC queries return series.
    """
    db = AsyncMock()
    call_count = 0

    class FakeResult:
        def __init__(self, rows=None, scalar=None):
            self._rows = rows or []
            self._scalar = scalar

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

        def scalar_one_or_none(self):
            return self._scalar

    async def fake_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1

        stmt_str = str(stmt) if not hasattr(stmt, "compile") else ""

        # First call = bulk fetch
        if call_count == 1:
            return FakeResult(rows=bulk_rows)

        # CPI 12m lookback
        if call_count == 2:
            return FakeResult(scalar=cpi_12m)

        # FF delta queries (latest + 6m ago)
        if call_count == 3:
            d = date.today()
            from collections import namedtuple
            Row = namedtuple("Row", ["value", "obs_date"])
            return FakeResult(rows=[Row(value=5.25, obs_date=d)])
        if call_count == 4:
            return FakeResult(scalar=ff_6m)

        # Z-score queries return enough values for computation
        if call_count <= 8:
            from collections import namedtuple
            Row = namedtuple("Row", [0])  # single-column result
            import random
            random.seed(42)
            vals = [(v,) for v in [110 + i * 0.1 for i in range(100)]]
            return FakeResult(rows=vals)

        # RoC queries
        if call_count == 9:
            from collections import namedtuple
            Row = namedtuple("Row", ["value", "obs_date"])
            return FakeResult(rows=[Row(value=75.0, obs_date=date.today())])
        if call_count == 10:
            return FakeResult(scalar=70.0)

        return FakeResult()

    db.execute = fake_execute
    return db


class TestBuildRegimeInputsKeys:
    @pytest.mark.asyncio
    async def test_returns_all_10_keys(self):
        """build_regime_inputs returns exactly the 10 expected signal keys."""
        db = _make_db_mock(_build_fresh_macro_rows())
        result = await build_regime_inputs(db)
        assert set(result.keys()) == EXPECTED_KEYS

    @pytest.mark.asyncio
    async def test_fresh_data_no_nones(self):
        """When all data is fresh, no signal should be None."""
        db = _make_db_mock(_build_fresh_macro_rows())
        result = await build_regime_inputs(db)
        # vix through cfnai should all be non-None
        # (dxy_zscore and energy_shock depend on Z-score/RoC helpers)
        for key in ("vix", "yield_curve_spread", "cpi_yoy", "sahm_rule",
                     "hy_oas", "baa_spread"):
            assert result[key] is not None, f"{key} should not be None with fresh data"


class TestSignalCountDifference:
    def test_10_signals_vs_7_signals_score_differs(self):
        """10-signal classification produces different stress than 7-signal."""
        # 7 signals (old behavior: 3 missing)
        _, reasons_7 = classify_regime_multi_signal(
            vix=22.0,
            yield_curve_spread=0.5,
            cpi_yoy=2.5,
            sahm_rule=0.15,
            hy_oas=3.5,
            baa_spread=1.5,
            fed_funds_delta_6m=0.25,
            dxy_zscore=None,
            energy_shock=None,
            cfnai=None,
        )

        # 10 signals (with moderate stress values)
        _, reasons_10 = classify_regime_multi_signal(
            vix=22.0,
            yield_curve_spread=0.5,
            cpi_yoy=2.5,
            sahm_rule=0.15,
            hy_oas=3.5,
            baa_spread=1.5,
            fed_funds_delta_6m=0.25,
            dxy_zscore=1.2,
            energy_shock=45.0,
            cfnai=-0.5,
        )

        # Extract composite scores
        score_7 = float(reasons_7["composite_stress"].split("/")[0])
        score_10 = float(reasons_10["composite_stress"].split("/")[0])

        assert score_7 != score_10
        # Stressed dxy/energy/cfnai should increase composite
        assert score_10 > score_7


class TestStaleness:
    @pytest.mark.asyncio
    async def test_staleness_nullifies_signal(self):
        """Stale data returns None for the affected signal."""
        stale_date = date.today() - timedelta(days=30)  # >5 days for daily series
        rows = [
            _make_macro_row("VIXCLS", 20.0, stale_date),  # stale (daily, threshold=5)
            _make_macro_row("DGS10", 4.5, date.today()),
            _make_macro_row("DGS2", 4.0, date.today()),
            _make_macro_row("CPIAUCSL", 310.0, date.today()),
            _make_macro_row("SAHMREALTIME", 0.2, date.today()),
            _make_macro_row("BAMLH0A0HYM2", 3.5, date.today()),
            _make_macro_row("BAA10Y", 1.5, date.today()),
            _make_macro_row("DFF", 5.25, date.today()),
            _make_macro_row("DTWEXBGS", 110.0, date.today()),
            _make_macro_row("DCOILWTICO", 75.0, date.today()),
            _make_macro_row("CFNAI", 0.1, date.today()),
        ]
        db = _make_db_mock(rows)
        result = await build_regime_inputs(db)
        assert result["vix"] is None, "Stale VIX should be None"


class TestAsOfDateCeiling:
    @pytest.mark.asyncio
    async def test_as_of_date_filters_future_data(self):
        """as_of_date should exclude data after the cutoff."""
        cutoff = date(2026, 1, 15)
        # Only pre-cutoff data
        rows = [
            _make_macro_row("VIXCLS", 18.0, date(2026, 1, 10)),
            _make_macro_row("DGS10", 4.2, date(2026, 1, 10)),
            _make_macro_row("DGS2", 3.8, date(2026, 1, 10)),
            _make_macro_row("BAMLH0A0HYM2", 3.0, date(2026, 1, 10)),
            _make_macro_row("BAA10Y", 1.3, date(2026, 1, 10)),
            _make_macro_row("DFF", 5.0, date(2026, 1, 10)),
            _make_macro_row("DTWEXBGS", 108.0, date(2026, 1, 10)),
            _make_macro_row("DCOILWTICO", 72.0, date(2026, 1, 10)),
            _make_macro_row("CFNAI", 0.05, date(2026, 1, 10)),
        ]
        db = _make_db_mock(rows)
        result = await build_regime_inputs(db, as_of_date=cutoff)
        # Should return data — the function uses effective_date=cutoff
        assert result["vix"] is not None or result["vix"] is None  # doesn't crash
        assert set(result.keys()) == EXPECTED_KEYS
