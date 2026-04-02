"""Materialized View refresh utility for macro intelligence layer."""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def refresh_macro_views(db: AsyncSession, concurrently: bool = True) -> None:
    """Refresh mv_macro_latest and mv_macro_regional_summary views."""
    mode = "CONCURRENTLY" if concurrently else ""
    
    views = ["mv_macro_latest", "mv_macro_regional_summary"]
    
    for view in views:
        logger.info("macro_view_refresh.started", view=view, concurrently=concurrently)
        try:
            await db.execute(text(f"REFRESH MATERIALIZED VIEW {mode} {view}"))
            await db.commit()
            logger.info("macro_view_refresh.completed", view=view)
        except Exception as exc:
            await db.rollback()
            logger.error("macro_view_refresh.failed", view=view, error=str(exc))
            if concurrently:
                logger.warning("macro_view_refresh.retrying_without_concurrently", view=view)
                await refresh_macro_views(db, concurrently=False)
