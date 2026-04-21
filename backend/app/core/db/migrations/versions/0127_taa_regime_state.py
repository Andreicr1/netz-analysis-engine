"""TAA regime state — daily snapshots of smoothed allocation centers.

Stores per-org+profile daily regime classification, EMA-smoothed
asset-class centers, and effective optimizer bands. Read by the
construction pipeline to resolve dynamic BlockConstraint bounds.

Revision ID: 0127_taa_regime_state
Revises: 0126_seed_na_equity_large_block
Create Date: 2026-04-12
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0127_taa_regime_state"
down_revision = "0126_seed_na_equity_large_block"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taa_regime_state",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("raw_regime", sa.String(20), nullable=False),
        sa.Column("stress_score", sa.Numeric(5, 1)),
        sa.Column("smoothed_centers", JSONB, nullable=False),
        sa.Column("effective_bands", JSONB, nullable=False),
        sa.Column("transition_velocity", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "profile", "as_of_date",
            name="uq_taa_regime_state_org_profile_date",
        ),
    )

    # Index for fast lookup in construction pipeline
    op.create_index(
        "ix_taa_regime_state_org_profile_date",
        "taa_regime_state",
        ["organization_id", "profile", sa.text("as_of_date DESC")],
    )

    # RLS policy — org-scoped
    op.execute("""
        ALTER TABLE taa_regime_state ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        CREATE POLICY taa_regime_state_rls ON taa_regime_state
            USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS taa_regime_state_rls ON taa_regime_state")
    op.execute("ALTER TABLE taa_regime_state DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_taa_regime_state_org_profile_date", table_name="taa_regime_state")
    op.drop_table("taa_regime_state")
