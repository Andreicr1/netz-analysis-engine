---
status: pending
priority: p2
issue_id: "200"
tags: [backend, queries, wealth, manager-screener]
dependencies: ["198"]
---

# Query builder for Manager Screener (manager_screener_sql.py)

## Problem Statement

The Manager Screener needs a pure query builder that constructs dynamic SQLAlchemy Core `Select` statements for the main screener list. This builder has zero I/O — frozen dataclass input, `Select` output — and is testable in isolation.

## Proposed Solution

### Approach

Create `backend/app/domains/wealth/queries/manager_screener_sql.py`:

1. **`ScreenerFilters` frozen dataclass** with all 5 filter blocks:
   - Block 1 — Firma: AUM range, strategy types, fee types, states, countries, registration status, compliance clean, ADV filed date range, text search
   - Block 2 — Portfolio (reads continuous aggregate): sectors, HHI range, position count range, portfolio value min
   - Block 3 — Drift (reads continuous aggregate): style drift detected, turnover range, high activity quarters min
   - Block 4 — Institutional: has institutional holders, holder types
   - Block 5 — Universe status: universe statuses list
   - Sort & pagination: sort_by, sort_dir, page, page_size

2. **`build_screener_queries(filters, org_id) -> tuple[Select, Select]`** returning `(data_query, count_query)` for `asyncio.gather()` execution.

3. **Sort column allowlist** `_SORT_COLUMNS` dict mapping string keys to SQLAlchemy columns (prevents ORDER BY injection).

4. **Text search escaping** for `firm_name` ILIKE with `%`, `_`, `\` escaping.

5. **Chunk pruning invariant:** All subqueries on hypertables/continuous aggregates include explicit time-column filters (`:latest_quarter`, `:drift_cutoff`, `:inst_cutoff`).

6. Create `backend/app/domains/wealth/queries/__init__.py` (empty).

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/queries/__init__.py` — new (empty)
- `backend/app/domains/wealth/queries/manager_screener_sql.py` — new

**Constraints:**
- Pure helper — no I/O, no DB session, no imports from `app.domains` routes/services
- Uses SQLAlchemy Core (`select`, `and_`, `func`, etc.), not ORM query API
- `instruments_universe` join must filter by `organization_id = :org_id`
- No LATERAL JOINs (TimescaleDB issue #8642)
- Reads from continuous aggregates `sec_13f_holdings_agg` and `sec_13f_drift_agg` (created by migration 0038)

## Acceptance Criteria

- [ ] `ScreenerFilters` is a frozen dataclass with all filter fields
- [ ] `build_screener_queries()` returns `tuple[Select, Select]` (data + count)
- [ ] Sort uses column allowlist, not user-supplied string in ORDER BY
- [ ] Text search escapes `%`, `_`, `\` before ILIKE
- [ ] All hypertable/aggregate subqueries include time-column filter (testable via compiled SQL inspection)
- [ ] `instruments_universe` join includes `organization_id` parameter
- [ ] No imports from `app.domains` routes or services
- [ ] `make check` passes (lint + typecheck + test)
