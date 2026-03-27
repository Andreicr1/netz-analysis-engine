"""OFR hedge fund monitor hypertable.

Stores OFR Hedge Fund Monitor data: leverage ratios, industry AUM,
strategy breakdowns, repo volumes, counterparty metrics, and stress scenarios.

GLOBAL TABLE: No organization_id, no RLS.
TimescaleDB hypertable partitioned by obs_date (3-month chunks).
Compression: 6 months. segmentby: series_id.
Wider chunks and longer compression because OFR data is mostly quarterly.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0036 (treasury_data_hypertable).
"""

import os

import psycopg
import sqlalchemy as sa
from alembic import op

revision = "0037_ofr_hedge_fund_hypertable"
down_revision = "0036_treasury_data_hypertable"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    op.create_table(
        "ofr_hedge_fund_data",
        sa.Column("obs_date", sa.Date(), nullable=False),
        sa.Column("series_id", sa.String(80), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="ofr_api"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("obs_date", "series_id"),
    )

    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT create_hypertable("
            "  'ofr_hedge_fund_data',"
            "  'obs_date',"
            "  chunk_time_interval => INTERVAL '3 months',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")",
        )

        cursor.execute(
            "ALTER TABLE ofr_hedge_fund_data SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'obs_date DESC',"
            "  timescaledb.compress_segmentby = 'series_id'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'ofr_hedge_fund_data', INTERVAL '6 months', if_not_exists => true"
            ")",
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ofr_hedge_fund_series_obs_date "
            "ON ofr_hedge_fund_data (series_id, obs_date DESC)",
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT remove_compression_policy('ofr_hedge_fund_data', if_exists => true)",
        )
        cursor.execute(
            "SELECT decompress_chunk(c.chunk_name) "
            "FROM timescaledb_information.chunks c "
            "WHERE c.hypertable_name = 'ofr_hedge_fund_data' "
            "AND c.is_compressed = true",
        )
        cursor.execute("DROP INDEX IF EXISTS idx_ofr_hedge_fund_series_obs_date")
        cursor.close()

    op.drop_table("ofr_hedge_fund_data")
