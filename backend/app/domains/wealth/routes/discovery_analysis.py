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
from app.domains.wealth.queries.analysis_returns import Window, fetch_returns_risk
from app.domains.wealth.queries.fund_resolver import resolve_fund

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wealth/discovery", tags=["wealth-discovery-analysis"])

RETURNS_TTL = 60 * 60  # 1 hour


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
