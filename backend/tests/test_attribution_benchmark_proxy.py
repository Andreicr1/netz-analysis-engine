"""Unit tests for the benchmark proxy rail (PR-Q5, G3 Fase 3).

Covers:
  - 3-level resolver cascade (exact → fuzzy → class_fallback → unmatched).
  - Proxy rail orchestrator using scripted fake DB sessions + seams.
  - Degradation paths (null benchmark, unmatched, proxy has no holdings,
    sector returns unavailable).
  - Dispatcher integration — falls through when proxy rail degrades.
"""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID, uuid4

import pytest

from vertical_engines.wealth.attribution import benchmark_proxy
from vertical_engines.wealth.attribution.benchmark_proxy import (
    classify_asset_class_keywords,
    resolve_benchmark,
    run_proxy_rail,
)
from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    BenchmarkProxyResult,
    BenchmarkResolution,
    RailBadge,
)
from vertical_engines.wealth.attribution.service import compute_fund_attribution

# ---------------------------------------------------------------------------
# Fake DB scaffolding
# ---------------------------------------------------------------------------


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows or []

    def first(self):
        return dict(self._rows[0]) if self._rows else None

    def all(self):
        return [dict(r) for r in self._rows]


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def first(self):
        if self._scalar is not None:
            return (self._scalar,)
        if self._rows:
            first = self._rows[0]
            return tuple(first.values()) if isinstance(first, dict) else first
        return None

    def mappings(self):
        return _FakeMappings(self._rows)


class _FakeSession:
    """Scripted async session — matches SQL fragments in order.

    Each fragment is matched against the rendered SQL; the first match
    returns the queued result. Matched entries stay in the list so the
    same fragment returns the same result on repeated queries (good
    default for idempotent lookups like the canonical map).
    """

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, dict(params or {})))
        for frag, result in self._script:
            if frag in sql:
                return result
        return _FakeResult()


def _req(fund_id=None):
    return AttributionRequest(
        fund_instrument_id=fund_id or uuid4(),
        asof=date(2026, 3, 31),
        lookback_months=60,
        min_months=36,
    )


# ---------------------------------------------------------------------------
# Asset-class keyword classifier
# ---------------------------------------------------------------------------


def test_classify_asset_class_keywords_large_cap_blend():
    assert classify_asset_class_keywords("Large Cap Blend Index") == "equity_us_large"


def test_classify_asset_class_keywords_emerging_markets():
    assert classify_asset_class_keywords("Some Emerging Markets Benchmark") == "equity_em"


def test_classify_asset_class_keywords_high_yield():
    assert classify_asset_class_keywords("ICE High Yield Corporate Bond") == "fi_us_hy"


def test_classify_asset_class_keywords_empty_returns_none():
    assert classify_asset_class_keywords("") is None
    assert classify_asset_class_keywords("   ") is None


def test_classify_asset_class_keywords_gibberish_returns_none():
    assert classify_asset_class_keywords("xyz nonsense flavor") is None


# ---------------------------------------------------------------------------
# resolve_benchmark — 3-level cascade
# ---------------------------------------------------------------------------


def test_resolve_benchmark_exact_alias_match():
    session = _FakeSession([
        ("= ANY(benchmark_name_aliases)", _FakeResult(rows=[{
            "proxy_etf_cik": "0000884394",
            "proxy_etf_series_id": None,
            "proxy_etf_ticker": "SPY",
            "asset_class": "equity_us_large",
        }])),
    ])
    result = asyncio.run(resolve_benchmark("S&P 500", session))
    assert result.match_type == "exact"
    assert result.proxy_etf_ticker == "SPY"
    assert result.asset_class == "equity_us_large"


def test_resolve_benchmark_fuzzy_match_above_threshold():
    session = _FakeSession([
        # First level: exact — no match.
        ("= ANY(benchmark_name_aliases)", _FakeResult(rows=[])),
        # Second level: fuzzy — hit with sim > 0.7.
        ("similarity(benchmark_name_canonical, :name) AS sim", _FakeResult(rows=[{
            "proxy_etf_cik": "0000884394",
            "proxy_etf_series_id": None,
            "proxy_etf_ticker": "SPY",
            "asset_class": "equity_us_large",
            "sim": 0.82,
        }])),
    ])
    result = asyncio.run(resolve_benchmark("Standard & Poor's 500 Index", session))
    assert result.match_type == "fuzzy"
    assert result.proxy_etf_ticker == "SPY"
    assert result.similarity == pytest.approx(0.82)


def test_resolve_benchmark_fuzzy_below_threshold_falls_through():
    session = _FakeSession([
        ("= ANY(benchmark_name_aliases)", _FakeResult(rows=[])),
        # Fuzzy returns row but sim <= 0.7 → dismissed.
        ("similarity(benchmark_name_canonical, :name) AS sim", _FakeResult(rows=[{
            "proxy_etf_cik": "X",
            "proxy_etf_series_id": None,
            "proxy_etf_ticker": "XYZ",
            "asset_class": "equity_us_large",
            "sim": 0.50,
        }])),
        # Class fallback on "large cap" keyword → hits.
        ("asset_class = CAST(:ac AS benchmark_asset_class)", _FakeResult(rows=[{
            "proxy_etf_cik": "0000884394",
            "proxy_etf_series_id": None,
            "proxy_etf_ticker": "SPY",
            "asset_class": "equity_us_large",
        }])),
    ])
    result = asyncio.run(resolve_benchmark("Large Cap Blend Benchmark", session))
    assert result.match_type == "class_fallback"
    assert result.proxy_etf_ticker == "SPY"


def test_resolve_benchmark_null_input_short_circuits():
    session = _FakeSession([])
    result = asyncio.run(resolve_benchmark(None, session))
    assert result.match_type == "null"
    assert result.proxy_etf_ticker is None
    # No DB calls issued for null input.
    assert session.calls == []


def test_resolve_benchmark_empty_string_short_circuits():
    session = _FakeSession([])
    result = asyncio.run(resolve_benchmark("   ", session))
    assert result.match_type == "null"
    assert session.calls == []


def test_resolve_benchmark_no_match_anywhere_returns_unmatched():
    session = _FakeSession([
        ("= ANY(benchmark_name_aliases)", _FakeResult(rows=[])),
        ("similarity(benchmark_name_canonical, :name) AS sim", _FakeResult(rows=[])),
        # Class fallback also empty.
        ("asset_class = CAST(:ac AS benchmark_asset_class)", _FakeResult(rows=[])),
    ])
    result = asyncio.run(resolve_benchmark("some obscure vendor index blob", session))
    assert result.match_type == "unmatched"
    assert result.proxy_etf_ticker is None


def test_resolve_benchmark_asset_class_fallback_for_large_cap_blend():
    """Level 3 fires when levels 1 and 2 both miss but the string
    matches a keyword bucket."""
    session = _FakeSession([
        ("= ANY(benchmark_name_aliases)", _FakeResult(rows=[])),
        ("similarity(benchmark_name_canonical, :name) AS sim", _FakeResult(rows=[])),
        ("asset_class = CAST(:ac AS benchmark_asset_class)", _FakeResult(rows=[{
            "proxy_etf_cik": "0000884394",
            "proxy_etf_series_id": None,
            "proxy_etf_ticker": "SPY",
            "asset_class": "equity_us_large",
        }])),
    ])
    result = asyncio.run(resolve_benchmark("Obscure Large Cap Blend Index", session))
    assert result.match_type == "class_fallback"
    assert result.asset_class == "equity_us_large"


# ---------------------------------------------------------------------------
# run_proxy_rail orchestrator
# ---------------------------------------------------------------------------


def test_run_proxy_rail_no_cik_returns_none():
    async def no_cik(_db, _iid):
        return None

    session = _FakeSession([])
    result = asyncio.run(run_proxy_rail(_req(), session, cik_resolver=no_cik))
    assert result is None


def test_run_proxy_rail_benchmark_null_degrades():
    async def cik(_db, _iid):
        return "0001234567"

    async def bench(_db, _cik):
        return None

    session = _FakeSession([])
    result = asyncio.run(
        run_proxy_rail(
            _req(), session, cik_resolver=cik, benchmark_fetcher=bench,
        ),
    )
    assert isinstance(result, BenchmarkProxyResult)
    assert result.degraded is True
    assert result.degraded_reason == "benchmark_unresolved"
    assert result.resolution.match_type == "null"


def test_run_proxy_rail_benchmark_unmatched_degrades():
    async def cik(_db, _iid):
        return "0001234567"

    async def bench(_db, _cik):
        return "Proprietary Gibberish Index v7"

    session = _FakeSession([
        ("= ANY(benchmark_name_aliases)", _FakeResult(rows=[])),
        ("similarity(benchmark_name_canonical, :name) AS sim", _FakeResult(rows=[])),
        ("asset_class = CAST(:ac AS benchmark_asset_class)", _FakeResult(rows=[])),
    ])
    result = asyncio.run(
        run_proxy_rail(
            _req(), session, cik_resolver=cik, benchmark_fetcher=bench,
        ),
    )
    assert result.degraded is True
    assert result.degraded_reason == "benchmark_unresolved"


def test_run_proxy_rail_proxy_no_holdings_degrades():
    """Proxy resolves to a BDC/MMF without N-PORT data → degrade."""
    async def cik(_db, _iid):
        return "0001234567"

    async def bench(_db, _cik):
        return "S&P 500"

    session = _FakeSession([
        ("= ANY(benchmark_name_aliases)", _FakeResult(rows=[{
            "proxy_etf_cik": "0000884394",
            "proxy_etf_series_id": None,
            "proxy_etf_ticker": "SPY",
            "asset_class": "equity_us_large",
        }])),
        # Latest period lookup — fund has a filing.
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
        # Fund sector fetch returns data; proxy sector fetch returns empty.
        ("SELECT issuer_category", _FakeResult(rows=[
            {"issuer_category": "EC", "industry_sector": "Tech",
             "aum_usd": 1000.0, "weight": 1.0, "holdings_count": 10},
        ])),
    ])

    # Simpler: intercept fetch_sector_weights to return fund sectors for
    # the fund CIK and empty for the proxy CIK.
    fund_sectors = [
        _sector_weight("Tech", 1.0, 1000.0, 10),
    ]

    async def fake_fetch_sw(_db, cik_arg, _period):
        return (fund_sectors, 1000.0) if cik_arg == "0001234567" else ([], 0.0)

    orig = benchmark_proxy.fetch_sector_weights
    benchmark_proxy.fetch_sector_weights = fake_fetch_sw  # type: ignore[assignment]
    try:
        result = asyncio.run(
            run_proxy_rail(
                _req(), session, cik_resolver=cik, benchmark_fetcher=bench,
            ),
        )
    finally:
        benchmark_proxy.fetch_sector_weights = orig  # type: ignore[assignment]
    assert result.degraded is True
    assert result.degraded_reason == "proxy_no_holdings"


def test_run_proxy_rail_sector_returns_unavailable_degrades():
    """All data present but sector returns fetcher yields empty → degrade."""
    async def cik(_db, _iid):
        return "0001234567"

    async def bench(_db, _cik):
        return "S&P 500"

    session = _FakeSession([
        ("= ANY(benchmark_name_aliases)", _FakeResult(rows=[{
            "proxy_etf_cik": "0000884394",
            "proxy_etf_series_id": None,
            "proxy_etf_ticker": "SPY",
            "asset_class": "equity_us_large",
        }])),
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
    ])
    fund_sectors = [_sector_weight("Tech", 0.6, 600.0, 6)]
    proxy_sectors = [_sector_weight("Tech", 0.5, 500.0, 5)]

    async def fake_fetch_sw(_db, cik_arg, _period):
        if cik_arg == "0001234567":
            return (fund_sectors, 600.0)
        return (proxy_sectors, 500.0)

    orig = benchmark_proxy.fetch_sector_weights
    benchmark_proxy.fetch_sector_weights = fake_fetch_sw  # type: ignore[assignment]
    try:
        result = asyncio.run(
            run_proxy_rail(
                _req(), session, cik_resolver=cik, benchmark_fetcher=bench,
            ),
        )
    finally:
        benchmark_proxy.fetch_sector_weights = orig  # type: ignore[assignment]
    assert result.degraded is True
    assert result.degraded_reason == "sector_returns_unavailable"
    # Brinson was still computed on weights alone (allocation uses R_B=0).
    assert result.brinson is not None
    assert len(result.brinson.by_sector) == 1


def test_run_proxy_rail_happy_path_full_brinson():
    """All three data sources present → rail succeeds with full Brinson math."""
    async def cik(_db, _iid):
        return "0001234567"

    async def bench(_db, _cik):
        return "S&P 500"

    async def sector_returns(_db, _cik, _period):
        return {"Tech": 0.10, "Financials": 0.04}

    session = _FakeSession([
        ("= ANY(benchmark_name_aliases)", _FakeResult(rows=[{
            "proxy_etf_cik": "0000884394",
            "proxy_etf_series_id": None,
            "proxy_etf_ticker": "SPY",
            "asset_class": "equity_us_large",
        }])),
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
    ])
    fund_sectors = [
        _sector_weight("Tech", 0.6, 600.0, 6),
        _sector_weight("Financials", 0.4, 400.0, 4),
    ]
    proxy_sectors = [
        _sector_weight("Tech", 0.5, 500.0, 5),
        _sector_weight("Financials", 0.5, 500.0, 5),
    ]

    async def fake_fetch_sw(_db, cik_arg, _period):
        if cik_arg == "0001234567":
            return (fund_sectors, 1000.0)
        return (proxy_sectors, 1000.0)

    orig = benchmark_proxy.fetch_sector_weights
    benchmark_proxy.fetch_sector_weights = fake_fetch_sw  # type: ignore[assignment]
    try:
        result = asyncio.run(
            run_proxy_rail(
                _req(), session,
                cik_resolver=cik,
                benchmark_fetcher=bench,
                sector_returns_fetcher=sector_returns,
            ),
        )
    finally:
        benchmark_proxy.fetch_sector_weights = orig  # type: ignore[assignment]

    assert result.degraded is False
    assert result.confidence == pytest.approx(0.60)  # exact-match tier
    assert result.resolution.match_type == "exact"
    assert result.resolution.proxy_etf_ticker == "SPY"
    # Brinson identity holds.
    total = (
        result.brinson.allocation_effect
        + result.brinson.selection_effect
        + result.brinson.interaction_effect
    )
    assert total == pytest.approx(result.brinson.total_active_return, abs=1e-12)


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


def test_dispatcher_uses_proxy_when_holdings_degrade():
    """Holdings rail degrades → proxy rail wins and returns RAIL_PROXY."""
    import numpy as np  # noqa: F401 — silence unused; kept for parity

    from vertical_engines.wealth.attribution.brinson_fachler import brinson_fachler
    from vertical_engines.wealth.attribution.models import HoldingsBasedResult

    async def holdings_fetch(_req, _db):
        return HoldingsBasedResult(
            sectors=(), period_of_report=None, coverage_pct=0.0,
            confidence=0.0, holdings_count=0,
            degraded=True, degraded_reason="low_aum_coverage",
        )

    brinson = brinson_fachler(
        fund_weights={"IT": 0.6, "Fin": 0.4},
        fund_returns={"IT": 0.10, "Fin": 0.03},
        bench_weights={"IT": 0.5, "Fin": 0.5},
        bench_returns={"IT": 0.08, "Fin": 0.05},
    )

    async def proxy_fetch(_req, _db):
        return BenchmarkProxyResult(
            resolution=BenchmarkResolution(
                match_type="exact",
                proxy_etf_ticker="SPY",
                proxy_etf_cik="0000884394",
                asset_class="equity_us_large",
            ),
            brinson=brinson,
            confidence=0.60,
            period_of_report=date(2026, 2, 28),
            degraded=False,
        )

    async def returns_fetch(_req, _db):
        pytest.fail("dispatcher should not fall through to returns when proxy wins")

    result = asyncio.run(
        compute_fund_attribution(
            _req(),
            db=None,
            holdings_fetch=holdings_fetch,
            proxy_fetch=proxy_fetch,
            returns_fetch=returns_fetch,
        ),
    )
    assert result.badge == RailBadge.RAIL_PROXY
    assert result.proxy is not None
    assert result.metadata["match_type"] == "exact"
    assert result.metadata["proxy_ticker"] == "SPY"


def test_dispatcher_falls_through_when_proxy_degrades():
    """Holdings degraded AND proxy degraded → returns rail runs."""
    import numpy as np

    from vertical_engines.wealth.attribution.brinson_fachler import brinson_fachler
    from vertical_engines.wealth.attribution.models import HoldingsBasedResult

    async def holdings_fetch(_req, _db):
        return HoldingsBasedResult(
            sectors=(), period_of_report=None, coverage_pct=0.0,
            confidence=0.0, holdings_count=0,
            degraded=True, degraded_reason="no_filing",
        )

    brinson = brinson_fachler({}, {}, {}, {})

    async def proxy_fetch(_req, _db):
        return BenchmarkProxyResult(
            resolution=BenchmarkResolution(match_type="unmatched"),
            brinson=brinson,
            confidence=0.0,
            degraded=True,
            degraded_reason="benchmark_unresolved",
        )

    rng = np.random.default_rng(7)
    r_fund = rng.normal(0.005, 0.02, 48)
    r_styles = rng.normal(0.004, 0.02, (48, 2))

    async def returns_fetch(_req, _db):
        return r_fund, r_styles, ("SPY", "AGG")

    result = asyncio.run(
        compute_fund_attribution(
            _req(),
            db=None,
            holdings_fetch=holdings_fetch,
            proxy_fetch=proxy_fetch,
            returns_fetch=returns_fetch,
        ),
    )
    assert result.badge == RailBadge.RAIL_RETURNS


def test_dispatcher_proxy_serialization_roundtrip():
    """Redis cache encode/decode of a RAIL_PROXY result must roundtrip."""
    from vertical_engines.wealth.attribution.brinson_fachler import brinson_fachler
    from vertical_engines.wealth.attribution.models import FundAttributionResult
    from vertical_engines.wealth.attribution.service import (
        _deserialize_result,
        _serialize_result,
    )

    brinson = brinson_fachler(
        fund_weights={"A": 0.5, "B": 0.5},
        fund_returns={"A": 0.08, "B": 0.03},
        bench_weights={"A": 0.4, "B": 0.6},
        bench_returns={"A": 0.07, "B": 0.04},
    )
    proxy = BenchmarkProxyResult(
        resolution=BenchmarkResolution(
            match_type="fuzzy",
            proxy_etf_ticker="SPY",
            proxy_etf_cik="0000884394",
            asset_class="equity_us_large",
            similarity=0.85,
        ),
        brinson=brinson,
        confidence=0.45,
        period_of_report=date(2026, 2, 28),
        degraded=False,
    )
    result = FundAttributionResult(
        fund_instrument_id=UUID("12345678-1234-5678-1234-567812345678"),
        asof=date(2026, 3, 31),
        badge=RailBadge.RAIL_PROXY,
        proxy=proxy,
        metadata={"match_type": "fuzzy"},
    )
    encoded = _serialize_result(result)
    decoded = _deserialize_result(encoded)
    assert decoded.badge == RailBadge.RAIL_PROXY
    assert decoded.proxy is not None
    assert decoded.proxy.resolution.match_type == "fuzzy"
    assert decoded.proxy.resolution.similarity == pytest.approx(0.85)
    assert len(decoded.proxy.brinson.by_sector) == 2


# ---------------------------------------------------------------------------
# DD ch.4 renderer — proxy rail copy invariants
# ---------------------------------------------------------------------------


def test_dd_ch4_proxy_copy_sanitised():
    """Rendered attribution for RAIL_PROXY never leaks raw quant jargon."""
    from vertical_engines.wealth.dd_report.chapters import _render_attribution_block

    evidence = {
        "attribution": {
            "badge": "RAIL_PROXY",
            "proxy": {
                "resolution": {"match_type": "exact", "proxy_etf_ticker": "SPY"},
                "brinson": {
                    "allocation_effect": 0.004,
                    "selection_effect": 0.0,
                    "interaction_effect": 0.004,
                    "total_active_return": 0.008,
                    "by_sector": [
                        {"sector": "Information Technology",
                         "allocation_effect": 0.002, "selection_effect": 0.010,
                         "interaction_effect": 0.002},
                        {"sector": "Financials",
                         "allocation_effect": 0.002, "selection_effect": -0.010,
                         "interaction_effect": 0.002},
                    ],
                },
            },
        },
    }
    out = "\n".join(_render_attribution_block(evidence))
    assert "MEDIUM CONFIDENCE" in out
    # No raw quant jargon leaks.
    assert "Brinson" not in out
    assert "brinson" not in out.lower() or "Brinson" not in out  # belt and braces
    assert "allocation_effect" not in out
    # Sanitised copy present.
    assert "Asset mix contribution" in out
    assert "Security selection" in out
    assert "Timing & interaction" in out
    # Sector breakdown renders both sectors.
    assert "Information Technology" in out
    assert "Financials" in out
    assert "SPY" in out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sector_weight(sector, weight, aum, count):
    from vertical_engines.wealth.attribution.models import SectorWeight
    return SectorWeight(
        sector=sector,
        issuer_category="EC",
        weight=weight,
        aum_usd=aum,
        holdings_count=count,
    )
