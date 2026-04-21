"""N-PORT holdings hypertable.

Stores monthly portfolio holdings from SEC N-PORT filings for US mutual funds.
Expands holdings coverage beyond 13F (institutional) to ~15K+ mutual funds.

GLOBAL TABLE: No organization_id, no RLS.
TimescaleDB hypertable partitioned by report_date (3-month chunks).
Compression: 3 months. segmentby: cik.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0039 (esma_tables).
"""

import os

import psycopg
import sqlalchemy as sa

from alembic import op

revision = "0040_sec_nport_holdings"
down_revision = "0039_esma_tables"
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
        "sec_nport_holdings",
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("cik", sa.Text(), nullable=False),
        sa.Column("cusip", sa.Text(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=True),
        sa.Column("issuer_name", sa.Text(), nullable=True),
        sa.Column("asset_class", sa.Text(), nullable=True),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("market_value", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("pct_of_nav", sa.Numeric(), nullable=True),
        sa.Column("is_restricted", sa.Boolean(), nullable=True),
        sa.Column("fair_value_level", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("report_date", "cik", "cusip"),
    )

    # Hypertable + compression must run outside transaction
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT create_hypertable("
            "  'sec_nport_holdings',"
            "  'report_date',"
            "  chunk_time_interval => INTERVAL '3 months',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")",
        )

        cursor.execute(
            "ALTER TABLE sec_nport_holdings SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'report_date DESC',"
            "  timescaledb.compress_segmentby = 'cik'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'sec_nport_holdings', INTERVAL '3 months', if_not_exists => true"
            ")",
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_nport_holdings_cik_date "
            "ON sec_nport_holdings (cik, report_date DESC)",
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sec_nport_holdings_cusip_date "
            "ON sec_nport_holdings (cusip, report_date DESC)",
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT remove_compression_policy('sec_nport_holdings', if_exists => true)",
        )
        cursor.execute(
            "SELECT decompress_chunk(c.chunk_name) "
            "FROM timescaledb_information.chunks c "
            "WHERE c.hypertable_name = 'sec_nport_holdings' "
            "AND c.is_compressed = true",
        )
        cursor.execute("DROP INDEX IF EXISTS idx_sec_nport_holdings_cik_date")
        cursor.execute("DROP INDEX IF EXISTS idx_sec_nport_holdings_cusip_date")
        cursor.close()

    op.drop_table("sec_nport_holdings")
