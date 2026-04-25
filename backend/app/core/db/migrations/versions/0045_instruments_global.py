"""Global instruments table — bonds, equities, ETFs shared across all tenants.

Mirrors instruments_universe but WITHOUT organization_id / RLS.
Populated by seed_instruments_global.py via yfinance.
The screener union_all includes this as the third source alongside
instruments_universe (org-scoped) and esma_funds (UCITS).

GLOBAL TABLE: No organization_id, no RLS.
Natural PK on ticker (Yahoo Finance ticker is globally unique per instrument).

depends_on: 0044 (blended_benchmarks).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0045_instruments_global"
down_revision = "0044_blended_benchmarks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instruments_global",
        sa.Column("ticker",          sa.Text(),                  nullable=False),
        sa.Column("isin",            sa.Text()),
        sa.Column("name",            sa.Text(),                  nullable=False),
        sa.Column("instrument_type", sa.Text(),                  nullable=False),
        sa.Column("asset_class",     sa.Text(),                  nullable=False),
        sa.Column("geography",       sa.Text(),                  nullable=False, server_default="us"),
        sa.Column("currency",        sa.Text(),                  nullable=False, server_default="USD"),
        sa.Column("exchange",        sa.Text()),
        sa.Column("sector",          sa.Text()),
        sa.Column("market_cap",      sa.BigInteger()),
        sa.Column("attributes",      postgresql.JSONB(),          nullable=False, server_default="{}"),
        sa.Column("source",          sa.Text(),                  nullable=False, server_default="yfinance"),
        sa.Column("is_active",       sa.Boolean(),               nullable=False, server_default="true"),
        sa.Column("last_updated",    sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at",      sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("ticker"),
    )
    op.create_index("ix_instruments_global_instrument_type", "instruments_global", ["instrument_type"])
    op.create_index("ix_instruments_global_asset_class",     "instruments_global", ["asset_class"])
    op.create_index("ix_instruments_global_geography",       "instruments_global", ["geography"])
    op.create_index("ix_instruments_global_isin",            "instruments_global", ["isin"],
                    postgresql_where=sa.text("isin IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_instruments_global_isin",            table_name="instruments_global")
    op.drop_index("ix_instruments_global_geography",       table_name="instruments_global")
    op.drop_index("ix_instruments_global_asset_class",     table_name="instruments_global")
    op.drop_index("ix_instruments_global_instrument_type", table_name="instruments_global")
    op.drop_table("instruments_global")
