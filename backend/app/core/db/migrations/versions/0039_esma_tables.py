"""ESMA reference tables — managers, funds, ISIN ticker map.

Creates 3 global tables for European UCITS fund data from ESMA Register:
  - esma_managers: management companies from ESMA Register
  - esma_funds: UCITS funds linked to managers (FK on esma_manager_id)
  - esma_isin_ticker_map: resolved ISIN → Yahoo Finance ticker mappings

GLOBAL TABLES: No organization_id, no RLS.
Not hypertables — static reference data, not time-series.

depends_on: 0038 (manager_screener_indexes_continuous_aggs).
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_esma_tables"
down_revision = "0038_manager_screener_indexes_continuous_aggs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. esma_managers ──────────────────────────────────────────
    op.create_table(
        "esma_managers",
        sa.Column("esma_id", sa.Text, primary_key=True),
        sa.Column("lei", sa.Text, nullable=True),
        sa.Column("company_name", sa.Text, nullable=False),
        sa.Column("country", sa.Text, nullable=True),
        sa.Column("authorization_status", sa.Text, nullable=True),
        sa.Column("fund_count", sa.Integer, nullable=True),
        sa.Column("sec_crd_number", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "data_fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── 2. esma_funds ─────────────────────────────────────────────
    op.create_table(
        "esma_funds",
        sa.Column("isin", sa.Text, primary_key=True),
        sa.Column("fund_name", sa.Text, nullable=False),
        sa.Column(
            "esma_manager_id",
            sa.Text,
            sa.ForeignKey("esma_managers.esma_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domicile", sa.Text, nullable=True),
        sa.Column("fund_type", sa.Text, nullable=True),
        sa.Column(
            "host_member_states",
            sa.ARRAY(sa.Text),
            nullable=True,
        ),
        sa.Column("yahoo_ticker", sa.Text, nullable=True),
        sa.Column("ticker_resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "data_fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Index for manager-scoped lookups
    op.create_index(
        "idx_esma_funds_manager_id",
        "esma_funds",
        ["esma_manager_id"],
    )

    # Index for ticker-resolved funds
    op.create_index(
        "idx_esma_funds_yahoo_ticker",
        "esma_funds",
        ["yahoo_ticker"],
        postgresql_where=sa.text("yahoo_ticker IS NOT NULL"),
    )

    # ── 3. esma_isin_ticker_map ──────────────────────────────────
    op.create_table(
        "esma_isin_ticker_map",
        sa.Column("isin", sa.Text, primary_key=True),
        sa.Column("yahoo_ticker", sa.Text, nullable=True),
        sa.Column("exchange", sa.Text, nullable=True),
        sa.Column("resolved_via", sa.Text, nullable=False),
        sa.Column(
            "is_tradeable",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "last_verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Drop in reverse FK order
    op.drop_table("esma_isin_ticker_map")
    op.drop_table("esma_funds")
    op.drop_table("esma_managers")
