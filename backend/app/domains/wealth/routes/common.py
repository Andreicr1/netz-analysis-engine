"""Shared utilities for API routers."""

from __future__ import annotations

import asyncio

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.portfolio import PortfolioSnapshot

logger = structlog.get_logger()

VALID_PROFILES = {"conservative", "moderate", "growth"}

# PR-BE-7 — backward-compat URL alias for the legacy ``aggressive``
# profile. Sunset 2026-10-30 (180d post-merge). Centralised here so
# every route that calls ``validate_profile`` inherits the alias
# automatically — see ``_profile_normalizer.py`` for the shared
# rationale.
_LEGACY_PROFILE_ALIASES: dict[str, str] = {"aggressive": "growth"}
_LEGACY_PROFILE_SUNSET_DATE = "2026-10-30"

# ---------------------------------------------------------------------------
#  Content generation backpressure
# ---------------------------------------------------------------------------
# CRITICAL: No module-level asyncio primitives (CLAUDE.md rule).
# The semaphore is created lazily on first access inside an async context.

_content_semaphore: asyncio.Semaphore | None = None
_MAX_CONCURRENT_CONTENT_TASKS = 4


def _get_content_semaphore() -> asyncio.Semaphore:
    """Return (or lazily create) the bounded semaphore for content generation."""
    global _content_semaphore
    if _content_semaphore is None:
        _content_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CONTENT_TASKS)
    return _content_semaphore


async def require_content_slot() -> None:
    """Try to acquire a content-generation slot without blocking.

    Raises HTTP 429 if all slots are occupied.  Callers must release the
    slot by calling ``_get_content_semaphore().release()`` in a finally block.
    """
    sem = _get_content_semaphore()
    if sem.locked():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many concurrent content generation tasks "
                f"(limit: {_MAX_CONCURRENT_CONTENT_TASKS}). "
                "Please retry shortly."
            ),
        )
    await sem.acquire()


def validate_profile(profile: str) -> str:
    """Validate that profile is one of the allowed values.

    Returns the canonical (lowercased, alias-resolved) slug — callers
    must use the return value, not the original argument, when joining
    against ``profile`` columns. The legacy ``aggressive`` slug is
    rewritten to ``growth`` (PR-BE-7) with a structured deprecation
    log so the sunset dashboard can track residual usage.
    """
    lc = profile.strip().lower()
    if lc in _LEGACY_PROFILE_ALIASES:
        canonical = _LEGACY_PROFILE_ALIASES[lc]
        logger.info(
            "legacy_profile_url_alias",
            received=profile,
            canonical=canonical,
            sunset_at=_LEGACY_PROFILE_SUNSET_DATE,
        )
        return canonical
    if lc not in VALID_PROFILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid profile. Must be one of: {', '.join(sorted(VALID_PROFILES))}",
        )
    return lc


async def get_latest_snapshot(
    db: AsyncSession, profile: str,
) -> PortfolioSnapshot | None:
    """Get the latest portfolio snapshot for a profile."""
    stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
