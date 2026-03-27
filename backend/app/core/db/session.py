"""Sync Database Session — for background workers and legacy sync handlers.

Provides sync session factory for code that runs in asyncio.to_thread()
or in legacy sync FastAPI route handlers.

get_sync_db_with_rls: FastAPI dependency for sync handlers needing tenant isolation.
sync_session_factory: raw factory for background workers (caller sets RLS manually).
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config.settings import settings
from app.core.security.clerk_auth import Actor, get_actor

sync_engine = create_engine(
    settings.database_url_sync,
    echo=settings.is_development,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=30,
)

sync_session_factory = sessionmaker(
    sync_engine,
    class_=Session,
    expire_on_commit=False,
)


def get_sync_db_with_rls(
    actor: Actor = Depends(get_actor),
) -> Generator[Session, None, None]:
    """FastAPI dependency: sync session with RLS tenant context.

    For legacy sync route handlers that need tenant isolation.
    Uses SET LOCAL so the org_id is transaction-scoped (safe for pooling).
    Prefer async get_db_with_rls for new code.
    """
    with sync_session_factory() as session, session.begin():
        if actor.organization_id is not None:
            safe_oid = str(actor.organization_id).replace("'", "")
            session.execute(
                text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"),
            )
        yield session
