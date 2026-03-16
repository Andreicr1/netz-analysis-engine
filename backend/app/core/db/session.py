"""Sync Database Session — for background workers in threads.

Provides sync session factory for code that runs in asyncio.to_thread().
Callers that need RLS must execute SET LOCAL within the session
transaction before any tenant-scoped queries.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config.settings import settings

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
