"""Admin session dependencies — cross-tenant DB access for admin routes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory


async def get_db_admin() -> AsyncGenerator[AsyncSession, None]:
    """Cross-tenant admin access. Sets admin_mode but no org context."""
    async with async_session_factory() as session, session.begin():
        await session.execute(text("SET LOCAL app.admin_mode = 'true'"))
        yield session


async def get_db_for_tenant(org_id: uuid.UUID) -> AsyncGenerator[AsyncSession, None]:
    """Per-tenant writes. Sets admin_mode + org context for RLS."""
    async with async_session_factory() as session, session.begin():
        await session.execute(text("SET LOCAL app.admin_mode = 'true'"))
        # Validate UUID and use string interpolation safely — SET LOCAL
        # does not support parameter binding in asyncpg.
        oid = str(uuid.UUID(str(org_id)))  # Re-validate as UUID
        await session.execute(
            text("SET LOCAL app.current_organization_id = :oid"),
            {"oid": oid},
        )
        yield session
