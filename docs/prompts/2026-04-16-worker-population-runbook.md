# Worker Population Runbook — Bring Local DB Current

**Date:** 2026-04-16
**Executor:** Opus 4.6 (1M context)
**Branch:** `main` (current HEAD, no branch needed — operational task, not code change)
**Scope:** Run ALL pending workers against docker-compose local DB to populate data from the classification + regime + risk improvements merged over 2026-04-13/14. Report before/after metrics for every step.

---

## Why this exists

16 prompts implemented by Andrei over 2026-04-13/14 merged code changes across 4 axes (regime intelligence, universe sanitization, classification cascade, construction engine). The code is in main but **workers have not been run** against the local DB, so data is stale:
- `macro_data` missing 3 new FRED series (ICSA, TOTBKCR, PERMIT)
- `macro_regime_snapshot` table is empty (regime_detection never ran)
- `fund_risk_metrics` missing DTW drift global + return_5y/10y columns
- `is_institutional` flags not set (universe_sanitization never ran)
- `strategy_label` stale (47-label classifier not applied)
- `mv_unified_funds` not refreshed with latest sanitization + classification

---

## Prerequisites

Confirm BEFORE starting:

```bash
# 1. Docker stack running
docker ps | grep -E "netz.*db|netz.*redis"
# Must show both healthy containers

# 2. Backend can connect
cd backend
python -c "import asyncio; from app.core.db.session import async_session_factory; print('DB OK')"

# 3. FRED API key set
echo $FRED_API_KEY
# Must be non-empty (free key from https://fred.stlouisfed.org/docs/api/api_key.html)

# 4. Migrations up to date
cd backend && alembic current
# Must show head (0138 or later)
```

If any prerequisite fails, STOP and report. Do NOT proceed with stale migrations or missing FRED key.

---

## Execution Protocol

For EACH step below:

1. **BEFORE snapshot:** Run the provided SQL query and capture row counts / coverage metrics
2. **Execute** the worker
3. **AFTER snapshot:** Run the same SQL query, capture new counts
4. **Report** as a table: `| Metric | Before | After | Delta |`
5. If any worker FAILS: capture the full traceback, report it, and STOP (do not skip to next worker)

Use `asyncio.run()` for async workers. Use the sync `DATABASE_URL_SYNC` for scripts that need psycopg.

---

## Step 1 — macro_ingestion (lock 43)

**Purpose:** Fetch 3 new FRED series (ICSA, TOTBKCR, PERMIT) + refresh all existing ~65 series.

**BEFORE snapshot SQL:**
```sql
SELECT series_id, COUNT(*) as obs_count, MIN(observation_date), MAX(observation_date)
FROM macro_data
WHERE series_id IN ('ICSA', 'TOTBKCR', 'PERMIT')
GROUP BY series_id
ORDER BY series_id;

SELECT COUNT(DISTINCT series_id) AS total_series,
       COUNT(*) AS total_observations
FROM macro_data;
```

**Execute:**
```python
import asyncio
from app.domains.wealth.workers.macro_ingestion import run_macro_ingestion

result = asyncio.run(run_macro_ingestion(lookback_years=10))
print(result)
```

**AFTER snapshot:** Same SQL. Report new series counts + total series delta.

**Expected outcome:** ICSA, TOTBKCR, PERMIT each appear with ~520 weekly/monthly observations. Total series ~68 (was ~65).

**Timeout:** 10 min max. If FRED API is rate-limited, wait 60s and retry once.

---

## Step 2 — regime_detection (lock 900_130)

**Purpose:** Compute global regime snapshot (multi-signal, 13 signals, dynamic weights).

**BEFORE snapshot SQL:**
```sql
SELECT COUNT(*) AS snapshot_count,
       MAX(eval_date) AS latest_eval_date
FROM macro_regime_snapshot;

SELECT regime, COUNT(*) FROM macro_regime_snapshot GROUP BY regime;
```

**Execute:**
```python
import asyncio
from app.domains.wealth.workers.regime_detection import run_global_regime_detection

asyncio.run(run_global_regime_detection())
```

Note: function may be exported from `risk_calc.py` instead — check import path. If `regime_detection.py` module exists, use it. If not, import from `risk_calc.py`.

**AFTER snapshot:** Same SQL. Report regime classification + stress score + signal breakdown.

**Additional verification:**
```sql
SELECT eval_date, regime, stress_score,
       signal_breakdown->>'vix_zscore' as vix,
       signal_breakdown->>'hy_oas_zscore' as hy_oas,
       signal_breakdown->>'cfnai' as cfnai,
       signal_breakdown->>'icsa_zscore' as icsa
FROM macro_regime_snapshot
ORDER BY eval_date DESC
LIMIT 5;
```

**Expected outcome:** At least 1 row with today's date. Regime should be one of EXPANSION/RISK_ON/RISK_OFF/CRISIS. Stress score 0-100.

---

## Step 3 — global_risk_metrics (lock 900_071)

**Purpose:** Compute risk metrics for ALL active instruments globally, including DTW drift + 5Y/10Y returns.

**BEFORE snapshot SQL:**
```sql
SELECT COUNT(*) AS total_rows,
       COUNT(dtw_drift_score) AS has_dtw,
       COUNT(return_5y_ann) AS has_5y,
       COUNT(return_10y_ann) AS has_10y,
       COUNT(manager_score) AS has_score,
       COUNT(DISTINCT instrument_id) AS distinct_instruments
FROM fund_risk_metrics
WHERE organization_id IS NULL;
```

**Execute:**
```python
import asyncio
from app.domains.wealth.workers.risk_calc import run_global_risk_metrics

result = asyncio.run(run_global_risk_metrics())
print(result)
```

**AFTER snapshot:** Same SQL. Report DTW coverage, 5Y/10Y return coverage, manager_score coverage.

**Expected outcome:**
- `has_dtw` > 80% of `distinct_instruments` (was likely 0%)
- `has_5y` ~82% of instruments with 5Y+ NAV history
- `has_10y` ~60% of instruments with 10Y+ NAV history
- `has_score` should be near 100%

**Timeout:** 30 min max (6k+ instruments × multiple metrics). This is the longest worker.

---

## Step 4 — risk_calc per org (lock 900_007)

**Purpose:** Compute org-scoped risk metrics, reading regime from the new global snapshot.

**BEFORE snapshot SQL:**
```sql
-- Find all active orgs
SELECT DISTINCT organization_id FROM instruments_org;

-- Per-org risk metric freshness
SELECT organization_id, COUNT(*), MAX(calc_date)
FROM fund_risk_metrics
WHERE organization_id IS NOT NULL
GROUP BY organization_id;
```

**Execute:**
```python
import asyncio
import uuid
from app.domains.wealth.workers.risk_calc import run_risk_calc

# Get org IDs first
from app.core.db.session import async_session_factory
from sqlalchemy import text

async def run_all_orgs():
    async with async_session_factory() as db:
        result = await db.execute(text("SELECT DISTINCT organization_id FROM instruments_org"))
        org_ids = [row[0] for row in result.all()]

    for oid in org_ids:
        print(f"Running risk_calc for org {oid}...")
        r = await run_risk_calc(org_id=uuid.UUID(str(oid)))
        print(f"  Result: {r}")

asyncio.run(run_all_orgs())
```

**AFTER snapshot:** Same SQL. Report per-org metric counts + calc_date.

**Expected outcome:** Each org's `fund_risk_metrics` rows have `calc_date = today`. Regime info sourced from `macro_regime_snapshot` (not recomputed).

---

## Step 5 — universe_sanitization (lock 900_063)

**Purpose:** Flag non-institutional vehicles across 6 tables (~26k excluded from ~79k).

**BEFORE snapshot SQL:**
```sql
SELECT
    'sec_manager_funds' AS tbl,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE is_institutional) AS institutional,
    COUNT(*) FILTER (WHERE NOT is_institutional) AS excluded
FROM sec_manager_funds
UNION ALL
SELECT 'sec_registered_funds', COUNT(*), COUNT(*) FILTER (WHERE is_institutional), COUNT(*) FILTER (WHERE NOT is_institutional) FROM sec_registered_funds
UNION ALL
SELECT 'sec_etfs', COUNT(*), COUNT(*) FILTER (WHERE is_institutional), COUNT(*) FILTER (WHERE NOT is_institutional) FROM sec_etfs
UNION ALL
SELECT 'esma_funds', COUNT(*), COUNT(*) FILTER (WHERE is_institutional), COUNT(*) FILTER (WHERE NOT is_institutional) FROM esma_funds
UNION ALL
SELECT 'sec_bdcs', COUNT(*), COUNT(*) FILTER (WHERE is_institutional), COUNT(*) FILTER (WHERE NOT is_institutional) FROM sec_bdcs
UNION ALL
SELECT 'sec_money_market_funds', COUNT(*), COUNT(*) FILTER (WHERE is_institutional), COUNT(*) FILTER (WHERE NOT is_institutional) FROM sec_money_market_funds;

-- Also check instruments_universe
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE is_institutional) AS institutional
FROM instruments_universe;
```

**Execute:**
```python
import asyncio
from app.domains.wealth.workers.universe_sanitization import run_universe_sanitization

result = asyncio.run(run_universe_sanitization())
print(result)
```

**AFTER snapshot:** Same SQL. Report per-table institutional/excluded counts.

**Expected outcome:** ~53k institutional (from ~79k total). ~26k flagged as non-institutional with `exclusion_reason` set.

---

## Step 6 — strategy_reclassification (lock 900_062)

**Purpose:** Run 47-label cascade classifier (Rounds 1+2 patches) against institutional-only funds. Writes to staging table ONLY (never touches production labels).

**BEFORE snapshot SQL:**
```sql
-- Current label distribution (production)
SELECT strategy_label, COUNT(*) AS cnt
FROM instruments_universe
WHERE is_institutional = true
GROUP BY strategy_label
ORDER BY cnt DESC
LIMIT 30;

-- Count NULLs
SELECT COUNT(*) AS null_labels
FROM instruments_universe
WHERE is_institutional = true AND strategy_label IS NULL;

-- Existing staging runs
SELECT run_id, created_at, COUNT(*) AS rows
FROM strategy_reclassification_stage
GROUP BY run_id, created_at
ORDER BY created_at DESC
LIMIT 5;
```

**Execute:**
```python
import asyncio
from app.domains.wealth.workers.strategy_reclassification import run_strategy_reclassification

result = asyncio.run(run_strategy_reclassification())
print(f"Run ID: {result.get('run_id')}")
print(f"Summary: {result}")
```

**CAPTURE the `run_id` from the output — it's needed for Steps 7-9.**

**AFTER snapshot SQL:**
```sql
-- Staging distribution for new run
SELECT proposed_label, COUNT(*) AS cnt
FROM strategy_reclassification_stage
WHERE run_id = '<RUN_ID_FROM_OUTPUT>'
GROUP BY proposed_label
ORDER BY cnt DESC
LIMIT 30;

-- Severity distribution
SELECT severity, COUNT(*) AS cnt
FROM strategy_reclassification_stage
WHERE run_id = '<RUN_ID_FROM_OUTPUT>'
GROUP BY severity
ORDER BY cnt DESC;
```

**Expected outcome:** New `run_id` with ~53k rows. Severity distribution: P0 ~1,400, P1 ~5,000, P2 ~13,000, P3 ~9,600, unchanged ~24,000.

---

## Step 7 — strategy_diff_report (manual)

**Purpose:** Generate CSV diff report for review before applying.

**Execute:**
```bash
cd backend
python scripts/strategy_diff_report.py --run-id <RUN_ID> --output reports/strategy_diff_full.csv
python scripts/strategy_diff_report.py --run-id <RUN_ID> --severity safe_auto_apply --output reports/strategy_diff_p0.csv
python scripts/strategy_diff_report.py --run-id <RUN_ID> --severity lost_class --output reports/strategy_diff_p3.csv
```

**Report:** row counts per severity tier from the CSV. Attach P0 and P3 CSVs to the output.

---

## Step 8 — apply P0 (safe_auto_apply, ~1,400 rows)

**Purpose:** Apply NULL → specific label changes. Zero risk (no existing label overwritten).

**BEFORE snapshot SQL:**
```sql
SELECT COUNT(*) AS null_labels
FROM instruments_universe
WHERE is_institutional = true AND strategy_label IS NULL;
```

**Execute:**
```bash
cd backend
python scripts/apply_strategy_reclassification.py \
    --run-id <RUN_ID> \
    --severity safe \
    --confirm
```

**AFTER snapshot:** Same SQL. `null_labels` should drop by ~1,400.

---

## Step 9 — apply P1 (style_refinement, ~5,000 rows)

**Purpose:** Apply same-family refinements (e.g., "Equity" → "Large Value"). Low risk.

**BEFORE snapshot SQL:**
```sql
SELECT strategy_label, COUNT(*) AS cnt
FROM instruments_universe
WHERE is_institutional = true
GROUP BY strategy_label
ORDER BY cnt DESC
LIMIT 20;
```

**Execute:**
```bash
cd backend
python scripts/apply_strategy_reclassification.py \
    --run-id <RUN_ID> \
    --severity style \
    --confirm
```

**AFTER snapshot:** Same SQL. Show label distribution shift.

**Note:** P2 (asset_class_change) and P3 (lost_class) require `--force` and IC review. For this local DB population, apply them too:

```bash
# P2 — asset class changes (~13k rows)
python scripts/apply_strategy_reclassification.py \
    --run-id <RUN_ID> \
    --severity asset_class \
    --confirm --force

# P3 — label removals (~9.6k rows)
python scripts/apply_strategy_reclassification.py \
    --run-id <RUN_ID> \
    --severity lost \
    --confirm --force \
    --justification "Local DB population — all severities applied for dev/test completeness"
```

---

## Step 10 — Refresh materialized views

**Purpose:** Rebuild `mv_unified_funds` and `mv_unified_assets` with fresh sanitization + classification data.

**Execute:**
```python
import asyncio
from app.core.db.session import async_session_factory
from app.domains.wealth.services.view_refresh import refresh_screener_views

async def refresh():
    async with async_session_factory() as db:
        await refresh_screener_views(db, concurrently=True)
        await db.commit()
        print("Views refreshed")

asyncio.run(refresh())
```

**Verification:**
```sql
SELECT COUNT(*) AS total_funds,
       COUNT(*) FILTER (WHERE aum_usd >= 200000000) AS aum_200m_plus,
       COUNT(*) FILTER (WHERE strategy_label IS NOT NULL) AS has_label
FROM mv_unified_funds;
```

**Expected outcome:** ~53k institutional funds, ~5k with AUM ≥ 200M, majority with strategy_label populated.

---

## Final Summary Report

After ALL steps complete, compile a single summary table:

```
## Worker Population Report — 2026-04-16

| Step | Worker | Duration | Status | Key Metric Before | Key Metric After | Delta |
|------|--------|----------|--------|-------------------|------------------|-------|
| 1 | macro_ingestion | Xs | OK/FAIL | N series | N+3 series | +3 |
| 2 | regime_detection | Xs | OK/FAIL | 0 snapshots | N snapshots | +N |
| 3 | global_risk_metrics | Xs | OK/FAIL | 0% DTW coverage | X% | +X% |
| 4 | risk_calc (per org) | Xs | OK/FAIL | stale calc_date | today | refreshed |
| 5 | universe_sanitization | Xs | OK/FAIL | 0 flagged | ~26k excluded | +26k |
| 6 | strategy_reclassification | Xs | OK/FAIL | 37 labels | 47 labels | +10 |
| 7 | diff_report | Xs | OK/FAIL | — | CSV generated | — |
| 8 | apply P0 | Xs | OK/FAIL | X null labels | X-1400 | -1400 |
| 9 | apply P1+P2+P3 | Xs | OK/FAIL | X labels | X+Δ labels | +Δ |
| 10 | view refresh | Xs | OK/FAIL | stale views | refreshed | — |

### Coverage after all workers:
- Institutional funds: ____
- Funds with AUM ≥ $200M: ____
- Funds with strategy_label: ____
- Funds with manager_score: ____
- Funds with DTW drift: ____
- Funds with 5Y return: ____
- Funds with 10Y return: ____
- Current regime: ____ (stress: ___/100)
```

If any step failed, include the full traceback and stop. Do NOT skip steps or fabricate results. Report what actually happened.

---

## What NOT to do

- Do NOT modify any code files. This is a pure operational runbook.
- Do NOT run workers against production DB (Timescale Cloud). This is local docker-compose only.
- Do NOT skip the BEFORE snapshot. The delta is the deliverable.
- Do NOT fabricate row counts if a query fails. Report the error.
- Do NOT apply P2/P3 on production without IC review. On local DB, `--force` is acceptable for dev completeness.
- Do NOT run `strategy_reclassification` BEFORE `universe_sanitization` — results will include retail/retirement funds.
- Do NOT run `regime_detection` BEFORE `macro_ingestion` — regime signals will be stale or missing.
- Do NOT interrupt `global_risk_metrics` mid-run (30+ min) — it holds advisory lock.

---

## Environment setup reminder

```bash
# From repo root
make up                    # docker-compose: PG 16 + TimescaleDB + Redis 7
cd backend
alembic upgrade head       # ensure all migrations applied
export FRED_API_KEY=<key>  # required for Step 1
```

**End of runbook. Execute sequentially. Report the final summary table when all 10 steps complete.**
