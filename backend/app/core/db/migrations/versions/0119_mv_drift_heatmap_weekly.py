"""mv_drift_heatmap_weekly continuous aggregate.

Weekly bucket of strategy_drift_alerts per
(organization_id, instrument_id, week_start). Dashboard / alerts
heatmap reads from this CAGG instead of aggregating raw
``strategy_drift_alerts`` on every request.

Schema notes (audited 2026-04-11 against live
``strategy_drift_alerts`` — the brief's placeholders ``portfolio_id``,
``fund_id``, ``drift_score`` and ``created_at`` do NOT exist on this
table; the real columns are ``organization_id``, ``instrument_id``,
``drift_magnitude``, ``detected_at``, ``severity`` (enum)).

``strategy_drift_alerts`` is already a hypertable partitioned on
``detected_at``, which is the required precondition for a
continuous aggregate.

Bucket: ISO week via ``time_bucket('1 week', detected_at)``.
Refresh policy: 6-month rolling history, 1-day lag, refresh every
4 hours.

Aggregates (all CAGG-safe — no FILTER clauses, no subqueries):
- alert_count           = COUNT(*)
- severe_count          = SUM(CASE severity='severe' THEN 1 ELSE 0)
- moderate_count        = SUM(CASE severity='moderate' THEN 1 ELSE 0)
- max_drift_magnitude   = MAX(drift_magnitude)
- avg_drift_magnitude   = AVG(drift_magnitude)

Index: ``(organization_id, week_start DESC)`` supports the
dashboard's "show me this tenant's latest N weeks" query. The
dashboard MUST include ``WHERE organization_id = :org`` because
continuous aggregates do not inherit RLS from the source hypertable.

Uses the DDL-in-autocommit pattern matching 0049 — CAGG DDL cannot
run inside a transaction block.

Revision ID: 0119_mv_drift_heatmap_weekly
Revises: 0118_mv_construction_run_diff
Create Date: 2026-04-11
"""
from __future__ import annotations

import os
from collections.abc import Sequence

import psycopg

from alembic import op

revision: str = "0119_mv_drift_heatmap_weekly"
down_revision: str | None = "0118_mv_construction_run_diff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    dbapi = op.get_bind().connection.dbapi_connection
    assert dbapi is not None, "Alembic bind has no live DBAPI connection"
    return str(dbapi.info.dsn)


def upgrade() -> None:
    conninfo = _autocommit_conninfo()
    dbapi = op.get_bind().connection.dbapi_connection
    assert dbapi is not None
    dbapi.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS mv_drift_heatmap_weekly
            WITH (timescaledb.continuous) AS
            SELECT
                organization_id,
                instrument_id,
                time_bucket('1 week', detected_at) AS week_start,
                COUNT(*) AS alert_count,
                SUM(CASE WHEN severity = 'severe'   THEN 1 ELSE 0 END) AS severe_count,
                SUM(CASE WHEN severity = 'moderate' THEN 1 ELSE 0 END) AS moderate_count,
                MAX(drift_magnitude) AS max_drift_magnitude,
                AVG(drift_magnitude) AS avg_drift_magnitude
            FROM strategy_drift_alerts
            GROUP BY
                organization_id,
                instrument_id,
                time_bucket('1 week', detected_at)
            WITH NO DATA
            """,
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mv_drift_heatmap_weekly_org_week
            ON mv_drift_heatmap_weekly (organization_id, week_start DESC)
            """,
        )

        cursor.execute(
            """
            SELECT add_continuous_aggregate_policy(
                'mv_drift_heatmap_weekly',
                start_offset      => INTERVAL '6 months',
                end_offset        => INTERVAL '1 day',
                schedule_interval => INTERVAL '4 hours',
                if_not_exists     => true
            )
            """,
        )

        cursor.execute(
            "CALL refresh_continuous_aggregate('mv_drift_heatmap_weekly', NULL, NULL)",
        )

        cursor.close()


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    dbapi = op.get_bind().connection.dbapi_connection
    assert dbapi is not None
    dbapi.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT remove_continuous_aggregate_policy(
                'mv_drift_heatmap_weekly', if_not_exists => true
            )
            """,
        )
        cursor.execute(
            "DROP MATERIALIZED VIEW IF EXISTS mv_drift_heatmap_weekly CASCADE",
        )

        cursor.close()
