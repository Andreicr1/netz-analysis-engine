"""PR-A26.3.2 — authoritative-first strategy_label refresh infrastructure.

Adds two global, no-RLS infrastructure tables consumed by
``backend/scripts/refresh_authoritative_labels.py``:

* ``strategy_label_authoritative_backup`` — per-row capture of every
  ``instruments_universe.attributes->>'strategy_label'`` change made by a
  refresh run, keyed by ``run_id`` for atomic rollback.
* ``strategy_label_refresh_runs`` — one row per script invocation, dry-run
  or apply, with counters by source and the full JSON report inline.

No changes to ``instruments_universe`` schema — the refresh script writes
new ``strategy_label_source`` / ``strategy_label_source_table`` /
``strategy_label_refreshed_at`` keys via JSONB merge into
``attributes``.

Reversible. Both tables drop cleanly on downgrade.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0156_authoritative_label_refresh"
down_revision = "0155_strategic_allocation_approved_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE strategy_label_authoritative_backup (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL,
            instrument_id UUID NOT NULL,
            ticker TEXT,
            fund_name TEXT,
            previous_strategy_label TEXT,
            new_strategy_label TEXT,
            source_table TEXT NOT NULL,
            source_value TEXT NOT NULL,
            backed_up_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_strategy_label_backup_run "
        "ON strategy_label_authoritative_backup(run_id)"
    )
    op.execute(
        "CREATE INDEX ix_strategy_label_backup_instrument "
        "ON strategy_label_authoritative_backup(instrument_id)"
    )

    op.execute(
        """
        CREATE TABLE strategy_label_refresh_runs (
            run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            dry_run BOOLEAN NOT NULL DEFAULT TRUE,
            candidates_count INTEGER,
            mmf_applied INTEGER NOT NULL DEFAULT 0,
            etf_applied INTEGER NOT NULL DEFAULT 0,
            bdc_applied INTEGER NOT NULL DEFAULT 0,
            esma_applied INTEGER NOT NULL DEFAULT 0,
            tiingo_fallback_count INTEGER NOT NULL DEFAULT 0,
            null_flagged_count INTEGER NOT NULL DEFAULT 0,
            report_json JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategy_label_refresh_runs")
    op.execute("DROP INDEX IF EXISTS ix_strategy_label_backup_instrument")
    op.execute("DROP INDEX IF EXISTS ix_strategy_label_backup_run")
    op.execute("DROP TABLE IF EXISTS strategy_label_authoritative_backup")
