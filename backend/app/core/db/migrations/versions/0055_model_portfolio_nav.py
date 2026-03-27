"""Create model_portfolio_nav hypertable for synthetic NAV time series.

Enables model portfolios to be treated as independent funds (polymorphism)
for analytics, charting, and eVestment-grade statistics.

ORG-SCOPED: has organization_id + RLS.
"""

revision = "0055_model_portfolio_nav"
down_revision = "0054_sec_registered_funds"

from alembic import op


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS model_portfolio_nav (
            portfolio_id     UUID        NOT NULL REFERENCES model_portfolios(id) ON DELETE CASCADE,
            nav_date         DATE        NOT NULL,
            nav              NUMERIC(18,6) NOT NULL,
            daily_return     NUMERIC(12,8),
            organization_id  TEXT        NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (portfolio_id, nav_date)
        );
    """)

    # TimescaleDB hypertable — 1-month chunks, partitioned by nav_date
    op.execute("""
        SELECT create_hypertable(
            'model_portfolio_nav',
            'nav_date',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    """)

    # Indexes for common query patterns
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_model_portfolio_nav_portfolio_date
            ON model_portfolio_nav (portfolio_id, nav_date DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_model_portfolio_nav_org
            ON model_portfolio_nav (organization_id);
    """)

    # NOTE: Compression skipped — PG18 + TimescaleDB does not allow columnstore
    # on hypertables with RLS enabled. RLS is mandatory for multi-tenant isolation.
    # Compression can be revisited when TimescaleDB lifts this restriction.

    # RLS
    op.execute("ALTER TABLE model_portfolio_nav ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'model_portfolio_nav'
                  AND policyname = 'model_portfolio_nav_org_isolation'
            ) THEN
                CREATE POLICY model_portfolio_nav_org_isolation ON model_portfolio_nav
                    USING (organization_id = (SELECT current_setting('app.current_organization_id', TRUE)))
                    WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id', TRUE)));
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS model_portfolio_nav_org_isolation ON model_portfolio_nav;")
    op.execute("DROP TABLE IF EXISTS model_portfolio_nav CASCADE;")
