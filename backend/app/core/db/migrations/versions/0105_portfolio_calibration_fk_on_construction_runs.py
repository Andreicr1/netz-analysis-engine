"""FK portfolio_construction_runs.calibration_id → portfolio_calibration(id)

Phase 2 Task 2.6 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Adds the foreign key that was intentionally left out of migration
0099 (Phase 1 Task 1.3) to avoid a forward reference on a table
that did not yet exist. Now that ``portfolio_calibration`` has
landed in migration 0100, wire the FK.

Behavior on deletion
--------------------
``ON DELETE SET NULL`` — deleting a calibration preset does NOT
cascade to historical construction runs (we want to preserve the
audit trail). The run's ``calibration_snapshot`` JSONB column
carries the full calibration payload that was in force at run
time, so the loss of the ``calibration_id`` pointer is purely a
UX hint, not data loss.

Downgrade
---------
NO ``IF EXISTS``. Fail loudly if the FK is missing on downgrade
(indicates structural drift).

Revision ID: 0105_portfolio_calibration_fk_on_construction_runs
Revises: 0104_portfolio_alerts_backfill
Create Date: 2026-04-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0105_portfolio_calibration_fk_on_construction_runs"
down_revision: str | None = "0104_portfolio_alerts_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE portfolio_construction_runs
        ADD CONSTRAINT fk_pcr_calibration_id
        FOREIGN KEY (calibration_id)
        REFERENCES portfolio_calibration(id)
        ON DELETE SET NULL
        """,
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE portfolio_construction_runs
        DROP CONSTRAINT fk_pcr_calibration_id
        """,
    )
