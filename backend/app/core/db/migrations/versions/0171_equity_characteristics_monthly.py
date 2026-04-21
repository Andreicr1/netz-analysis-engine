"""Add equity_characteristics_monthly hypertable.

6 Kelly-Pruitt-Su characteristics derived from Tiingo Fundamentals + nav_timeseries.
Global table (no RLS, no organization_id) — shared across all tenants.

Revision ID: 0171_equity_characteristics_monthly
Revises: 0170_sec_xbrl_facts
Create Date: 2026-04-20
"""

from alembic import op

revision = "0171_equity_characteristics_monthly"
down_revision = "0170_sec_xbrl_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE equity_characteristics_monthly (
            instrument_id       UUID NOT NULL,
            ticker              TEXT NOT NULL,
            as_of               DATE NOT NULL,
            size_log_mkt_cap    NUMERIC(10,4),
            book_to_market      NUMERIC(10,4),
            mom_12_1            NUMERIC(10,4),
            quality_roa         NUMERIC(10,4),
            investment_growth   NUMERIC(10,4),
            profitability_gross NUMERIC(10,4),
            source_filing_date  DATE,
            computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (instrument_id, as_of)
        );
    """)

    op.execute("""
        SELECT create_hypertable(
            'equity_characteristics_monthly',
            'as_of',
            chunk_time_interval => INTERVAL '1 year',
            if_not_exists => TRUE
        );
    """)

    op.execute("""
        CREATE INDEX ix_equity_chars_ticker_as_of
            ON equity_characteristics_monthly (ticker, as_of DESC);
    """)

    op.execute("""
        ALTER TABLE equity_characteristics_monthly SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'instrument_id',
            timescaledb.compress_orderby = 'as_of DESC'
        );
    """)

    op.execute(
        "SELECT add_compression_policy('equity_characteristics_monthly', INTERVAL '2 years');"
    )


def downgrade() -> None:
    op.execute("SELECT remove_compression_policy('equity_characteristics_monthly', if_exists => true);")
    op.execute("DROP TABLE IF EXISTS equity_characteristics_monthly;")
