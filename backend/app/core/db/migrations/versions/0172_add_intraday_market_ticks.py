"""Add intraday market ticks hypertable and 1m candle CAGG.

Global market data table (no RLS, no organization_id) shared across tenants.

Revision ID: 0172_add_intraday_market_ticks
Revises: 0171_equity_characteristics_monthly
Create Date: 2026-04-21
"""

from alembic import op

revision = "0172_add_intraday_market_ticks"
down_revision = "0171_equity_characteristics_monthly"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE intraday_market_ticks (
            time        TIMESTAMPTZ NOT NULL,
            ticker      TEXT        NOT NULL,
            price       DOUBLE PRECISION NOT NULL,
            size        INTEGER     NOT NULL,
            source      TEXT        NOT NULL DEFAULT 'tiingo'
        );
    """)

    op.execute("""
        SELECT create_hypertable(
            'intraday_market_ticks',
            'time',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        );
    """)

    op.execute("""
        CREATE INDEX ix_intraday_market_ticks_ticker_time
            ON intraday_market_ticks (ticker, time DESC);
    """)

    op.execute("""
        ALTER TABLE intraday_market_ticks SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'ticker',
            timescaledb.compress_orderby = 'time DESC'
        );
    """)

    op.execute("""
        SELECT add_compression_policy(
            'intraday_market_ticks',
            INTERVAL '7 days'
        );
    """)

    op.execute("""
        CREATE MATERIALIZED VIEW market_candles_1m
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 minute', time) AS bucket,
            ticker,
            first(price, time)            AS open,
            max(price)                    AS high,
            min(price)                    AS low,
            last(price, time)             AS close,
            sum(size)                     AS volume
        FROM intraday_market_ticks
        GROUP BY bucket, ticker
        WITH NO DATA;
    """)

    op.execute("""
        SELECT add_continuous_aggregate_policy(
            'market_candles_1m',
            start_offset => INTERVAL '2 hours',
            end_offset => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute'
        );
    """)


def downgrade() -> None:
    op.execute("""
        SELECT remove_continuous_aggregate_policy(
            'market_candles_1m',
            if_exists => TRUE
        );
    """)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS market_candles_1m;")
    op.execute("""
        SELECT remove_compression_policy(
            'intraday_market_ticks',
            if_exists => TRUE
        );
    """)
    op.execute("DROP TABLE IF EXISTS intraday_market_ticks;")
