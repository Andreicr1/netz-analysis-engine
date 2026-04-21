"""portfolio_weight_snapshots — 7-day hypertable

Phase 2 Task 2.3 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Three vectors per day per (portfolio, instrument) — strategic,
tactical, effective. Keyed on ``(organization_id, portfolio_id,
instrument_id, as_of)`` with ``as_of`` as the TimescaleDB partition
column.

Sizing rationale (per DB draft §6): 50 tenants × 5 portfolios ×
30 holdings = 7,500 rows/day → 52,500 rows per 7-day chunk. Well
inside Timescale's 25MB-1GB per chunk target.

**RLS architectural exception**
-------------------------------
This hypertable does NOT enable Row Level Security. This is a
deliberate departure from the project's tenant-isolation default,
driven by the established codebase pattern for compressed
hypertables:

    audit_events: RLS=False, compression=True
    fund_risk_metrics: RLS=False, compression=True
    macro_data: RLS=False, compression=True

The existing migration ``0030_audit_event_hypertables.py`` drops
RLS before enabling compression with the comment: "RLS incompatible
with TimescaleDB columnstore — drop policies + disable". This
constraint applied to older TimescaleDB versions and the project
committed to the pattern for consistency across all compressed
hypertables.

**Security model for portfolio_weight_snapshots:**
- Every query MUST include ``WHERE organization_id = :org_id``
- The composite PK ``(organization_id, portfolio_id, instrument_id,
  as_of)`` makes ``organization_id`` the first equality filter — any
  query that forgets it will scan the entire hypertable and be
  caught in code review / load test
- Application-layer helper ``get_portfolio_weights(db, org_id, ...)``
  will be the only writer/reader surface (Phase 9 Task 9.7)
- Phase 0 diagnostic flagged this departure from the plan's R7 risk

Hypertable configuration
------------------------
- ``chunk_time_interval``: 7 days
- ``compress_segmentby``: ``portfolio_id`` (cardinality ~250 across
  all tenants — inside the 100-100k sweet spot)
- ``compress_orderby``: ``as_of DESC, instrument_id``
- ``add_compression_policy``: 14 days

FK references
-------------
- ``model_portfolios(id)`` — kept, ON DELETE CASCADE (tested on
  TimescaleDB 2.26.1 — supported)
- ``instruments_universe(instrument_id)`` — kept (global catalog,
  no RLS on either side)

Downgrade
---------
NO ``IF EXISTS``. Drops the compression policy, decompresses any
compressed chunks, drops the hypertable. Matches pattern from
``0030_audit_event_hypertables.py:351``.

Revision ID: 0102_portfolio_weight_snapshots_hypertable
Revises: 0101_portfolio_stress_results
Create Date: 2026-04-08
"""
import os
from collections.abc import Sequence

import psycopg

from alembic import op

revision: str = "0102_portfolio_weight_snapshots_hypertable"
down_revision: str | None = "0101_portfolio_stress_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL.

    ``create_hypertable`` and ``add_compression_policy`` cannot run
    inside an Alembic transaction — they require autocommit. Same
    pattern as ``0030_audit_event_hypertables.py``.
    """
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    # ── Table (inside Alembic transaction) ────────────────────────
    op.execute(
        """
        CREATE TABLE portfolio_weight_snapshots (
            organization_id   uuid           NOT NULL,
            portfolio_id      uuid           NOT NULL
                REFERENCES model_portfolios(id) ON DELETE CASCADE,
            instrument_id     uuid           NOT NULL
                REFERENCES instruments_universe(instrument_id),
            as_of             date           NOT NULL,
            weight_strategic  numeric(10,8),
            weight_tactical   numeric(10,8),
            weight_effective  numeric(10,8),
            source            text           NOT NULL DEFAULT 'eod',
            notes             text,
            created_at        timestamptz    NOT NULL DEFAULT now(),

            PRIMARY KEY (organization_id, portfolio_id, instrument_id, as_of),
            CONSTRAINT ck_pws_source
                CHECK (source IN ('eod', 'intraday', 'construction_run', 'overlay'))
        )
        """,
    )

    # ── Auxiliary index: latest-snapshot lookup per portfolio ─────
    # Supports the workbench "current holdings" query without the
    # cost of a full chunk scan.
    op.execute(
        """
        CREATE INDEX ix_pws_portfolio_as_of
        ON portfolio_weight_snapshots (portfolio_id, as_of DESC)
        """,
    )

    # ── Hypertable + compression (autocommit) ─────────────────────
    # create_hypertable + add_compression_policy cannot run inside
    # a transaction — same pattern as 0030_audit_event_hypertables.
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT create_hypertable("
            "  'portfolio_weight_snapshots',"
            "  'as_of',"
            "  chunk_time_interval => INTERVAL '7 days',"
            "  if_not_exists => true"
            ")",
        )

        cursor.execute(
            "ALTER TABLE portfolio_weight_snapshots SET ("
            "  timescaledb.compress,"
            "  timescaledb.compress_orderby = 'as_of DESC, instrument_id',"
            "  timescaledb.compress_segmentby = 'portfolio_id'"
            ")",
        )

        cursor.execute(
            "SELECT add_compression_policy("
            "  'portfolio_weight_snapshots', INTERVAL '14 days',"
            "  if_not_exists => true"
            ")",
        )

        cursor.close()


def downgrade() -> None:
    # Drop compression policy + decompress any chunks before
    # removing the hypertable. Autocommit required for the policy
    # and decompression calls.
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT remove_compression_policy("
            "  'portfolio_weight_snapshots', if_exists => true"
            ")",
        )
        cursor.execute(
            "SELECT decompress_chunk(c.chunk_schema || '.' || c.chunk_name) "
            "FROM timescaledb_information.chunks c "
            "WHERE c.hypertable_name = 'portfolio_weight_snapshots' "
            "AND c.is_compressed = true",
        )
        cursor.execute(
            "ALTER TABLE portfolio_weight_snapshots SET (timescaledb.compress = false)",
        )
        cursor.close()

    # Table drop runs inside the Alembic transaction again.
    op.execute("DROP INDEX ix_pws_portfolio_as_of")
    op.execute("DROP TABLE portfolio_weight_snapshots")
