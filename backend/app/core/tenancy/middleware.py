"""Multi-Tenancy RLS Middleware — Netz Analysis Engine
====================================================

Sets PostgreSQL session variables per transaction via `set_config(..., true)`
(transaction-scoped, equivalent to SET LOCAL — safe for connection pooling).

Two GUCs are populated for every authenticated request:

  app.current_organization_id  → tenant scope (always set)
  app.current_user_id          → Clerk subject of the authenticated actor
                                  (set when an actor identity exists)

RLS policies use:
  USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))

And, for per-user resources such as `wealth_library_pins`:
  USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid)
         AND user_id = (SELECT current_setting('app.current_user_id')::text))

The subselect wrapper is CRITICAL for performance — without it,
current_setting() evaluates per-row instead of once per query
(1000x slower on large tables).
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


async def set_rls_context(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: str | None = None,
) -> None:
    """Set RLS tenant + user context on an existing session.

    For use in background workers that manage their own sessions.
    Must be called after session creation and re-called after each commit(),
    because the `true` flag on set_config() makes the value transaction-scoped
    and the setting is cleared on commit/rollback.

    The optional ``user_id`` is the Clerk subject (``actor.actor_id``) for
    per-user RLS policies (e.g. ``wealth_library_pins``). When omitted —
    typically in background workers that operate on behalf of the system —
    the GUC is left unset and per-user policies fall closed.
    """
    # SET is a utility statement — PostgreSQL rejects bind params ($1) in it.
    # Use set_config() which runs via SELECT (plannable, accepts params).
    # Third arg true = transaction-scoped (equivalent to SET LOCAL).
    await session.execute(
        text("SELECT set_config('app.current_organization_id', :oid, true)"),
        {"oid": str(org_id)},
    )
    if user_id is not None:
        await session.execute(
            text("SELECT set_config('app.current_user_id', :uid, true)"),
            {"uid": user_id},
        )


async def get_db_with_rls(
    actor: Actor = Depends(get_actor),
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: async session with RLS tenant + user context.

    Uses transaction-scoped ``set_config(..., true)`` so both
    ``app.current_organization_id`` and ``app.current_user_id`` are scoped
    to this transaction only. When the transaction ends (commit or rollback),
    the settings are automatically cleared — safe for connection pooling.

    The Clerk subject (``actor.actor_id``) is propagated even when the actor
    has no organization_id — for example, dev tokens or onboarding flows —
    so per-user RLS policies still receive a deterministic value.
    """
    async with async_session_factory() as session, session.begin():
        if actor.organization_id is not None:
            await set_rls_context(
                session,
                actor.organization_id,
                user_id=actor.actor_id,
            )
        else:
            # Dev token without org_id — set a nil UUID so RLS policies using
            # current_setting('app.current_organization_id') don't throw
            # "unrecognized configuration parameter". Queries return no rows
            # (nil UUID matches nothing) which is the correct fail-closed
            # behavior. The user GUC still receives the Clerk subject so
            # per-user policies can fail closed deterministically too.
            await session.execute(
                text("SET LOCAL app.current_organization_id = '00000000-0000-0000-0000-000000000000'"),
            )
            await session.execute(
                text("SELECT set_config('app.current_user_id', :uid, true)"),
                {"uid": actor.actor_id},
            )
        yield session
