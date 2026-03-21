---
status: resolved
priority: p3
issue_id: "214"
tags: [migration, timescaledb, bis, imf, macro]
dependencies: []
---

# Migration 0041: BIS + IMF hypertables (bis_statistics, imf_weo_forecasts)

## Problem Statement

Phase 6 requires 2 new hypertables for BIS statistics and IMF World Economic Outlook forecast data.

## Proposed Solution

### Approach

Create Alembic migration `0041_bis_imf_hypertables.py`:

1. **`bis_statistics` hypertable:**
   - `country_code TEXT NOT NULL`
   - `indicator TEXT NOT NULL` (e.g., `credit_to_gdp_gap`, `debt_service_ratio`, `property_prices`)
   - `dataset TEXT NOT NULL` (e.g., `WS_CREDIT_GAP`, `WS_DSR`, `WS_SPP`)
   - `period TIMESTAMPTZ NOT NULL` — time column
   - `value NUMERIC NOT NULL`
   - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
   - Primary key: `(country_code, indicator, period)`
   - Hypertable: chunk interval 1 year, `compress_segmentby = 'country_code'`
   - Index: `(country_code, indicator, period DESC)`

2. **`imf_weo_forecasts` hypertable:**
   - `country_code TEXT NOT NULL`
   - `indicator TEXT NOT NULL` (e.g., `NGDP_RPCH`, `PCPIPCH`, `GGXCNL_NGDP`)
   - `year INTEGER NOT NULL` — forecast year
   - `period TIMESTAMPTZ NOT NULL` — publication date (time column)
   - `value NUMERIC`
   - `edition TEXT NOT NULL` (e.g., `202604`, `202610`)
   - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
   - Primary key: `(country_code, indicator, year, period)`
   - Hypertable: chunk interval 1 year, `compress_segmentby = 'country_code'`
   - Index: `(country_code, indicator, period DESC)`

Both tables are **global** (no `organization_id`, no RLS).

## Technical Details

**Affected files:**
- `backend/alembic/versions/0041_bis_imf_hypertables.py` — new migration

**Constraints:**
- Global tables — no RLS
- Both hypertables with 1-year chunks
- `compress_segmentby = 'country_code'` (not `organization_id` — global tables)
- Downgrade drops both hypertables

## Acceptance Criteria

- [ ] Both hypertables created with correct partitioning and compression
- [ ] Indexes on `(country_code, indicator, period DESC)` for both
- [ ] No RLS policies
- [ ] Downgrade drops tables cleanly
- [ ] `make check` passes (lint + typecheck + test)
