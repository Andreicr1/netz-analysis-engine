---
status: done
priority: p3
issue_id: "209"
tags: [backend, seed, esma, wealth]
dependencies: ["207", "208"]
---

# ESMA 4-phase resumable seed pipeline

## Problem Statement

Populate ESMA tables with ~134K UCITS fund entries, resolve ISINs to Yahoo Finance tickers, backfill NAV data, and cross-reference with SEC managers. Must be resumable (checkpoint file) due to large volume.

## Proposed Solution

### Approach

Create `backend/data_providers/esma/seed/populate_seed.py` following the `data_providers/sec/seed/populate_seed.py` pattern:

**4 phases (each independently resumable via `.esma_seed_checkpoint.json`):**

| Phase | Input | Output | Volume |
|-------|-------|--------|--------|
| 1 | ESMA Solr API (paginated, 1000/page) | `esma_managers` + `esma_funds` (LEI-keyed) | ~134K UCITS |
| 2 | FIRDS FULINS_C XML download + OpenFIGI batch | Join ISIN to `esma_funds` via LEI → `esma_isin_ticker_map` | ~70-80% resolved |
| 3 | `yfinance.download()` for resolved tickers (3yr backfill) | `nav_timeseries` (existing hypertable) | ~35-45K × 750 days |
| 4 | Name fuzzy match (`rapidfuzz` ≥0.85) + LEI (GLEIF) | `esma_managers.sec_crd_number` cross-reference | Cross-ref |

**Phase 3 auto-creates `Instrument` entries** in `instruments_universe` with `attributes.source = "esma_register"`, entering existing screening/risk/DD pipelines.

## Technical Details

**Affected files:**
- `backend/data_providers/esma/seed/__init__.py` — new
- `backend/data_providers/esma/seed/populate_seed.py` — new

**Constraints:**
- Checkpoint file `.esma_seed_checkpoint.json` for resume capability
- ESMA Solr pagination: `rows=1000&start=N`
- OpenFIGI: 100 ISINs per batch, 250 req/min with API key
- FIRDS XML can be large (~500MB) — stream with `iterparse`, don't load full DOM
- `instruments_universe` writes are org-scoped — need a "system" org context or skip auto-create
- Import-linter: no forbidden imports from `data_providers`

## Acceptance Criteria

- [ ] Phase 1 populates `esma_managers` and `esma_funds` from ESMA Solr API
- [ ] Phase 2 resolves ISINs via FIRDS XML + OpenFIGI batch
- [ ] Phase 3 backfills NAV into existing `nav_timeseries` hypertable
- [ ] Phase 4 cross-references ESMA managers with SEC managers (fuzzy match ≥0.85)
- [ ] Checkpoint/resume works at each phase boundary
- [ ] ISIN → ticker resolution achieves ≥30% success rate
- [ ] `make check` passes (lint + typecheck + test)
