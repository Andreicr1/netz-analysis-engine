"""TimescaleDB hypertables + compression for nav_timeseries and fund_risk_metrics

Converts time-series tables to TimescaleDB hypertables with compression
policies. compress_segmentby='organization_id' per CLAUDE.md requirements.

-- NOTE: run during low-traffic window in production (migrate_data rewrites
-- the entire table and blocks writes during conversion).

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-18
"""
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── nav_timeseries → hypertable ──────────────────────────────────────
    op.execute(
        "SELECT create_hypertable('nav_timeseries', 'nav_date', "
        "migrate_data => true, if_not_exists => true)"
    )
    op.execute(
        "ALTER TABLE nav_timeseries SET ("
        "  timescaledb.compress,"
        "  timescaledb.compress_segmentby = 'organization_id',"
        "  timescaledb.compress_orderby = 'nav_date DESC'"
        ")"
    )
    op.execute(
        "SELECT add_compression_policy('nav_timeseries', "
        "INTERVAL '30 days', if_not_exists => true)"
    )

    # ── fund_risk_metrics → hypertable ───────────────────────────────────
    op.execute(
        "SELECT create_hypertable('fund_risk_metrics', 'calc_date', "
        "migrate_data => true, if_not_exists => true)"
    )
    op.execute(
        "ALTER TABLE fund_risk_metrics SET ("
        "  timescaledb.compress,"
        "  timescaledb.compress_segmentby = 'organization_id',"
        "  timescaledb.compress_orderby = 'calc_date DESC'"
        ")"
    )
    op.execute(
        "SELECT add_compression_policy('fund_risk_metrics', "
        "INTERVAL '30 days', if_not_exists => true)"
    )


def downgrade() -> None:
    # Remove compression policies first, then decompress
    op.execute(
        "SELECT remove_compression_policy('fund_risk_metrics', if_exists => true)"
    )
    op.execute(
        "ALTER TABLE fund_risk_metrics SET (timescaledb.compress = false)"
    )

    op.execute(
        "SELECT remove_compression_policy('nav_timeseries', if_exists => true)"
    )
    op.execute(
        "ALTER TABLE nav_timeseries SET (timescaledb.compress = false)"
    )
    # NOTE: TimescaleDB does not support reverting a hypertable back to a
    # regular table. The tables remain hypertables after downgrade but
    # without compression.
