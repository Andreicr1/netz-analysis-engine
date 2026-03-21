---
status: pending
priority: p2
issue_id: "199"
tags: [backend, schemas, wealth, manager-screener]
dependencies: []
---

# Pydantic schemas for Manager Screener

## Problem Statement

The Manager Screener endpoints need request/response Pydantic schemas. These are a dependency for both the query builder and the route handlers.

## Proposed Solution

### Approach

Create `backend/app/domains/wealth/schemas/manager_screener.py` with all schemas defined in the plan §1.6:

**Request schemas:**
- `ManagerCompareRequest` — `crd_numbers: list[str]` (min 2, max 5)
- `ManagerToUniverseRequest` — `asset_class`, `geography`, `currency` (default USD), `block_id` optional

**Response schemas:**
- `ManagerRow` — single row in screener list (CRD, firm, AUM, sectors, HHI, drift, institutional, universe status)
- `ManagerScreenerPage` — paginated wrapper (`managers`, `total_count`, `page`, `page_size`, `has_next`)
- `ManagerProfileRead` — profile tab (ADV fields + `funds: list[ManagerFundRead]` + `team: list[ManagerTeamMemberRead]`)
- `ManagerFundRead` — fund sub-schema
- `ManagerTeamMemberRead` — team member sub-schema
- `HoldingRow` — single holding (CUSIP, issuer, sector, value, weight)
- `ManagerHoldingsRead` — holdings tab (sector allocation dict, top 10, HHI, history)
- `DriftQuarter` — quarter drift metrics (turnover, new/exited/increased/decreased/unchanged)
- `ManagerDriftRead` — drift tab (quarters list + style_drift_detected bool)
- `InstitutionalHolder` — single holder (name, type, CIK, value)
- `ManagerInstitutionalRead` — institutional tab (coverage_type + holders)
- `ManagerUniverseRead` — universe status tab
- `ManagerCompareResult` — comparison (managers, sector allocations, jaccard overlap, drift comparison)

All response schemas use `model_config = ConfigDict(from_attributes=True)` where applicable.

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/schemas/manager_screener.py` — new file

**Constraints:**
- Follow pattern from `backend/app/domains/wealth/schemas/screening.py`
- Use `Field(default_factory=list)` for list defaults, `Field(default_factory=dict)` for dict defaults
- Import `uuid`, `date` from stdlib; `BaseModel`, `Field`, `ConfigDict` from pydantic

## Acceptance Criteria

- [ ] All 14 schema classes defined matching plan §1.6
- [ ] `ManagerCompareRequest.crd_numbers` has `min_length=2, max_length=5` validation
- [ ] All response schemas use `ConfigDict(from_attributes=True)`
- [ ] `make check` passes (lint + typecheck + test)
