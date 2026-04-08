"""Discovery Analysis page routes (Phase 5).

Standalone analytics endpoints consumed by the Analysis page (a separate
deep-dive route from the Col3 fact sheet). DB-only hot path, Redis
fail-open cache, RLS via ``get_db_with_rls``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs.tracker import get_redis_pool
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.queries.analysis_holdings import (
    fetch_reverse_lookup,
    fetch_style_drift,
    fetch_top_holdings,
)
from app.domains.wealth.queries.analysis_peer import (
    fetch_institutional_reveal,
    fetch_peer_comparison,
)
from app.domains.wealth.queries.analysis_returns import Window, fetch_returns_risk
from app.domains.wealth.queries.fund_resolver import resolve_fund

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wealth/discovery", tags=["wealth-discovery-analysis"])

RETURNS_TTL = 60 * 60  # 1 hour
HOLDINGS_TTL = 60 * 60  # 1 hour
PEER_TTL = 60 * 60  # 1 hour


@router.get("/funds/{external_id}/analysis/returns-risk")
async def analysis_returns_risk(
    external_id: str,
    window: Window = Query("3y"),
    actor: Actor = Depends(get_actor),  # noqa: ARG001 — auth gate
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    cache_key = f"discovery:analysis:returns:{external_id}:{window}"

    redis: aioredis.Redis | None
    try:
        redis = aioredis.Redis(connection_pool=get_redis_pool())
        cached = await redis.get(cache_key)
        if cached is not None:
            raw = cached.decode() if isinstance(cached, bytes) else str(cached)
            return dict(json.loads(raw))
    except Exception as exc:  # noqa: BLE001 — fail-open on Redis outage
        logger.debug("analysis cache GET fail-open %s: %s", cache_key, exc)
        redis = None

    fund = await resolve_fund(db, external_id)
    payload: dict[str, Any]
    if not fund.get("instrument_id"):
        payload = {
            "window": window,
            "nav_series": [],
            "monthly_returns": [],
            "rolling_metrics": [],
            "return_distribution": {"bins": [], "counts": []},
            "risk_metrics": None,
            "disclosure": {"has_nav": False},
            "fund": fund,
        }
    else:
        payload = await fetch_returns_risk(db, str(fund["instrument_id"]), window)
        payload["fund"] = fund

    if redis is not None:
        try:
            await redis.setex(
                cache_key,
                RETURNS_TTL,
                json.dumps(payload, default=str),
            )
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.debug("analysis cache SET fail-open %s: %s", cache_key, exc)
        finally:
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass

    return payload


async def _cache_get(cache_key: str) -> tuple[aioredis.Redis | None, dict[str, Any] | None]:
    try:
        redis = aioredis.Redis(connection_pool=get_redis_pool())
        cached = await redis.get(cache_key)
        if cached is not None:
            raw = cached.decode() if isinstance(cached, bytes) else str(cached)
            return redis, dict(json.loads(raw))
        return redis, None
    except Exception as exc:  # noqa: BLE001 — fail-open on Redis outage
        logger.debug("analysis cache GET fail-open %s: %s", cache_key, exc)
        return None, None


async def _cache_set(
    redis: aioredis.Redis | None,
    cache_key: str,
    payload: dict[str, Any],
    ttl: int,
) -> None:
    if redis is None:
        return
    try:
        await redis.setex(cache_key, ttl, json.dumps(payload, default=str))
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.debug("analysis cache SET fail-open %s: %s", cache_key, exc)
    finally:
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass


@router.get("/funds/{external_id}/analysis/holdings/top")
async def analysis_holdings_top(
    external_id: str,
    actor: Actor = Depends(get_actor),  # noqa: ARG001 — auth gate
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    cache_key = f"discovery:analysis:holdings-top:{external_id}"
    redis, cached = await _cache_get(cache_key)
    if cached is not None:
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass
        return cached

    fund = await resolve_fund(db, external_id)
    cik = fund.get("cik")
    if not cik:
        payload: dict[str, Any] = {
            "top_holdings": [],
            "sector_breakdown": [],
            "as_of": None,
            "disclosure": {"has_holdings": False},
            "fund": fund,
        }
    else:
        data = await fetch_top_holdings(db, str(cik))
        payload = {
            **data,
            "disclosure": {"has_holdings": len(data["top_holdings"]) > 0},
            "fund": fund,
        }

    await _cache_set(redis, cache_key, payload, HOLDINGS_TTL)
    return payload


@router.get("/funds/{external_id}/analysis/holdings/style-drift")
async def analysis_holdings_style_drift(
    external_id: str,
    quarters: int = Query(8, ge=1, le=20),
    actor: Actor = Depends(get_actor),  # noqa: ARG001 — auth gate
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    cache_key = f"discovery:analysis:style-drift:{external_id}:{quarters}"
    redis, cached = await _cache_get(cache_key)
    if cached is not None:
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass
        return cached

    fund = await resolve_fund(db, external_id)
    cik = fund.get("cik")
    if not cik:
        payload: dict[str, Any] = {
            "snapshots": [],
            "disclosure": {"has_holdings": False},
            "fund": fund,
        }
    else:
        data = await fetch_style_drift(db, str(cik), quarters=quarters)
        payload = {
            **data,
            "disclosure": {"has_holdings": len(data["snapshots"]) > 0},
            "fund": fund,
        }

    await _cache_set(redis, cache_key, payload, HOLDINGS_TTL)
    return payload


@router.get("/holdings/{cusip}/reverse-lookup")
async def analysis_reverse_lookup(
    cusip: str,
    limit: int = Query(30, ge=5, le=100),
    actor: Actor = Depends(get_actor),  # noqa: ARG001 — auth gate
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    cache_key = f"discovery:analysis:reverse-lookup:{cusip}:{limit}"
    redis, cached = await _cache_get(cache_key)
    if cached is not None:
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass
        return cached

    payload = await fetch_reverse_lookup(db, cusip, limit=limit)
    await _cache_set(redis, cache_key, payload, HOLDINGS_TTL)
    return payload


@router.get("/funds/{external_id}/analysis/peers")
async def analysis_peers(
    external_id: str,
    limit: int = Query(40, ge=5, le=100),
    actor: Actor = Depends(get_actor),  # noqa: ARG001 — auth gate
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Peer comparison — funds with the same ``strategy_label`` + risk metrics."""
    cache_key = f"discovery:analysis:peers:{external_id}:{limit}"
    redis, cached = await _cache_get(cache_key)
    if cached is not None:
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass
        return cached

    # Resolve the subject's strategy_label from mv_unified_funds
    from sqlalchemy import text as _text

    strat_row = (
        await db.execute(
            _text(
                "SELECT strategy_label FROM mv_unified_funds WHERE external_id = :id",
            ),
            {"id": external_id},
        )
    ).mappings().first()
    strategy = strat_row["strategy_label"] if strat_row else None

    data = await fetch_peer_comparison(
        db,
        subject_external_id=external_id,
        strategy=strategy,
        limit=limit,
    )
    payload: dict[str, Any] = {
        **data,
        "strategy_label": strategy,
        "external_id": external_id,
    }

    await _cache_set(redis, cache_key, payload, PEER_TTL)
    return payload


@router.get("/funds/{external_id}/analysis/institutional-reveal")
async def analysis_institutional_reveal(
    external_id: str,
    categories: str | None = Query(None),
    actor: Actor = Depends(get_actor),  # noqa: ARG001 — auth gate
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """Cross-reference fund holdings against curated institutions (endowments etc)."""
    category_filter: list[str] | None = None
    if categories:
        category_filter = [c.strip() for c in categories.split(",") if c.strip()]
        if not category_filter:
            category_filter = None

    cache_key = (
        "discovery:analysis:inst-reveal:"
        f"{external_id}:{','.join(sorted(category_filter)) if category_filter else 'all'}"
    )
    redis, cached = await _cache_get(cache_key)
    if cached is not None:
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass
        return cached

    fund = await resolve_fund(db, external_id)
    cik = fund.get("cik")
    if not cik:
        payload: dict[str, Any] = {
            "institutions": [],
            "overlap_matrix": {},
            "holdings": [],
            "disclosure": {"has_holdings": False},
            "fund": fund,
        }
    else:
        data = await fetch_institutional_reveal(
            db,
            str(cik),
            category_filter=category_filter,
        )
        payload = {
            **data,
            "disclosure": {"has_holdings": len(data["holdings"]) > 0},
            "fund": fund,
        }

    await _cache_set(redis, cache_key, payload, PEER_TTL)
    return payload
