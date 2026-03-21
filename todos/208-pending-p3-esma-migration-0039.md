---
status: done
priority: p3
issue_id: "208"
tags: [migration, esma, wealth]
dependencies: []
---

# Migration 0039: ESMA tables (esma_managers, esma_funds, esma_isin_ticker_map)

## Problem Statement

The ESMA seed pipeline needs 3 reference tables for storing European fund register data and ISIN-to-ticker mappings.

## Proposed Solution

### Approach

Create Alembic migration `0039_esma_tables.py` with 3 tables:

1. **`esma_managers`** — European fund managers from ESMA register
   - `esma_id TEXT PRIMARY KEY`
   - `lei TEXT`, `company_name TEXT NOT NULL`, `country TEXT`
   - `authorization_status TEXT`, `fund_count INTEGER`
   - `sec_crd_number TEXT` (nullable cross-reference to `sec_managers`)
   - `created_at TIMESTAMPTZ`, `data_fetched_at TIMESTAMPTZ`

2. **`esma_funds`** — UCITS funds linked to managers
   - `isin TEXT PRIMARY KEY`
   - `fund_name TEXT NOT NULL`
   - `esma_manager_id TEXT NOT NULL REFERENCES esma_managers(esma_id)`
   - `domicile TEXT`, `fund_type TEXT`, `host_member_states TEXT[]`
   - `yahoo_ticker TEXT`, `ticker_resolved_at TIMESTAMPTZ`
   - `created_at TIMESTAMPTZ`, `data_fetched_at TIMESTAMPTZ`

3. **`esma_isin_ticker_map`** — resolved ISIN → ticker mappings
   - `isin TEXT PRIMARY KEY`
   - `yahoo_ticker TEXT`, `exchange TEXT`
   - `resolved_via TEXT NOT NULL`, `is_tradeable BOOLEAN NOT NULL`
   - `last_verified_at TIMESTAMPTZ NOT NULL`

All tables are **global** (no `organization_id`, no RLS). Not hypertables (low-volume reference data).

## Technical Details

**Affected files:**
- `backend/alembic/versions/0039_esma_tables.py` — new migration

**Constraints:**
- No RLS — global reference tables
- Not hypertables — static reference data, not time-series
- FK: `esma_funds.esma_manager_id → esma_managers.esma_id`
- Downgrade drops all 3 tables in reverse FK order

## Acceptance Criteria

- [ ] Migration creates all 3 tables with correct columns and types
- [ ] FK constraint on `esma_funds.esma_manager_id` works
- [ ] No RLS policies applied
- [ ] Downgrade drops tables cleanly
- [ ] `make check` passes (lint + typecheck + test)
