"""Materialized View refresh utility for wealth performance layer.

Used by ingestion workers to ensure screener/search views are fresh
after bulk data updates.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def refresh_screener_views(db: AsyncSession, concurrently: bool = True) -> None:
    """Refresh mv_unified_funds and mv_unified_assets views.
    
    CONCURRENTLY allows reads during refresh but requires a UNIQUE index
    (which we have on external_id and id).
    """
    mode = "CONCURRENTLY" if concurrently else ""
    
    views = ["mv_unified_funds", "mv_unified_assets"]
    
    for view in views:
        logger.info("view_refresh.started", view=view, concurrently=concurrently)
        try:
            await db.execute(text(f"REFRESH MATERIALIZED VIEW {mode} {view}"))
            await db.commit()
            logger.info("view_refresh.completed", view=view)
        except Exception as exc:
            await db.rollback()
            logger.error("view_refresh.failed", view=view, error=str(exc))
            # Fallback to non-concurrent if concurrent fails (e.g. if index is missing)
            if concurrently:
                logger.warning("view_refresh.retrying_without_concurrently", view=view)
                await refresh_screener_views(db, concurrently=False)
