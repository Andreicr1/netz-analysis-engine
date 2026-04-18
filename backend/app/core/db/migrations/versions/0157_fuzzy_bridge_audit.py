"""PR-A26.3.3 — fuzzy bridge audit infrastructure.

Adds two pieces of audit scaffolding consumed by A26.3.3 scripts:

* ``sec_etfs.strategy_label_source`` — TEXT column recording whether
  ``strategy_label`` came from SEC bulk ingestion (``'sec_bulk'``) or
  from the Tiingo description cascade backfill
  (``'tiingo_cascade'``) or remained unclassified (``'unclassified'``).
  NULL before the backfill runs.
* ``sec_mmf_bridge_candidates`` — per-match audit for
  ``backend/scripts/bridge_mmf_catalog.py``. Auto-applied rows are
  stamped with ``applied_at``; needs-review rows stay open until the
  operator resolves them manually.

Both objects are global, no RLS. Reversible.
"""
from __future__ import annotations

from alembic import op

revision = "0157_fuzzy_bridge_audit"
down_revision = "0156_authoritative_label_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sec_etfs ADD COLUMN IF NOT EXISTS strategy_label_source TEXT"
    )

    op.execute(
        """
        CREATE TABLE sec_mmf_bridge_candidates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            instrument_id UUID NOT NULL,
            instrument_name TEXT NOT NULL,
            matched_cik TEXT NOT NULL,
            matched_series_id TEXT NOT NULL,
            matched_fund_name TEXT NOT NULL,
            score NUMERIC(5,4) NOT NULL,
            match_tier TEXT NOT NULL,
            applied_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_mmf_bridge_instrument "
        "ON sec_mmf_bridge_candidates(instrument_id)"
    )
    op.execute(
        "CREATE INDEX ix_mmf_bridge_tier "
        "ON sec_mmf_bridge_candidates(match_tier) "
        "WHERE applied_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_mmf_bridge_tier")
    op.execute("DROP INDEX IF EXISTS ix_mmf_bridge_instrument")
    op.execute("DROP TABLE IF EXISTS sec_mmf_bridge_candidates")
    op.execute("ALTER TABLE sec_etfs DROP COLUMN IF EXISTS strategy_label_source")
