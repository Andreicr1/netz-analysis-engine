"""CUSIP → Ticker mapping table for YFinance price lookups.

Reference/lookup table (not a hypertable — not time series).
GLOBAL TABLE: No organization_id, no RLS.
Populated by sec seed Phase 6 via OpenFIGI batch API.

depends_on: 0032 (hypertable_skip_documentation).
"""

from alembic import op
import sqlalchemy as sa

revision = "0033_sec_cusip_ticker_map"
down_revision = "0032_hypertable_skip_docs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sec_cusip_ticker_map",
        sa.Column("cusip", sa.Text, primary_key=True),
        sa.Column("ticker", sa.Text, nullable=True),
        sa.Column("issuer_name", sa.Text, nullable=True),
        sa.Column("exchange", sa.Text, nullable=True),
        sa.Column("security_type", sa.Text, nullable=True),
        sa.Column("figi", sa.Text, nullable=True),
        sa.Column("composite_figi", sa.Text, nullable=True),
        sa.Column("resolved_via", sa.Text, nullable=False),
        sa.Column("is_tradeable", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "last_verified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Lookup by ticker (reverse: find all CUSIPs for a ticker)
    op.create_index(
        "idx_cusip_ticker_map_ticker",
        "sec_cusip_ticker_map",
        ["ticker"],
        postgresql_where=sa.text("ticker IS NOT NULL"),
    )

    # Find untradeable/unresolved for retry
    op.create_index(
        "idx_cusip_ticker_map_unresolved",
        "sec_cusip_ticker_map",
        ["resolved_via"],
        postgresql_where=sa.text("resolved_via = 'unresolved'"),
    )


def downgrade() -> None:
    op.drop_index("idx_cusip_ticker_map_unresolved", table_name="sec_cusip_ticker_map")
    op.drop_index("idx_cusip_ticker_map_ticker", table_name="sec_cusip_ticker_map")
    op.drop_table("sec_cusip_ticker_map")
