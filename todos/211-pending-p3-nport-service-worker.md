---
status: done
priority: p3
issue_id: "211"
tags: [backend, data-provider, sec, nport, worker]
dependencies: ["210"]
---

# N-PORT service + ingestion worker (Phase 4)

## Problem Statement

N-PORT filings provide monthly portfolio holdings for ~15K+ US mutual funds, expanding coverage beyond the ~5K 13F filers. Need a data provider service and ingestion worker.

## Proposed Solution

### Approach

1. **New service:** `backend/data_providers/sec/nport_service.py`
   - Fetch N-PORT XML filings from SEC EDGAR
   - Parse holdings from `<invstOrSec>` elements
   - Extract: CUSIP, ISIN, issuer name, asset class, market value, quantity, currency, % of NAV, restricted flag, fair value level
   - Follows `thirteenf_service.py` pattern (SEC EDGAR rate limit: 8 req/s)

2. **New worker:** `backend/app/domains/wealth/workers/nport_ingestion.py`
   - Advisory lock ID: **900_018** (deterministic)
   - Scope: global
   - Frequency: weekly (N-PORT filed monthly, but check weekly for new filings)
   - Upserts into `sec_nport_holdings` hypertable
   - Unlock in `finally`

3. **ORM model:** Add `SecNportHolding` to `backend/app/shared/models.py`

4. **Register worker** in worker dispatch.

## Technical Details

**Affected files:**
- `backend/data_providers/sec/nport_service.py` — new
- `backend/app/domains/wealth/workers/nport_ingestion.py` — new
- `backend/app/shared/models.py` — add `SecNportHolding` model
- `backend/app/domains/wealth/routes/workers.py` — register dispatch

**Constraints:**
- Advisory lock ID: 900_018 (deterministic, not `hash()`)
- Unlock in `finally`
- SEC EDGAR rate limit: 8 req/s (conservative)
- Import-linter: `data_providers` must not import `vertical_engines`, `app.domains`, or `quant_engine`
- N-PORT XML can be large — stream parse, don't load full DOM

## Acceptance Criteria

- [ ] `nport_service.py` parses N-PORT XML filings correctly
- [ ] Worker uses `pg_try_advisory_lock(900018)` with unlock in `finally`
- [ ] Holdings upserted into `sec_nport_holdings` hypertable
- [ ] `SecNportHolding` model added to shared models
- [ ] Import-linter passes (no forbidden imports)
- [ ] `make check` passes (lint + typecheck + test)
