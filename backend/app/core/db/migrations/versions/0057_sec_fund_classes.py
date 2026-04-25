"""Create sec_fund_classes table — one row per share class.

GLOBAL TABLE: No organization_id, no RLS.
FK to sec_registered_funds(cik) ON DELETE CASCADE.
"""

revision = "0057_sec_fund_classes"
down_revision = "0056_wealth_content"

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.create_table(
        "sec_fund_classes",
        sa.Column("cik", sa.Text, sa.ForeignKey("sec_registered_funds.cik", ondelete="CASCADE"), nullable=False),
        sa.Column("series_id", sa.Text, nullable=False),
        sa.Column("series_name", sa.Text),
        sa.Column("class_id", sa.Text, nullable=False),
        sa.Column("class_name", sa.Text),
        sa.Column("ticker", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("data_fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("cik", "series_id", "class_id"),
    )
    op.create_index("ix_sec_fund_classes_ticker", "sec_fund_classes", ["ticker"], postgresql_where=sa.text("ticker IS NOT NULL"))
    op.create_index("ix_sec_fund_classes_cik", "sec_fund_classes", ["cik"])


def downgrade() -> None:
    op.drop_index("ix_sec_fund_classes_cik", table_name="sec_fund_classes")
    op.drop_index("ix_sec_fund_classes_ticker", table_name="sec_fund_classes")
    op.drop_table("sec_fund_classes")
