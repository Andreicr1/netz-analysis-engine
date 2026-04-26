"""Unit tests for IPCA rail rank-transform integration (PR-Q10).

Tests the internal math of run_ipca_rail, not just the dispatcher mock
surface. Verifies that the rail applies cross-sectional rank transform
before building z_fund, and that the kill-switch threshold is correct.
"""
from __future__ import annotations

from collections import namedtuple
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from data_providers.identity.resolver import CikIdentity
from quant_engine.ipca.fit import IPCAFit
from vertical_engines.wealth.attribution.ipca_rail import run_ipca_rail
from vertical_engines.wealth.attribution.models import AttributionRequest, IPCAResult


def _mock_cik(padded: str | None) -> CikIdentity:
    """Build a CikIdentity instance for patching ipca_rail.resolve_cik (PR-Q11).

    Returns a real CikIdentity dataclass — ipca_rail calls .padded and
    .candidates(); both must work on the mock.
    """
    if padded is None:
        return CikIdentity(padded=None, unpadded=None)
    unpadded = padded.lstrip("0") or "0"
    return CikIdentity(padded=padded, unpadded=unpadded)


def _make_request(**overrides) -> AttributionRequest:
    defaults = dict(
        fund_instrument_id=uuid4(),
        asof=date(2026, 4, 19),
        fund_asset_class="Equity",
        fund_cik="0001234567",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 4, 19),
    )
    defaults.update(overrides)
    return AttributionRequest(**defaults)


def _make_fit(oos_r_squared: float = 0.03, K: int = 6) -> IPCAFit:
    return IPCAFit(
        gamma=np.eye(K, dtype=np.float64),
        factor_returns=np.random.default_rng(42).standard_normal((K, 20)),
        K=K,
        intercept=False,
        r_squared=0.5,
        oos_r_squared=oos_r_squared,
        converged=True,
        n_iterations=50,
        dates=pd.date_range("2024-01-31", periods=20, freq="ME"),
    )


# Helper namedtuple to simulate DB rows
_RefRow = namedtuple("_RefRow", ["ref_period"])
_CSRow = namedtuple("_CSRow", ["instrument_id", "size", "value", "momentum", "quality", "investment", "profitability"])
_HRow = namedtuple("_HRow", ["pct_of_nav", "instrument_id"])


class _FakeResult:
    """Minimal mock for sqlalchemy CursorResult."""

    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_rank_transform_applied_before_z_fund():
    """1. Rank transform is applied to chars before z_fund is built.

    With Gamma = I_6, z_fund == ranked chars for the single holding.
    Raw chars have values far outside [-0.5, +0.5]; after ranking they
    must be within that band.
    """
    req = _make_request()
    fit = _make_fit()
    fund_id = req.fund_instrument_id
    universe_id = uuid4()

    ref_date = date(2026, 3, 31)
    cs_rows = [
        _CSRow(instrument_id=fund_id, size=100.0, value=0.0001, momentum=50.0, quality=0.9, investment=80.0, profitability=0.01),
        _CSRow(instrument_id=universe_id, size=0.0, value=0.0, momentum=0.0, quality=0.0, investment=0.0, profitability=0.0),
    ]
    h_rows = [_HRow(pct_of_nav=10.0, instrument_id=fund_id)]

    call_count = 0

    async def mock_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        # load_latest_ipca_fit is patched, so db.execute calls are:
        # 1: ref_period, 2: cross-section, 3: holdings, 4+: alpha estimation
        if call_count == 1:
            return _FakeResult([_RefRow(ref_period=ref_date)])
        elif call_count == 2:
            return _FakeResult(cs_rows)
        elif call_count == 3:
            return _FakeResult(h_rows)
        return _FakeResult([])

    db = AsyncMock()
    db.execute = mock_execute

    with patch("vertical_engines.wealth.attribution.ipca_rail.load_latest_ipca_fit", return_value=fit), \
         patch("vertical_engines.wealth.attribution.ipca_rail.resolve_cik", new=AsyncMock(return_value=_mock_cik("0001234567"))), \
         patch("vertical_engines.wealth.attribution.ipca_rail.latest_period_for_cik", return_value=date(2026, 3, 31)):
        result = await run_ipca_rail(req, db)

    assert result is not None
    # With Gamma=I, factor_exposures == z_fund. Ranked values must be in [-0.5, +0.5].
    for exp in result.factor_exposures:
        assert -0.5 <= exp <= 0.5, f"factor exposure {exp} outside ranked range"


@pytest.mark.asyncio
async def test_ref_period_none_falls_back_to_option_a():
    """2. ref_period=None falls back to Option A (not terminal None)."""
    req = _make_request()
    fit = _make_fit()

    call_count = 0

    async def mock_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # ref_period query — no data
            return _FakeResult([_RefRow(ref_period=None)])
        return _FakeResult([])

    db = AsyncMock()
    db.execute = mock_execute

    with patch("vertical_engines.wealth.attribution.ipca_rail.load_latest_ipca_fit", return_value=fit), \
         patch("vertical_engines.wealth.attribution.ipca_rail.resolve_cik", new=AsyncMock(return_value=_mock_cik("0001234567"))), \
         patch("vertical_engines.wealth.attribution.ipca_rail.latest_period_for_cik", return_value=date(2026, 3, 31)), \
         patch("vertical_engines.wealth.attribution.ipca_rail._run_ipca_rail_option_a", new_callable=AsyncMock) as mock_opt_a:
        mock_opt_a.return_value = None
        await run_ipca_rail(req, db)
        mock_opt_a.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_holdings_match_falls_back_to_option_a():
    """3. Holdings with no chars at ref_period -> fallback to Option A."""
    req = _make_request()
    fit = _make_fit()

    ref_date = date(2026, 3, 31)
    unrelated_id = uuid4()
    cs_rows = [
        _CSRow(instrument_id=unrelated_id, size=1.0, value=1.0, momentum=1.0, quality=1.0, investment=1.0, profitability=1.0),
    ]
    holding_id = uuid4()
    h_rows = [_HRow(pct_of_nav=10.0, instrument_id=holding_id)]

    call_count = 0

    async def mock_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _FakeResult([_RefRow(ref_period=ref_date)])
        elif call_count == 2:
            return _FakeResult(cs_rows)
        elif call_count == 3:
            return _FakeResult(h_rows)
        return _FakeResult([])

    db = AsyncMock()
    db.execute = mock_execute

    with patch("vertical_engines.wealth.attribution.ipca_rail.load_latest_ipca_fit", return_value=fit), \
         patch("vertical_engines.wealth.attribution.ipca_rail.resolve_cik", new=AsyncMock(return_value=_mock_cik("0001234567"))), \
         patch("vertical_engines.wealth.attribution.ipca_rail.latest_period_for_cik", return_value=date(2026, 3, 31)), \
         patch("vertical_engines.wealth.attribution.ipca_rail._run_ipca_rail_option_a", new_callable=AsyncMock) as mock_opt_a:
        mock_opt_a.return_value = None
        result = await run_ipca_rail(req, db)
        mock_opt_a.assert_awaited_once()


@pytest.mark.asyncio
async def test_kill_switch_fires_on_zero_oos_r2():
    """4. Kill switch fires on oos_r_squared = 0.0."""
    req = _make_request()
    fit = _make_fit(oos_r_squared=0.0)

    with patch("vertical_engines.wealth.attribution.ipca_rail.load_latest_ipca_fit", return_value=fit):
        db = AsyncMock()
        result = await run_ipca_rail(req, db)

    assert result is None


@pytest.mark.asyncio
async def test_kill_switch_passes_on_small_positive_oos_r2():
    """5. Kill switch passes on small positive oos_r_squared (e.g. 0.003)."""
    req = _make_request()
    fit = _make_fit(oos_r_squared=0.003)

    ref_date = date(2026, 3, 31)
    fund_id = req.fund_instrument_id
    cs_rows = [
        _CSRow(instrument_id=fund_id, size=1.0, value=1.0, momentum=1.0, quality=1.0, investment=1.0, profitability=1.0),
    ]
    h_rows = [_HRow(pct_of_nav=10.0, instrument_id=fund_id)]

    call_count = 0

    async def mock_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _FakeResult([_RefRow(ref_period=ref_date)])
        elif call_count == 2:
            return _FakeResult(cs_rows)
        elif call_count == 3:
            return _FakeResult(h_rows)
        return _FakeResult([])

    db = AsyncMock()
    db.execute = mock_execute

    with patch("vertical_engines.wealth.attribution.ipca_rail.load_latest_ipca_fit", return_value=fit), \
         patch("vertical_engines.wealth.attribution.ipca_rail.resolve_cik", new=AsyncMock(return_value=_mock_cik("0001234567"))), \
         patch("vertical_engines.wealth.attribution.ipca_rail.latest_period_for_cik", return_value=date(2026, 3, 31)):
        result = await run_ipca_rail(req, db)

    # Rail proceeds (doesn't return None from kill switch).
    # Result may be None due to alpha estimation mock returning empty rows,
    # but it must NOT be None from the kill switch — verify by checking
    # that db.execute was called (meaning we got past the threshold gate).
    assert result is not None or call_count > 1, "Kill switch blocked at oos_r²=0.003"


# ---------------------------------------------------------------------------
# Tests 6-8: Dispatcher bug fixes (PR-Q10 batch 3)
# ---------------------------------------------------------------------------

def test_cik_variants_produces_both_forms():
    """6. cik_variants returns (unpadded, zero-padded-10) for any input."""
    from vertical_engines.wealth.attribution.holdings_based import cik_variants

    assert cik_variants("36405") == ("36405", "0000036405")
    assert cik_variants("0000036405") == ("36405", "0000036405")
    assert cik_variants("0001234567") == ("1234567", "0001234567")
    # Edge: all zeros
    assert cik_variants("0000000000") == ("0", "0000000000")


@pytest.mark.asyncio
async def test_option_a_date_alignment():
    """7. Option A aligns first-of-month NAV dates with end-of-month factor dates."""
    from vertical_engines.wealth.attribution.ipca_rail import _run_ipca_rail_option_a

    req = _make_request()
    fit = _make_fit(K=4)
    # Override dates to end-of-month (like real IPCA fits)
    fit = IPCAFit(
        gamma=fit.gamma[:, :4],  # 6×4
        factor_returns=np.random.default_rng(99).standard_normal((4, 24)),
        K=4,
        intercept=False,
        r_squared=0.5,
        oos_r_squared=0.03,
        converged=True,
        n_iterations=50,
        dates=pd.date_range("2024-01-31", periods=24, freq="ME"),
    )

    # Simulate nav rows with first-of-month dates (as produced by date_trunc)
    _NavRow = namedtuple("_NavRow", ["month", "nav_eom"])
    nav_rows = [
        _NavRow(month=date(2023, m, 1), nav_eom=100.0 + m)
        for m in range(1, 13)
    ] + [
        _NavRow(month=date(2024, m, 1), nav_eom=112.0 + m * 0.5)
        for m in range(1, 13)
    ]

    async def mock_execute(stmt, params=None):
        return _FakeResult(nav_rows)

    db = AsyncMock()
    db.execute = mock_execute

    result = await _run_ipca_rail_option_a(req, db, fit)
    assert result is not None, "Option A returned None — date alignment still broken"
    assert len(result.factor_exposures) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_scenario", ["no_cik", "no_period", "no_ref_period"])
async def test_symmetric_option_a_fallback(failure_scenario):
    """8. Every Option-B precondition failure falls back to Option A."""
    from contextlib import ExitStack

    req = _make_request()
    fit = _make_fit()
    sentinel = IPCAResult(
        factor_names=["Sentinel"],
        factor_exposures=[0.0],
        factor_returns_contribution=[0.0],
        alpha=0.0,
        confidence=0.0,
    )

    _P = "vertical_engines.wealth.attribution.ipca_rail"

    mock_opt_a = AsyncMock(return_value=sentinel)
    patches_list = [
        patch(f"{_P}.load_latest_ipca_fit", AsyncMock(return_value=fit)),
        patch(f"{_P}._run_ipca_rail_option_a", mock_opt_a),
    ]

    if failure_scenario == "no_cik":
        patches_list.append(patch(f"{_P}.resolve_cik", AsyncMock(return_value=_mock_cik(None))))
    elif failure_scenario == "no_period":
        patches_list.append(patch(f"{_P}.resolve_cik", AsyncMock(return_value=_mock_cik("0001234567"))))
        patches_list.append(patch(f"{_P}.latest_period_for_cik", AsyncMock(return_value=None)))
    elif failure_scenario == "no_ref_period":
        patches_list.append(patch(f"{_P}.resolve_cik", AsyncMock(return_value=_mock_cik("0001234567"))))
        patches_list.append(patch(f"{_P}.latest_period_for_cik", AsyncMock(return_value=date(2026, 3, 31))))

    db = AsyncMock()
    if failure_scenario == "no_ref_period":
        async def mock_execute(stmt, params=None):
            return _FakeResult([_RefRow(ref_period=None)])
        db.execute = mock_execute

    with ExitStack() as stack:
        for p in patches_list:
            stack.enter_context(p)
        result = await run_ipca_rail(req, db)

    assert result is sentinel, f"Expected Option A fallback for {failure_scenario}, got {result}"
    mock_opt_a.assert_awaited_once()
