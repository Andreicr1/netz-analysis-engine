"""Add sec_entity_links table for RIA-to-13F-filer linkage.

The sec_entity_links table maps Registered advisers (RIAs) to their parent
13F filers, subsidiary entities, and managed funds. This is the critical
linkage that connects RIAs to their holdings data — RIAs file ADV with one
CIK, while parent holding companies file 13F with a different CIK.
"""

from alembic import op

revision = "0052_sec_entity_links"
down_revision = "0051_sec_mgr_fund_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sec_entity_links (
            id SERIAL PRIMARY KEY,
            manager_crd TEXT NOT NULL REFERENCES sec_managers(crd_number) ON DELETE CASCADE,
            related_cik TEXT NOT NULL,
            relationship TEXT NOT NULL,
            related_name TEXT,
            source TEXT NOT NULL,
            confidence FLOAT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (manager_crd, related_cik, relationship)
        )
    """)
    op.execute("CREATE INDEX idx_sec_entity_links_crd ON sec_entity_links (manager_crd)")
    op.execute("CREATE INDEX idx_sec_entity_links_cik ON sec_entity_links (related_cik)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sec_entity_links")
