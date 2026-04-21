"""PR-A26.1 — ``run_mode`` column on portfolio_construction_runs.

Introduces the ``propose`` mode for the optimizer. Existing runs default
to ``realize`` (the only mode pre-A26). The new index supports the
``GET /portfolio/profiles/{profile}/latest-proposal`` query which sorts
by ``requested_at DESC`` filtered on ``run_mode = 'propose'``.

Reversible. The CHECK constraint and the supporting index are dropped
in the down-migration before the column is removed.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0154_portfolio_construction_run_mode"
down_revision = "0153_canonical_allocation_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "portfolio_construction_runs",
        sa.Column(
            "run_mode",
            sa.String(length=20),
            nullable=False,
            server_default="realize",
        ),
    )
    op.create_check_constraint(
        "ck_pcr_run_mode_valid",
        "portfolio_construction_runs",
        "run_mode IN ('realize', 'propose')",
    )
    op.create_index(
        "ix_pcr_run_mode_requested_at",
        "portfolio_construction_runs",
        ["run_mode", sa.text("requested_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pcr_run_mode_requested_at",
        table_name="portfolio_construction_runs",
    )
    op.drop_constraint(
        "ck_pcr_run_mode_valid",
        "portfolio_construction_runs",
        type_="check",
    )
    op.drop_column("portfolio_construction_runs", "run_mode")
