"""Regression: attribution route falls back to instruments_org when no live portfolio.

Before the fix, get_attribution would produce fund_returns_by_block={} for all
blocks when live_portfolio was None or had no fund_selection_schema, causing
every block to be logged as attribution_block_excluded.

The fix queries instruments_org (approved instruments) as fallback so that
attribution still runs with real fund NAV data even without a live portfolio.
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.wealth.routes.attribution import get_attribution


def _make_user() -> MagicMock:
    u = MagicMock()
    u.name = "tester"
    return u


def _make_sa_rows() -> list[MagicMock]:
    """Two allocation blocks with target weights."""
    rows = []
    for block_id, weight in [("na_equity_large", 0.6), ("fi_us_aggregate", 0.4)]:
        r = MagicMock()
        r.block_id = block_id
        r.target_weight = weight
        r.effective_from = date(2020, 1, 1)
        rows.append(r)
    return rows


def _make_block_rows() -> list[MagicMock]:
    rows = []
    for block_id, name in [("na_equity_large", "US Equity"), ("fi_us_aggregate", "US Bonds")]:
        r = MagicMock()
        r.block_id = block_id
        r.display_name = name
        rows.append(r)
    return rows


def _make_benchmark_rows() -> list[MagicMock]:
    """Synthetic daily returns for each block over 2 days."""
    rows = []
    for block_id in ["na_equity_large", "fi_us_aggregate"]:
        for d in [date(2024, 1, 2), date(2024, 1, 3)]:
            r = MagicMock()
            r.block_id = block_id
            r.nav_date = d
            r.return_1d = 0.001
            rows.append(r)
    return rows


def _make_nav_rows(instrument_id: uuid.UUID) -> list[MagicMock]:
    rows = []
    for d in [date(2024, 1, 2), date(2024, 1, 3)]:
        r = MagicMock()
        r.instrument_id = instrument_id
        r.nav_date = d
        r.return_1d = 0.002
        rows.append(r)
    return rows


def _make_instruments_org_rows() -> list[tuple[uuid.UUID, str]]:
    return [
        (uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"), "na_equity_large"),
        (uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002"), "fi_us_aggregate"),
    ]


def _build_db(*, has_live_portfolio: bool) -> AsyncMock:
    """Stub AsyncSession routing execute calls by call index."""
    db = AsyncMock()
    call_n = {"i": 0}

    sa_rows = _make_sa_rows()
    block_rows = _make_block_rows()
    bench_rows = _make_benchmark_rows()
    org_rows = _make_instruments_org_rows()
    inst_id_1 = org_rows[0][0]
    inst_id_2 = org_rows[1][0]
    nav_rows = _make_nav_rows(inst_id_1) + _make_nav_rows(inst_id_2)

    def _scalars(rows):
        r = MagicMock()
        r.all.return_value = rows
        r.scalars.return_value = r
        return r

    def _mapping_result(rows):
        r = MagicMock()
        r.all.return_value = [MagicMock(block_id=b, instrument_id=i) for i, b in rows]
        return r

    async def _execute(stmt, params=None):
        call_n["i"] += 1
        n = call_n["i"]
        if n == 1:  # strategic_allocation
            r = MagicMock()
            r.scalars.return_value.all.return_value = sa_rows
            return r
        if n == 2:  # block labels
            r = MagicMock()
            r.all.return_value = block_rows
            return r
        if n == 3:  # live model portfolio
            r = MagicMock()
            if has_live_portfolio:
                mp = MagicMock()
                mp.fund_selection_schema = None  # schema present but empty
                r.scalar.return_value = mp
            else:
                r.scalar.return_value = None
            return r
        if n == 4:  # benchmark_nav
            r = MagicMock()
            r.scalars.return_value.all.return_value = bench_rows
            return r
        if n == 5:  # instruments_org fallback (only when no fund_selection)
            return _mapping_result(org_rows)
        if n == 6:  # nav_timeseries
            r = MagicMock()
            r.scalars.return_value.all.return_value = nav_rows
            return r
        return MagicMock()

    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.mark.asyncio
async def test_attribution_fallback_no_live_portfolio() -> None:
    """Attribution runs via instruments_org when no live portfolio exists.

    Regression: previously all blocks were excluded (fund_returns_by_block={})
    because instruments_by_block was never populated without a live portfolio.
    """
    db = _build_db(has_live_portfolio=False)

    result = await get_attribution(
        profile="conservative",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        granularity="monthly",
        db=db,
        user=_make_user(),
    )

    assert result.profile == "conservative"
    assert result.benchmark_available is True
    # At least some sectors should have been computed
    assert len(result.sectors) > 0


@pytest.mark.asyncio
async def test_attribution_fallback_empty_fund_selection_schema() -> None:
    """Attribution runs via instruments_org when fund_selection_schema is None.

    Regression: live portfolio exists but fund_selection_schema is None —
    instruments_by_block was empty and all blocks were excluded.
    """
    db = _build_db(has_live_portfolio=True)

    result = await get_attribution(
        profile="conservative",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        granularity="monthly",
        db=db,
        user=_make_user(),
    )

    assert result.benchmark_available is True
    assert len(result.sectors) > 0
