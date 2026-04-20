"""Tests for fund-level attribution dispatcher (PR-Q3).

Dispatcher decides which rail runs per fund. PR-Q3 only implements the
returns-based rail; other rails return ``RAIL_NONE``.
"""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import numpy as np
import pytest

from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    RailBadge,
)
from vertical_engines.wealth.attribution.service import (
    _cache_key,
    compute_fund_attribution,
)

RNG_SEED = 20260420


def _request(**overrides) -> AttributionRequest:
    base = {
        "fund_instrument_id": uuid4(),
        "asof": date(2026, 4, 19),
        "lookback_months": 60,
        "style_tickers": ("SPY", "IWM", "EFA", "EEM", "AGG", "HYG", "LQD"),
        "min_months": 36,
    }
    base.update(overrides)
    return AttributionRequest(**base)


def _synth_returns(n: int, k: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(RNG_SEED)
    r_styles = rng.normal(0.005, 0.04, size=(n, k))
    r_fund = r_styles @ rng.dirichlet(np.ones(k)) + rng.normal(0, 0.001, n)
    return r_fund, r_styles


async def _fetch_valid(req: AttributionRequest, _db):
    r_fund, r_styles = _synth_returns(60, len(req.style_tickers))
    return r_fund, r_styles, req.style_tickers


async def _fetch_short(req: AttributionRequest, _db):
    r_fund, r_styles = _synth_returns(20, len(req.style_tickers))
    return r_fund, r_styles, req.style_tickers


async def _fetch_empty(_req, _db):
    return (
        np.empty(0, dtype=np.float64),
        np.empty((0, 0), dtype=np.float64),
        tuple(),
    )


def test_dispatcher_returns_rail_when_data_is_sufficient() -> None:
    result = asyncio.run(
        compute_fund_attribution(_request(), returns_fetch=_fetch_valid),
    )
    assert result.badge == RailBadge.RAIL_RETURNS
    assert result.returns_based is not None
    assert len(result.returns_based.exposures) == 7


def test_dispatcher_rail_none_when_insufficient_history() -> None:
    result = asyncio.run(
        compute_fund_attribution(_request(), returns_fetch=_fetch_short),
    )
    assert result.badge == RailBadge.RAIL_NONE
    assert result.reason == "insufficient_history"


def test_dispatcher_rail_none_when_no_data() -> None:
    result = asyncio.run(
        compute_fund_attribution(_request(), returns_fetch=_fetch_empty),
    )
    assert result.badge == RailBadge.RAIL_NONE
    assert result.reason == "no_data"


def test_metadata_records_style_basket_and_n_months() -> None:
    result = asyncio.run(
        compute_fund_attribution(_request(), returns_fetch=_fetch_valid),
    )
    assert result.metadata["n_months"] == "60"
    assert "SPY" in result.metadata["style_basket"]


def test_style_tickers_override_is_respected() -> None:
    async def fetch(req, _db):
        assert req.style_tickers == ("SPY", "AGG")
        r_fund, r_styles = _synth_returns(60, 2)
        return r_fund, r_styles, req.style_tickers

    req = _request(style_tickers=("SPY", "AGG"))
    result = asyncio.run(compute_fund_attribution(req, returns_fetch=fetch))
    assert result.badge == RailBadge.RAIL_RETURNS
    assert {e.ticker for e in result.returns_based.exposures} == {"SPY", "AGG"}


def test_default_request_uses_seven_etfs() -> None:
    req = AttributionRequest(fund_instrument_id=uuid4(), asof=date(2026, 4, 19))
    assert req.style_tickers == (
        "SPY", "IWM", "EFA", "EEM", "AGG", "HYG", "LQD",
    )
    assert req.min_months == 36
    assert req.lookback_months == 60


def test_concurrent_dispatcher_calls_are_isolated() -> None:
    req1 = _request()
    req2 = _request()

    async def run_both() -> tuple:
        return await asyncio.gather(
            compute_fund_attribution(req1, returns_fetch=_fetch_valid),
            compute_fund_attribution(req2, returns_fetch=_fetch_valid),
        )

    a, b = asyncio.run(run_both())
    assert a.fund_instrument_id == req1.fund_instrument_id
    assert b.fund_instrument_id == req2.fund_instrument_id
    assert a.badge == RailBadge.RAIL_RETURNS
    assert b.badge == RailBadge.RAIL_RETURNS


def test_cache_key_is_deterministic() -> None:
    fund_id = uuid4()
    req_a = AttributionRequest(fund_instrument_id=fund_id, asof=date(2026, 4, 19))
    req_b = AttributionRequest(fund_instrument_id=fund_id, asof=date(2026, 4, 19))
    assert _cache_key(req_a) == _cache_key(req_b)


def test_cache_key_changes_with_basket() -> None:
    fund_id = uuid4()
    req_a = AttributionRequest(fund_instrument_id=fund_id, asof=date(2026, 4, 19))
    req_b = AttributionRequest(
        fund_instrument_id=fund_id,
        asof=date(2026, 4, 19),
        style_tickers=("SPY", "AGG"),
    )
    assert _cache_key(req_a) != _cache_key(req_b)


def test_idempotent_same_inputs_same_output() -> None:
    req = _request()
    a = asyncio.run(compute_fund_attribution(req, returns_fetch=_fetch_valid))
    b = asyncio.run(compute_fund_attribution(req, returns_fetch=_fetch_valid))
    assert a.badge == b.badge
    # Exposures numerically equal given deterministic synthetic returns.
    for e1, e2 in zip(a.returns_based.exposures, b.returns_based.exposures, strict=True):
        assert e1.ticker == e2.ticker
        assert e1.weight == pytest.approx(e2.weight, rel=1e-9, abs=1e-12)


def test_cache_is_used_when_client_provided() -> None:
    class InMemoryRedis:
        def __init__(self) -> None:
            self.store: dict[str, bytes] = {}
            self.set_calls = 0
            self.get_calls = 0

        async def get(self, key: str):
            self.get_calls += 1
            return self.store.get(key)

        async def setex(self, key: str, ttl: int, value: str) -> None:
            self.set_calls += 1
            self.store[key] = value.encode()

    redis = InMemoryRedis()
    req = _request()

    first = asyncio.run(
        compute_fund_attribution(req, returns_fetch=_fetch_valid, redis_client=redis),
    )
    fetch_count = {"n": 0}

    async def counting_fetch(r, db):
        fetch_count["n"] += 1
        return await _fetch_valid(r, db)

    second = asyncio.run(
        compute_fund_attribution(
            req, returns_fetch=counting_fetch, redis_client=redis,
        ),
    )

    assert first.badge == RailBadge.RAIL_RETURNS
    assert second.badge == RailBadge.RAIL_RETURNS
    # Second call served from cache — fetch override not invoked.
    assert fetch_count["n"] == 0
    assert redis.set_calls == 1
