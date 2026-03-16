"""Admin health routes — Worker status, pipeline stats, tenant usage.

All routes require ADMIN role.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.core.db.engine import async_session_factory
from app.core.security.clerk_auth import Actor, require_role
from app.domains.admin.schemas import PipelineStats, TenantUsage, WorkerStatus
from app.shared.enums import Role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/health", tags=["admin-health"])


@router.get(
    "/workers",
    response_model=list[WorkerStatus],
    summary="Get background worker status",
    description="Returns last run time, duration, and error count for each worker.",
)
async def get_worker_status(
    actor: Actor = Depends(require_role(Role.ADMIN)),
) -> list[WorkerStatus]:
    """Worker status from Redis or DB worker registry.

    For now returns a static list of known workers with placeholder status.
    In production, this queries Redis for last heartbeat/run metadata.
    """
    # Known worker names — expand as workers are added
    workers = [
        "document_scanner",
        "pipeline_ingest",
        "macro_data_refresh",
        "search_rebuild",
        "fact_sheet_generator",
    ]

    # Try to get last run info from Redis (graceful fallback if unavailable)
    try:
        from app.core.jobs.tracker import get_redis_pool

        redis = await get_redis_pool()
        statuses = []
        for name in workers:
            last_run_str = await redis.get(f"worker:{name}:last_run")
            duration_str = await redis.get(f"worker:{name}:duration")
            error_count_str = await redis.get(f"worker:{name}:error_count")

            last_run = (
                datetime.fromisoformat(last_run_str.decode())
                if last_run_str
                else None
            )
            duration = float(duration_str) if duration_str else None
            error_count = int(error_count_str) if error_count_str else 0

            # Determine health status
            if last_run is None:
                worker_status = "unknown"
            elif (datetime.now(UTC) - last_run).total_seconds() > 3600:
                worker_status = "degraded"
            else:
                worker_status = "healthy" if error_count == 0 else "error"

            statuses.append(
                WorkerStatus(
                    name=name,
                    last_run=last_run,
                    duration_seconds=duration,
                    status=worker_status,
                    error_count=error_count,
                )
            )
        return statuses
    except Exception:
        logger.warning("Redis unavailable for worker status — returning unknown status")
        return [
            WorkerStatus(name=name, status="unknown")
            for name in workers
        ]


@router.get(
    "/pipelines",
    response_model=PipelineStats,
    summary="Get pipeline processing statistics",
)
async def get_pipeline_stats(
    actor: Actor = Depends(require_role(Role.ADMIN)),
) -> PipelineStats:
    """Pipeline stats from DB counters or Redis.

    Returns document processing counts, queue depth, error rate.
    """
    try:
        from app.core.jobs.tracker import get_redis_pool

        redis = await get_redis_pool()
        processed = await redis.get("pipeline:docs_processed")
        queue = await redis.llen("pipeline:queue")  # type: ignore[union-attr]
        errors = await redis.get("pipeline:error_count")

        docs_processed = int(processed) if processed else 0
        error_count = int(errors) if errors else 0
        error_rate = error_count / max(docs_processed, 1)

        return PipelineStats(
            documents_processed=docs_processed,
            queue_depth=queue or 0,
            error_rate=round(error_rate, 4),
        )
    except Exception:
        logger.warning("Redis unavailable for pipeline stats")
        return PipelineStats()


@router.get(
    "/usage",
    response_model=list[TenantUsage],
    summary="Get per-tenant usage statistics",
)
async def get_tenant_usage(
    actor: Actor = Depends(require_role(Role.ADMIN)),
) -> list[TenantUsage]:
    """Per-tenant usage from DB aggregations.

    Uses async_session_factory directly (no RLS) because this endpoint
    needs cross-tenant aggregation for admin dashboards.

    Currently aggregates document counts as a proxy for usage.
    Expand with API call counts and storage metrics as instrumentation grows.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT organization_id, COUNT(*) as doc_count
                    FROM vertical_config_overrides
                    GROUP BY organization_id
                    ORDER BY organization_id
                """)
            )
            return [
                TenantUsage(
                    organization_id=row[0],
                    api_calls=0,
                    storage_bytes=0,
                    memos_generated=row[1],
                )
                for row in result.all()
            ]
    except Exception:
        logger.warning("Failed to query tenant usage")
        return []
