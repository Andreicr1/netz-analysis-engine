"""Add macro_regime_history hypertable for HMM regime persistence.

Global table (no organization_id, no RLS) — stores full HMM-classified
regime series from regime_fit worker.  Consumed by risk_calc for
regime-conditional CVaR instead of VIX threshold proxy.

Revision ID: 0061_macro_regime_history
Revises: 0060_portfolio_views
Create Date: 2026-03-27
"""

from alembic import op

revision = "0061_macro_regime_history"
down_revision = "0060_portfolio_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS macro_regime_history (
            regime_date DATE NOT NULL,
            p_low_vol DOUBLE PRECISION NOT NULL,
            p_high_vol DOUBLE PRECISION NOT NULL,
            classified_regime TEXT NOT NULL,
            vix_value DOUBLE PRECISION,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (regime_date)
        )
    """)

    # create_hypertable requires autocommit — same pattern as migrations 0025, 0038
    conn = op.get_bind().connection.dbapi_connection
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute("""
        SELECT create_hypertable(
            'macro_regime_history', 'regime_date',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE
        )
    """)
    cursor.execute("""
        ALTER TABLE macro_regime_history SET (
            timescaledb.compress,
            timescaledb.compress_orderby = 'regime_date DESC'
        )
    """)
    cursor.execute("""
        SELECT add_compression_policy(
            'macro_regime_history',
            INTERVAL '3 months',
            if_not_exists => TRUE
        )
    """)
    conn.autocommit = False

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_macro_regime_history_date_regime
        ON macro_regime_history (regime_date DESC, classified_regime)
        WITH (timescaledb.transaction_per_chunk)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS macro_regime_history CASCADE")
