"""FastAPI dependencies for ConfigWriter."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_writer import ConfigWriter
from app.core.tenancy.middleware import get_db_with_rls


async def get_config_writer(
    db: AsyncSession = Depends(get_db_with_rls),
) -> ConfigWriter:
    """Inject ConfigWriter with RLS-aware session."""
    return ConfigWriter(db=db)
