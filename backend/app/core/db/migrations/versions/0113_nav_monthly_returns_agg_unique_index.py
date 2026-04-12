"""nav_monthly_returns_agg unique index on (instrument_id, month).

Audit 2026-04-11 §A.7 confirmed the CAGG's auto-generated index
``_materialized_hypertable_<N>_instrument_id_month_idx`` is
NON-UNIQUE. Migration 0049 originally attempted
``CREATE INDEX ... ON nav_monthly_returns_agg (instrument_id, month DESC)``
but TimescaleDB rewrote that against the underlying materialization
hypertable as a non-unique index.

CAGG shape investigation (2026-04-11, run against local dev DB
at migration head 0112 before this commit):

    SELECT view_definition FROM information_schema.views
    WHERE table_name='nav_monthly_returns_agg';
    → SELECT instrument_id, month, nav_open, nav_close, trading_days,
             avg_daily_return, daily_volatility
        FROM _timescaledb_internal._materialized_hypertable_90;

    SELECT COUNT(*) FILTER (WHERE instrument_id IS NULL),
           COUNT(DISTINCT (instrument_id, month)),
           COUNT(*)
    FROM nav_monthly_returns_agg;
    → null_inst=0, distinct_pairs=583850, total_rows=583850
      (after refresh_continuous_aggregate)

Conclusion: ``organization_id`` was removed from the CAGG in
migration 0069 when nav_timeseries globalized. Group key is
``(instrument_id, month)`` only — a 2-column unique index is
correct and sufficient.

TimescaleDB specifics discovered during implementation:

1. ``CREATE UNIQUE INDEX ... ON nav_monthly_returns_agg (...)``
   is REJECTED by TimescaleDB with
   ``ERROR: continuous aggregates do not support UNIQUE indexes``.
2. TimescaleDB allows UNIQUE indexes to be created directly on
   the underlying materialization hypertable
   (``_timescaledb_internal._materialized_hypertable_<N>``), and
   ``refresh_continuous_aggregate()`` continues to function
   correctly against the constrained table (verified by full
   refresh of 583,850 rows with the index in place).
3. ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` is NOT applicable
   to CAGGs at all — CAGGs use ``refresh_continuous_aggregate()``
   which is incremental and non-blocking by design. The brief's
   motivation for this commit (unblocking CONCURRENT refresh) is
   a TimescaleDB misconception. The index is still shipped
   because it enforces a real data-integrity invariant (one
   row per (instrument_id, month)) and enables future upsert
   patterns via ON CONFLICT. Session 2.B's ``mv_fund_risk_latest``
   will be a plain materialized view — its CONCURRENT-refresh
   unique index is Session 2.B's responsibility, not this
   migration's.

Implementation: the materialization hypertable name contains an
install-specific numeric suffix, so the migration looks it up
dynamically from ``timescaledb_information.continuous_aggregates``
and builds the DDL string via ``format()`` in a DO block.

Revision ID: 0113_nav_monthly_returns_agg_unique_index
Revises: 0112_nav_timeseries_chunk_interval_tune
Create Date: 2026-04-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0113_nav_monthly_returns_agg_unique_index"
down_revision: str | None = "0112_nav_timeseries_chunk_interval_tune"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            mh_schema name;
            mh_name   name;
        BEGIN
            SELECT materialization_hypertable_schema,
                   materialization_hypertable_name
              INTO mh_schema, mh_name
              FROM timescaledb_information.continuous_aggregates
             WHERE view_name = 'nav_monthly_returns_agg';

            IF mh_schema IS NULL THEN
                RAISE EXCEPTION
                    'nav_monthly_returns_agg CAGG not found — has '
                    'migration 0069 been applied?';
            END IF;

            EXECUTE format(
                'CREATE UNIQUE INDEX IF NOT EXISTS '
                'uq_nav_monthly_returns_agg_inst_month '
                'ON %I.%I (instrument_id, month)',
                mh_schema, mh_name
            );
        END $$
        """,
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            mh_schema name;
            mh_name   name;
        BEGIN
            SELECT materialization_hypertable_schema,
                   materialization_hypertable_name
              INTO mh_schema, mh_name
              FROM timescaledb_information.continuous_aggregates
             WHERE view_name = 'nav_monthly_returns_agg';

            IF mh_schema IS NULL THEN
                RAISE EXCEPTION
                    'nav_monthly_returns_agg CAGG not found';
            END IF;

            EXECUTE format(
                'DROP INDEX %I.uq_nav_monthly_returns_agg_inst_month',
                mh_schema
            );
        END $$
        """,
    )
