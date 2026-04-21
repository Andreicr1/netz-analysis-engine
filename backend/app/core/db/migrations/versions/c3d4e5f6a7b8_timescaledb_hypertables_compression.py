"""TimescaleDB hypertables + compression for nav_timeseries and fund_risk_metrics

TimescaleDB compression (columnstore) is incompatible with PostgreSQL RLS.
Uses a separate DBAPI connection to bypass Alembic's transaction management.

RLS is NOT re-enabled (incompatible with compression). Tenant isolation
for these tables is enforced at the application level via
WHERE organization_id = :org_id (mandated by CLAUDE.md).

NOTE: run during low-traffic window in production (migrate_data rewrites
the entire table and blocks writes during conversion).

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-18
"""

import logging

import psycopg
from sqlalchemy import text

from alembic import op

logger = logging.getLogger(__name__)

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

_HYPERTABLE_TABLES = [
    {
        "table": "nav_timeseries",
        "time_col": "nav_date",
        "compress_orderby": "nav_date DESC",
    },
    {
        "table": "fund_risk_metrics",
        "time_col": "calc_date",
        "compress_orderby": "calc_date DESC",
    },
]


def _has_timescaledb(bind) -> bool:
    """Check if TimescaleDB extension is available."""
    result = bind.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'"),
    )
    return result.scalar() is not None


def _get_conninfo(bind) -> str:
    """Get psycopg-compatible connection string from the SQLAlchemy engine.

    ``alembic_dbapi.info.dsn`` strips the password for security, so we
    derive the conninfo from the engine URL instead.
    """
    url = bind.engine.url.render_as_string(hide_password=False)
    # Strip SQLAlchemy dialect prefix → standard postgresql://
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgresql+asyncpg://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    return url


def upgrade() -> None:
    bind = op.get_bind()

    # Skip gracefully when TimescaleDB is not installed (CI, plain PG).
    if not _has_timescaledb(bind):
        logger.info("TimescaleDB extension not found — skipping hypertable creation")
        return

    # We need a separate autocommit connection because create_hypertable
    # with migrate_data cannot run inside a transaction block.
    conninfo = _get_conninfo(bind)
    bind.execute(text("COMMIT"))

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # Phase 1: Drop RLS (incompatible with compression)
        for spec in _HYPERTABLE_TABLES:
            table = spec["table"]
            cursor.execute(f"DROP POLICY IF EXISTS org_isolation ON {table}")
            cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
            cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")

        # Phase 2: Create hypertables + compression
        for spec in _HYPERTABLE_TABLES:
            table = spec["table"]
            time_col = spec["time_col"]
            orderby = spec["compress_orderby"]

            cursor.execute(
                f"SELECT create_hypertable('{table}', '{time_col}', "
                f"migrate_data => true, if_not_exists => true)",
            )
            cursor.execute(
                f"ALTER TABLE {table} SET ("
                f"  timescaledb.compress,"
                f"  timescaledb.compress_segmentby = 'organization_id',"
                f"  timescaledb.compress_orderby = '{orderby}'"
                f")",
            )
            cursor.execute(
                f"SELECT add_compression_policy('{table}', "
                f"INTERVAL '30 days', if_not_exists => true)",
            )

        cursor.close()


def downgrade() -> None:
    for spec in reversed(_HYPERTABLE_TABLES):
        table = spec["table"]
        op.execute(
            f"SELECT remove_compression_policy('{table}', if_exists => true)",
        )
        op.execute(
            f"ALTER TABLE {table} SET (timescaledb.compress = false)",
        )
    # NOTE: TimescaleDB does not support reverting a hypertable back to a
    # regular table. The tables remain hypertables after downgrade but
    # without compression.
