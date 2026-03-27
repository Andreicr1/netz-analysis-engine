"""Multi-Tenancy RLS Middleware — Netz Analysis Engine
====================================================

Sets PostgreSQL session variable `app.current_organization_id` per transaction
via SET LOCAL (transaction-scoped, safe for connection pooling).

RLS policies use:
  USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))

The subselect wrapper is CRITICAL for performance — without it, current_setting()
evaluates per-row instead of once per query (1000x slower on large tables).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory
from app.core.security.clerk_auth import Actor, get_actor


async def get_org_id(actor: Actor = Depends(get_actor)) -> uuid.UUID | None:
    """Extract organization_id from the authenticated actor."""
    return actor.organization_id


async def set_rls_context(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Set RLS tenant context on an existing session.

    For use in background workers that manage their own sessions.
    Must be called after session creation and re-called after each commit(),
    because SET LOCAL is transaction-scoped and lost on commit/rollback.
    """
    # asyncpg does not support bind parameters in SET commands — interpolate
    # the UUID directly. UUIDs are safe to interpolate (hex chars + hyphens only).
    safe_oid = str(org_id).replace("'", "")
    await session.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))


async def get_db_with_rls(
    actor: Actor = Depends(get_actor),
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: async session with RLS tenant context.

    Uses SET LOCAL so the organization_id is scoped to this transaction only.
    When the transaction ends (commit or rollback), the setting is automatically
    cleared — safe for connection pooling.
    """
    async with async_session_factory() as session, session.begin():
        if actor.organization_id is not None:
            await set_rls_context(session, actor.organization_id)
        else:
            # Dev token without org_id — set a nil UUID so RLS policies using
            # current_setting('app.current_organization_id') don't throw
            # "unrecognized configuration parameter". Queries return no rows
            # (nil UUID matches nothing) which is the correct fail-closed behavior.
            await session.execute(
                text("SET LOCAL app.current_organization_id = '00000000-0000-0000-0000-000000000000'"),
            )
        yield session
