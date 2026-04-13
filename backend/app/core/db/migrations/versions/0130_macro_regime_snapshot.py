"""Global daily regime snapshot — market conditions shared across all tenants.

One row per as_of_date. Computed by global_regime_detection worker after
macro_ingestion. Read by risk_calc worker to avoid redundant per-org
classification.

Revision ID: 0130_macro_regime_snapshot
Revises: 0129_elite_regime_flags
Create Date: 2026-04-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0130_macro_regime_snapshot"
down_revision = "0129_elite_regime_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "macro_regime_snapshot",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("raw_regime", sa.String(20), nullable=False),
        sa.Column("stress_score", sa.Numeric(5, 1), nullable=True),
        sa.Column("signal_details", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("as_of_date", name="uq_macro_regime_snapshot_date"),
    )

    op.create_index(
        "ix_macro_regime_snapshot_date_desc",
        "macro_regime_snapshot",
        [sa.text("as_of_date DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_macro_regime_snapshot_date_desc", table_name="macro_regime_snapshot")
    op.drop_table("macro_regime_snapshot")
