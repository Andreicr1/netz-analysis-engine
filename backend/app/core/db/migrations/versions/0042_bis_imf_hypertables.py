"""BIS + IMF hypertables for macro enrichment.

Stores BIS credit-to-GDP gap, debt service ratio, and property prices;
and IMF WEO 5-year forward GDP/inflation/fiscal forecasts.

GLOBAL TABLES: No organization_id, no RLS.
TimescaleDB hypertables partitioned by period (1-year chunks).
Compression: 1 year. segmentby: country_code.

Uses a separate DBAPI connection with autocommit because
create_hypertable() cannot run inside a transaction block.

depends_on: 0041 (sec_manager_brochure_text).
"""

import os

import psycopg
import sqlalchemy as sa
from alembic import op

revision = "0042_bis_imf_hypertables"
down_revision = "0041_sec_manager_brochure_text"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    # ── bis_statistics ────────────────────────────────────────────
    op.create_table(
        "bis_statistics",
        sa.Column("country_code", sa.Text(), nullable=False),
        sa.Column("indicator", sa.Text(), nullable=False),
        sa.Column("period", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("country_code", "indicator", "period"),
    )

    # ── imf_weo_forecasts ─────────────────────────────────────────
    op.create_table(
        "imf_weo_forecasts",
        sa.Column("country_code", sa.Text(), nullable=False),
        sa.Column("indicator", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("period", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=True),
        sa.Column("edition", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("country_code", "indicator", "year", "period"),
    )

    # Hypertable + compression must run outside transaction
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # ── bis_statistics hypertable ─────────────────────────────
        cursor.execute(
            "SELECT create_hypertable("
            "  'bis_statistics',"
            "  'period',"
            "  chunk_time_interval => INTERVAL '1 year',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")"
        )
        cursor.execute(
            "ALTER TABLE bis_statistics SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'period DESC',"
            "  timescaledb.compress_segmentby = 'country_code'"
            ")"
        )
        cursor.execute(
            "SELECT add_compression_policy("
            "  'bis_statistics', INTERVAL '1 year', if_not_exists => true"
            ")"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_bis_statistics_country_indicator_period "
            "ON bis_statistics (country_code, indicator, period DESC)"
        )

        # ── imf_weo_forecasts hypertable ──────────────────────────
        cursor.execute(
            "SELECT create_hypertable("
            "  'imf_weo_forecasts',"
            "  'period',"
            "  chunk_time_interval => INTERVAL '1 year',"
            "  migrate_data => true,"
            "  if_not_exists => true"
            ")"
        )
        cursor.execute(
            "ALTER TABLE imf_weo_forecasts SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'period DESC',"
            "  timescaledb.compress_segmentby = 'country_code'"
            ")"
        )
        cursor.execute(
            "SELECT add_compression_policy("
            "  'imf_weo_forecasts', INTERVAL '1 year', if_not_exists => true"
            ")"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_imf_weo_forecasts_country_indicator_period "
            "ON imf_weo_forecasts (country_code, indicator, period DESC)"
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # ── bis_statistics ────────────────────────────────────────
        cursor.execute(
            "SELECT remove_compression_policy('bis_statistics', if_exists => true)"
        )
        cursor.execute(
            "SELECT decompress_chunk(c.chunk_name) "
            "FROM timescaledb_information.chunks c "
            "WHERE c.hypertable_name = 'bis_statistics' "
            "AND c.is_compressed = true"
        )
        cursor.execute("DROP INDEX IF EXISTS idx_bis_statistics_country_indicator_period")

        # ── imf_weo_forecasts ─────────────────────────────────────
        cursor.execute(
            "SELECT remove_compression_policy('imf_weo_forecasts', if_exists => true)"
        )
        cursor.execute(
            "SELECT decompress_chunk(c.chunk_name) "
            "FROM timescaledb_information.chunks c "
            "WHERE c.hypertable_name = 'imf_weo_forecasts' "
            "AND c.is_compressed = true"
        )
        cursor.execute("DROP INDEX IF EXISTS idx_imf_weo_forecasts_country_indicator_period")

        cursor.close()

    op.drop_table("imf_weo_forecasts")
    op.drop_table("bis_statistics")
