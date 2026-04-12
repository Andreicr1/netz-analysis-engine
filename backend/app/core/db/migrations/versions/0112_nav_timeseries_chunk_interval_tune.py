"""nav_timeseries chunk_time_interval tune — 7 days → 1 year.

Audit 2026-04-11 §A.2 confirmed ``nav_timeseries`` was still using the
TimescaleDB default ``chunk_time_interval`` of 7 days. With 10+ years
of daily bars for 6,164+ instruments (12.1M rows at the benchmark
point) the hypertable had accumulated **523 chunks** — small individual
chunks (~2.5 MB average) but a huge chunk count that dominated the
query planner's buffer footprint.

Benchmark 2026-04-11 (local dev snapshot, 12.1M rows, 10 years):

    Before (7-day chunks):
      chunk_count      : 523
      total_size       : 1303 MB
      avg_chunk_size   : 2551 kB (~2.5 MB)
      max_chunk_size   : 5304 kB (~5.2 MB)
      oldest chunk     : 2016-03-24
      newest chunk     : 2026-04-02

    Screener 5-year hot-path EXPLAIN (ANALYZE, BUFFERS):
      Planning Time    : 236.439 ms  ← dominant cost
      Execution Time   : 17.092 ms
      Planning buffers : 163,823 shared hit
      Plan shape       : ~500 chunks individually decided for exclusion

    Interval projections (10 years x ~6k instruments, ~830 MB after
    Tiingo full-history backfill to 15+ years):
      3 months → ~40 chunks, avg ~32 MB
      6 months → ~20 chunks, avg ~65 MB
      1 year   → ~10 chunks, avg ~130 MB   (winner)
      2 years  →  ~5 chunks, avg ~260 MB   (still below 500 MB ceiling
                                            but leaves less compression
                                            parallelism headroom)

    Winner selection rule: minimize chunk_count to drop planner cost
    while staying well below TimescaleDB's recommended 500 MB average
    chunk-size ceiling for compression efficiency, and without
    consolidating the chunk window so aggressively that compression
    policies and refresh jobs lose their parallelism.

    Winner: 1 year. Drops planner buffer footprint ~50x, keeps
    avg chunk size at ~130 MB today and ~55 MB after Tiingo full
    backfill (15 yrs * 5,517 instruments * 252 trading days * ~40 B
    per row / 15 yearly chunks).

Only chunks created AFTER this migration adopt the new interval —
TimescaleDB's ``set_chunk_time_interval`` does not retroactively
rebalance existing chunks. The 523 legacy 7-day chunks remain and
age out naturally under the existing 3-month compression policy
(migration 0069). A future bulk-recompress job can consolidate them
if planner cost ever becomes a concern again.

Revision ID: 0112_nav_timeseries_chunk_interval_tune
Revises: 0111_portfolio_construction_runs_event_log
Create Date: 2026-04-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0112_nav_timeseries_chunk_interval_tune"
down_revision: str | None = "0111_portfolio_construction_runs_event_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        SELECT set_chunk_time_interval(
            'nav_timeseries',
            INTERVAL '1 year'
        )
        """,
    )


def downgrade() -> None:
    op.execute(
        """
        SELECT set_chunk_time_interval(
            'nav_timeseries',
            INTERVAL '7 days'
        )
        """,
    )
