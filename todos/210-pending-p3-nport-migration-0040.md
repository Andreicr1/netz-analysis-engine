---
status: done
priority: p3
issue_id: "210"
tags: [migration, sec, timescaledb, nport]
dependencies: []
---

# Migration 0040: sec_nport_holdings hypertable

## Problem Statement

N-PORT filings provide monthly portfolio holdings for US mutual funds (not covered by 13F). A new hypertable is needed to store this data.

## Proposed Solution

### Approach

Create Alembic migration `0040_sec_nport_holdings.py`:

1. **Table `sec_nport_holdings`:**
   - `cik TEXT NOT NULL` — filer CIK
   - `report_date TIMESTAMPTZ NOT NULL` — reporting period end date
   - `cusip TEXT`, `isin TEXT`, `issuer_name TEXT`
   - `asset_class TEXT`, `sector TEXT`
   - `market_value BIGINT`, `quantity NUMERIC`
   - `currency TEXT`, `pct_of_nav NUMERIC`
   - `is_restricted BOOLEAN`, `fair_value_level TEXT`
   - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
   - Primary key: `(cik, report_date, cusip)`

2. **Convert to hypertable:** `SELECT create_hypertable('sec_nport_holdings', 'report_date', chunk_time_interval => INTERVAL '3 months')`

3. **Compression:** `ALTER TABLE sec_nport_holdings SET (timescaledb.compress, timescaledb.compress_segmentby = 'cik')`

4. **Indexes:** `(cik, report_date DESC)`, `(cusip, report_date DESC)`

## Technical Details

**Affected files:**
- `backend/alembic/versions/0040_sec_nport_holdings.py` — new migration

**Constraints:**
- Global table (no `organization_id`, no RLS)
- Hypertable with 3-month chunks, `compress_segmentby = 'cik'`
- Downgrade drops hypertable

## Acceptance Criteria

- [ ] Hypertable created with correct partitioning and compression
- [ ] Indexes on `(cik, report_date DESC)` and `(cusip, report_date DESC)`
- [ ] No RLS policies
- [ ] Downgrade drops table cleanly
- [ ] `make check` passes (lint + typecheck + test)
