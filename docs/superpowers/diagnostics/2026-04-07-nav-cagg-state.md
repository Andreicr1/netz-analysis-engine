# nav_monthly_returns_agg — Production State Diagnostic

- **Date:** 2026-04-08
- **Target:** Timescale Cloud prod (`nvhhm6dwvh.keh9pcdgv1.tsdb.cloud.timescale.com:30124/tsdb`)
- **Service id:** `nvhhm6dwvh`
- **Scope:** Phase 0 Task 0.1 — read-only state check of the NAV monthly returns CAGG before Phase 1 Task 1.2 (attribution route wiring)

## Connection method

- **Attempt 1 — MCP `mcp__tiger__db_execute_query` (service `nvhhm6dwvh`):** FAILED with
  `SASL auth: FATAL: password authentication failed for user "tsdbadmin" (SQLSTATE 28P01)`.
  The stored credential on the tiger MCP service record is stale; MCP is unusable for this
  service until the operator rotates its stored password (out of scope for a read-only
  diagnostic — we intentionally do NOT call `service_update_password`).
- **Attempt 2 — Direct `asyncpg` from `.venv` with the freshly provided `tsdbadmin` password,
  SSL `require`:** SUCCEEDED. All three diagnostic queries executed read-only.

Temporary diagnostic scripts were created under the system temp directory, run once, and
deleted before committing. The password was never written to any tracked file.

## Q1 — Does the CAGG exist?

```sql
SELECT view_name, materialization_hypertable_name
FROM timescaledb_information.continuous_aggregates
WHERE view_name = 'nav_monthly_returns_agg';
```

Result (1 row):

| view_name | materialization_hypertable_name |
|---|---|
| `nav_monthly_returns_agg` | `_materialized_hypertable_90` |

CAGG object exists and is bound to internal hypertable `_materialized_hypertable_90`.

## Q2 — Column layout (verify migration 0069 rebuild is complete)

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'nav_monthly_returns_agg'
ORDER BY ordinal_position;
```

Result (7 rows):

| ordinal | column_name | data_type |
|---|---|---|
| 1 | `instrument_id` | `uuid` |
| 2 | `month` | `date` |
| 3 | `nav_open` | `numeric` |
| 4 | `nav_close` | `numeric` |
| 5 | `trading_days` | `bigint` |
| 6 | `avg_daily_return` | `numeric` |
| 7 | `daily_volatility` | `numeric` |

**No `organization_id` column.** Migration 0069 (global rebuild — `nav_timeseries` is global,
no RLS) is fully applied. Schema matches the post-0069 contract the attribution route expects.

## Q3 — Most recent materialized buckets

```sql
SELECT instrument_id, MAX(month) AS last_bucket, COUNT(*) AS buckets
FROM nav_monthly_returns_agg
GROUP BY instrument_id
ORDER BY last_bucket DESC LIMIT 10;
```

Result: **0 rows.** The CAGG is structurally empty — no materialized buckets for any
instrument.

### Cross-check against source hypertable

To distinguish "empty because source is empty" from "empty because never refreshed", the
source was also counted:

```sql
SELECT COUNT(*) FROM nav_timeseries;
-- => 12,127,189
```

`nav_timeseries` (columns: `instrument_id uuid`, `nav_date date`, `nav numeric`,
`return_1d numeric`, `aum_usd numeric`, `currency`, `source`, `return_type`) holds ~12.1M
rows of NAV observations. The source is healthy; the CAGG simply holds zero materialized
buckets. Most likely root cause: migration 0069 dropped and recreated the CAGG with
`WITH NO DATA` and no subsequent full refresh was issued, so the continuous refresh policy
(if any) only advances the watermark forward from "now" and never backfills history.

## Verdict

**STALE_NEEDS_REFRESH**

Rationale: the CAGG object and schema are correct (post-0069 contract satisfied, no
`organization_id` column, expected `month`/`nav_open`/`nav_close`/`trading_days` columns
present), but the materialization is empty. The condition "last_bucket older than current
month" is trivially true because there is no last_bucket at all. This is a refresh problem,
not a rebuild problem — the DDL is fine, only the data is missing. `MISSING_NEEDS_CREATE`
does not apply because Q1 returns the view. `BROKEN_NEEDS_REBUILD` does not apply because
Q2 shows the post-0069 column set with no lingering `organization_id`.

## Recommendation for Phase 1 Task 1.2

**FIX — mode: REFRESH (full history backfill), do NOT rebuild.**

Concrete next step for Task 1.2 (before wiring the attribution route to the CAGG):

```sql
CALL refresh_continuous_aggregate(
    'nav_monthly_returns_agg',
    NULL,   -- start: -infinity, materialize all history
    NULL    -- end:   now(), materialize up to current watermark
);
```

Then re-run Q3 to confirm `last_bucket >= 2026-04-01` for the instruments with recent NAVs,
and verify a non-trivial row count (expected order of magnitude: ~12M source rows × 1 bucket
per (instrument, month) — ballpark 300k–500k materialized rows depending on instrument
count and history depth).

Additional hygiene items to verify while in there (not part of Task 1.2 scope, but cheap to
check once the refresh completes):

1. Confirm a `policy_refresh_continuous_aggregate` job is attached to
   `_materialized_hypertable_90` with a reasonable `schedule_interval` (daily) and an
   appropriate `start_offset` / `end_offset` window. If absent, add one via
   `add_continuous_aggregate_policy('nav_monthly_returns_agg', ...)`.
2. Confirm compression policy on the CAGG hypertable if retention horizon > 12 months.
3. After the attribution route is wired, spot-check one fund end-to-end: raw NAV in
   `nav_timeseries` → monthly bucket in `nav_monthly_returns_agg` → attribution output.

**Do NOT:**
- Drop and recreate the CAGG (the schema is correct — a drop would lose the already-correct
  DDL contract that migration 0069 installed).
- Add `organization_id` to the CAGG (it is a global hypertable, per the project rule for
  `nav_timeseries`).
- Block Task 1.2 on this — the refresh can run in the background (it is a single TimescaleDB
  `CALL`, no application code change). Task 1.2 should proceed as planned, with the refresh
  scheduled immediately before or alongside the route wiring.
