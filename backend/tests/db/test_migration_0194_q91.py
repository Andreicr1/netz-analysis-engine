"""PR-Q91 — UCITS data-availability gate invariants.

Validates the post-migration state of mv_unified_funds and the
ESMA↔instruments_universe bridge. Read-only assertions on the live DB.
"""

from __future__ import annotations

from pathlib import Path

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


# ---------------------------------------------------------------------------
# Q105 — Codex P1+P2 catches on Q91 downgrade path
# ---------------------------------------------------------------------------

_MIGRATION_PATH = Path(
    "backend/app/core/db/migrations/versions/0194_q91_ucits_data_gate.py"
)


def test_q105_mv_sql_down_contains_all_6_branches():
    """Q105 invariant: _MV_SQL_DOWN must recreate all 6 universe branches
    (registered_us, ETFs, BDCs, private_us, ucits_eu, money_market).
    Codex P1 catch — original _MV_SQL_DOWN only had the UCITS branch."""
    text = _MIGRATION_PATH.read_text()
    down_idx = text.index("_MV_SQL_DOWN")
    # Find the closing triple-quote to delimit the SQL block
    block_start = text.index('"""', down_idx)
    block_end = text.index('"""', block_start + 3)
    down_block = text[block_start:block_end]

    assert "sec_registered_funds rf" in down_block, "Branch 1 (registered_us) missing"
    assert "sec_etfs e" in down_block, "Branch 2 (ETFs) missing"
    assert "sec_bdcs b" in down_block, "Branch 3 (BDCs) missing"
    assert "sec_manager_funds mf" in down_block, "Branch 4 (private_us) missing"
    assert "esma_funds ef" in down_block, "Branch 5 (ucits_eu) missing"
    assert "sec_money_market_funds mmf" in down_block, "Branch 6 (money_market) missing"

    # Verify it uses the 0183 UCITS shape (LEFT JOIN esma_securities, not INNER JOIN instruments_universe)
    assert "LEFT JOIN esma_securities es" in down_block, (
        "UCITS branch should use LEFT JOIN esma_securities (0183 shape)"
    )
    assert "COALESCE(es.isin, ef.lei)" in down_block, (
        "UCITS branch should use COALESCE(es.isin, ef.lei) for external_id (0183 shape)"
    )


def test_q105_bridge_down_constrains_to_q91_added_rows():
    """Q105 invariant: _BRIDGE_DOWN must restrict removal to rows Q91
    plausibly added (JOIN esma_funds + match fund_lei = ef.lei).
    Codex P2 catch — original removed fund_lei from ALL UCITS rows."""
    text = _MIGRATION_PATH.read_text()
    bridge_down_idx = text.index("_BRIDGE_DOWN")
    bridge_down_block = text[bridge_down_idx:bridge_down_idx + 2000]

    assert "FROM esma_funds ef" in bridge_down_block, (
        "_BRIDGE_DOWN must JOIN esma_funds to restrict rollback scope"
    )
    assert "iu.attributes->>'fund_lei' = ef.lei" in bridge_down_block, (
        "_BRIDGE_DOWN must verify fund_lei matches the value Q91 would have set"
    )
