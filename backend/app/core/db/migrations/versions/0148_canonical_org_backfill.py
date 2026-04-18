"""PR-A20 Section C — canonical org-scope backfill for 5 new tickers.

After migration 0147 seeded IVV, BND, TLT, SHY into
``instruments_universe`` and the Section-B trigger populated NAV
history for those four plus VTI, every wealth org still needs each
ticker in ``instruments_org`` with ``approval_status='approved'`` to
enter the optimizer universe.

This migration replays migration 0146's per-org × per-ticker INSERT
for the 5 tickers the earlier pass could not fully handle:

* VTI — already catalog-present; 0146 backfilled it when the ticker
  row existed, but this migration is safe to re-run (ON CONFLICT DO
  NOTHING on UNIQUE (organization_id, instrument_id)).
* IVV, BND, TLT, SHY — new in 0147.

Source flagged ``pr_a20_backfill`` for audit; downgrade removes only
rows this migration wrote. Block mapping reuses 0146's
``CANONICAL_BLOCK_MAP`` semantics.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0148_canonical_org_backfill"
down_revision = "0147_canonical_catalog_backfill"
branch_labels = None
depends_on = None


# Reuse 0146's block_id mapping. Scope limited to the 5 tickers that
# PR-A20 addresses. If an allocation_blocks row is missing, backfill
# proceeds with NULL block_id (non-blocking — operators remap in UI).
CANONICAL_BLOCK_MAP: dict[str, str | None] = {
    "VTI": "na_equity_large",
    "IVV": "na_equity_large",
    "BND": "fi_aggregate",
    "TLT": "fi_govt",
    "SHY": "fi_short_term",
}


def upgrade() -> None:
    conn = op.get_bind()

    resolved_map: dict[str, str | None] = {}
    for ticker, block_id in CANONICAL_BLOCK_MAP.items():
        # Skip tickers still absent from the catalog — 0147 covered the
        # known-missing ones, but guard against divergence in future
        # re-runs on partially-migrated clones.
        present = conn.execute(
            sa.text(
                "SELECT 1 FROM instruments_universe WHERE ticker = :t"
            ),
            {"t": ticker},
        ).scalar()
        if not present:
            print(
                f"WARNING pr_a20_catalog_missing ticker={ticker} — "
                "skipped from org backfill"
            )
            continue

        if block_id is None:
            resolved_map[ticker] = None
            continue
        exists = conn.execute(
            sa.text("SELECT 1 FROM allocation_blocks WHERE block_id = :bid"),
            {"bid": block_id},
        ).scalar()
        if not exists:
            print(
                f"WARNING pr_a20_block_missing ticker={ticker} "
                f"block_id={block_id} — inserting with NULL block_id"
            )
            resolved_map[ticker] = None
        else:
            resolved_map[ticker] = block_id

    for ticker, block_id in resolved_map.items():
        block_expr = "NULL" if block_id is None else f"'{block_id}'"
        op.execute(
            f"""
            INSERT INTO instruments_org
                (organization_id, instrument_id, block_id, approval_status,
                 source, block_overridden)
            SELECT
                o.id,
                iu.instrument_id,
                {block_expr},
                'approved',
                'pr_a20_backfill',
                FALSE
            FROM (
                SELECT DISTINCT organization_id AS id FROM instruments_org
                UNION
                SELECT DISTINCT organization_id AS id FROM model_portfolios
            ) o
            CROSS JOIN instruments_universe iu
            WHERE iu.ticker = '{ticker}'
            ON CONFLICT (organization_id, instrument_id) DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM instruments_org
        WHERE source = 'pr_a20_backfill'
        """
    )
