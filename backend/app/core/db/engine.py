"""Async Database Engine — Netz Analysis Engine
=============================================

Pattern from netz-wealth-os/backend/app/database.py, adapted with:
- Larger pool for production (pool_size=20, max_overflow=10)
- pool_pre_ping=True (critical for Azure — kills idle connections > 10 min)
- pool_recycle=300 (recycle connections every 5 min)
- expire_on_commit=False (CRITICAL for async — prevents implicit I/O)
"""

from __future__ import annotations

import ssl as _ssl
from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlparse

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config.settings import settings


def _build_connect_args(url: str) -> dict:
    """Extract SSL config from URL and return asyncpg connect_args.

    asyncpg does not accept ``ssl`` or ``sslmode`` as URL query parameters
    when passed through SQLAlchemy — it must receive an ``ssl.SSLContext``
    via ``connect_args``.  We strip the SSL param from the URL and pass it
    correctly.
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    needs_ssl = (
        qs.get("ssl", [None])[0] in ("true", "True", "1")
        or qs.get("sslmode", [None])[0] in ("require", "verify-ca", "verify-full")
    )
    if needs_ssl:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        return {"ssl": ctx}
    return {}


def _clean_url(url: str) -> str:
    """Remove ssl/sslmode query params that asyncpg cannot parse."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("ssl", None)
    qs.pop("sslmode", None)
    # Rebuild query string
    new_qs = "&".join(f"{k}={v[0]}" for k, v in qs.items()) if qs else ""
    cleaned = parsed._replace(query=new_qs)
    return cleaned.geturl()


_connect_args = _build_connect_args(settings.database_url)
_db_url = _clean_url(settings.database_url)

engine = create_async_engine(
    _db_url,
    echo=False,  # SQL logging adds latency — use structlog for selective query logging
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_timeout=30,
    connect_args=_connect_args,
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
