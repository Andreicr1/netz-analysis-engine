"""Add index on sec_13f_holdings(cik) for manager search join performance.

The US Fund Analysis search does outerjoin with GROUP BY cik on sec_13f_holdings
(1M+ rows). Without a dedicated index, this requires full hypertable scan.
TimescaleDB automatically includes hypertable chunks in the index.
"""

from alembic import op

revision = "0050_sec_13f_cik_index"
down_revision = "0049_wealth_continuous_aggregates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index on cik for GROUP BY cik (13F join in manager search)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_13f_holdings_cik
        ON sec_13f_holdings (cik)
        """,
    )
    # Also index sec_managers.cik for the join condition
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_managers_cik
        ON sec_managers (cik)
        WHERE cik IS NOT NULL
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_cik")
    op.execute("DROP INDEX IF EXISTS idx_sec_13f_holdings_cik")
