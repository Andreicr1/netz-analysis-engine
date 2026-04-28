"""PR-Q91 — UCITS data-availability gate invariants.

Validates the post-migration state of mv_unified_funds and the
ESMA↔instruments_universe bridge. Read-only assertions on the live DB.
"""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.mark.asyncio
async def test_ucits_branch_excludes_funds_without_nav():
    """Every UCITS row in mv_unified_funds must have an instruments_universe
    row with at least one nav_timeseries entry — no more has_nav lies."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        violations = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM mv_unified_funds m
            WHERE m.universe = 'ucits_eu'
              AND NOT EXISTS (
                  SELECT 1
                  FROM instruments_universe iu
                  JOIN nav_timeseries n ON n.instrument_id = iu.instrument_id
                  WHERE iu.ticker = m.ticker
              )
            """
        )
    finally:
        await conn.close()
    assert violations == 0, (
        f"{violations} UCITS rows in mv_unified_funds have no NAV — "
        "data-availability gate broken"
    )


@pytest.mark.asyncio
async def test_ucits_external_id_is_not_lei_misnamed():
    """external_id must use real ISIN or ticker — never the legacy_isin_misnamed
    column that historically stored LEIs."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        leaked_leis = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM mv_unified_funds m
            JOIN esma_funds ef ON ef.legacy_isin_misnamed = m.external_id
            WHERE m.universe = 'ucits_eu'
              AND ef.legacy_isin_misnamed ~ '^[A-Z0-9]{20}$'
              AND m.external_id NOT IN (
                  SELECT lei FROM esma_funds
              )
            """
        )
    finally:
        await conn.close()
    assert leaked_leis == 0, (
        "UCITS external_id is leaking legacy_isin_misnamed values that look "
        "like LEIs but are not registered in esma_funds.lei"
    )


@pytest.mark.asyncio
async def test_ucits_aum_populated_when_q78_enrichment_present():
    """If instruments_universe.attributes->>'aum_usd' is populated by Q78,
    the materialized view must surface it (not NULL)."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        missing_aum = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM mv_unified_funds m
            JOIN instruments_universe iu ON iu.ticker = m.ticker
            WHERE m.universe = 'ucits_eu'
              AND iu.attributes->>'aum_usd' IS NOT NULL
              AND m.aum_usd IS NULL
            """
        )
    finally:
        await conn.close()
    assert missing_aum == 0, (
        f"{missing_aum} UCITS funds have aum_usd in attributes but NULL in "
        "mv_unified_funds — Q78 enrichment not flowing through"
    )


@pytest.mark.asyncio
async def test_bridge_fund_lei_populated_for_ucits_with_ticker_match():
    """For UCITS instruments whose ticker matches an esma_funds.yahoo_ticker,
    attributes->>'fund_lei' must be populated."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        missing = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM instruments_universe iu
            JOIN esma_funds ef ON ef.yahoo_ticker = iu.ticker
            WHERE iu.attributes->>'fund_subtype' = 'ucits'
              AND ef.yahoo_ticker IS NOT NULL
              AND ef.yahoo_ticker <> ''
              AND (iu.attributes->>'fund_lei' IS NULL OR iu.attributes->>'fund_lei' = '')
            """
        )
    finally:
        await conn.close()
    assert missing == 0, (
        f"{missing} UCITS instruments have a matching esma_funds row but "
        "attributes.fund_lei was not populated by Q91 bridge"
    )


@pytest.mark.asyncio
async def test_ucits_with_nav_are_active():
    """Every UCITS in instruments_universe with at least one nav_timeseries
    row must be is_active = true (Q91 reactivation invariant)."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        violators = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM instruments_universe iu
            WHERE iu.attributes->>'fund_subtype' = 'ucits'
              AND iu.is_active = false
              AND EXISTS (
                  SELECT 1 FROM nav_timeseries n
                  WHERE n.instrument_id = iu.instrument_id
              )
            """
        )
    finally:
        await conn.close()
    assert violators == 0, (
        f"{violators} UCITS instruments have NAV data but are is_active=false — "
        "universe_sync._deactivate_no_nav race not yet patched (Q92 follow-up)"
    )
