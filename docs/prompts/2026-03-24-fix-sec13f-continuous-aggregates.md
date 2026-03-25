---
date: 2026-03-24
task: fix-sec13f-continuous-aggregates
priority: P0 — required for demo presentation
---

# Fix: sec_13f_holdings_agg + sec_13f_drift_agg

## Context

You are the engineer who seeded the demo tenant for the Netz Analysis Engine.
During seeding you identified two broken continuous aggregates:

1. `sec_13f_holdings_agg` — 0 rows despite 1,092,225 rows in source table.
   Root cause: aggregate definition filters `WHERE asset_class = 'COM'` but
   actual data uses `'Shares'` and `'Principal'`.

2. `sec_13f_drift_agg` — 0 rows because `sec_13f_diffs` has 0 rows.
   Root cause: `sec_13f_ingestion` worker has not computed diffs yet.

Both aggregates are required for the demo presentation:
- `sec_13f_holdings_agg` → 13F screener, reverse holding lookup
- `sec_13f_drift_agg` → drift analysis (manager position changes over time)

Demo org:
- org_id: e28fc30c-9d6d-4b21-8e91-cad8696b44fa
- DB: Timescale Cloud (nvhhm6dwvh.keh9pcdgv1.tsdb.cloud.timescale.com:30124/tsdb)

---

## Step 1 — Inspect current aggregate definitions

```bash
# Find the migration that creates sec_13f_holdings_agg and sec_13f_drift_agg
grep -r "sec_13f_holdings_agg\|sec_13f_drift_agg" \
  backend/app/core/db/migrations/versions/ --include="*.py" -l
```

Read the migration file. Note the exact CREATE MATERIALIZED VIEW SQL for
both aggregates — you will need to recreate them with corrections.

Also inspect the actual data to confirm asset_class values:

```sql
SELECT DISTINCT asset_class, COUNT(*) AS cnt
FROM sec_13f_holdings
GROUP BY asset_class
ORDER BY cnt DESC;
```

---

## Step 2 — Fix sec_13f_holdings_agg

The aggregate must be dropped and recreated with the correct asset_class
filter. Use the existing migration SQL as base — change only what is broken.

```sql
-- 1. Drop existing broken aggregate (CASCADE drops dependent objects)
DROP MATERIALIZED VIEW IF EXISTS sec_13f_holdings_agg CASCADE;

-- 2. Recreate with corrected asset_class filter
-- Use the exact SQL from the migration but replace:
--   WHERE asset_class = 'COM'
-- with the correct values found in Step 1 (likely 'Shares' and 'Principal')
-- OR remove the asset_class filter entirely if all values are valid

CREATE MATERIALIZED VIEW sec_13f_holdings_agg
WITH (timescaledb.continuous) AS
-- [paste corrected SQL from migration here]
;

-- 3. Re-add refresh policy (use same parameters as original migration)
SELECT add_continuous_aggregate_policy('sec_13f_holdings_agg',
    start_offset => INTERVAL '2 years',
    end_offset   => INTERVAL '1 day',
    schedule_interval => INTERVAL '7 days');

-- 4. Refresh immediately
CALL refresh_continuous_aggregate('sec_13f_holdings_agg', NULL, NULL);

-- 5. Verify
SELECT COUNT(*) AS rows FROM sec_13f_holdings_agg;
-- Expected: > 0 (proportional to 1,092,225 source rows aggregated by quarter)
```

---

## Step 3 — Populate sec_13f_diffs and fix sec_13f_drift_agg

`sec_13f_drift_agg` depends on `sec_13f_diffs`. First populate diffs:

```bash
# Find the sec_13f_ingestion worker
find . -name "sec_13f_ingestion.py" -not -path "*__pycache__*"
```

Read the worker source. Identify how it computes diffs (likely a
`compute_diffs()` call from `ThirteenFService`). Run the diff computation:

```bash
DATABASE_URL=<cloud-url> python -m workers.sec_13f_ingestion --compute-diffs
# OR however the worker triggers diff computation — read source first
```

If the worker does not have a standalone diff flag, call the service directly:

```python
# Run in a one-off script against Cloud DB
from data_providers.sec.thirteenf_service import ThirteenFService

async def run():
    async with get_db_session() as db:
        svc = ThirteenFService(db)
        # Compute diffs for all available CIKs and quarters
        ciks = await svc.list_known_ciks()
        for cik in ciks:
            await svc.compute_diffs(cik)

asyncio.run(run())
```

After diffs are populated, refresh the drift aggregate:

```sql
-- Verify sec_13f_diffs is populated
SELECT COUNT(*), COUNT(DISTINCT filer_cik) FROM sec_13f_diffs;

-- Refresh drift aggregate
CALL refresh_continuous_aggregate('sec_13f_drift_agg', NULL, NULL);

-- Verify
SELECT COUNT(*) AS rows FROM sec_13f_drift_agg;
-- Expected: > 0
```

---

## Step 4 — Verify both aggregates

```sql
SELECT
    'sec_13f_holdings'      AS tbl, COUNT(*) AS rows FROM sec_13f_holdings
UNION ALL SELECT
    'sec_13f_diffs',                COUNT(*) FROM sec_13f_diffs
UNION ALL SELECT
    'sec_13f_holdings_agg',         COUNT(*) FROM sec_13f_holdings_agg
UNION ALL SELECT
    'sec_13f_drift_agg',            COUNT(*) FROM sec_13f_drift_agg
UNION ALL SELECT
    'sec_13f_latest_quarter',       COUNT(*) FROM sec_13f_latest_quarter;
```

Expected:
- `sec_13f_holdings`: 1,092,225
- `sec_13f_diffs`: > 0
- `sec_13f_holdings_agg`: > 0
- `sec_13f_drift_agg`: > 0
- `sec_13f_latest_quarter`: 543 (already correct)

---

## Step 5 — Update the migration (prevent regression)

After fixing in production, update the migration file so future
`make migrate` runs apply the correct definition:

```bash
# Edit the migration that creates sec_13f_holdings_agg
# Replace the broken WHERE asset_class = 'COM' with correct values
# This prevents the same breakage on any fresh DB setup
```

Run `make check` after editing the migration.

---

## Rules

- Read the migration source before touching the aggregate definition
- Do NOT drop sec_13f_latest_quarter — it is already correct (543 rows)
- Do NOT touch nav_monthly_returns_agg or benchmark_monthly_agg
- If compute_diffs fails, capture full traceback and report before proceeding
- Always confirm DATABASE_URL = Timescale Cloud before any DDL

## Success Criteria

- `sec_13f_holdings_agg`: > 0 rows
- `sec_13f_drift_agg`: > 0 rows
- `sec_13f_latest_quarter`: still 543 rows (unchanged)
- Migration updated to prevent regression
- `make check` passes
