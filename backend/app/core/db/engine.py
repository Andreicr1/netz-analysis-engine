"""
Async Database Engine — Netz Analysis Engine
=============================================

Pattern from netz-wealth-os/backend/app/database.py, adapted with:
- Larger pool for production (pool_size=20, max_overflow=10)
- pool_pre_ping=True (critical for Azure — kills idle connections > 10 min)
- pool_recycle=300 (recycle connections every 5 min)
- expire_on_commit=False (CRITICAL for async — prevents implicit I/O)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config.settings import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=30,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async session with auto-commit/rollback."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
