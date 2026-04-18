"""PR-A25 — allocation_template_audit trigger DB-level integration test.

Exercises the live Postgres trigger installed by migration 0153. The
test inserts a single ``strategic_allocation`` row for a brand-new
``(organization_id, profile)`` combo and asserts:

* The trigger fan-outs the remaining 17 canonical block rows.
* Every auto-insert produces a matching ``allocation_template_audit``
  entry with ``trigger_reason = 'new_profile_created'``.

Runs against the Docker Postgres the repo uses for dev/CI. Cleans up
after itself in ``finally`` so rerunning is safe.
"""
from __future__ import annotations

import uuid

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://",
    )


@pytest.mark.asyncio
async def test_template_trigger_fans_out_canonical_rows() -> None:
    conn = await asyncpg.connect(_asyncpg_dsn())
    synthetic_org = uuid.uuid4()
    synthetic_profile = f"test_{uuid.uuid4().hex[:8]}"
    try:
        # Pick a canonical block_id to seed the first row with — any one
        # will do; the trigger fills the remaining 17.
        seed_block = await conn.fetchval(
            """
            SELECT block_id FROM allocation_blocks
             WHERE is_canonical = true
             ORDER BY block_id
             LIMIT 1
            """,
        )
        assert seed_block is not None, (
            "migration 0153 must have seeded at least one canonical block"
        )

        canonical_ids = {
            r["block_id"]
            for r in await conn.fetch(
                "SELECT block_id FROM allocation_blocks WHERE is_canonical = true"
            )
        }
        assert len(canonical_ids) == 18, (
            f"expected 18 canonical blocks, got {len(canonical_ids)}"
        )

        # Single INSERT fires the AFTER trigger.
        await conn.execute(
            """
            INSERT INTO strategic_allocation (
                allocation_id, organization_id, profile, block_id,
                target_weight, drift_min, drift_max, risk_budget,
                rationale, approved_by, effective_from, effective_to,
                actor_source, excluded_from_portfolio
            )
            VALUES (
                gen_random_uuid(), $1, $2, $3,
                NULL, NULL, NULL, NULL,
                'test_seed', 'test', CURRENT_DATE, NULL,
                'test_trigger', false
            )
            """,
            synthetic_org, synthetic_profile, seed_block,
        )

        rows = await conn.fetch(
            """
            SELECT block_id FROM strategic_allocation
             WHERE organization_id = $1 AND profile = $2
            """,
            synthetic_org, synthetic_profile,
        )
        present_blocks = {r["block_id"] for r in rows}
        assert present_blocks == canonical_ids, (
            "trigger should backfill every canonical block — missing "
            f"{canonical_ids - present_blocks}, extra "
            f"{present_blocks - canonical_ids}"
        )

        audit_rows = await conn.fetch(
            """
            SELECT block_id, action, trigger_reason
              FROM allocation_template_audit
             WHERE organization_id = $1 AND profile = $2
            """,
            synthetic_org, synthetic_profile,
        )
        # 17 auto-inserts (the seed row is NOT audited — only the
        # trigger-inserted ones are).
        assert len(audit_rows) == 17, (
            f"expected 17 audit entries, got {len(audit_rows)}"
        )
        assert all(
            r["trigger_reason"] == "new_profile_created" for r in audit_rows
        )
        assert all(r["action"] == "inserted" for r in audit_rows)
        audited_blocks = {r["block_id"] for r in audit_rows}
        assert audited_blocks == canonical_ids - {seed_block}
    finally:
        await conn.execute(
            """
            DELETE FROM allocation_template_audit
             WHERE organization_id = $1 AND profile = $2
            """,
            synthetic_org, synthetic_profile,
        )
        await conn.execute(
            """
            DELETE FROM strategic_allocation
             WHERE organization_id = $1 AND profile = $2
            """,
            synthetic_org, synthetic_profile,
        )
        await conn.close()
