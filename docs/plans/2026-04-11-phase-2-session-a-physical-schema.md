# Phase 2 Session A — Physical Schema Tuning

**Date:** 2026-04-11
**Branch:** `feat/terminal-unification-phase-2-session-a`
**Session scope:** 5 atomic commits touching physical TimescaleDB schema
**Estimated duration:** 2-3 hours of concentrated Opus session
**Prerequisite reading:** `docs/plans/2026-04-11-phase-2-overview.md` (read in full before any code)

## Mission

Close the physical schema gaps that the audit confirmed as real — compression segmentation, chunk interval tuning, unique index for CONCURRENT refresh, event_log column for SSE replay, and converting `wealth_vector_chunks` to a hypertable with compression. After this session, the physical data layer is production-grade and Session 2.B's analytical layer can build on top of it.

Five atomic commits on `feat/terminal-unification-phase-2-session-a`, in this exact order:

1. `fix(db): fund_risk_metrics compress_segmentby from organization_id to instrument_id`
2. `feat(db): add event_log JSONB column to portfolio_construction_runs`
3. `perf(db): tune nav_timeseries chunk_time_interval based on benchmark`
4. `feat(db): add unique index on nav_monthly_returns_agg (instrument_id, month)`
5. `feat(db): convert wealth_vector_chunks to hypertable with compression`

## Project mandate (binding)

See `docs/plans/2026-04-11-phase-2-overview.md` §"Project mandate". Summary: high-end institutional product, install any deps needed, no shortcuts, infrastructure correctness before visual polish.

## READ FIRST (mandatory, in this order)

1. `docs/plans/2026-04-11-phase-2-overview.md` — the shared context for all three Phase 2 sessions
2. `docs/audits/Phase-2-Scope-Audit-Investigation-Report.md` — the audit that drove this scope
3. `backend/app/core/db/migrations/versions/c3d4e5f6a7b8_timescaledb_hypertables_compression.py` — current compression setup for `fund_risk_metrics`, confirm current segmentby
4. `backend/app/core/db/migrations/versions/0049_wealth_continuous_aggregates.py` — the CAGG for `nav_monthly_returns_agg`, confirm current non-unique index
5. `backend/app/core/db/migrations/versions/0069_globalize_instruments_nav.py` — nav_timeseries hypertable definition, confirm chunk_time_interval
6. `backend/app/core/db/migrations/versions/0099_portfolio_construction_runs.py` — full column list, confirm event_log is NOT present
7. `backend/app/core/db/migrations/versions/0059_wealth_vector_chunks.py` — or whatever migration creates `wealth_vector_chunks`, confirm regular table
8. `backend/app/core/db/migrations/versions/0105_portfolio_calibration_fk_on_construction_runs.py`, `0107_shadow_oms.py`, `0108_terminal_oms_hardening.py`, `0109_fund_risk_audit_columns.py` — recent migration style reference (imports, docstring conventions, upgrade/downgrade patterns)
9. `backend/app/domains/wealth/models.py` (or wherever `FundRiskMetrics` / `PortfolioConstructionRun` / `WealthVectorChunks` models live) — ORM model definitions
10. `backend/Makefile` — confirm `make migrate` + `make migration MSG=...` + `make test` targets for verification

## Pre-flight checks

Before commit 1, run:

```bash
alembic heads
```

This confirms current Alembic head. Expected: `0109_fund_risk_audit_columns` (or later if Tiingo or another sprint shipped first). Phase 2 migrations start at `head + 1`. If numbering conflict surfaces mid-session, adjust commits to the next available slot.

Also run:

```bash
make up  # docker-compose up for local dev DB
make migrate  # apply all migrations to confirm current state
```

This confirms the local dev DB reflects current schema before you begin. If `make up` or `make migrate` fails, STOP and report — Phase 2 cannot proceed against a broken local DB.

---

# COMMIT 1 — fix(db): fund_risk_metrics compress_segmentby from organization_id to instrument_id

## Problem

Audit `docs/audits/Phase-2-Scope-Audit-Investigation-Report.md` §A.1 confirmed that `fund_risk_metrics.compress_segmentby = 'organization_id'` at `backend/app/core/db/migrations/versions/c3d4e5f6a7b8_timescaledb_hypertables_compression.py` L104.

`fund_risk_metrics` is a **global** table — `organization_id` is nullable and NULL for the vast majority of rows (base risk metrics computed by `global_risk_metrics` worker lock 900_071 are emitted with org=NULL). Segmenting by a predominantly-NULL column defeats compression optimization: PostgreSQL/TimescaleDB cannot efficiently segment a column whose values are mostly NULL into meaningful compression groups. The result is degraded compression ratios and poor query performance on the risk metrics hot path.

The correct segmentation is `instrument_id` — the primary access pattern is "read risk metrics for a given instrument over time", and `instrument_id` is always populated with high cardinality.

## Deliverable

New migration `backend/app/core/db/migrations/versions/0110_fund_risk_metrics_compress_segmentby_fix.py` (adjust number to current head + 1).

```python
"""fund_risk_metrics compress_segmentby fix — organization_id → instrument_id.

Driver: audit 2026-04-11 confirmed fund_risk_metrics was segmented by
organization_id, which is nullable and predominantly NULL (base risk
metrics are written globally by the risk_calc worker with org=NULL).
Compression efficiency degraded. Switch to instrument_id, which is
always populated with high cardinality and matches the dominant access
pattern of the screener and entity analytics hot paths.

Revision ID: 0110_fund_risk_metrics_compress_segmentby_fix
Revises: <current head, verify with alembic heads>
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0110_fund_risk_metrics_compress_segmentby_fix"
down_revision = "0109_fund_risk_audit_columns"  # verify with alembic heads
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Decompress the last N chunks so we can change segmentby.
    #    TimescaleDB requires decompression before altering segmentby.
    op.execute("""
        SELECT decompress_chunk(c.schema_name || '.' || c.table_name)
        FROM timescaledb_information.chunks c
        WHERE c.hypertable_name = 'fund_risk_metrics'
          AND c.is_compressed = true
        ORDER BY c.range_start DESC
        LIMIT 3
    """)

    # 2. Alter the compression setting.
    op.execute("""
        ALTER TABLE fund_risk_metrics
        SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'instrument_id',
            timescaledb.compress_orderby = 'as_of DESC'
        )
    """)

    # 3. Recompress the chunks we decompressed, applying the new segmentby.
    op.execute("""
        SELECT compress_chunk(c.schema_name || '.' || c.table_name)
        FROM timescaledb_information.chunks c
        WHERE c.hypertable_name = 'fund_risk_metrics'
          AND c.is_compressed = false
          AND c.range_start < NOW() - INTERVAL '1 month'
    """)


def downgrade() -> None:
    op.execute("""
        SELECT decompress_chunk(c.schema_name || '.' || c.table_name)
        FROM timescaledb_information.chunks c
        WHERE c.hypertable_name = 'fund_risk_metrics'
          AND c.is_compressed = true
        ORDER BY c.range_start DESC
        LIMIT 3
    """)

    op.execute("""
        ALTER TABLE fund_risk_metrics
        SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'organization_id',
            timescaledb.compress_orderby = 'as_of DESC'
        )
    """)

    op.execute("""
        SELECT compress_chunk(c.schema_name || '.' || c.table_name)
        FROM timescaledb_information.chunks c
        WHERE c.hypertable_name = 'fund_risk_metrics'
          AND c.is_compressed = false
          AND c.range_start < NOW() - INTERVAL '1 month'
    """)
```

**Notes:**
- Verify the exact `compress_orderby` value from the existing migration (`c3d4e5f6a7b8`) and preserve it, OR update if the audit finds a different value. Do NOT invent.
- The `LIMIT 3` on decompression is conservative — decompressing more chunks is expensive. If the audit or inspection shows compression is only applied to older chunks (e.g., > 3 months old), decompressing only the most recent 3 is sufficient for the alter to succeed.
- If `timescaledb_information.chunks` query returns zero rows (no compressed chunks exist yet), the decompress/recompress cycle is a no-op and the migration still succeeds. That is acceptable.

## Verification

1. `alembic upgrade head` clean on local dev DB
2. `alembic downgrade -1` cleanly reverses
3. `alembic upgrade head` again to re-apply
4. Run:
   ```sql
   SELECT hypertable_name, segmentby_column_name, orderby_column_name
   FROM timescaledb_information.compression_settings
   WHERE hypertable_name = 'fund_risk_metrics';
   ```
   Expected: `segmentby_column_name = 'instrument_id'`, orderby as before.
5. `make test` passes (no tests should break, this is a compression setting change)
6. Capture compression ratio before/after via `chunks_detailed_size()` and note in commit message body for reference.

## Commit 1 template

```
fix(db): fund_risk_metrics compress_segmentby from organization_id to instrument_id

Audit 2026-04-11 (docs/audits/Phase-2-Scope-Audit-Investigation-Report.md
§A.1) confirmed fund_risk_metrics was segmented by organization_id at
c3d4e5f6a7b8 L104. The table is global with nullable org; base risk
metrics are written globally by risk_calc worker lock 900_071 with
org=NULL for the vast majority of rows. Segmenting by a predominantly
NULL column defeats TimescaleDB compression.

Switches to instrument_id, which is always populated with high
cardinality and matches the dominant screener + entity analytics
access pattern (WHERE instrument_id = X ORDER BY as_of DESC).

Migration decompresses the 3 most recent chunks, alters the setting,
and recompresses. Older chunks (>1 month) are already compressed under
the old segmentby; they remain that way until they age out of retention
or a future migration bulk-recompresses them.

Compression ratio before/after: <capture via chunks_detailed_size() and fill in>

Part of Phase 2 Session A — physical schema tuning.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 2 — feat(db): add event_log JSONB column to portfolio_construction_runs

## Problem

Audit §A.5 confirmed `portfolio_construction_runs` does NOT have an `event_log` column. Phase 4 Builder's SSE late-subscriber replay (per master plan §Commit 7) assumed this column would exist. It doesn't. Phase 2 must add it so Phase 4 can consume it.

## Deliverable

New migration `backend/app/core/db/migrations/versions/0111_portfolio_construction_runs_event_log.py`.

```python
"""portfolio_construction_runs event_log JSONB column.

Adds an event_log JSONB column that accumulates every SSE event
published by construction_run_executor during a run. Enables late
subscribers (e.g., a user opening the Builder in another tab mid-run)
to replay the full optimizer trace by reading the column — no need to
buffer in Redis beyond the active connection.

Schema: event_log is a JSONB array of event objects, each with
{seq, type, ts, payload}. construction_run_executor appends to the
array via jsonb_set as events fire. mv_construction_run_diff (Session
2.B) reads from this column to compute diffs between runs.

GIN index on event_log for efficient JSONB query (used by the diff MV
and by Phase 4 analytics replay UI).

Revision ID: 0111_portfolio_construction_runs_event_log
Revises: 0110_fund_risk_metrics_compress_segmentby_fix
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0111_portfolio_construction_runs_event_log"
down_revision = "0110_fund_risk_metrics_compress_segmentby_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "portfolio_construction_runs",
        sa.Column(
            "event_log",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "idx_portfolio_construction_runs_event_log_gin",
        "portfolio_construction_runs",
        ["event_log"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_portfolio_construction_runs_event_log_gin",
        table_name="portfolio_construction_runs",
    )
    op.drop_column("portfolio_construction_runs", "event_log")
```

**Notes:**
- `nullable=False` + `server_default='[]'::jsonb` ensures existing rows get a sensible default without a separate backfill step.
- GIN index is the standard choice for JSONB columns queried with `@>` or path extraction. It's essential for the diff MV performance.
- Also update the ORM model in `backend/app/domains/wealth/models.py` (or wherever `PortfolioConstructionRun` is defined) to expose the `event_log` field. Include the model update in this same commit.

## Verification

1. `alembic upgrade head` clean
2. `alembic downgrade -1` clean
3. Insert a test row and verify `event_log` defaults to `[]`
4. `make test` passes including any construction run tests

## Commit 2 template

```
feat(db): add event_log JSONB column to portfolio_construction_runs

Phase 4 Builder's SSE late-subscriber replay requires every event
published during a construction run to be persisted, not just buffered
in Redis. Adds event_log JSONB column (default '[]'::jsonb) +
GIN index for efficient diff queries.

construction_run_executor (Session 2.C) appends events via jsonb_set as
they fire. mv_construction_run_diff (Session 2.B) reads from the column
to compute weight/metrics deltas between runs N and N-1.

ORM model PortfolioConstructionRun updated to expose the event_log
field.

Part of Phase 2 Session A — physical schema tuning.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 3 — perf(db): tune nav_timeseries chunk_time_interval based on benchmark

## Problem

Audit §A.2 found `nav_timeseries` uses the TimescaleDB default `chunk_time_interval` of 7 days. With 5,517+ instruments and 15+ years of daily history coming via Tiingo, 7-day chunks produce ~780+ chunks per instrument pair, bloating the chunk count and degrading query planner chunk exclusion performance.

The master plan proposed 3mo but Andrei specified "even longer if it improves performance". This commit includes a **benchmark investigation** before picking the final value.

## Deliverable

**Two-phase execution in a single commit:**

### Phase 3A — Benchmark investigation (run in a Jupyter notebook or REPL, capture results in the commit message)

Run the following diagnostic queries on the local dev DB (or a production snapshot if available):

```sql
-- 1. Current chunk count and size distribution
SELECT
  chunk_schema,
  chunk_name,
  range_start,
  range_end,
  pg_size_pretty(total_bytes) AS total_size,
  pg_size_pretty(compressed_total_bytes) AS compressed_size
FROM chunks_detailed_size('nav_timeseries')
ORDER BY range_start DESC
LIMIT 20;

-- 2. Aggregate chunk count + total size
SELECT
  COUNT(*) AS chunk_count,
  pg_size_pretty(SUM(total_bytes)) AS total_size,
  pg_size_pretty(AVG(total_bytes)) AS avg_chunk_size
FROM chunks_detailed_size('nav_timeseries');

-- 3. Query plan on the screener hot path (the dominant read)
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT instrument_id, nav_date, nav_close
FROM nav_timeseries
WHERE instrument_id = (SELECT id FROM instruments_universe LIMIT 1)
  AND nav_date >= NOW() - INTERVAL '5 years'
ORDER BY nav_date;
```

Capture:
- Current chunk count
- Average chunk size
- Number of chunks scanned / excluded in the 5-year query
- Execution time

Simulate the same queries with `chunk_time_interval` values of 3 months, 6 months, and 1 year by using TimescaleDB's `set_chunk_time_interval` on a test table or by mathematical projection (expected chunks = total time span / interval).

**Optimal value selection rule:** pick the interval that minimizes total chunk count while keeping average chunk size below 500MB (TimescaleDB's recommended ceiling for compression efficiency). For 5-6 years of 5,517 instruments at typical daily bar sizes, **6 months is the expected winner**, but benchmark before committing.

### Phase 3B — Apply the winning interval

New migration `backend/app/core/db/migrations/versions/0112_nav_timeseries_chunk_interval_tune.py`.

```python
"""nav_timeseries chunk_time_interval tune.

Increases chunk_time_interval from default 7 days to <WINNING_VALUE>
based on benchmark investigation 2026-04-11. Benchmark captured in
commit message body and docs/audits/Phase-2-Scope-Audit-Investigation-
Report.md §A.2.

Pre-existing chunks retain their old interval (TimescaleDB applies
the new value only to chunks created after the migration). Retention
and compression policies continue to apply to both old and new chunks.

Revision ID: 0112_nav_timeseries_chunk_interval_tune
Revises: 0111_portfolio_construction_runs_event_log
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op

revision = "0112_nav_timeseries_chunk_interval_tune"
down_revision = "0111_portfolio_construction_runs_event_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        SELECT set_chunk_time_interval(
            'nav_timeseries',
            INTERVAL '<WINNING_VALUE>'  -- e.g., '6 months'
        )
    """)


def downgrade() -> None:
    op.execute("""
        SELECT set_chunk_time_interval(
            'nav_timeseries',
            INTERVAL '7 days'
        )
    """)
```

Replace `<WINNING_VALUE>` with the result of the benchmark. Commit message body must include the benchmark output.

## Verification

1. `alembic upgrade head` clean
2. `alembic downgrade -1` reverts to 7 days
3. Re-run the same EXPLAIN query from Phase 3A post-migration — chunk count scanned should decrease proportionally
4. `make test` passes

## Commit 3 template

```
perf(db): tune nav_timeseries chunk_time_interval to <WINNING_VALUE>

Audit §A.2 found chunk_time_interval was the TimescaleDB default
(7 days). For 5,517+ instruments and 15+ years of daily history,
this produced <N> chunks totaling <SIZE>, degrading chunk exclusion
performance on the screener hot path.

Benchmark captured 2026-04-11:

- Before: <N> chunks, avg chunk size <SIZE>, screener 5-year query
  scanned <M> chunks, execution <T> ms
- 3 months: projected <N3> chunks, avg size <SIZE3>
- 6 months: projected <N6> chunks, avg size <SIZE6>
- 1 year:   projected <N12> chunks, avg size <SIZE12>

Winner: <WINNING_VALUE> — minimizes total chunk count while staying
below the 500MB average chunk size ceiling TimescaleDB recommends for
compression efficiency.

Pre-existing chunks retain their 7-day interval. Only chunks created
after this migration use the new value. Retention and compression
policies apply to both.

Part of Phase 2 Session A — physical schema tuning.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 4 — feat(db): add unique index on nav_monthly_returns_agg (instrument_id, month)

## Problem

Audit §A.7 confirmed `nav_monthly_returns_agg` (the continuous aggregate created in `0049_wealth_continuous_aggregates.py`) has a non-unique index `idx_nav_monthly_returns_agg_inst_month` at L60. CONCURRENT refresh of a materialized view requires a unique index — without it, `REFRESH MATERIALIZED VIEW CONCURRENTLY` fails with "cannot refresh materialized view concurrently".

Session 2.B's `mv_fund_risk_latest` and future refresh automation will need CONCURRENT refresh capability across CAGGs. Add the unique index now.

## Deliverable

New migration `backend/app/core/db/migrations/versions/0113_nav_monthly_returns_agg_unique_index.py`.

```python
"""nav_monthly_returns_agg unique index on (instrument_id, month).

Enables REFRESH MATERIALIZED VIEW CONCURRENTLY on the CAGG, which is a
prerequisite for non-blocking refresh automation used by Session 2.B's
mv_fund_risk_latest and future analytical views.

Note: nav_monthly_returns_agg groups by
(instrument_id, organization_id, month). If organization_id is never
NULL for a given (instrument_id, month) pair in practice, the 2-column
unique index is sufficient. If the CAGG emits rows with NULL
organization_id for global instruments, the unique index must include
organization_id. Verify shape before choosing.

Revision ID: 0113_nav_monthly_returns_agg_unique_index
Revises: 0112_nav_timeseries_chunk_interval_tune
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op

revision = "0113_nav_monthly_returns_agg_unique_index"
down_revision = "0112_nav_timeseries_chunk_interval_tune"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Verify first whether organization_id can be NULL in the CAGG —
    # if yes, unique index must be (instrument_id, organization_id, month).
    # If organization_id is always populated, (instrument_id, month) is
    # sufficient and gives better storage.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_nav_monthly_returns_agg_inst_org_month
        ON nav_monthly_returns_agg (instrument_id, organization_id, month)
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS uq_nav_monthly_returns_agg_inst_org_month
    """)
```

**Critical investigation before committing:** Before writing the final migration, run:

```sql
SELECT COUNT(*) FILTER (WHERE organization_id IS NULL),
       COUNT(*) FILTER (WHERE organization_id IS NOT NULL),
       COUNT(DISTINCT (instrument_id, month)) AS distinct_pairs,
       COUNT(*) AS total_rows
FROM nav_monthly_returns_agg;
```

- If `distinct_pairs = total_rows` and `organization_id` is always NULL: use `(instrument_id, month)` — 2-column unique
- If `distinct_pairs < total_rows`: must include `organization_id` in the unique — 3-column
- If shape is unexpected: STOP, investigate, update the migration accordingly

## Verification

1. `alembic upgrade head` clean
2. `REFRESH MATERIALIZED VIEW CONCURRENTLY nav_monthly_returns_agg` succeeds (before the index, this fails)
3. `alembic downgrade -1` drops the index cleanly
4. `make test` passes

## Commit 4 template

```
feat(db): add unique index on nav_monthly_returns_agg for CONCURRENT refresh

Audit §A.7 confirmed the existing CAGG index
idx_nav_monthly_returns_agg_inst_month at 0049 L60 is non-unique.
CONCURRENT refresh requires a unique index. Without it, the planned
analytical layer refresh automation in Session 2.B cannot use
non-blocking refresh.

Adds UNIQUE INDEX uq_nav_monthly_returns_agg_inst_org_month on
(instrument_id, organization_id, month) based on CAGG shape verification:
<describe what the COUNT query showed — whether 2-col or 3-col was needed>.

REFRESH MATERIALIZED VIEW CONCURRENTLY now succeeds.

Part of Phase 2 Session A — physical schema tuning.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 5 — feat(db): convert wealth_vector_chunks to hypertable with compression

## Problem

Audit §A.3 confirmed `wealth_vector_chunks` is a regular table, not a hypertable, with no compression. As the embedding corpus grows (16 embedding sources including SEC filings, ADV brochures, ESMA funds, DD chapters), storage will balloon without compression. Converting to a hypertable with `source_type` segmentation enables TimescaleDB compression and chunk retention.

## Deliverable

New migration `backend/app/core/db/migrations/versions/0114_wealth_vector_chunks_hypertable.py`.

```python
"""Convert wealth_vector_chunks to hypertable with compression.

Audit 2026-04-11 §A.3 confirmed wealth_vector_chunks was a regular table
with no compression. Converting to a hypertable enables TimescaleDB
compression policies keyed by source_type (firm, fund, macro, brochure,
dd, etc.), which is the dominant filter in pgvector_search_service.

Time column: updated_at (reflects when the chunk was last embedded).
Chunk interval: 3 months (balances chunk count with query efficiency).
compress_segmentby: source_type (matches pgvector_search_service WHERE
clauses).
compress_orderby: updated_at DESC (matches retention policy sort order).

migrate_data=true on create_hypertable preserves existing rows during
conversion. This is safe because wealth_vector_chunks already has
updated_at populated on every row (default NOW()).

Revision ID: 0114_wealth_vector_chunks_hypertable
Revises: 0113_nav_monthly_returns_agg_unique_index
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op

revision = "0114_wealth_vector_chunks_hypertable"
down_revision = "0113_nav_monthly_returns_agg_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Convert to hypertable, preserving existing data
    op.execute("""
        SELECT create_hypertable(
            'wealth_vector_chunks',
            'updated_at',
            chunk_time_interval => INTERVAL '3 months',
            migrate_data => true,
            if_not_exists => true
        )
    """)

    # 2. Enable compression with source_type segmentation
    op.execute("""
        ALTER TABLE wealth_vector_chunks
        SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'source_type',
            timescaledb.compress_orderby = 'updated_at DESC'
        )
    """)

    # 3. Add compression policy — compress chunks older than 3 months
    op.execute("""
        SELECT add_compression_policy(
            'wealth_vector_chunks',
            INTERVAL '3 months',
            if_not_exists => true
        )
    """)


def downgrade() -> None:
    # Removing a hypertable conversion is destructive (would require
    # creating a temp table, copying rows, dropping, renaming).
    # This migration is intentionally forward-only.
    raise NotImplementedError(
        "wealth_vector_chunks hypertable conversion is forward-only. "
        "To revert, restore from backup or manually recreate the regular table."
    )
```

**Critical pre-flight checks before running:**

1. Verify `wealth_vector_chunks` has an `updated_at` column. If the time column is named differently (e.g., `created_at`, `embedded_at`), adjust accordingly.
2. Verify `source_type` is a low-cardinality column (ideally 10-20 distinct values). If it's high-cardinality, compression won't be efficient — segment by a different column.
3. Verify NO foreign keys reference `wealth_vector_chunks` — if yes, the hypertable conversion may fail (TimescaleDB restriction).
4. Back up the table before running the migration in dev:
   ```sql
   CREATE TABLE wealth_vector_chunks_backup AS SELECT * FROM wealth_vector_chunks;
   ```
   (Drop after successful verification.)

## Verification

1. `alembic upgrade head` clean — note: this may take several minutes as `migrate_data=true` copies rows
2. Verify hypertable state:
   ```sql
   SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'wealth_vector_chunks';
   SELECT * FROM timescaledb_information.compression_settings WHERE hypertable_name = 'wealth_vector_chunks';
   ```
   Expected: hypertable row exists, `segmentby_column_name = 'source_type'`, `orderby_column_name = 'updated_at'`.
3. `alembic downgrade -1` raises NotImplementedError (as designed — forward-only)
4. `make test` passes including pgvector search tests
5. Run a sample pgvector query (from `pgvector_search_service.py`) and confirm performance is same or better

## Commit 5 template

```
feat(db): convert wealth_vector_chunks to hypertable with compression

Audit §A.3 confirmed wealth_vector_chunks was a regular table with no
compression. As the embedding corpus grows (16 embedding sources —
brochures, ESMA funds, SEC filings, DD chapters, etc.), storage bloats
without TimescaleDB compression.

Converts to a hypertable keyed on updated_at with 3-month chunks,
compression segmented by source_type (matching pgvector_search_service
WHERE clauses), orderby updated_at DESC, and a 3-month compression
policy. migrate_data=true preserves existing rows during conversion.

Forward-only migration — downgrade raises NotImplementedError because
reversing a hypertable conversion with data is destructive. To revert,
restore from backup.

Part of Phase 2 Session A — physical schema tuning.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# FINAL FULL-TREE VERIFICATION

After all 5 commits land:

1. `alembic upgrade head` → clean from fresh docker-compose DB
2. `alembic downgrade -3` → reverses commits 1-3 (commit 5 is forward-only by design)
3. `alembic upgrade head` → re-applies cleanly
4. `make check` → lint + architecture + typecheck + test all green
5. `make test` → all wealth tests pass
6. Compression settings verified via `timescaledb_information.compression_settings`
7. Chunk count verified via `timescaledb_information.chunks`
8. No regressions in baseline test count

# SELF-CHECK CHECKLIST

- [ ] `alembic heads` confirmed at commit-0 before starting
- [ ] Commit 1: compress_segmentby fix applied, compression setting verified in pg_catalog
- [ ] Commit 2: event_log column present, GIN index created, ORM model updated
- [ ] Commit 3: benchmark investigation captured in commit body, winning interval applied, EXPLAIN re-run shows improvement
- [ ] Commit 4: CAGG shape verified before index shape decided, unique index created, CONCURRENT refresh succeeds
- [ ] Commit 5: hypertable conversion complete, data preserved, compression policy added
- [ ] `make check` green
- [ ] No files outside this session's scope touched
- [ ] packages/investintell-ui unchanged (smoke check)
- [ ] tokens sync still green (smoke check)
- [ ] Parallel session files (Tiingo worktree) untouched

# VALID ESCAPE HATCHES

1. `alembic heads` shows a head other than `0109_fund_risk_audit_columns` → adjust migration numbering accordingly, use the next available slot
2. Tiingo sprint already shipped migration 0110 → Phase 2 Session A starts at 0111 or later, adjust all commit numbers and down_revision chains
3. `create_hypertable` on `wealth_vector_chunks` fails because of FK references → report, investigate which FKs exist, decide whether to drop+readd or block the migration
4. `set_chunk_time_interval` fails on `nav_timeseries` → report, check if the table has existing compressed chunks that need decompression first
5. Benchmark investigation in commit 3 is ambiguous or produces no clear winner → report findings, request human decision before committing
6. `wealth_vector_chunks` time column is not `updated_at` → identify actual column (`created_at`, `embedded_at`), use that, report the correction
7. Any `make test` failure introduced by a commit → DO NOT mask by marking tests as expected-fail. Investigate root cause, fix or report.

# NOT VALID ESCAPE HATCHES

- "Compression segmentby change is too complex, let me skip it" → NO, this is the highest-priority commit of the session
- "The benchmark takes too long, let me just pick 3 months" → NO, user explicitly said "even longer if it improves performance". Measure.
- "I'll skip the wealth_vector_chunks conversion because it's big" → NO, in-scope per audit and user direction
- "I'll use IF EXISTS on downgrade to be safe" → NO. Downgrades must fail loudly on drift per CLAUDE.md migration discipline

# REPORT FORMAT

1. Five commit SHAs with full messages
2. Per commit: migration file path, lines added, verification output (alembic upgrade/downgrade, relevant SELECT queries showing schema state)
3. Commit 3 extra: complete benchmark investigation output (before/after chunk counts, EXPLAIN plans, winning interval justification)
4. Commit 4 extra: CAGG shape investigation output (COUNT query results that determined 2-col vs 3-col unique)
5. Commit 5 extra: hypertable info + compression settings from timescaledb_information, pgvector sample query performance delta
6. Full-tree verification output
7. Any escape hatches hit with context

Begin by reading the overview file + audit report + this brief. Then run `alembic heads` and `make migrate` to confirm current state. Do not start commit 1 until local DB is in a known-good state.
