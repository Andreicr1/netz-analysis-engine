"""Treasury fiscal data hypertable.

Stores US Treasury rates, debt snapshots, auction results, exchange rates,
and interest expense from the Treasury Fiscal Data API.

GLOBAL TABLE: No organization_id, no RLS.
TimescaleDB hypertable partitioned by obs_date (1-month chunks).
Compression: 3 months. segmentby: series_id.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0035 (fund_risk_metrics_momentum).
"""

import os

import psycopg
import sqlalchemy as sa
from alembic import op

revision = "0036_treasury_data_hypertable"
down_revision = "0035_fund_risk_metrics_momentum"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    # Create table via Alembic (inside transaction)
    op.create_table(
        "treasury_data",
        sa.Column("obs_date", sa.Date(), nullable=False),
        sa.Column("series_id", sa.String(80), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="treasury_api"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("obs_date", "series_id"),
    )

    # Hypertable + compression must run outside transaction
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT create_hypertable("
            "  'treasury_data',"
            "  'obs_date',"
            "  chunk_time_interval => INTERVAL '1 month',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")",
        )

        cursor.execute(
            "ALTER TABLE treasury_data SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'obs_date DESC',"
            "  timescaledb.compress_segmentby = 'series_id'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'treasury_data', INTERVAL '3 months', if_not_exists => true"
            ")",
        )

        # Index for querying a specific series by date range
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_treasury_data_series_obs_date "
            "ON treasury_data (series_id, obs_date DESC)",
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT remove_compression_policy('treasury_data', if_exists => true)",
        )
        cursor.execute(
            "SELECT decompress_chunk(c.chunk_name) "
            "FROM timescaledb_information.chunks c "
            "WHERE c.hypertable_name = 'treasury_data' "
            "AND c.is_compressed = true",
        )
        cursor.execute("DROP INDEX IF EXISTS idx_treasury_data_series_obs_date")
        cursor.close()

    op.drop_table("treasury_data")
