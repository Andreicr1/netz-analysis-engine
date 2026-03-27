"""ADV Part 2A brochure text sections with full-text search.

GLOBAL TABLE: No organization_id, no RLS.
Stores OCR-extracted text sections from ADV Part 2A brochure PDFs.
GIN index on tsvector(content) enables full-text search across manager philosophies.

depends_on: 0040 (sec_nport_holdings).
"""

import sqlalchemy as sa
from alembic import op

revision = "0041_sec_manager_brochure_text"
down_revision = "0040_sec_nport_holdings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sec_manager_brochure_text",
        sa.Column("crd_number", sa.Text(), sa.ForeignKey("sec_managers.crd_number", ondelete="CASCADE"), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("crd_number", "section", "filing_date"),
    )

    # GIN index on tsvector for full-text search
    op.execute(
        "CREATE INDEX ix_sec_brochure_text_fts "
        "ON sec_manager_brochure_text "
        "USING gin (to_tsvector('english', content))",
    )

    # Index for fast lookup by CRD
    op.create_index(
        "ix_sec_brochure_text_crd",
        "sec_manager_brochure_text",
        ["crd_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_sec_brochure_text_crd", table_name="sec_manager_brochure_text")
    op.drop_index("ix_sec_brochure_text_fts", table_name="sec_manager_brochure_text")
    op.drop_table("sec_manager_brochure_text")
