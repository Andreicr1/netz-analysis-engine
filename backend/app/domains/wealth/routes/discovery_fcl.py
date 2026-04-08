"""Discovery FCL (Fund-Centric Layout) routes.

Three-column Discovery page backend:

- ``POST /wealth/discovery/managers`` — keyset paginated manager list.
- ``POST /wealth/discovery/managers/{id}/funds`` — funds for a manager.
- ``GET  /wealth/discovery/funds/{external_id}/fact-sheet`` — aggregated
  Col3 fact sheet payload.
- ``GET  /wealth/discovery/funds/{external_id}/dd-report/snapshot`` —
  latest DD report chapters (one-shot JSON).
- ``GET  /wealth/discovery/funds/{external_id}/dd-report/stream`` — SSE
  stream bridging Redis pub/sub updates for live DD generation.

DB-only hot path — no external API calls. RLS via
``get_db_with_rls``; responses cached in Redis (route-level keyspaces
prefixed with ``discovery:*``) behind an in-process
``SingleFlightLock`` so concurrent requests coalesce on a single DB
round-trip.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from app.core.db.audit import write_audit_event  # noqa: F401 — reserved for future audits
from app.core.jobs.tracker import get_redis_pool
from app.core.runtime.single_flight import SingleFlightLock
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.queries.discovery_keyset import (
    build_funds_query,
    build_managers_query,
)
from app.domains.wealth.queries.fund_resolver import resolve_fund
from app.domains.wealth.schemas.discovery import (
    DiscoveryFilters,
    FundCursor,
    FundRow,
    FundsListResponse,
    ManagerCursor,
    ManagerRow,
    ManagersListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wealth/discovery", tags=["wealth-discovery"])

MANAGERS_TTL = 5 * 60  # 5 minutes
FUNDS_TTL = 10 * 60  # 10 minutes
FACTSHEET_TTL = 60 * 60  # 1 hour

# In-process single-flight + TTL cache. Coalesces concurrent requests
# hitting the same cache key on one worker process so the DB sees a
# single query per (key, window). Redis is the cross-process cache.
_managers_sf: SingleFlightLock[str, str] = SingleFlightLock()
_funds_sf: SingleFlightLock[str, str] = SingleFlightLock()
_factsheet_sf: SingleFlightLock[str, str] = SingleFlightLock()


class ManagersListRequest(BaseModel):
    filters: DiscoveryFilters = DiscoveryFilters()
    cursor: ManagerCursor | None = None
    limit: int = 50


class FundsListRequest(BaseModel):
    cursor: FundCursor | None = None
    limit: int = 50


def _cache_key(namespace: str, org_id: str, **kwargs: Any) -> str:
    payload = json.dumps(kwargs, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"discovery:{namespace}:{org_id}:{digest}"


def _redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=get_redis_pool())


async def _cache_get(key: str) -> str | None:
    r = _redis()
    try:
        raw = await r.get(key)
    except Exception as exc:  # noqa: BLE001 — fail-open on Redis outage
        logger.debug("discovery cache GET fail-open %s: %s", key, exc)
        return None
    finally:
        await r.aclose()
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


async def _cache_set(key: str, value: str, ttl: int) -> None:
    r = _redis()
    try:
        await r.setex(key, ttl, value)
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.debug("discovery cache SET fail-open %s: %s", key, exc)
    finally:
        await r.aclose()


# ── Col1: managers list ─────────────────────────────────────────────


@router.post("/managers", response_model=ManagersListResponse)
async def list_managers(
    req: ManagersListRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ManagersListResponse:
    org_id = str(actor.organization_id or uuid.UUID(int=0))
    key = _cache_key(
        "managers",
        org_id,
        filters=req.filters.model_dump(),
        cursor=req.cursor.model_dump() if req.cursor else None,
        limit=req.limit,
    )

    cached = await _cache_get(key)
    if cached is not None:
        return ManagersListResponse.model_validate_json(cached)

    async def _fetch() -> str:
        # Re-check cache under the lock to avoid a thundering herd
        # stampeding the DB when the first flight's result hasn't
        # propagated to Redis yet.
        inner = await _cache_get(key)
        if inner is not None:
            return inner

        sql, params = build_managers_query(req.filters, req.cursor, req.limit + 1)
        result = await db.execute(text(sql), params)
        raw_rows = result.mappings().all()

        has_more = len(raw_rows) > req.limit
        rows_data = raw_rows[: req.limit]
        rows = [ManagerRow.model_validate(dict(r)) for r in rows_data]

        next_cursor: ManagerCursor | None = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = ManagerCursor(aum=last.aum_total, crd=last.manager_id)

        response = ManagersListResponse(rows=rows, next_cursor=next_cursor)
        serialized = response.model_dump_json()
        await _cache_set(key, serialized, MANAGERS_TTL)
        return serialized

    serialized = await _managers_sf.run(key, _fetch, ttl_s=float(MANAGERS_TTL))
    return ManagersListResponse.model_validate_json(serialized)


# ── Col2: funds by manager ──────────────────────────────────────────


@router.post("/managers/{manager_id}/funds", response_model=FundsListResponse)
async def list_funds_by_manager(
    manager_id: str,
    req: FundsListRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> FundsListResponse:
    org_id = str(actor.organization_id or uuid.UUID(int=0))
    key = _cache_key(
        "funds",
        org_id,
        manager_id=manager_id,
        cursor=req.cursor.model_dump() if req.cursor else None,
        limit=req.limit,
    )

    cached = await _cache_get(key)
    if cached is not None:
        return FundsListResponse.model_validate_json(cached)

    async def _fetch() -> str:
        inner = await _cache_get(key)
        if inner is not None:
            return inner

        sql, params = build_funds_query(manager_id, req.cursor, req.limit + 1)
        result = await db.execute(text(sql), params)
        raw_rows = result.mappings().all()

        if not raw_rows:
            raise HTTPException(
                status_code=404,
                detail=f"manager {manager_id} has no funds",
            )

        has_more = len(raw_rows) > req.limit
        rows_data = raw_rows[: req.limit]
        rows = [FundRow.model_validate(dict(r)) for r in rows_data]

        next_cursor: FundCursor | None = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = FundCursor(aum=last.aum_usd, external_id=last.external_id)

        summary_sql = """
            SELECT
                f.manager_id,
                COALESCE(MAX(f.manager_name), sm.firm_name, f.manager_id) AS manager_name,
                sm.firm_name,
                sm.cik,
                sm.aum_total,
                COUNT(DISTINCT COALESCE(f.series_id, f.external_id)) AS fund_count,
                ARRAY_AGG(DISTINCT f.fund_type) FILTER (WHERE f.fund_type IS NOT NULL) AS fund_types,
                MODE() WITHIN GROUP (ORDER BY f.strategy_label) AS strategy_label_top
            FROM mv_unified_funds f
            LEFT JOIN sec_managers sm ON f.manager_id = sm.crd_number
            WHERE f.manager_id = :manager_id
            GROUP BY f.manager_id, sm.firm_name, sm.cik, sm.aum_total
        """
        summary_row = (
            await db.execute(text(summary_sql), {"manager_id": manager_id})
        ).mappings().first()

        if summary_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"manager {manager_id} not found",
            )

        summary_dict = dict(summary_row)
        summary_dict.setdefault("fund_types", [])
        if summary_dict.get("fund_types") is None:
            summary_dict["fund_types"] = []
        manager_summary = ManagerRow.model_validate(summary_dict)

        response = FundsListResponse(
            rows=rows,
            next_cursor=next_cursor,
            manager_summary=manager_summary,
        )
        serialized = response.model_dump_json()
        await _cache_set(key, serialized, FUNDS_TTL)
        return serialized

    serialized = await _funds_sf.run(key, _fetch, ttl_s=float(FUNDS_TTL))
    return FundsListResponse.model_validate_json(serialized)


# ── Col3: fact sheet ────────────────────────────────────────────────


@router.get("/funds/{external_id}/fact-sheet")
async def fund_fact_sheet(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    key = f"discovery:factsheet:{external_id}"

    cached = await _cache_get(key)
    if cached is not None:
        return dict(json.loads(cached))

    async def _fetch() -> str:
        inner = await _cache_get(key)
        if inner is not None:
            return inner

        sql = """
            SELECT
                to_jsonb(f) AS fund,
                (SELECT to_jsonb(rm) FROM fund_risk_metrics rm
                   JOIN instruments_universe i ON i.instrument_id = rm.instrument_id
                   WHERE i.ticker = f.ticker
                   ORDER BY rm.calc_date DESC LIMIT 1) AS risk,
                (SELECT to_jsonb(ps) FROM sec_fund_prospectus_stats ps
                   WHERE ps.series_id = f.series_id LIMIT 1) AS prospectus,
                (SELECT jsonb_agg(to_jsonb(fc)) FROM sec_fund_classes fc
                   WHERE fc.series_id = f.series_id) AS classes
            FROM mv_unified_funds f
            WHERE f.external_id = :id
        """
        row = (
            await db.execute(text(sql), {"id": external_id})
        ).mappings().first()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"fund {external_id} not found",
            )

        payload: dict[str, Any] = dict(row)
        serialized = json.dumps(payload, default=str)
        await _cache_set(key, serialized, FACTSHEET_TTL)
        return serialized

    serialized = await _factsheet_sf.run(key, _fetch, ttl_s=float(FACTSHEET_TTL))
    return dict(json.loads(serialized))


# ── Col3: DD report snapshot (one-shot JSON) ────────────────────────


@router.get("/funds/{external_id}/dd-report/snapshot")
async def dd_report_snapshot(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, Any]:
    # Resolve fund → instrument_id since dd_reports is keyed by instrument_id.
    resolved = await resolve_fund(db, external_id)
    instrument_id = resolved.get("instrument_id")
    if instrument_id is None:
        return {"chapters": [], "instrument_id": None}

    sql = """
        SELECT chapter_tag, chapter_order, content_md, critic_status, generated_at
        FROM dd_chapters
        WHERE dd_report_id = (
            SELECT id FROM dd_reports
            WHERE instrument_id = :iid
              AND organization_id = (SELECT current_setting('app.current_organization_id')::uuid)
              AND is_current = true
            ORDER BY created_at DESC
            LIMIT 1
        )
        ORDER BY chapter_order ASC
    """
    rows = (
        await db.execute(text(sql), {"iid": str(instrument_id)})
    ).mappings().all()
    return {
        "instrument_id": str(instrument_id),
        "chapters": [dict(r) for r in rows],
    }


# ── Col3: DD report SSE stream ─────────────────────────────────────


@router.get("/funds/{external_id}/dd-report/stream")
async def dd_report_stream(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
) -> EventSourceResponse:
    """Stream the latest DD report for a fund as Server-Sent Events.

    Emits one ``snapshot`` event with all currently persisted chapters,
    then subscribes to ``dd:report:{report_id}`` on Redis and forwards
    every ``chapter`` / ``terminal`` message published by the DD worker.
    """
    resolved = await resolve_fund(db, external_id)
    instrument_id = resolved.get("instrument_id")
    if instrument_id is None:
        raise HTTPException(status_code=404, detail="fund has no instrument binding")

    report_row = (
        await db.execute(
            text(
                """
                SELECT id
                FROM dd_reports
                WHERE instrument_id = :iid
                  AND organization_id = (SELECT current_setting('app.current_organization_id')::uuid)
                  AND is_current = true
                ORDER BY created_at DESC
                LIMIT 1
                """,
            ),
            {"iid": str(instrument_id)},
        )
    ).first()
    if report_row is None:
        raise HTTPException(status_code=404, detail="no DD report for fund")
    report_id = str(report_row[0])

    snapshot_rows = (
        await db.execute(
            text(
                """
                SELECT chapter_tag, chapter_order, content_md,
                       critic_status, generated_at
                FROM dd_chapters
                WHERE dd_report_id = :rid
                ORDER BY chapter_order ASC
                """,
            ),
            {"rid": report_id},
        )
    ).mappings().all()
    snapshot_payload = json.dumps(
        {"chapters": [dict(r) for r in snapshot_rows]},
        default=str,
    )

    async def event_generator() -> Any:
        yield ServerSentEvent(event="snapshot", data=snapshot_payload)

        # Per-request Redis connection — pub/sub is exclusive.
        r = aioredis.Redis(connection_pool=get_redis_pool())
        pubsub = r.pubsub()
        channel = f"dd:report:{report_id}"
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                raw = message["data"]
                if isinstance(raw, bytes):
                    raw = raw.decode()
                try:
                    parsed = json.loads(raw)
                    event_type = parsed.get("event", "chapter")
                    data = json.dumps(parsed.get("data", parsed), default=str)
                except Exception:  # noqa: BLE001 — forward raw payload
                    event_type = "chapter"
                    data = str(raw)
                yield ServerSentEvent(event=event_type, data=data)
                if event_type in ("terminal", "done", "error"):
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]
            await r.aclose()

    return EventSourceResponse(
        event_generator(),
        ping=15,
        ping_message_factory=lambda: ServerSentEvent(comment="keep-alive"),
    )
