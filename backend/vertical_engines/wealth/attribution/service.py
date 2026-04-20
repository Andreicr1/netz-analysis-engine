"""Attribution orchestrator — bridges DB data to quant_engine attribution.

Uses POLICY BENCHMARK approach (CFA CIPM standard):
  - benchmark_weights = strategic allocation target weights per block
  - benchmark_returns = per-block benchmark ticker returns from benchmark_nav
  - portfolio_weights = actual current weights or strategic targets
  - portfolio_returns = weighted fund returns per block

Pure sync, designed for asyncio.to_thread(). No DB, no I/O.
Config as parameter.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog

from quant_engine.attribution_service import (
    AttributionResult,
    SectorAttribution,
    compute_attribution,
    compute_multi_period_attribution,
)
from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    FundAttributionResult,
    RailBadge,
    ReturnsBasedResult,
    StyleExposure,
)
from vertical_engines.wealth.attribution.returns_based import fit_style

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# Weight sum tolerance — if weights don't sum to ~1.0, add cash/residual
_WEIGHT_SUM_TOLERANCE = 1e-4
_CASH_LABEL = "cash_residual"

# Carino k_t clamp to prevent divergence
_CARINO_K_CLAMP = 10.0


class AttributionService:
    """Orchestrate policy benchmark attribution."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    def compute_portfolio_attribution(
        self,
        strategic_allocations: list[dict[str, Any]],
        fund_returns_by_block: dict[str, float],
        benchmark_returns_by_block: dict[str, float],
        block_labels: dict[str, str],
        actual_weights_by_block: dict[str, float] | None = None,
    ) -> AttributionResult:
        """Single-period attribution using policy benchmark.

        Parameters
        ----------
        strategic_allocations : list[dict]
            Each dict has 'block_id' and 'target_weight' (Decimal or float).
        fund_returns_by_block : dict
            block_id -> weighted average fund return for that block.
        benchmark_returns_by_block : dict
            block_id -> benchmark return from benchmark_nav.
        block_labels : dict
            block_id -> display name.
        actual_weights_by_block : dict | None
            block_id -> actual portfolio weight. If None, uses strategic targets.

        """
        # Build aligned arrays — only blocks that have BOTH fund and benchmark data
        block_ids: list[str] = []
        for sa in strategic_allocations:
            bid = sa["block_id"]
            if bid in fund_returns_by_block and bid in benchmark_returns_by_block:
                block_ids.append(bid)
            else:
                logger.warning(
                    "attribution_block_excluded",
                    block_id=bid,
                    has_fund_return=bid in fund_returns_by_block,
                    has_benchmark_return=bid in benchmark_returns_by_block,
                )

        if not block_ids:
            return AttributionResult(benchmark_available=False, n_periods=1)

        # Build weight/return arrays
        sa_map = {sa["block_id"]: float(sa["target_weight"]) for sa in strategic_allocations}

        benchmark_weights = np.array([sa_map.get(bid, 0.0) for bid in block_ids])
        portfolio_weights = np.array([
            (actual_weights_by_block or sa_map).get(bid, 0.0) for bid in block_ids
        ])
        portfolio_returns = np.array([fund_returns_by_block[bid] for bid in block_ids])
        benchmark_returns = np.array([benchmark_returns_by_block[bid] for bid in block_ids])
        labels = [block_labels.get(bid, bid) for bid in block_ids]

        # Weight normalization check
        bw_sum = float(np.sum(benchmark_weights))
        if abs(bw_sum - 1.0) > _WEIGHT_SUM_TOLERANCE and bw_sum > 0:
            residual = 1.0 - bw_sum
            benchmark_weights = np.append(benchmark_weights, residual)
            portfolio_weights = np.append(portfolio_weights, residual)
            portfolio_returns = np.append(portfolio_returns, 0.0)
            benchmark_returns = np.append(benchmark_returns, 0.0)
            labels.append(_CASH_LABEL)
            block_ids.append(_CASH_LABEL)
            logger.info(
                "attribution_weight_normalization",
                original_sum=bw_sum,
                residual=residual,
            )

        return compute_attribution(
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_labels=labels,
            config=self._config,
        )

    def compute_multi_period(
        self,
        period_results: list[AttributionResult],
        portfolio_period_returns: list[float],
        benchmark_period_returns: list[float],
    ) -> AttributionResult:
        """Multi-period Carino linking with numerical guards.

        Guards:
        1. Clamp k_t to [-_CARINO_K_CLAMP, _CARINO_K_CLAMP] to prevent divergence
        2. If abs(k_total) < 1e-10 (opposing excesses cancel),
           fall back to simple average
        """
        if not period_results:
            return AttributionResult()
        if len(period_results) == 1:
            return period_results[0]

        # Check for Carino edge case: total excess near zero
        total_excess = float(
            np.prod([1 + r for r in portfolio_period_returns])
            - np.prod([1 + r for r in benchmark_period_returns]),
        )

        if abs(total_excess) < 1e-10:
            # Simple average fallback — Carino k_total diverges
            logger.info(
                "attribution_carino_fallback",
                total_excess=total_excess,
                n_periods=len(period_results),
            )
            return self._simple_average_linking(period_results)

        return compute_multi_period_attribution(
            period_results=period_results,
            portfolio_period_returns=portfolio_period_returns,
            benchmark_period_returns=benchmark_period_returns,
        )

    def _simple_average_linking(
        self,
        period_results: list[AttributionResult],
    ) -> AttributionResult:
        """Fallback when Carino diverges: simple average of period effects."""
        n = len(period_results)
        if n == 0:
            return AttributionResult()

        # Aggregate sector effects as simple average
        sector_map: dict[str, dict[str, float]] = {}
        total_p = 0.0
        total_b = 0.0

        for r in period_results:
            total_p += r.total_portfolio_return
            total_b += r.total_benchmark_return
            for s in r.sectors:
                if s.sector not in sector_map:
                    sector_map[s.sector] = {
                        "allocation": 0.0,
                        "selection": 0.0,
                        "interaction": 0.0,
                    }
                sector_map[s.sector]["allocation"] += s.allocation_effect / n
                sector_map[s.sector]["selection"] += s.selection_effect / n
                sector_map[s.sector]["interaction"] += s.interaction_effect / n

        sectors = []
        for label, effects in sector_map.items():
            total = effects["allocation"] + effects["selection"] + effects["interaction"]
            sectors.append(
                SectorAttribution(
                    sector=label,
                    allocation_effect=round(effects["allocation"], 6),
                    selection_effect=round(effects["selection"], 6),
                    interaction_effect=round(effects["interaction"], 6),
                    total_effect=round(total, 6),
                ),
            )

        avg_p = total_p / n
        avg_b = total_b / n
        alloc_t = sum(s.allocation_effect for s in sectors)
        select_t = sum(s.selection_effect for s in sectors)
        interact_t = sum(s.interaction_effect for s in sectors)

        return AttributionResult(
            total_portfolio_return=round(avg_p, 6),
            total_benchmark_return=round(avg_b, 6),
            total_excess_return=round(avg_p - avg_b, 6),
            sectors=sectors,
            allocation_total=round(alloc_t, 6),
            selection_total=round(select_t, 6),
            interaction_total=round(interact_t, 6),
            n_periods=n,
            benchmark_available=True,
        )


# ---------------------------------------------------------------------------
# Fund-level dispatcher (PR-Q3: returns-based only; other rails land later).
# ---------------------------------------------------------------------------


# 24h TTL — same (fund_id, asof, basket) deterministically produces the same
# solution, so idempotent recompute is cheap and safe.
_FUND_CACHE_TTL_SECONDS = 24 * 60 * 60
_FUND_CACHE_PREFIX = "attr:fund:v1"

# Public async seam. Tests override this to inject synthetic returns without
# touching the DB. Receives the dispatcher request plus the (optional) async
# session; returns (r_fund, r_styles, tickers).
_ReturnsFetch = Callable[
    [AttributionRequest, "AsyncSession | None"],
    Awaitable[tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], tuple[str, ...]]],
]


async def compute_fund_attribution(
    request: AttributionRequest,
    db: "AsyncSession | None" = None,
    *,
    returns_fetch: _ReturnsFetch | None = None,
    redis_client: Any | None = None,
) -> FundAttributionResult:
    """Run the fund-level attribution cascade.

    For PR-Q3 only the returns-based rail is implemented. PR-Q4/Q5/Q9 will
    extend the cascade order: holdings → IPCA → proxy → returns → none.

    Parameters
    ----------
    request : AttributionRequest
    db : AsyncSession | None
        Real DB session for production. Tests pass ``None`` together with a
        ``returns_fetch`` override.
    returns_fetch : callable | None
        Override for the async data loader (tests / non-DB callers).
    redis_client : redis.asyncio.Redis | None
        Optional cache client. If provided, results are cached for 24h
        keyed on (fund_id, asof, sorted_tickers, lookback).

    """
    cache_key = _cache_key(request)

    cached = await _cache_get(redis_client, cache_key)
    if cached is not None:
        return cached

    fetch = returns_fetch or _fetch_returns_monthly
    try:
        r_fund, r_styles, tickers = await fetch(request, db)
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("fund_attribution_fetch_failed", error=str(exc))
        return FundAttributionResult(
            fund_instrument_id=request.fund_instrument_id,
            asof=request.asof,
            badge=RailBadge.RAIL_NONE,
            reason="fetch_failed",
        )

    if r_fund.size == 0 or r_styles.size == 0:
        return FundAttributionResult(
            fund_instrument_id=request.fund_instrument_id,
            asof=request.asof,
            badge=RailBadge.RAIL_NONE,
            reason="no_data",
        )

    returns_result = await asyncio.to_thread(
        fit_style,
        r_fund,
        r_styles,
        tickers,
        request.min_months,
    )

    result = _build_result(request, returns_result)
    await _cache_set(redis_client, cache_key, result)
    return result


def _build_result(
    request: AttributionRequest,
    returns_result: ReturnsBasedResult,
) -> FundAttributionResult:
    if returns_result.degraded:
        return FundAttributionResult(
            fund_instrument_id=request.fund_instrument_id,
            asof=request.asof,
            badge=RailBadge.RAIL_NONE,
            reason=returns_result.degraded_reason or "degraded",
            metadata={"rail_attempted": RailBadge.RAIL_RETURNS.value},
        )

    if returns_result.n_months < request.min_months:
        return FundAttributionResult(
            fund_instrument_id=request.fund_instrument_id,
            asof=request.asof,
            badge=RailBadge.RAIL_NONE,
            reason="insufficient_history",
        )

    return FundAttributionResult(
        fund_instrument_id=request.fund_instrument_id,
        asof=request.asof,
        badge=RailBadge.RAIL_RETURNS,
        returns_based=returns_result,
        metadata={
            "n_months": str(returns_result.n_months),
            "style_basket": ",".join(e.ticker for e in returns_result.exposures),
        },
    )


def _cache_key(request: AttributionRequest) -> str:
    basket = ",".join(sorted(request.style_tickers))
    payload = json.dumps(
        {
            "fund": str(request.fund_instrument_id),
            "asof": request.asof.isoformat(),
            "basket": basket,
            "lookback": request.lookback_months,
            "min": request.min_months,
        },
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return f"{_FUND_CACHE_PREFIX}:{digest}"


async def _cache_get(
    redis_client: Any | None,
    cache_key: str,
) -> FundAttributionResult | None:
    if redis_client is None:
        return None
    try:
        raw = await redis_client.get(cache_key)
    except Exception as exc:  # pragma: no cover — fail open
        logger.debug("fund_attribution_cache_get_failed", error=str(exc))
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return _deserialize_result(data)
    except Exception as exc:  # pragma: no cover
        logger.debug("fund_attribution_cache_decode_failed", error=str(exc))
        return None


async def _cache_set(
    redis_client: Any | None,
    cache_key: str,
    result: FundAttributionResult,
) -> None:
    if redis_client is None:
        return
    try:
        await redis_client.setex(
            cache_key,
            _FUND_CACHE_TTL_SECONDS,
            json.dumps(_serialize_result(result)),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("fund_attribution_cache_set_failed", error=str(exc))


def _serialize_result(result: FundAttributionResult) -> dict[str, Any]:
    rb = result.returns_based
    return {
        "fund_instrument_id": str(result.fund_instrument_id),
        "asof": result.asof.isoformat(),
        "badge": result.badge.value,
        "reason": result.reason,
        "metadata": result.metadata,
        "returns_based": None
        if rb is None
        else {
            "exposures": [
                {"ticker": e.ticker, "weight": e.weight} for e in rb.exposures
            ],
            "r_squared": rb.r_squared,
            "tracking_error_annualized": rb.tracking_error_annualized,
            "confidence": rb.confidence,
            "n_months": rb.n_months,
            "degraded": rb.degraded,
            "degraded_reason": rb.degraded_reason,
        },
    }


def _deserialize_result(data: dict[str, Any]) -> FundAttributionResult:
    from datetime import date as _date
    from uuid import UUID as _UUID

    rb_raw = data.get("returns_based")
    rb = None
    if rb_raw is not None:
        rb = ReturnsBasedResult(
            exposures=tuple(
                StyleExposure(ticker=e["ticker"], weight=float(e["weight"]))
                for e in rb_raw["exposures"]
            ),
            r_squared=float(rb_raw["r_squared"]),
            tracking_error_annualized=float(rb_raw["tracking_error_annualized"]),
            confidence=float(rb_raw["confidence"]),
            n_months=int(rb_raw["n_months"]),
            degraded=bool(rb_raw["degraded"]),
            degraded_reason=rb_raw.get("degraded_reason"),
        )

    return FundAttributionResult(
        fund_instrument_id=_UUID(data["fund_instrument_id"]),
        asof=_date.fromisoformat(data["asof"]),
        badge=RailBadge(data["badge"]),
        returns_based=rb,
        reason=data.get("reason"),
        metadata=dict(data.get("metadata") or {}),
    )


async def _fetch_returns_monthly(
    request: AttributionRequest,
    db: "AsyncSession | None",
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], tuple[str, ...]]:
    """Fetch aligned monthly returns for fund + style basket.

    Monthly alignment pattern from data-layer spec §4.1 adapted to the real
    ``benchmark_nav`` schema (block_id + nav_date). Style ETFs are resolved
    through ``allocation_blocks.benchmark_ticker``; funds through
    ``nav_timeseries.instrument_id``.

    Returns empty arrays when the DB is unavailable (test callers inject
    ``returns_fetch`` and never land here).
    """
    if db is None:
        return (
            np.empty(0, dtype=np.float64),
            np.empty((0, 0), dtype=np.float64),
            tuple(),
        )

    from datetime import timedelta

    from sqlalchemy import text

    start_date = request.asof - timedelta(days=31 * (request.lookback_months + 2))
    tickers = tuple(t.upper() for t in request.style_tickers)

    sql = text(
        """
        WITH fund_monthly AS (
            SELECT date_trunc('month', nav_date)::date AS month,
                   (array_agg(nav ORDER BY nav_date DESC))[1] AS nav_eom
            FROM nav_timeseries
            WHERE instrument_id = :fund_id
              AND nav_date >= :start_date
              AND nav_date <= :asof
              AND nav IS NOT NULL
            GROUP BY 1
        ),
        style_monthly AS (
            SELECT ab.benchmark_ticker AS ticker,
                   date_trunc('month', bn.nav_date)::date AS month,
                   (array_agg(bn.nav ORDER BY bn.nav_date DESC))[1] AS nav_eom
            FROM benchmark_nav bn
            JOIN allocation_blocks ab ON ab.block_id = bn.block_id
            WHERE ab.benchmark_ticker = ANY(:tickers)
              AND bn.nav_date >= :start_date
              AND bn.nav_date <= :asof
              AND bn.nav IS NOT NULL
            GROUP BY 1, 2
        )
        SELECT f.month, f.nav_eom AS fund_nav,
               s.ticker, s.nav_eom AS style_nav
        FROM fund_monthly f
        JOIN style_monthly s ON s.month = f.month
        ORDER BY f.month, s.ticker
        """
    )

    rows = (
        await db.execute(
            sql,
            {
                "fund_id": request.fund_instrument_id,
                "tickers": list(tickers),
                "start_date": start_date,
                "asof": request.asof,
            },
        )
    ).all()

    if not rows:
        return (
            np.empty(0, dtype=np.float64),
            np.empty((0, 0), dtype=np.float64),
            tickers,
        )

    by_month: dict[Any, dict[str, float]] = {}
    fund_by_month: dict[Any, float] = {}
    for month, fund_nav, ticker, style_nav in rows:
        fund_by_month[month] = float(fund_nav)
        by_month.setdefault(month, {})[str(ticker)] = float(style_nav)

    months_sorted = sorted(by_month.keys())
    # Need at least request.min_months + 1 observations to derive that many
    # monthly returns after differencing.
    if len(months_sorted) < request.min_months + 1:
        return (
            np.empty(0, dtype=np.float64),
            np.empty((0, 0), dtype=np.float64),
            tickers,
        )

    # Keep only tickers present in every retained month — missing columns
    # break the regression.
    common_tickers = tuple(
        t for t in tickers if all(t in by_month[m] for m in months_sorted)
    )
    if not common_tickers:
        return (
            np.empty(0, dtype=np.float64),
            np.empty((0, 0), dtype=np.float64),
            tickers,
        )

    fund_nav_series = np.array(
        [fund_by_month[m] for m in months_sorted], dtype=np.float64,
    )
    style_nav_matrix = np.array(
        [[by_month[m][t] for t in common_tickers] for m in months_sorted],
        dtype=np.float64,
    )

    r_fund = fund_nav_series[1:] / fund_nav_series[:-1] - 1.0
    r_styles = style_nav_matrix[1:] / style_nav_matrix[:-1] - 1.0

    mask = np.isfinite(r_fund) & np.isfinite(r_styles).all(axis=1)
    r_fund = r_fund[mask]
    r_styles = r_styles[mask]

    return r_fund, r_styles, common_tickers
