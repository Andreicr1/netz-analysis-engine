---
status: pending
priority: p2
issue_id: "198"
tags: [migration, timescaledb, wealth, manager-screener]
dependencies: []
---

# Migration 0038: Manager Screener indexes + continuous aggregates

## Problem Statement

The Manager Screener needs 2 indexes on `sec_managers` and 2 TimescaleDB continuous aggregates (`sec_13f_holdings_agg`, `sec_13f_drift_agg`) to avoid per-request CTE computation over raw hypertables.

## Proposed Solution

### Approach

Create Alembic migration `0038_manager_screener_indexes_continuous_aggs.py`:

1. **Indexes on `sec_managers`:**
   ```sql
   CREATE INDEX idx_sec_managers_aum ON sec_managers (aum_total DESC);
   CREATE INDEX idx_sec_managers_compliance_aum ON sec_managers (compliance_disclosures, aum_total DESC);
   ```

2. **Continuous aggregate `sec_13f_holdings_agg`:**
   ```sql
   CREATE MATERIALIZED VIEW sec_13f_holdings_agg
   WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
   SELECT cik,
          time_bucket('3 months'::interval, report_date) AS quarter,
          sector,
          SUM(market_value) AS sector_value,
          COUNT(DISTINCT cusip) AS position_count
   FROM sec_13f_holdings
   WHERE asset_class = 'COM'
   GROUP BY cik, time_bucket('3 months'::interval, report_date), sector
   WITH NO DATA;
   ```
   Plus manual index: `idx_sec_13f_holdings_agg_cik_quarter (cik, quarter DESC)`

3. **Continuous aggregate `sec_13f_drift_agg`:**
   ```sql
   CREATE MATERIALIZED VIEW sec_13f_drift_agg
   WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
   SELECT cik,
          time_bucket('3 months'::interval, quarter_to) AS quarter,
          COUNT(*) FILTER (WHERE action IN ('NEW_POSITION','EXITED')) AS churn_count,
          COUNT(*) AS total_changes
   FROM sec_13f_diffs
   GROUP BY cik, time_bucket('3 months'::interval, quarter_to)
   WITH NO DATA;
   ```
   Plus manual index: `idx_sec_13f_drift_agg_cik_quarter (cik, quarter DESC)`

4. **Refresh policies:** Daily refresh for both aggregates (`refresh_continuous_aggregate`).

5. **Downgrade:** Drop views and indexes in reverse order.

Use `op.execute()` for continuous aggregate DDL (Alembic has no native support for TimescaleDB views).

## Technical Details

**Affected files:**
- `backend/alembic/versions/0038_manager_screener_indexes_continuous_aggs.py` — new migration

**Constraints:**
- `materialized_only = true` — SEC 13F data arrives quarterly, no benefit from real-time mode
- Continuous aggregates are on global tables (no RLS)
- Downgrade must `DROP MATERIALIZED VIEW` (not `DROP VIEW`)
- Must run `CALL refresh_continuous_aggregate(...)` after creation to seed initial data

## Acceptance Criteria

- [ ] Migration applies cleanly on fresh DB and on existing DB with SEC data
- [ ] `sec_13f_holdings_agg` and `sec_13f_drift_agg` created with correct columns
- [ ] Manual indexes on aggregates exist after migration
- [ ] `sec_managers` indexes exist after migration
- [ ] Downgrade drops all objects cleanly
- [ ] `make check` passes (lint + typecheck + test)
