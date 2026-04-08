"""discovery FCL keyset indexes

Revision ID: 0096_discovery_fcl_keyset_indexes
Revises: 0095_mv_unified_funds_share_class
Create Date: 2026-04-08

Adds composite indexes supporting keyset pagination for the Discovery
Fund/Manager three-column layout:

  - `idx_sec_managers_aum_crd` — powers col1 (managers ordered by AUM desc,
    tiebroken by crd_number asc). Partial on `aum_total IS NOT NULL` to skip
    rows without reported AUM.

  - `idx_mv_unified_funds_mgr_aum` — powers col2 (funds for a given manager
    ordered by aum_usd desc). Partial on `manager_id IS NOT NULL` to exclude
    registered/ETF/BDC/MMF branches that do not carry a manager link.

Note: `CREATE INDEX CONCURRENTLY` is NOT used — Alembic runs migrations
inside a transaction, which is incompatible with CONCURRENTLY. On prod the
keyset indexes should be re-created manually with CONCURRENTLY if the tables
are large and locking is a concern.
"""
from alembic import op

revision = "0096_discovery_fcl_keyset_indexes"
down_revision = "0095_mv_unified_funds_share_class"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_managers_aum_crd
          ON sec_managers (aum_total DESC NULLS LAST, crd_number ASC)
          WHERE aum_total IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mv_unified_funds_mgr_aum
          ON mv_unified_funds (manager_id, aum_usd DESC NULLS LAST)
          WHERE manager_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_mv_unified_funds_mgr_aum")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_aum_crd")
