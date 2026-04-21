"""Blended benchmarks — global tables for composite benchmark composition.

Allows IC to define weighted combinations of allocation blocks as custom
benchmarks for each portfolio profile. NAV series computed dynamically
from benchmark_nav returns.

Global tables — no organization_id, no RLS.
"""

import sqlalchemy as sa

from alembic import op

revision = "0044_blended_benchmarks"
down_revision = "0043_esma_isin_ticker_fund_lei"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blended_benchmarks",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("portfolio_profile", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blended_benchmarks_profile", "blended_benchmarks", ["portfolio_profile"])

    op.create_table(
        "blended_benchmark_components",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("benchmark_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.String(80), nullable=False),
        sa.Column("weight", sa.Numeric(6, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["benchmark_id"], ["blended_benchmarks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["block_id"], ["allocation_blocks.block_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("benchmark_id", "block_id", name="uq_blended_component_benchmark_block"),
        sa.CheckConstraint("weight > 0 AND weight <= 1", name="ck_blended_component_weight_range"),
    )
    op.create_index(
        "ix_blended_benchmark_components_benchmark_id",
        "blended_benchmark_components",
        ["benchmark_id"],
    )


def downgrade() -> None:
    op.drop_table("blended_benchmark_components")
    op.drop_table("blended_benchmarks")
