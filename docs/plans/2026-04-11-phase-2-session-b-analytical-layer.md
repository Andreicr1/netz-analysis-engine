# Phase 2 Session B — Analytical Layer

**Date:** 2026-04-11
**Branch:** `feat/terminal-unification-phase-2-session-b`
**Session scope:** 7 atomic commits building the analytical layer on top of Session A's physical schema
**Estimated duration:** 2-3 hours of concentrated Opus session
**Prerequisite reading:** `docs/plans/2026-04-11-phase-2-overview.md` (read in full before any code)
**Depends on:** Session 2.A merged to main (especially the event_log column for commit 4)

## Mission

Build the analytical views, materialized views, continuous aggregates, and ELITE ranking logic on top of the physical schema shipped in Session 2.A. After this session, the backend has:
- ELITE flag column + ranking logic that produces the top 300 funds by strategy proportional to global default allocation
- Single-row-per-instrument risk metrics lookup via `mv_fund_risk_latest`
- Fast screener "already in my universe" flag via `v_screener_org_membership`
- Run N vs N-1 diff computation via `mv_construction_run_diff`
- Weekly drift heatmap via `mv_drift_heatmap_weekly` continuous aggregate

Seven atomic commits on `feat/terminal-unification-phase-2-session-b`, in this exact order:

1. `feat(db): add elite_flag + ranking columns to fund_risk_metrics`
2. `feat(db): mv_fund_risk_latest materialized view`
3. `feat(db): v_screener_org_membership security view`
4. `feat(db): mv_construction_run_diff materialized view`
5. `feat(db): mv_drift_heatmap_weekly continuous aggregate`
6. `feat(wealth/config): confirm global default allocation blocks as ELITE ranking source`
7. `feat(wealth/workers): risk_calc ELITE ranking logic`

## Project mandate (binding)

See `docs/plans/2026-04-11-phase-2-overview.md` §"Project mandate". Plus the ELITE definition is locked per that overview — this session implements it exactly.

## READ FIRST (mandatory, in this order)

1. `docs/plans/2026-04-11-phase-2-overview.md` — ELITE definition is in §"ELITE definition (locked)"
2. `docs/audits/Phase-2-Scope-Audit-Investigation-Report.md` — §E found frontend already uses `.elite` class based on `managerScore >= 75`; this session's real implementation supersedes that simple hack
3. `backend/app/domains/wealth/workers/risk_calc.py` — the worker you will add ELITE ranking logic to
4. `backend/quant_engine/scoring_service.py` — existing composite score computation (do NOT modify, just read to understand which field ELITE ranking should consume)
5. `backend/app/core/db/migrations/versions/` — look for any migration that creates `allocation_blocks` table or similar (needed for commit 6)
6. `backend/app/domains/wealth/models.py` — `FundRiskMetrics`, `AllocationBlock` (or similar), `PortfolioConstructionRun`, `StrategyDriftAlert` ORM definitions
7. `backend/app/domains/wealth/routes/screener.py` — the primary consumer of `v_screener_org_membership` and elite_flag; read to understand the query shape it will use post-Session-B
8. `backend/app/core/db/migrations/versions/0049_wealth_continuous_aggregates.py` — reference for CAGG creation pattern (used in commit 5)
9. Session 2.A migrations in main — confirm `event_log` column landed (dependency of commit 4)
10. `CLAUDE.md` §"Data Ingestion Workers (DB-First Pattern)" — worker lock ID conventions (commit 7 uses lock 900_071 per master plan)

## Pre-flight checks

```bash
alembic heads  # expected: Session 2.A's last migration (0114 or equivalent)
make migrate  # apply Session 2.A migrations
```

If `event_log` column is not present on `portfolio_construction_runs`, Session 2.A didn't ship or didn't merge — STOP and report.

---

# COMMIT 1 — feat(db): add elite_flag + ranking columns to fund_risk_metrics

## Purpose

Add the columns that the ELITE ranking logic (commit 7) will populate. Schema-only commit.

## Deliverable

New migration `backend/app/core/db/migrations/versions/0115_fund_risk_metrics_elite_flag.py` (adjust numbering to current head + 1).

```python
"""fund_risk_metrics elite_flag + ranking columns.

Adds the three columns that the ELITE ranking worker (Session 2.B
commit 7) populates:

- elite_flag: boolean, true for funds in the top N of their strategy
  where N is computed from the global default allocation weight for
  that strategy. Total elite funds across all strategies sums to 300.
- elite_rank_within_strategy: ordinal rank of the fund within its
  strategy bucket, 1 = best. NULL for funds outside their strategy's
  target count.
- elite_target_count_per_strategy: the computed target count for this
  fund's strategy (300 * strategy_weight), denormalized here for
  traceability and audit.

The columns are nullable to allow incremental population — the worker
may not produce values for every instrument every pass.

Revision ID: 0115_fund_risk_metrics_elite_flag
Revises: <Session 2.A last commit, verify with alembic heads>
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0115_fund_risk_metrics_elite_flag"
down_revision = "0114_wealth_vector_chunks_hypertable"  # verify
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fund_risk_metrics",
        sa.Column("elite_flag", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("elite_rank_within_strategy", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "fund_risk_metrics",
        sa.Column("elite_target_count_per_strategy", sa.SmallInteger(), nullable=True),
    )

    # Partial index supporting the screener's ELITE filter hot path
    op.create_index(
        "idx_fund_risk_metrics_elite_partial",
        "fund_risk_metrics",
        ["instrument_id", "as_of"],
        postgresql_where=sa.text("elite_flag = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_fund_risk_metrics_elite_partial",
        table_name="fund_risk_metrics",
    )
    op.drop_column("fund_risk_metrics", "elite_target_count_per_strategy")
    op.drop_column("fund_risk_metrics", "elite_rank_within_strategy")
    op.drop_column("fund_risk_metrics", "elite_flag")
```

**Critical:** partial index on `WHERE elite_flag = true` is the index that Phase 3 Screener's ELITE filter will use. Must match the predicate the screener query applies.

Update ORM model `FundRiskMetrics` in `backend/app/domains/wealth/models.py` (or wherever defined) in the same commit.

## Verification

1. `alembic upgrade head` clean
2. `alembic downgrade -1` clean
3. Insert a test row with `elite_flag=true` and verify the partial index is used: `EXPLAIN SELECT * FROM fund_risk_metrics WHERE elite_flag = true AND instrument_id = 'X'`
4. `make test` passes

## Commit 1 template

```
feat(db): add elite_flag + ranking columns to fund_risk_metrics

Prepares fund_risk_metrics for the ELITE ranking logic that will be
populated by risk_calc worker in commit 7 of this session. Adds:

- elite_flag: boolean, top-N-of-strategy marker
- elite_rank_within_strategy: ordinal rank within the strategy
- elite_target_count_per_strategy: denormalized target count
  (300 * strategy_weight) for traceability

Partial index idx_fund_risk_metrics_elite_partial (WHERE elite_flag =
true) supports Phase 3 Screener's ELITE filter hot path with minimal
index size.

ORM model FundRiskMetrics updated to expose the three fields.

Part of Phase 2 Session B — analytical layer.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 2 — feat(db): mv_fund_risk_latest materialized view

## Purpose

Screener hot path needs the latest `as_of` row per instrument without a correlated subquery. Pre-compute via materialized view with uniqueness and refresh policy.

## Deliverable

Migration `0116_mv_fund_risk_latest.py`:

```python
"""mv_fund_risk_latest materialized view.

Pre-computes the latest (by as_of) fund_risk_metrics row per
instrument_id. Screener queries read from this view directly instead
of running a correlated subquery like:

  SELECT * FROM fund_risk_metrics f
  WHERE f.as_of = (SELECT MAX(as_of) FROM fund_risk_metrics
                    WHERE instrument_id = f.instrument_id)

which is prohibitively slow at 9k+ instruments. This MV is refreshed
after each risk_calc worker pass (hourly or daily).

Revision ID: 0116_mv_fund_risk_latest
Revises: 0115_fund_risk_metrics_elite_flag
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op

revision = "0116_mv_fund_risk_latest"
down_revision = "0115_fund_risk_metrics_elite_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW mv_fund_risk_latest AS
        SELECT DISTINCT ON (instrument_id)
            instrument_id,
            as_of,
            sharpe_1y,
            volatility_1y,
            volatility_garch,
            cvar_95_12m,
            cvar_95_conditional,
            max_drawdown_1y,
            manager_score,
            blended_momentum_score,
            peer_sharpe_pctl,
            elite_flag,
            elite_rank_within_strategy,
            elite_target_count_per_strategy
        FROM fund_risk_metrics
        ORDER BY instrument_id, as_of DESC
        WITH NO DATA
    """)

    # Unique index required for CONCURRENT refresh
    op.execute("""
        CREATE UNIQUE INDEX uq_mv_fund_risk_latest_instrument
        ON mv_fund_risk_latest (instrument_id)
    """)

    # Supporting indexes for screener filter hot paths
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_elite
        ON mv_fund_risk_latest (instrument_id)
        WHERE elite_flag = true
    """)
    op.execute("""
        CREATE INDEX idx_mv_fund_risk_latest_sharpe
        ON mv_fund_risk_latest (sharpe_1y DESC NULLS LAST)
    """)

    # Initial population
    op.execute("REFRESH MATERIALIZED VIEW mv_fund_risk_latest")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_fund_risk_latest")
```

**Adjust column list** to match the actual columns Screener needs. Do NOT include columns the screener will not display — keeps the MV small. Read `backend/app/domains/wealth/routes/screener.py` to confirm the column selection.

## Verification

1. `alembic upgrade head` clean, initial population succeeds
2. `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_fund_risk_latest` succeeds (uniqueness is satisfied)
3. Row count matches `SELECT COUNT(DISTINCT instrument_id) FROM fund_risk_metrics`
4. EXPLAIN on a screener-shaped query shows the partial/supporting indexes being used

## Commit 2 template

```
feat(db): mv_fund_risk_latest materialized view

Pre-computes the latest fund_risk_metrics row per instrument_id so the
screener hot path avoids a correlated subquery that scales O(N) per row
at 9k+ instruments. DISTINCT ON (instrument_id) ORDER BY as_of DESC
gives the latest-row pattern.

Unique index on (instrument_id) enables CONCURRENT refresh. Partial
index on WHERE elite_flag = true and btree on sharpe_1y DESC NULLS
LAST support the screener's primary filter + sort hot paths.

Refresh triggered by risk_calc worker after each pass (to be wired in
Session 2.B commit 7 or a separate refresh trigger).

Part of Phase 2 Session B — analytical layer.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 3 — feat(db): v_screener_org_membership security view

## Purpose

Screener needs to display an "already in my universe" marker per fund without making the query a 3-way JOIN. A security-barrier view pre-joins `instruments_org` with RLS so the screener can read it as a single table with zero JOIN overhead.

## Deliverable

Migration `0117_v_screener_org_membership.py`:

```python
"""v_screener_org_membership security-barrier view.

Pre-joins instruments_org so the screener query can read membership
status (approved / pending / rejected) per instrument without a 3-way
JOIN on every filter change. The view uses security_barrier=true so
the RLS predicate on the underlying instruments_org table is applied
before the outer WHERE clause, preserving tenant isolation.

RLS predicate uses (SELECT current_setting(...)) subselect pattern per
CLAUDE.md Critical Rules — bare current_setting() causes 1000x slowdown.

Revision ID: 0117_v_screener_org_membership
Revises: 0116_mv_fund_risk_latest
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op

revision = "0117_v_screener_org_membership"
down_revision = "0116_mv_fund_risk_latest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW v_screener_org_membership
        WITH (security_barrier=true) AS
        SELECT
            io.instrument_universe_id AS instrument_id,
            io.organization_id,
            io.block_id,
            io.approval_status,
            io.fast_track,
            io.approved_at,
            io.approved_by
        FROM instruments_org io
        WHERE io.organization_id = (
            SELECT current_setting('app.current_organization_id', true)::uuid
        )
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_screener_org_membership")
```

**Adjust column selection** to match what the screener frontend actually reads. Do not expose columns not used by the UI.

## Verification

1. `alembic upgrade head` clean
2. `SET LOCAL app.current_organization_id = '<test-org-uuid>'` then `SELECT * FROM v_screener_org_membership` returns only that org's rows
3. A screener query that LEFT JOINs this view runs fast and returns membership status per instrument
4. `make test` passes

## Commit 3 template

```
feat(db): v_screener_org_membership security view

Pre-joins instruments_org with security_barrier=true so the screener
hot path can read org membership status (approved / pending / rejected,
block_id, fast_track flag, approval metadata) as a single-table LEFT
JOIN instead of a 3-way JOIN on every filter change.

RLS uses the mandatory (SELECT current_setting(...)) subselect pattern
per CLAUDE.md Critical Rules.

Exposes the columns the screener UI actually consumes:
instrument_id, organization_id, block_id, approval_status, fast_track,
approved_at, approved_by.

Part of Phase 2 Session B — analytical layer.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 4 — feat(db): mv_construction_run_diff materialized view

## Purpose

Phase 4 Builder wants a "diff against previous run" view to show weight + metrics deltas between consecutive construction runs for the same portfolio. Computing this on read is expensive; pre-compute via MV.

## Dependency

Commit 2 of Session 2.A (`event_log JSONB` column on `portfolio_construction_runs`). If that column is not present in main, STOP and escalate.

## Deliverable

Migration `0118_mv_construction_run_diff.py`:

```python
"""mv_construction_run_diff materialized view.

Computes weight + metrics deltas between consecutive construction runs
per portfolio. Phase 4 Builder's "Compare to previous run" analytics
panel reads from this view.

Structure per row:
  (portfolio_id, run_id, previous_run_id, weight_delta_jsonb,
   metrics_delta_jsonb, status_delta_text)

weight_delta_jsonb is a JSONB object keyed by instrument_id with
{from: old_weight, to: new_weight, delta: new - old}.
metrics_delta_jsonb captures expected return, volatility, CVaR, etc.
status_delta_text summarizes ("tightened 3 allocations, loosened 1").

Depends on the event_log column added in Session 2.A commit 2 — this
MV reads optimizer events from the log to extract final weights.

Revision ID: 0118_mv_construction_run_diff
Revises: 0117_v_screener_org_membership
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op

revision = "0118_mv_construction_run_diff"
down_revision = "0117_v_screener_org_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW mv_construction_run_diff AS
        WITH ordered AS (
            SELECT
                portfolio_id,
                id AS run_id,
                LAG(id) OVER (
                    PARTITION BY portfolio_id
                    ORDER BY started_at
                ) AS previous_run_id,
                started_at,
                event_log,
                final_weights,  -- assume column exists; adjust if different
                final_metrics,  -- assume column exists; adjust if different
                status
            FROM portfolio_construction_runs
            WHERE status IN ('succeeded', 'superseded')
        )
        SELECT
            o.portfolio_id,
            o.run_id,
            o.previous_run_id,
            (
                SELECT jsonb_object_agg(
                    key,
                    jsonb_build_object(
                        'from', COALESCE((p.final_weights->>key)::numeric, 0),
                        'to',   COALESCE((o.final_weights->>key)::numeric, 0),
                        'delta', COALESCE((o.final_weights->>key)::numeric, 0)
                               - COALESCE((p.final_weights->>key)::numeric, 0)
                    )
                )
                FROM jsonb_object_keys(COALESCE(o.final_weights, '{}'::jsonb)
                                       || COALESCE(p.final_weights, '{}'::jsonb)) AS key
            ) AS weight_delta_jsonb,
            (o.final_metrics - p.final_metrics) AS metrics_delta_jsonb,
            CASE
                WHEN o.previous_run_id IS NULL THEN 'initial run'
                ELSE 'delta computed'
            END AS status_delta_text
        FROM ordered o
        LEFT JOIN portfolio_construction_runs p ON p.id = o.previous_run_id
        WITH NO DATA
    """)

    op.execute("""
        CREATE UNIQUE INDEX uq_mv_construction_run_diff_run
        ON mv_construction_run_diff (run_id)
    """)
    op.execute("""
        CREATE INDEX idx_mv_construction_run_diff_portfolio
        ON mv_construction_run_diff (portfolio_id, run_id)
    """)

    op.execute("REFRESH MATERIALIZED VIEW mv_construction_run_diff")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_construction_run_diff")
```

**CRITICAL:** the query references `final_weights` and `final_metrics` columns. Verify these exist on `portfolio_construction_runs` before committing. If they have different names (e.g., `weights`, `metrics`, `output_jsonb`), adjust. If they don't exist at all, Phase 2 must first add them — but that's a separate commit and may indicate `portfolio_construction_runs` schema is incomplete.

## Verification

1. `alembic upgrade head` clean, MV populated
2. Check sample output: pick any portfolio with 2+ runs, verify diff rows are correct
3. `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_construction_run_diff` succeeds
4. `make test` passes

## Commit 4 template

```
feat(db): mv_construction_run_diff materialized view

Computes weight and metrics deltas between consecutive construction
runs per portfolio. Phase 4 Builder's "Compare to previous run" panel
will consume this view instead of recomputing on every request.

weight_delta_jsonb: keyed by instrument_id with {from, to, delta}
metrics_delta_jsonb: subtraction of final_metrics JSONB between runs
status_delta_text: short summary

Depends on event_log column from Session 2.A commit 2 — reads
optimizer trace events to extract final weights.

Unique index on run_id enables CONCURRENT refresh. Btree index on
(portfolio_id, run_id) supports the Builder's per-portfolio query.

Part of Phase 2 Session B — analytical layer.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 5 — feat(db): mv_drift_heatmap_weekly continuous aggregate

## Purpose

Dashboard / alerts surface needs a weekly drift bucket view for the heatmap visualization. Reading raw `strategy_drift_alerts` for a week-by-fund breakdown is expensive at scale; pre-compute via CAGG.

## Deliverable

Migration `0119_mv_drift_heatmap_weekly.py`:

```python
"""mv_drift_heatmap_weekly continuous aggregate.

Weekly bucket of strategy drift alerts per (portfolio_id, fund_id).
Dashboard / alerts heatmap reads from this CAGG instead of
aggregating raw strategy_drift_alerts on every request.

Bucket: ISO week (Monday start). Refresh policy: 1-day lag, refresh
every 4 hours.

Revision ID: 0119_mv_drift_heatmap_weekly
Revises: 0118_mv_construction_run_diff
Create Date: 2026-04-11
"""
from __future__ import annotations

import os
import psycopg
from alembic import op

revision = "0119_mv_drift_heatmap_weekly"
down_revision = "0118_mv_construction_run_diff"
branch_labels = None
depends_on = None


def _autocommit_conninfo() -> str:
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS mv_drift_heatmap_weekly
            WITH (timescaledb.continuous) AS
            SELECT
                portfolio_id,
                fund_id,
                time_bucket('1 week', created_at) AS week_start,
                COUNT(*) AS alert_count,
                MAX(severity) AS max_severity,
                AVG(drift_score) AS avg_drift_score,
                MAX(drift_score) AS max_drift_score
            FROM strategy_drift_alerts
            GROUP BY portfolio_id, fund_id, week_start
            WITH NO DATA
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_mv_drift_heatmap_weekly_pf_week
            ON mv_drift_heatmap_weekly (portfolio_id, week_start DESC)
        """)

        cur.execute("""
            SELECT add_continuous_aggregate_policy(
                'mv_drift_heatmap_weekly',
                start_offset => INTERVAL '6 months',
                end_offset => INTERVAL '1 day',
                schedule_interval => INTERVAL '4 hours',
                if_not_exists => true
            )
        """)


def downgrade() -> None:
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("DROP MATERIALIZED VIEW IF EXISTS mv_drift_heatmap_weekly")
```

**Adjust columns** based on actual `strategy_drift_alerts` schema. Verify `drift_score`, `severity`, `created_at`, `portfolio_id`, `fund_id` exist — if not, use the actual column names.

## Verification

1. `alembic upgrade head` clean, CAGG created
2. `SELECT * FROM timescaledb_information.continuous_aggregates WHERE view_name = 'mv_drift_heatmap_weekly'` returns a row with the correct refresh policy
3. Insert sample drift alerts, trigger refresh, verify aggregated output
4. `make test` passes

## Commit 5 template

```
feat(db): mv_drift_heatmap_weekly continuous aggregate

Weekly bucket of strategy_drift_alerts per (portfolio_id, fund_id).
Dashboard heatmap and alerts surface read from this CAGG instead of
aggregating raw strategy_drift_alerts every request.

Bucket: 1 week (Monday-start via time_bucket).
Refresh policy: 6-month history, 1-day lag, refresh every 4 hours.

Index on (portfolio_id, week_start DESC) for the dashboard query
pattern.

Uses DDL-in-autocommit pattern (CAGG DDL cannot run inside a
transaction block) matching the established 0049 pattern.

Part of Phase 2 Session B — analytical layer.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 6 — feat(wealth/config): confirm global default allocation blocks as ELITE ranking source

## Purpose

The ELITE ranking algorithm (commit 7) needs to read global default allocation weights per strategy. This commit is the investigation + lock-down of WHICH table and WHICH rows are the authoritative source, so commit 7's worker can read them without ambiguity.

## Investigation step

Before writing any code, run:

```bash
grep -rn "allocation_blocks" backend/app/domains/wealth/models.py
grep -rn "AllocationBlock" backend/app/domains/wealth/models.py
grep -rn "default.*allocation" backend/app/domains/wealth/ backend/vertical_engines/wealth/ backend/calibration/ backend/profiles/
grep -rn "strategy_weight\|strategic_weight\|allocation_weight" backend/
```

Answer these questions:

1. Does a table `allocation_blocks` exist? What columns?
2. Is there a flag column like `is_default`, `is_global_default`, `scope`, `tenant_id`, or similar to distinguish the global default set from per-portfolio allocation blocks?
3. Are there seed files in `calibration/` or `profiles/` that populate the global default?
4. What are the "strategies" — is there a `strategy_label` enum, or are strategies free-form strings, or are they rows in an `asset_classes` / `strategies` table?
5. How are strategic weights currently accessed? Via `ConfigService.get("wealth", "allocation_blocks", org_id=None)` or a direct DB query?

## Deliverable

Based on investigation findings, the commit takes ONE of these three forms:

### Form A — Global defaults already exist and are accessible

If investigation confirms a `global_default_allocation_blocks` row set (e.g., `WHERE organization_id IS NULL AND is_default = true`) already in the DB, commit 6 is a **documentation + accessor** commit:

- Add a module `backend/vertical_engines/wealth/elite_ranking/allocation_source.py` with a single function:
  ```python
  def get_global_default_strategy_weights(db: Session) -> dict[str, float]:
      """Authoritative source of strategic weights for ELITE ranking.

      Returns {strategy_label: weight_fraction} summing to 1.0.
      """
      ...
  ```
- The function queries whatever rows the investigation identified as the authoritative default
- Include a docstring explaining WHY this is the source of truth and what the weights mean
- Add a unit test confirming the sum is 1.0 (or within tolerance)

### Form B — Global defaults exist but are scattered / undocumented

If investigation finds the data but it's in multiple places (e.g., YAML seeds + DB rows + hardcoded constants), commit 6 **consolidates** them:

- Pick the authoritative source (prefer DB row set with `is_default=true`)
- Add a data migration that sets the flag on the correct rows if it's not set
- Delete or deprecate the hardcoded constants
- Document the single source of truth
- Add the accessor function per Form A

### Form C — Global defaults do not exist at all

If investigation confirms no global default allocation set exists anywhere, commit 6 **creates** them:

- Add a seed migration `0120_seed_global_default_allocation_blocks.py` that INSERTs the default blocks with `organization_id = NULL` and `is_default = true` (add the flag column if it doesn't exist)
- Default strategy weights: consult Andrei via escape hatch — do NOT invent institutional-grade weights without human approval
- Add the accessor function per Form A

**Escape hatch:** if Form C is required (no defaults exist) AND investigation cannot determine reasonable default weights, STOP and escalate. Inventing allocation weights without domain input violates the project mandate's "real accurate data" principle.

## Verification

1. Accessor function returns a dict summing to 1.0 (±0.001 tolerance for rounding)
2. `make test` passes including new accessor unit test
3. If Form B or C: `alembic upgrade head` clean, data migration applied
4. The strategies returned match known strategies in the catalog (`mv_unified_funds.strategy_label` or equivalent)

## Commit 6 template

```
feat(wealth/config): confirm global default allocation blocks as ELITE ranking source

Investigation (Phase 2 Session B commit 6) resolved the authoritative
source of strategic weights for ELITE ranking:

<describe findings: Form A / B / C outcome, which table+rows, which
column marks the default, what the weights are>

Adds backend/vertical_engines/wealth/elite_ranking/allocation_source.py
with get_global_default_strategy_weights() — the single callable every
ELITE ranking consumer uses. Returns {strategy_label: weight_fraction}
summing to 1.0.

<If Form B or C: describe the data migration that normalized the
source, or the seed that created the default rows.>

Unit test asserts sum = 1.0 (±0.001) and that all returned strategies
exist in the catalog.

This commit is the prerequisite for commit 7 (risk_calc ELITE ranking
logic) which reads this accessor to compute target counts per strategy.

Part of Phase 2 Session B — analytical layer.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 7 — feat(wealth/workers): risk_calc ELITE ranking logic

## Purpose

Implement the ELITE ranking algorithm in `risk_calc.py`. Reads strategic weights via commit 6's accessor, ranks funds within each strategy by composite score, sets `elite_flag`, `elite_rank_within_strategy`, and `elite_target_count_per_strategy` on `fund_risk_metrics`.

## Algorithm (from overview file)

```python
# Pseudocode:
strategy_weights = get_global_default_strategy_weights(db)
total_elite_target = 300

# 1. Compute per-strategy target counts (should sum to 300)
target_counts = {
    strategy: round(total_elite_target * weight)
    for strategy, weight in strategy_weights.items()
}

# 2. For each strategy, rank funds by composite score
for strategy, target_count in target_counts.items():
    ranked = db.execute(
        """
        SELECT instrument_id, composite_score
        FROM fund_risk_metrics
        WHERE strategy_label = :strategy
          AND as_of = (latest as_of for this instrument)
          AND composite_score IS NOT NULL
        ORDER BY composite_score DESC NULLS LAST
        LIMIT :limit
        """,
        {"strategy": strategy, "limit": target_count}
    ).fetchall()

    elite_instrument_ids = {row.instrument_id for row in ranked}

    # 3. Update fund_risk_metrics rows
    for rank, row in enumerate(ranked, start=1):
        db.execute(
            """
            UPDATE fund_risk_metrics
            SET elite_flag = true,
                elite_rank_within_strategy = :rank,
                elite_target_count_per_strategy = :target_count
            WHERE instrument_id = :instrument_id
              AND as_of = (latest as_of)
            """,
            {
                "rank": rank,
                "target_count": target_count,
                "instrument_id": row.instrument_id,
            }
        )

    # 4. Clear elite_flag for funds in this strategy that didn't make the cut
    db.execute(
        """
        UPDATE fund_risk_metrics
        SET elite_flag = false,
            elite_rank_within_strategy = NULL,
            elite_target_count_per_strategy = :target_count
        WHERE strategy_label = :strategy
          AND as_of = (latest as_of)
          AND instrument_id NOT IN :elite_ids
        """,
        {
            "strategy": strategy,
            "target_count": target_count,
            "elite_ids": tuple(elite_instrument_ids) or (None,),
        }
    )
```

## Deliverable

Modify `backend/app/domains/wealth/workers/risk_calc.py`:

- Add a new function `compute_elite_ranking(db)` implementing the algorithm
- Call it from the worker's main pass (after composite scores are computed, before MV refresh)
- Wrap in `pg_try_advisory_lock(900_071)` consistent with existing worker discipline
- Trigger `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_fund_risk_latest` after the UPDATE pass

Key considerations:
- Use a single transaction per strategy to minimize lock contention
- Use `SELECT ... FOR UPDATE SKIP LOCKED` if parallel worker instances could race (unlikely with advisory lock, but defensive)
- Log each strategy's target count vs actual count for observability
- Handle the edge case where `sum(round(300 * weight))` is not exactly 300 — off-by-rounding is acceptable, log a warning if deviation > 3 funds

**Tests:**
- Add `backend/tests/wealth/workers/test_risk_calc_elite_ranking.py`:
  - Unit test with fixture: 5 strategies × 100 funds each, weights 0.4/0.25/0.2/0.1/0.05
  - Assert: total elite funds = 300 (or 299/301 with rounding tolerance)
  - Assert: each strategy has `round(300 * weight)` elite funds ± rounding
  - Assert: within each strategy, elite funds are the top-N by composite score
  - Assert: `elite_flag`, `elite_rank_within_strategy`, `elite_target_count_per_strategy` are all populated correctly

## Verification

1. `make test` passes including new tests
2. Run the worker against local dev DB with fixture data, verify output via:
   ```sql
   SELECT strategy_label, COUNT(*) FILTER (WHERE elite_flag = true) AS elite_count,
                                    COUNT(*) AS total_count
   FROM fund_risk_metrics f
   JOIN instruments_universe i ON i.id = f.instrument_id
   WHERE f.as_of = (SELECT MAX(as_of) FROM fund_risk_metrics)
   GROUP BY strategy_label;
   ```
3. Sum of `elite_count` across strategies should be 300 ± small rounding tolerance
4. No strategy exceeds its target count

## Commit 7 template

```
feat(wealth/workers): risk_calc ELITE ranking logic

Implements the ELITE ranking algorithm per overview §"ELITE definition":
the top 300 funds by composite score, distributed across strategies
proportionally to global default allocation weights.

Algorithm:
1. Read strategy weights via allocation_source.get_global_default_strategy_weights()
2. Compute target_count_per_strategy = round(300 * strategy_weight)
3. For each strategy, rank funds by composite_score DESC, select top N
4. Set elite_flag=true, elite_rank_within_strategy, elite_target_count_per_strategy
5. Clear elite_flag on non-winners within the same strategy
6. Refresh mv_fund_risk_latest CONCURRENTLY after the pass

Trigger: existing risk_calc worker pass, after composite score
computation, before MV refresh. Wrapped in pg_try_advisory_lock(900_071)
consistent with the worker's lock discipline.

Observability: logs target count and actual count per strategy;
warns if rounding deviation > 3 funds.

Tests: 5 strategies × 100 funds fixture, asserts correct distribution
and top-N selection within each strategy.

Partial data caveat: ELITE values will only be correct once the Tiingo
Migration sprint fixes score input population (blended_momentum_score,
peer_sharpe_pctl currently degraded). Until then, ELITE reflects
whatever score data is available.

Part of Phase 2 Session B — analytical layer. Final commit.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# FINAL FULL-TREE VERIFICATION

After all 7 commits land:

1. `alembic upgrade head` → clean
2. `alembic downgrade -5` → reverses commits 1-5 cleanly (commits 6 and 7 are Python/worker changes, reverted via git revert if needed)
3. `make check` → green
4. `make test` → all wealth tests pass including new ELITE ranking tests
5. Manual query: run the risk_calc ELITE ranking against local dev DB, verify `elite_count ≈ 300` across strategies
6. Check materialized views populated:
   ```sql
   SELECT * FROM mv_fund_risk_latest LIMIT 5;
   SELECT * FROM mv_construction_run_diff LIMIT 5;
   SELECT * FROM mv_drift_heatmap_weekly LIMIT 5;
   ```

# SELF-CHECK CHECKLIST

- [ ] `alembic heads` confirmed at 2.A's last migration before starting
- [ ] Commit 1: schema columns + partial index, ORM model updated
- [ ] Commit 2: MV populated, CONCURRENT refresh works, row count matches expected
- [ ] Commit 3: view returns correct org-scoped rows with security_barrier
- [ ] Commit 4: diff MV populated, sample runs show correct deltas, depends on event_log confirmed
- [ ] Commit 5: CAGG created with refresh policy, DDL-in-autocommit pattern followed
- [ ] Commit 6: investigation done, Form A/B/C path chosen, accessor function added with unit test
- [ ] Commit 7: ELITE ranking algorithm implemented, tests pass, advisory lock used, MV refresh triggered
- [ ] No files outside Session B scope touched
- [ ] Sessions A migrations untouched
- [ ] Parallel session (Tiingo) files untouched
- [ ] packages/investintell-ui unchanged (smoke check)

# VALID ESCAPE HATCHES

1. `event_log` column from Session 2.A is not present in main → Session 2.A didn't ship, STOP and report
2. Commit 6 investigation shows Form C (no defaults exist) AND cannot determine weights → STOP, escalate to Andrei for strategic weight values
3. `portfolio_construction_runs` lacks `final_weights` / `final_metrics` columns referenced in commit 4 → report actual column names, adjust the MV query
4. `strategy_drift_alerts` lacks `drift_score` or `severity` columns referenced in commit 5 → report actual columns, adjust the CAGG query
5. ELITE ranking unit tests fail because fixture shape doesn't match production reality → review fixture, DO NOT relax assertions
6. Worker pass takes > 5 minutes on local dev DB → report as performance concern, investigate whether per-strategy transactions are correct

# NOT VALID ESCAPE HATCHES

- "The partial index isn't worth it, let me skip" → NO, phase 3 screener needs it
- "I'll hardcode strategy weights in commit 7 to avoid the investigation" → NO, commit 6 is mandatory
- "I'll use a simpler threshold-based ELITE definition" → NO, the 300-by-strategy-quota is locked per overview
- "I'll skip the unit test" → NO, ELITE math is subtle, tests are mandatory

# REPORT FORMAT

1. Seven commit SHAs with full messages
2. Per commit: migration/file paths, verification output, relevant schema state
3. Commit 6 extra: full investigation report (what was found, which Form was chosen, what the accessor returns)
4. Commit 7 extra: ELITE distribution output from the verification query (counts per strategy)
5. Full-tree verification output
6. Any escape hatches hit

Begin by reading the overview + this brief + audit report. Confirm Session 2.A merged (event_log column exists). Run commit 6 investigation before writing commit 6 code.
