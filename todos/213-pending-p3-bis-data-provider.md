---
status: resolved
priority: p3
issue_id: "213"
tags: [backend, data-provider, bis, macro]
dependencies: ["214"]
---

# BIS Statistics data provider + ingestion worker (Phase 6)

## Problem Statement

BIS provides credit-to-GDP gap, debt service ratio, and property prices for 44 countries — pre-computed indicators that enrich the regional macro scoring in `quant_engine/regional_macro_service.py`.

## Proposed Solution

### Approach

1. **New data provider:** `backend/data_providers/bis/service.py`
   - BIS SDMX REST API (`https://stats.bis.org/api/v1/data/`)
   - Datasets: `WS_CREDIT_GAP` (credit-to-GDP gap, pre-computed CG_DTYPE=C), `WS_DSR` (debt service ratio), `WS_SPP` (property prices)
   - Parse via `sdmx1` library (BIS source available since v2.5.0)
   - Returns typed dataclasses per indicator

2. **New worker:** `backend/app/domains/wealth/workers/bis_ingestion.py`
   - Advisory lock ID: **900_014** (deterministic)
   - Scope: global
   - Frequency: quarterly (BIS data is quarterly)
   - Upserts into `bis_statistics` hypertable

3. **Migration (part of 0041):** `bis_statistics` hypertable
   - `country_code TEXT NOT NULL`, `indicator TEXT NOT NULL`
   - `period TIMESTAMPTZ NOT NULL` (time column)
   - `value NUMERIC NOT NULL`
   - `dataset TEXT NOT NULL`
   - Chunk interval: 1 year, `compress_segmentby = 'country_code'`

4. **Integration:** BIS credit-to-GDP gap → `financial_conditions` dimension in `regional_macro_service.py`. Consider adding a 7th `credit_cycle` dimension.

## Technical Details

**Affected files:**
- `backend/data_providers/bis/__init__.py` — new
- `backend/data_providers/bis/service.py` — new
- `backend/app/domains/wealth/workers/bis_ingestion.py` — new
- `backend/app/domains/wealth/routes/workers.py` — register dispatch

**Constraints:**
- Advisory lock ID: 900_014 (deterministic, not `hash()`)
- Unlock in `finally`
- `sdmx1>=2.5.0` dependency needed
- Import-linter: `data_providers` must not import `vertical_engines`, `app.domains`, or `quant_engine`
- Credit-to-GDP gap is pre-computed by BIS (CG_DTYPE=C) — no HP filter needed

## Acceptance Criteria

- [ ] BIS service fetches credit-to-GDP gap, DSR, and property prices
- [ ] Worker uses `pg_try_advisory_lock(900014)` with unlock in `finally`
- [ ] Data upserted into `bis_statistics` hypertable
- [ ] Import-linter passes (no forbidden imports)
- [ ] `make check` passes (lint + typecheck + test)
