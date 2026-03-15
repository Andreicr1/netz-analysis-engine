"""FastAPI dependencies for ConfigService."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.tenancy.middleware import get_db_with_rls


async def get_config_service(
    db: AsyncSession = Depends(get_db_with_rls),
) -> ConfigService:
    """Inject ConfigService with RLS-aware session.

    Single session for both defaults + overrides queries.
    Defaults table has no RLS, so SET LOCAL has zero effect on it.
    No Redis dependency in Sprint 3.
    """
    return ConfigService(db=db)
