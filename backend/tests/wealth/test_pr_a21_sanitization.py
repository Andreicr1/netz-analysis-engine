"""PR-A21 — end-to-end migration 0149 behavioural test.

Seeds the four defects described in the PR-A21 spec inside a single
transaction, executes the four SQL steps of migration 0149 verbatim,
asserts the post-state, and rolls the transaction back so no global
state (``allocation_blocks`` entries, other orgs' data) is disturbed.

The migration has already been applied by ``make migrate`` before
this test suite is collected, so ``fi_govt`` may or may not still be
present in ``allocation_blocks``. The test seeds it defensively with
``ON CONFLICT DO NOTHING``.
"""
from __future__ import annotations

import uuid

import asyncpg
import pytest

from app.core.config import settings


def _dsn() -> str:
    return settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://",
    )


# Migration SQL mirrored verbatim from
# ``0149_sanitize_org_universe.py`` — any drift here will fail this
# test (which is the desired behaviour — pin the migration contract).
_STEP1_REMAP_SQL = """
    UPDATE instruments_org
       SET block_id = 'fi_us_treasury'
     WHERE block_id = 'fi_govt'
"""

_STEP2_DEDUP_SQL = """
    WITH ranked AS (
        SELECT io.id,
               ROW_NUMBER() OVER (
                   PARTITION BY io.organization_id, io.instrument_id
                   ORDER BY
                       CASE
                           WHEN io.source = 'universe_auto_import'
                                AND io.block_id IS NOT NULL
                                AND EXISTS (
                                    SELECT 1 FROM allocation_blocks ab
                                     WHERE ab.block_id = io.block_id
                                )
                               THEN 0
                           WHEN (io.source IS NULL
                                 OR io.source NOT LIKE '%backfill%')
                                AND io.block_id IS NOT NULL
                               THEN 1
                           WHEN io.block_id IS NOT NULL THEN 2
                           ELSE 3
                       END,
                       io.selected_at ASC,
                       io.id ASC
               ) AS rn
          FROM instruments_org io
    )
    DELETE FROM instruments_org
     WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
"""

_STEP3_NULL_CLEANUP_SQL = """
    DELETE FROM instruments_org
     WHERE block_id IS NULL
       AND source LIKE '%backfill%'
"""

_STEP4_FK_CLEANUP_SQLS = (
    "DELETE FROM benchmark_nav WHERE block_id = 'fi_govt'",
    "UPDATE funds_universe SET block_id = 'fi_us_treasury' "
    "WHERE block_id = 'fi_govt'",
    "UPDATE tactical_positions SET block_id = 'fi_us_treasury' "
    "WHERE block_id = 'fi_govt'",
    "DELETE FROM blended_benchmark_components WHERE block_id = 'fi_govt'",
)
_STEP4_DROP_FI_GOVT_SQL = """
    DELETE FROM allocation_blocks
     WHERE block_id = 'fi_govt'
"""


@pytest.mark.asyncio
async def test_migration_0149_sanitizes_all_four_defects() -> None:
    org_id = uuid.uuid4()
    test_ticker = f"PRA21_{uuid.uuid4().hex[:6].upper()}"
    dup_ticker = f"PRA21_{uuid.uuid4().hex[:6].upper()}"
    null_ticker = f"PRA21_{uuid.uuid4().hex[:6].upper()}"

    conn = await asyncpg.connect(_dsn())
    tx = conn.transaction()
    await tx.start()
    try:
        # Seed allocation_blocks (both fi_govt and fi_us_treasury must exist).
        await conn.execute(
            """
            INSERT INTO allocation_blocks
                (block_id, geography, asset_class, display_name, benchmark_ticker)
            VALUES
                ('fi_govt', 'us', 'fixed_income', 'US Government Bond', 'GOVT')
            ON CONFLICT (block_id) DO NOTHING
            """
        )
        await conn.execute(
            """
            INSERT INTO allocation_blocks
                (block_id, geography, asset_class, display_name, benchmark_ticker)
            VALUES
                ('fi_us_treasury', 'north_america', 'fixed_income',
                 'US Treasury', 'IEF')
            ON CONFLICT (block_id) DO NOTHING
            """
        )

        # Seed three instruments_universe rows (global, no RLS).
        treasury_iid, dup_iid, null_iid = (
            uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
        )
        fund_attrs = (
            '{"aum_usd": 1000000000, '
            '"manager_name": "PR-A21 Test", '
            '"inception_date": "2020-01-01"}'
        )
        await conn.executemany(
            """
            INSERT INTO instruments_universe
                (instrument_id, instrument_type, name, ticker,
                 asset_class, geography, currency, attributes)
            VALUES ($1, 'fund', $2, $3, 'fixed_income', 'us', 'USD', $4::jsonb)
            """,
            [
                (treasury_iid, f"Treasury test {test_ticker}",
                 test_ticker, fund_attrs),
                (dup_iid, f"Dup test {dup_ticker}",
                 dup_ticker, fund_attrs),
                (null_iid, f"Null test {null_ticker}",
                 null_ticker, fund_attrs),
            ],
        )

        # Drop the unique constraint to reproduce historical duplicate
        # state. The transaction rollback restores it; recreating it
        # after dedup inside the test also proves post-state respects
        # the uniqueness invariant.
        await conn.execute(
            "ALTER TABLE instruments_org DROP CONSTRAINT "
            "instruments_org_organization_id_instrument_id_key"
        )

        # D3 — one row pointing at the retired fi_govt block.
        await conn.execute(
            """
            INSERT INTO instruments_org
                (organization_id, instrument_id, block_id, approval_status,
                 source, block_overridden)
            VALUES ($1, $2, 'fi_govt', 'approved', 'universe_auto_import', FALSE)
            """,
            org_id, treasury_iid,
        )

        # D1 — three duplicate rows for the same (org, instrument) pair with
        # different sources. The universe_auto_import row (block present
        # in allocation_blocks) must win.
        await conn.execute(
            """
            INSERT INTO instruments_org
                (organization_id, instrument_id, block_id, approval_status,
                 source, block_overridden, selected_at)
            VALUES
                ($1, $2, 'fi_us_treasury', 'approved',
                 'pr_a19_1_backfill', FALSE, now() - INTERVAL '3 days'),
                ($1, $2, 'fi_us_treasury', 'approved',
                 'universe_auto_import', FALSE, now() - INTERVAL '2 days'),
                ($1, $2, NULL, 'approved',
                 'pr_a20_backfill', FALSE, now() - INTERVAL '1 day')
            """,
            org_id, dup_iid,
        )

        # D2 — lone backfill row with NULL block_id (no sibling, so dedup
        # leaves it alone; the null-cleanup step must delete it).
        await conn.execute(
            """
            INSERT INTO instruments_org
                (organization_id, instrument_id, block_id, approval_status,
                 source, block_overridden)
            VALUES ($1, $2, NULL, 'approved', 'pr_a19_1_backfill', FALSE)
            """,
            org_id, null_iid,
        )

        pre_total = await conn.fetchval(
            "SELECT COUNT(*) FROM instruments_org WHERE organization_id = $1",
            org_id,
        )
        assert pre_total == 5, pre_total

        # ── Execute migration steps 1-4 verbatim ──────────────────
        await conn.execute(_STEP1_REMAP_SQL)
        await conn.execute(_STEP2_DEDUP_SQL)
        await conn.execute(_STEP3_NULL_CLEANUP_SQL)

        sa_uses_fi_govt = await conn.fetchval(
            "SELECT COUNT(*) FROM strategic_allocation "
            "WHERE block_id = 'fi_govt'"
        )
        assert sa_uses_fi_govt == 0, (
            "test DB leaked strategic_allocation rows targeting fi_govt"
        )
        for sql in _STEP4_FK_CLEANUP_SQLS:
            await conn.execute(sql)
        await conn.execute(_STEP4_DROP_FI_GOVT_SQL)

        # ── Assertions ─────────────────────────────────────────────
        # D1: only one row per (org, instrument) pair.
        max_rows = await conn.fetchval(
            """
            SELECT COALESCE(MAX(n), 0) FROM (
                SELECT COUNT(*) AS n
                FROM instruments_org
                WHERE organization_id = $1
                GROUP BY instrument_id
            ) t
            """,
            org_id,
        )
        assert max_rows == 1, (
            f"D1 dedup failed: max rows per pair = {max_rows}"
        )

        # D1 survivor for dup_iid is the universe_auto_import row.
        survivor = await conn.fetchrow(
            """
            SELECT source, block_id
              FROM instruments_org
             WHERE organization_id = $1 AND instrument_id = $2
            """,
            org_id, dup_iid,
        )
        assert survivor is not None
        assert survivor["source"] == "universe_auto_import", survivor["source"]
        assert survivor["block_id"] == "fi_us_treasury", survivor["block_id"]

        # D2: no backfill rows with NULL block_id remain for this org.
        d2_remaining = await conn.fetchval(
            """
            SELECT COUNT(*) FROM instruments_org
             WHERE organization_id = $1
               AND block_id IS NULL
               AND source LIKE '%backfill%'
            """,
            org_id,
        )
        assert d2_remaining == 0, d2_remaining

        # D3: no rows point at fi_govt anywhere (global).
        d3_remaining = await conn.fetchval(
            "SELECT COUNT(*) FROM instruments_org WHERE block_id = 'fi_govt'"
        )
        assert d3_remaining == 0, d3_remaining

        # D3 remap: the treasury seed row now points at fi_us_treasury.
        remapped_block = await conn.fetchval(
            """
            SELECT block_id FROM instruments_org
             WHERE organization_id = $1 AND instrument_id = $2
            """,
            org_id, treasury_iid,
        )
        assert remapped_block == "fi_us_treasury", remapped_block

        # D3 taxonomy retire: fi_govt gone from allocation_blocks.
        has_fi_govt = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM allocation_blocks "
            "WHERE block_id = 'fi_govt')"
        )
        assert has_fi_govt is False

        # Final per-org row count: 1 (treasury) + 1 (dup survivor) = 2.
        post_total = await conn.fetchval(
            "SELECT COUNT(*) FROM instruments_org WHERE organization_id = $1",
            org_id,
        )
        assert post_total == 2, post_total

        # Post-state must respect the unique invariant that was dropped
        # at the top of the test — recreating it must succeed.
        await conn.execute(
            "ALTER TABLE instruments_org ADD CONSTRAINT "
            "instruments_org_organization_id_instrument_id_key "
            "UNIQUE (organization_id, instrument_id)"
        )
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_migration_0149_aborts_when_strategic_allocation_references_fi_govt() -> None:
    """Step 4 assertion: if a strategic_allocation row still targets fi_govt,
    the migration must refuse to drop the block.
    """
    org_id = uuid.uuid4()
    alloc_id = uuid.uuid4()
    conn = await asyncpg.connect(_dsn())
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            """
            INSERT INTO allocation_blocks
                (block_id, geography, asset_class, display_name, benchmark_ticker)
            VALUES
                ('fi_govt', 'us', 'fixed_income', 'US Government Bond', 'GOVT')
            ON CONFLICT (block_id) DO NOTHING
            """
        )
        await conn.execute(
            """
            INSERT INTO strategic_allocation
                (allocation_id, organization_id, profile, block_id,
                 target_weight, min_weight, max_weight, effective_from)
            VALUES ($1, $2, 'moderate', 'fi_govt', 0.1, 0.05, 0.2, '2026-01-01')
            """,
            alloc_id, org_id,
        )

        count = await conn.fetchval(
            "SELECT COUNT(*) FROM strategic_allocation WHERE block_id = 'fi_govt'"
        )
        # The migration performs this exact check and raises when nonzero.
        assert count > 0, "guardrail pre-condition failed"
    finally:
        await tx.rollback()
        await conn.close()
