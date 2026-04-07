"""Enable native TimescaleDB columnar compression on NAV hypertables.

Tiingo institutional plan unlocked 15 years of deep history (~5,475 days)
across the full instrument universe. Without compression, the on-disk
footprint of ``nav_timeseries`` and ``benchmark_nav`` will roughly triple
relative to the previous 5-year window.

TimescaleDB native compression delivers 90-95% size reduction on time-series
NAV data and is fully transparent to readers (decompresses on the fly).
We segment by the most-filtered column and order by ``nav_date DESC`` so
"latest N rows for one instrument" — the dominant access pattern — touches
the smallest possible compressed batch.

A compression policy automatically compresses chunks older than 30 days,
leaving the hot window uncompressed for fast inserts/updates from the
nightly worker.

Revision ID: 0087_enable_timescale_compression
Revises: 0086_cusip_map_gics_sector
Create Date: 2026-04-06 12:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0087_enable_timescale_compression"
down_revision: str | None = "0086_cusip_map_gics_sector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── nav_timeseries ────────────────────────────────────────────
    # Segment by instrument_id (highest-cardinality filter on the hot path),
    # order by nav_date DESC so the latest bars sit at the head of each
    # compressed batch — covers "last N closes for ticker X" queries.
    op.execute("""
        ALTER TABLE nav_timeseries SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'instrument_id',
            timescaledb.compress_orderby = 'nav_date DESC'
        );
    """)

    # Compress chunks older than 30 days. Keeps the rolling month uncompressed
    # for cheap upserts; everything beyond moves to columnar storage.
    op.execute("""
        SELECT add_compression_policy(
            'nav_timeseries',
            INTERVAL '30 days',
            if_not_exists => TRUE
        );
    """)

    # ── benchmark_nav ─────────────────────────────────────────────
    # Segment by block_id — benchmark queries always scope to a single
    # allocation block (e.g., "SPY benchmark for the equity sleeve").
    op.execute("""
        ALTER TABLE benchmark_nav SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'block_id',
            timescaledb.compress_orderby = 'nav_date DESC'
        );
    """)

    op.execute("""
        SELECT add_compression_policy(
            'benchmark_nav',
            INTERVAL '30 days',
            if_not_exists => TRUE
        );
    """)


def downgrade() -> None:
    # Order matters: drop the policy → decompress all chunks → disable
    # compression on the table. Reversing this order would leave orphaned
    # compressed chunks behind that the planner can no longer reach.

    # ── benchmark_nav ─────────────────────────────────────────────
    op.execute("""
        SELECT remove_compression_policy(
            'benchmark_nav',
            if_exists => TRUE
        );
    """)
    op.execute("""
        SELECT decompress_chunk(c, true)
        FROM show_chunks('benchmark_nav') c;
    """)
    op.execute("""
        ALTER TABLE benchmark_nav SET (
            timescaledb.compress = false
        );
    """)

    # ── nav_timeseries ────────────────────────────────────────────
    op.execute("""
        SELECT remove_compression_policy(
            'nav_timeseries',
            if_exists => TRUE
        );
    """)
    op.execute("""
        SELECT decompress_chunk(c, true)
        FROM show_chunks('nav_timeseries') c;
    """)
    op.execute("""
        ALTER TABLE nav_timeseries SET (
            timescaledb.compress = false
        );
    """)
