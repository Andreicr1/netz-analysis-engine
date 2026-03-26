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

    # RLS
    op.execute("ALTER TABLE model_portfolio_nav ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY model_portfolio_nav_org_isolation ON model_portfolio_nav
            USING (organization_id = (SELECT current_setting('app.current_organization_id', TRUE)))
            WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id', TRUE)));
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

    # Compression policy — compress after 3 months, segment by portfolio_id
    op.execute("""
        ALTER TABLE model_portfolio_nav SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'portfolio_id,organization_id',
            timescaledb.compress_orderby = 'nav_date DESC'
        );
    """)
    op.execute("""
        SELECT add_compression_policy('model_portfolio_nav', INTERVAL '3 months', if_not_exists => TRUE);
    """)


def downgrade() -> None:
    op.execute("SELECT remove_compression_policy('model_portfolio_nav', if_not_exists => TRUE);")
    op.execute("DROP POLICY IF EXISTS model_portfolio_nav_org_isolation ON model_portfolio_nav;")
    op.execute("DROP TABLE IF EXISTS model_portfolio_nav CASCADE;")
