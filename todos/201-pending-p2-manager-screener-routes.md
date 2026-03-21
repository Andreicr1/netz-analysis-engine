---
status: pending
priority: p2
issue_id: "201"
tags: [backend, routes, wealth, manager-screener]
dependencies: ["198", "199", "200"]
---

# Manager Screener route handlers (8 endpoints)

## Problem Statement

Implement the 8 Manager Screener endpoints as thin async route handlers that delegate query construction to the query builder and execute via `asyncio.gather()`.

## Proposed Solution

### Approach

Create `backend/app/domains/wealth/routes/manager_screener.py` with router prefix `/manager-screener` and tag `manager-screener`.

**Endpoints (all require INVESTMENT_TEAM or ADMIN role):**

| Method | Path | Response Model | Notes |
|--------|------|---------------|-------|
| `GET` | `/` | `ManagerScreenerPage` | Uses `build_screener_queries()` + `asyncio.gather()` for data+count |
| `GET` | `/managers/{crd}/profile` | `ManagerProfileRead` | `selectinload(SecManager.funds, SecManager.team)` |
| `GET` | `/managers/{crd}/holdings` | `ManagerHoldingsRead` | Sector aggregation, top 10, HHI, 4Q history |
| `GET` | `/managers/{crd}/drift` | `ManagerDriftRead` | Turnover timeline from `sec_13f_diffs` |
| `GET` | `/managers/{crd}/institutional` | `ManagerInstitutionalRead` | 13F reverse lookup via `sec_institutional_allocations` |
| `GET` | `/managers/{crd}/universe-status` | `ManagerUniverseRead` | Status from `instruments_universe` (org-scoped) |
| `POST` | `/managers/{crd}/add-to-universe` | `InstrumentRead` (201) | Creates Instrument with `approval_status="pending"` |
| `POST` | `/managers/compare` | `ManagerCompareResult` | 2-5 CRDs, Jaccard overlap, sector comparison |

**Dependencies per handler:** `get_db_with_rls`, `get_org_id`, `get_actor` (follows `screener.py` pattern).

**Register router in `backend/app/main.py`:**
```python
from app.domains.wealth.routes.manager_screener import router as wealth_manager_screener_router
api_v1.include_router(wealth_manager_screener_router)
```

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/routes/manager_screener.py` — new
- `backend/app/main.py` — add router import + include_router

**Constraints:**
- All handlers `async def` + `AsyncSession`
- SEC tables are global (no RLS) — queried directly
- `instruments_universe` join uses RLS-scoped session with `organization_id`
- `POST /add-to-universe` writes `Instrument` with `attributes.source = "sec_manager"`, `attributes.sec_crd_number`, `attributes.sec_cik`
- CRD number validated as alphanumeric before use
- All hypertable queries include time-column filters for chunk pruning
- Weighted Jaccard computed in Python (not SQL FULL OUTER JOIN)

## Acceptance Criteria

- [ ] All 8 endpoints implemented and registered in `main.py`
- [ ] All endpoints enforce INVESTMENT_TEAM or ADMIN role
- [ ] Main screener uses `asyncio.gather()` for data + count queries
- [ ] `POST /add-to-universe` creates Instrument with correct `attributes` JSONB and `approval_status="pending"`
- [ ] `POST /compare` validates 2-5 CRDs, returns overlap + drift comparison
- [ ] All SQL uses parameterized queries (no f-string injection)
- [ ] All hypertable queries include time-column filters
- [ ] `make check` passes (lint + typecheck + test)
