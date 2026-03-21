---
status: pending
priority: p2
issue_id: "202"
tags: [backend, tests, wealth, manager-screener]
dependencies: ["199", "200", "201"]
---

# Tests for Manager Screener (query builder + endpoints)

## Problem Statement

Comprehensive test suite for the Manager Screener covering query builder logic, endpoint behavior, authorization, and chunk pruning invariants.

## Proposed Solution

### Approach

Create `backend/tests/test_manager_screener.py` with test categories:

1. **Query builder unit tests** (no DB needed — compile SQL and inspect):
   - Each filter block generates correct WHERE clauses
   - Sort column allowlist prevents injection
   - Text search escaping works for `%`, `_`, `\`
   - **Invariant test:** `test_holdings_subquery_always_filters_report_date` — compiled SQL must contain `report_date` filter
   - Pagination: LIMIT/OFFSET generated correctly
   - Empty filters: returns valid query with no WHERE conditions beyond time filters

2. **Endpoint integration tests:**
   - `GET /` — paginated results, filter combinations
   - `GET /managers/{crd}/profile` — returns funds + team via selectinload
   - `GET /managers/{crd}/holdings` — sector allocation dict, top 10, HHI
   - `GET /managers/{crd}/drift` — turnover timeline, style drift detection
   - `GET /managers/{crd}/institutional` — coverage type detection
   - `POST /add-to-universe` — creates Instrument with correct attributes
   - `POST /compare` — Jaccard overlap, sector comparison, 2-5 CRD validation

3. **Authorization tests:** 403 for non-investment roles on all endpoints

4. **Edge cases:** Empty SEC data, manager with no 13F filings, manager already in universe

## Technical Details

**Affected files:**
- `backend/tests/test_manager_screener.py` — new

**Constraints:**
- Follow existing test patterns from `backend/tests/`
- Query builder tests can be pure unit tests (compile SQL, assert conditions)
- Endpoint tests use test client with fixtures

## Acceptance Criteria

- [ ] Query builder invariant test verifies time-column filter presence
- [ ] All 8 endpoints have at least one happy-path test
- [ ] Authorization tested (403 for unauthorized roles)
- [ ] Edge cases covered (empty data, no 13F, duplicate add-to-universe)
- [ ] `make check` passes (lint + typecheck + test)
