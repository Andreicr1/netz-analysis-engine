"""Add indexes for screener performance on sec_managers, esma_funds, esma_managers.

sec_managers has 951K rows / 192 MB — screener filters on registration_status,
company_name, aum_total. Only investment companies are listed in the screener.

esma_funds (10K rows) — filters on domicile, fund_type.
esma_managers (658 rows) — filters on country, company_name.

depends_on: 0045 (instruments_global).
"""

from alembic import op

revision = "0046_screener_indexes"
down_revision = "0045_instruments_global"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sec_managers (951K rows) ──────────────────────────────────
    # Partial index: only investment companies (screener never queries advisers)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_managers_investment
        ON sec_managers (aum_total DESC NULLS LAST)
        WHERE registration_status = 'investment'
        """,
    )

    # Company name text search (trigram) for screener search box
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_managers_name_trgm
        ON sec_managers USING gin (firm_name gin_trgm_ops)
        """,
    )

    # Registration status for filtering
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sec_managers_reg_status
        ON sec_managers (registration_status)
        """,
    )

    # ── esma_funds (10K rows) ─────────────────────────────────────
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_esma_funds_domicile
        ON esma_funds (domicile)
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_esma_funds_fund_type
        ON esma_funds (fund_type)
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_esma_funds_domicile_type
        ON esma_funds (domicile, fund_type)
        """,
    )

    # ── esma_managers (658 rows) ──────────────────────────────────
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_esma_managers_country
        ON esma_managers (country)
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_esma_managers_name_trgm
        ON esma_managers USING gin (company_name gin_trgm_ops)
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_esma_managers_name_trgm")
    op.execute("DROP INDEX IF EXISTS idx_esma_managers_country")
    op.execute("DROP INDEX IF EXISTS idx_esma_funds_domicile_type")
    op.execute("DROP INDEX IF EXISTS idx_esma_funds_fund_type")
    op.execute("DROP INDEX IF EXISTS idx_esma_funds_domicile")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_reg_status")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_name_trgm")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_investment")
