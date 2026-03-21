---
status: resolved
priority: p3
issue_id: "215"
tags: [backend, data-provider, imf, macro]
dependencies: ["214"]
---

# IMF WEO data provider + ingestion worker (Phase 6)

## Problem Statement

IMF World Economic Outlook provides 5-year forward GDP and inflation projections for ~190 countries. This enriches the `growth` dimension in `regional_macro_service.py` with forward-looking data (complementing FRED backward-looking).

## Proposed Solution

### Approach

1. **New data provider:** `backend/data_providers/imf/service.py`
   - IMF WEO DataMapper API (`https://www.imf.org/external/datamapper/api/v1/`)
   - Simple JSON (not SDMX) — direct `httpx.get()`, no `sdmx1` needed
   - Indicators: `NGDP_RPCH` (GDP growth), `PCPIPCH` (inflation), `GGXCNL_NGDP` (fiscal balance), `GGXWDG_NGDP` (govt debt)
   - No authentication required
   - Updated April + October each year

2. **New worker:** `backend/app/domains/wealth/workers/imf_ingestion.py`
   - Advisory lock ID: **900_015** (deterministic)
   - Scope: global
   - Frequency: quarterly (check for new WEO editions)
   - Upserts into `imf_weo_forecasts` hypertable

3. **Integration:** IMF GDP forecasts → `growth` dimension in `regional_macro_service.py` (forward-looking complement to FRED backward-looking data).

## Technical Details

**Affected files:**
- `backend/data_providers/imf/__init__.py` — new
- `backend/data_providers/imf/service.py` — new
- `backend/app/domains/wealth/workers/imf_ingestion.py` — new
- `backend/app/domains/wealth/routes/workers.py` — register dispatch

**Constraints:**
- Advisory lock ID: 900_015 (deterministic, not `hash()`)
- Unlock in `finally`
- No external dependencies beyond `httpx` (already available)
- Import-linter: `data_providers` must not import `vertical_engines`, `app.domains`, or `quant_engine`
- IMF API is simple JSON — no SDMX parsing needed

## Acceptance Criteria

- [ ] IMF service fetches GDP, inflation, fiscal balance, and govt debt forecasts
- [ ] Worker uses `pg_try_advisory_lock(900015)` with unlock in `finally`
- [ ] Data upserted into `imf_weo_forecasts` hypertable
- [ ] Import-linter passes (no forbidden imports)
- [ ] `make check` passes (lint + typecheck + test)
