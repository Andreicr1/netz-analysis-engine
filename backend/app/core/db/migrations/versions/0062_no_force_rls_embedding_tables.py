"""NO FORCE RLS on dd_chapters, dd_reports, macro_reviews.

FORCE ROW LEVEL SECURITY makes RLS apply even to the table owner
(tsdbadmin on Timescale Cloud). The wealth_embedding_worker runs
as table owner and needs to read all orgs without SET LOCAL hacks.

NO FORCE lets the owner bypass RLS while normal sessions (routes)
that set app.current_organization_id via get_db_with_rls remain
fully protected by the org_isolation policy.

Revision ID: 0062_no_force_rls_embedding_tables
Revises: 0061_macro_regime_history
Create Date: 2026-03-28
"""

from alembic import op

revision = "0062_no_force_rls_embedding_tables"
down_revision = "0061_macro_regime_history"
branch_labels = None
depends_on = None

_TABLES = ["dd_chapters", "dd_reports", "macro_reviews"]


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
