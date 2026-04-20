"""Benchmark proxy rail — PR-Q5 (G3 Fase 3).

Resolves a fund's free-text ``primary_benchmark`` string to a canonical
ETF (via ``benchmark_etf_canonical_map``), then runs Brinson-Fachler
attribution using that ETF's N-PORT holdings as the benchmark side.

Three-level resolution cascade (data-layer spec §1.4):
    1. Exact alias match (`ANY(benchmark_name_aliases)`)
    2. Trigram fuzzy match (`similarity(...) > 0.7`)
    3. Asset-class keyword fallback (Python classifier → default proxy)

The rail degrades (not error) when the benchmark is null/unmatched, the
proxy ETF has no N-PORT holdings (BDC/MMF edge), or sector returns are
unavailable. The dispatcher falls through to the returns-based rail.

Not wired to production sector-returns yet — the `sector_returns_fetcher`
seam is injected by tests; the default returns an empty dict so the rail
degrades with ``sector_returns_unavailable`` until a later PR pipes in
per-sector period returns (Tiingo aggregate by ticker).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text

from vertical_engines.wealth.attribution.brinson_fachler import brinson_fachler
from vertical_engines.wealth.attribution.holdings_based import (
    fetch_sector_weights,
    latest_period_for_cik,
    resolve_fund_cik,
)
from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    BenchmarkProxyResult,
    BenchmarkResolution,
    BrinsonResult,
    SectorWeight,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# Per data-layer spec §1.4. 0.7 is the canonical threshold; tests lock
# the boundary behaviour.
_FUZZY_THRESHOLD = 0.7

# Confidence tiers for the rail output. Tuned to keep HOLDINGS > PROXY
# > RETURNS ordering intuitive to operators.
_CONFIDENCE_EXACT = 0.60
_CONFIDENCE_FUZZY = 0.45
_CONFIDENCE_CLASS_FALLBACK = 0.30


# Asset class keyword classifier (Level 3 fallback). Order matters: the
# first matching bucket wins, so more specific patterns come first. The
# default proxy per class ships in the 0165 seed.
_ASSET_CLASS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("fi_us_treasury", re.compile(r"\b(u\.?s\.?\s+)?treasury|govt?\b", re.I)),
    ("fi_us_hy", re.compile(r"high\s*yield|junk\s+bond", re.I)),
    ("fi_us_ig", re.compile(r"investment\s*grade|corporate\s+bond|us\s+corp", re.I)),
    ("fi_us_muni", re.compile(r"muni(cipal)?", re.I)),
    ("fi_us_agg", re.compile(r"aggregate|agg\b|bond\s+index", re.I)),
    ("fi_intl", re.compile(r"global\s+agg|international\s+bond", re.I)),
    ("equity_em", re.compile(r"emerg(ing)?\s+markets?|em\s+equity", re.I)),
    ("equity_intl_dev", re.compile(r"eafe|acwi|developed\s+markets?|msci\s+world", re.I)),
    ("equity_us_small", re.compile(r"small\s*cap|russell\s*2000", re.I)),
    ("equity_us_mid", re.compile(r"mid\s*cap", re.I)),
    ("equity_us_large", re.compile(r"large\s*cap|s&p\s*500|blend\s+index|russell\s*1000", re.I)),
    ("reits", re.compile(r"reit|real\s+estate", re.I)),
    ("commodities", re.compile(r"commodit|bcom", re.I)),
]


# Type seams — tests inject stubs without hitting the DB.
SectorReturnsFetcher = Callable[
    ["AsyncSession | None", str, date],
    Awaitable[dict[str, float]],
]


def classify_asset_class_keywords(name: str) -> str | None:
    """Bucket a free-text benchmark string into a coarse asset class.

    Returns None when no pattern matches. Designed to be cheap and
    opinionated — misclassification is better than degrading the whole
    rail, since the worst-case default proxy (SPY) is still a reasonable
    anchor for diversified US funds.
    """
    if not name or not name.strip():
        return None
    for asset_class, pattern in _ASSET_CLASS_PATTERNS:
        if pattern.search(name):
            return asset_class
    return None


async def resolve_benchmark(
    primary_benchmark: str | None,
    db: "AsyncSession",
) -> BenchmarkResolution:
    """Resolve ``primary_benchmark`` to a canonical proxy ETF row."""
    if primary_benchmark is None or not primary_benchmark.strip():
        return BenchmarkResolution(match_type="null")

    name = primary_benchmark.strip()

    # Level 1 — exact alias. Case-sensitive match by design: the seed
    # captures real aliases from sec_registered_funds verbatim.
    row = (await db.execute(
        text("""
            SELECT proxy_etf_cik, proxy_etf_series_id, proxy_etf_ticker, asset_class
            FROM benchmark_etf_canonical_map
            WHERE :name = ANY(benchmark_name_aliases)
              AND CURRENT_DATE BETWEEN effective_from AND effective_to
            LIMIT 1
        """),
        {"name": name},
    )).mappings().first()
    if row:
        return BenchmarkResolution(
            match_type="exact",
            proxy_etf_ticker=row["proxy_etf_ticker"],
            proxy_etf_cik=row["proxy_etf_cik"],
            proxy_etf_series_id=row["proxy_etf_series_id"],
            asset_class=str(row["asset_class"]),
        )

    # Level 2 — trigram fuzzy. Pick the single best similarity >= 0.7.
    row = (await db.execute(
        text("""
            SELECT proxy_etf_cik, proxy_etf_series_id, proxy_etf_ticker,
                   asset_class,
                   similarity(benchmark_name_canonical, :name) AS sim
            FROM benchmark_etf_canonical_map
            WHERE benchmark_name_canonical % :name
              AND CURRENT_DATE BETWEEN effective_from AND effective_to
            ORDER BY similarity(benchmark_name_canonical, :name) DESC
            LIMIT 1
        """),
        {"name": name},
    )).mappings().first()
    if row and float(row["sim"] or 0.0) > _FUZZY_THRESHOLD:
        return BenchmarkResolution(
            match_type="fuzzy",
            proxy_etf_ticker=row["proxy_etf_ticker"],
            proxy_etf_cik=row["proxy_etf_cik"],
            proxy_etf_series_id=row["proxy_etf_series_id"],
            asset_class=str(row["asset_class"]),
            similarity=float(row["sim"]),
        )

    # Level 3 — asset-class keyword classifier → default proxy row.
    asset_class = classify_asset_class_keywords(name)
    if asset_class:
        fallback = await _resolve_by_asset_class(asset_class, db)
        if fallback is not None:
            return fallback

    return BenchmarkResolution(match_type="unmatched")


async def _resolve_by_asset_class(
    asset_class: str,
    db: "AsyncSession",
) -> BenchmarkResolution | None:
    row = (await db.execute(
        text("""
            SELECT proxy_etf_cik, proxy_etf_series_id, proxy_etf_ticker, asset_class
            FROM benchmark_etf_canonical_map
            WHERE asset_class = CAST(:ac AS benchmark_asset_class)
              AND effective_to = '9999-12-31'
            ORDER BY fit_quality_score DESC, id ASC
            LIMIT 1
        """),
        {"ac": asset_class},
    )).mappings().first()
    if not row:
        return None
    return BenchmarkResolution(
        match_type="class_fallback",
        proxy_etf_ticker=row["proxy_etf_ticker"],
        proxy_etf_cik=row["proxy_etf_cik"],
        proxy_etf_series_id=row["proxy_etf_series_id"],
        asset_class=str(row["asset_class"]),
    )


async def _fund_primary_benchmark(
    db: "AsyncSession", cik: str,
) -> str | None:
    row = (await db.execute(
        text("""
            SELECT primary_benchmark
            FROM sec_registered_funds
            WHERE cik = :cik
            LIMIT 1
        """),
        {"cik": cik},
    )).first()
    if row is None:
        return None
    val = row[0]
    if val is None:
        return None
    s = str(val).strip()
    return s or None


async def _default_sector_returns(
    _db: "AsyncSession | None", _cik: str, _period: date,
) -> dict[str, float]:
    """Default fetcher returns no sector returns.

    Per-sector periodic returns are not yet materialised; the rail marks
    itself degraded and the dispatcher falls through. Tests inject a real
    fetcher to exercise the full Brinson math.
    """
    return {}


def _weights_by_sector(sectors: list[SectorWeight]) -> dict[str, float]:
    """Aggregate sector weights across issuer_category splits."""
    out: dict[str, float] = {}
    for s in sectors:
        out[s.sector] = out.get(s.sector, 0.0) + float(s.weight)
    return out


async def run_proxy_rail(
    request: AttributionRequest,
    db: "AsyncSession",
    *,
    max_filing_age_months: int = 9,
    cik_resolver: Any = None,
    benchmark_fetcher: Callable[
        ["AsyncSession", str], Awaitable[str | None],
    ] | None = None,
    sector_returns_fetcher: SectorReturnsFetcher | None = None,
) -> BenchmarkProxyResult | None:
    """Execute the proxy rail. Returns None when the fund lacks a CIK.

    ``cik_resolver``, ``benchmark_fetcher``, and ``sector_returns_fetcher``
    are test seams. Production leaves them as the module defaults.
    """
    resolver = cik_resolver or resolve_fund_cik
    fund_cik = await resolver(db, request.fund_instrument_id)
    if not fund_cik:
        # No SEC CIK → private / UCITS. Proxy rail cannot read N-PORT
        # weights on the fund side. Fall through to returns rail.
        return None

    bench_fetcher = benchmark_fetcher or _fund_primary_benchmark
    primary_benchmark = await bench_fetcher(db, fund_cik)

    resolution = await resolve_benchmark(primary_benchmark, db)

    if resolution.match_type in {"null", "unmatched"} or not resolution.proxy_etf_cik:
        # No proxy CIK to fetch holdings for — cannot run Brinson on the
        # benchmark side. Degraded so dispatcher continues.
        return BenchmarkProxyResult(
            resolution=resolution,
            brinson=_empty_brinson(),
            confidence=0.0,
            degraded=True,
            degraded_reason="benchmark_unresolved",
        )

    not_before = request.asof - timedelta(days=int(30.4375 * max_filing_age_months))

    fund_period = await latest_period_for_cik(db, fund_cik, not_before=not_before)
    proxy_period = await latest_period_for_cik(
        db, resolution.proxy_etf_cik, not_before=not_before,
    )

    if fund_period is None or proxy_period is None:
        return BenchmarkProxyResult(
            resolution=resolution,
            brinson=_empty_brinson(),
            confidence=0.0,
            period_of_report=fund_period,
            degraded=True,
            degraded_reason="stale_filing",
        )

    fund_sectors, _ = await fetch_sector_weights(db, fund_cik, fund_period)
    proxy_sectors, _ = await fetch_sector_weights(
        db, resolution.proxy_etf_cik, proxy_period,
    )

    if not proxy_sectors:
        return BenchmarkProxyResult(
            resolution=resolution,
            brinson=_empty_brinson(),
            confidence=0.0,
            period_of_report=fund_period,
            degraded=True,
            degraded_reason="proxy_no_holdings",
        )

    fund_weights = _weights_by_sector(fund_sectors)
    bench_weights = _weights_by_sector(proxy_sectors)

    returns_fetcher = sector_returns_fetcher or _default_sector_returns
    try:
        fund_returns = await returns_fetcher(db, fund_cik, fund_period)
        bench_returns = await returns_fetcher(
            db, resolution.proxy_etf_cik, proxy_period,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("proxy_rail_returns_fetch_failed", error=str(exc))
        fund_returns, bench_returns = {}, {}

    brinson = brinson_fachler(
        fund_weights=fund_weights,
        fund_returns=fund_returns,
        bench_weights=bench_weights,
        bench_returns=bench_returns,
    )

    if not fund_returns or not bench_returns:
        return BenchmarkProxyResult(
            resolution=resolution,
            brinson=brinson,
            confidence=0.0,
            period_of_report=fund_period,
            degraded=True,
            degraded_reason="sector_returns_unavailable",
        )

    confidence = {
        "exact": _CONFIDENCE_EXACT,
        "fuzzy": _CONFIDENCE_FUZZY,
        "class_fallback": _CONFIDENCE_CLASS_FALLBACK,
    }.get(resolution.match_type, 0.0)

    return BenchmarkProxyResult(
        resolution=resolution,
        brinson=brinson,
        confidence=confidence,
        period_of_report=fund_period,
        degraded=False,
    )


def _empty_brinson() -> "BrinsonResult":
    return BrinsonResult(
        allocation_effect=0.0,
        selection_effect=0.0,
        interaction_effect=0.0,
        total_active_return=0.0,
        by_sector=(),
    )
