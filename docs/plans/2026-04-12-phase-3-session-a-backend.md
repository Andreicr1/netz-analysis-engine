# Phase 3 Session A — Backend Alignment

**Date:** 2026-04-12
**Branch:** `feat/phase-3-session-a`
**Scope:** 6 atomic commits refactoring screener backend to consume Phase 2 MVs + new endpoints
**Prerequisite reading:** `docs/plans/2026-04-12-phase-3-overview.md`
**Depends on:** Phase 2 complete (main has `mv_fund_risk_latest`, `v_screener_org_membership`, `elite_flag` column, `nav_monthly_returns_agg` CAGG, sanitized.py retrofit)

## Mission

Refactor the screener backend so every response includes real ELITE data, org membership markers, and sparkline batch data — all from the Phase 2 materialized views. Also migrate pagination from offset to keyset, add fast-track liquid universe approval, and ship integration tests. After this session, Session B's frontend work has correct, performant, and sanitized backend data to consume.

Six atomic commits in this exact order:

1. `refactor(screener): catalog route joins mv_fund_risk_latest + v_screener_org_membership`
2. `feat(screener): elite_flag + elite_rank in catalog response schema`
3. `feat(screener): batch sparkline endpoint for grid inline charts`
4. `feat(universe): fast-track liquid approval in POST /universe/approve`
5. `refactor(screener): keyset pagination replacing offset-based`
6. `test(screener): integration tests for catalog, elite, sparkline, approve routes`

## READ FIRST

1. `docs/plans/2026-04-12-phase-3-overview.md` — shared context
2. `backend/app/domains/wealth/routes/screener.py` — read FULLY, understand current catalog query construction in `catalog_sql.py`, note the existing `GET /screener/catalog/elite` endpoint that already reads `mv_fund_risk_latest`
3. `backend/app/domains/wealth/schemas/catalog.py` — current response schema, identify where `elite_flag` must be added
4. `backend/app/domains/wealth/routes/universe.py` or wherever `POST /universe/approve` lives — read fully
5. `backend/app/domains/wealth/queries/catalog_sql.py` (if exists) — the SQL query builder for the catalog
6. `backend/app/domains/wealth/queries/analysis_returns.py` — uses `nav_monthly_returns_agg` for single-fund, reference for batch endpoint
7. `backend/app/core/db/migrations/versions/0116_mv_fund_risk_latest.py` — the MV Phase 3 will consume
8. `backend/app/core/db/migrations/versions/0117_v_screener_org_membership.py` — the security view Phase 3 will consume
9. `backend/app/domains/wealth/schemas/sanitized.py` — ensure all new response fields route through sanitization
10. Recent Phase 2 route patterns (dd_reports queue, construction diff endpoint) — for consistent style

## Pre-flight

```bash
alembic heads  # expected: 0119 or later
make migrate
make test  # baseline green
```

Verify MVs exist:
```sql
SELECT matviewname FROM pg_matviews WHERE matviewname IN ('mv_fund_risk_latest', 'mv_construction_run_diff');
SELECT viewname FROM pg_views WHERE viewname = 'v_screener_org_membership';
```

---

# COMMIT 1 — refactor(screener): catalog route joins mv_fund_risk_latest + v_screener_org_membership

## Problem

Audit §C.1 confirmed main catalog (`GET /screener/catalog`) reads from `mv_unified_funds` via `catalog_sql.py` WITHOUT joining `mv_fund_risk_latest` or `v_screener_org_membership`. This means:
- Risk metrics (Sharpe, drawdown, CVaR, elite_flag) come from a separate query or aren't included at all
- Org membership ("already in my universe") requires a separate JOIN the frontend has to trigger

## Deliverable

Refactor the catalog query builder to LEFT JOIN both Phase 2 views:

```sql
FROM mv_unified_funds u
LEFT JOIN mv_fund_risk_latest r ON r.instrument_id = u.instrument_id
LEFT JOIN v_screener_org_membership m ON m.instrument_id = u.instrument_id
WHERE ...
```

The `v_screener_org_membership` view has `security_barrier=true` and uses `(SELECT current_setting('app.current_organization_id'))` — the RLS context is already set by the route's `get_db_with_rls` dependency. The JOIN just works; no additional RLS wiring needed.

**Critical:** the existing `GET /screener/catalog/elite` endpoint already reads from `mv_fund_risk_latest` per the audit. DO NOT duplicate or conflict with that endpoint's query. Either:
- (a) The main catalog endpoint consumes the same MV via the refactored JOIN (and the elite endpoint becomes a filter on the main catalog), OR
- (b) Keep both endpoints but ensure they share the same query builder with the MV JOIN

Prefer (a) — one query builder, two filter paths.

**No new columns in the response yet** — commit 2 adds `elite_flag` to the schema. This commit is pure query refactoring.

## Verification

1. `make test` green including existing screener tests
2. Response shape unchanged (same columns as before, new JOINs don't change the SELECT list yet)
3. `EXPLAIN ANALYZE` on the refactored query shows `mv_fund_risk_latest` and `v_screener_org_membership` in the plan
4. Performance: p95 should remain under 300ms (Phase 2 load test gate still valid)

---

# COMMIT 2 — feat(screener): elite_flag + elite_rank in catalog response schema

## Deliverable

Add `elite_flag`, `elite_rank_within_strategy`, and `in_universe` (from org membership JOIN) to the catalog response schema in `backend/app/domains/wealth/schemas/catalog.py`.

- `elite_flag: bool | None` — true if fund is in the ELITE 300 per strategy allocation
- `elite_rank_within_strategy: int | None` — ordinal rank within strategy, 1 = best
- `in_universe: bool` — true if the fund is approved in the authenticated org's universe (from `v_screener_org_membership.approval_status = 'approved'`)
- `approval_status: str | None` — "approved" / "pending" / "rejected" / None (from v_screener_org_membership)

**Sanitization:** `elite_flag` and `in_universe` are boolean/enum fields with no jargon risk. The risk metrics fields (Sharpe, CVaR, drawdown) that `mv_fund_risk_latest` JOINs are already sanitized in Phase 2 if they flow through `SanitizedResponseMixin`. Verify and apply if not.

## Verification

1. `POST /screener/catalog` response now includes `elite_flag`, `elite_rank_within_strategy`, `in_universe`, `approval_status` per row
2. `POST /screener/catalog` with a fixture org that has approved instruments returns `in_universe: true` for those
3. `make test` green
4. Schema Pydantic validation passes (no type errors)

---

# COMMIT 3 — feat(screener): batch sparkline endpoint for grid inline charts

## Problem

The screener DataGrid needs NAV sparklines per row, but only for visible rows (~40 at a time from virtualization). Querying `nav_monthly_returns_agg` per-instrument is N+1. A batch endpoint avoids that.

## Deliverable

New route in `backend/app/domains/wealth/routes/screener.py` (or a dedicated sub-router):

```python
@router.post("/screener/sparklines")
async def get_screener_sparklines(
    instrument_ids: list[UUID],
    months: int = 60,  # 5 years of monthly data
    db: AsyncSession = Depends(get_db_with_rls),
) -> dict[str, list[SparklinePoint]]:
    """Return monthly NAV data for a batch of instruments.

    Reads from nav_monthly_returns_agg CAGG. Returns at most
    `months` data points per instrument, ordered chronologically.
    Instruments with no data are omitted from the response dict.
    """
```

Response shape:
```python
class SparklinePoint(BaseModel):
    month: date
    nav_close: float
    return_1m: float | None

# Response: dict keyed by instrument_id string → list of SparklinePoint
```

**Performance:** batch query should be a single SQL with `instrument_id = ANY(:ids)` predicate. Cap `instrument_ids` list at 100 per request (frontend sends visible rows only, ~40). If caller sends > 100, return 400.

**No new migration needed** — `nav_monthly_returns_agg` CAGG already exists (migration 0049).

## Verification

1. POST with 5 instrument IDs → returns 5 lists of monthly NAV data
2. POST with 0 IDs → returns empty dict
3. POST with > 100 IDs → returns 400
4. POST with mix of real + non-existent IDs → non-existent omitted, no error
5. `make test` green with new test

---

# COMMIT 4 — feat(universe): fast-track liquid approval in POST /universe/approve

## Problem

Audit §C.2 confirmed `POST /universe/approve` exists but requires a pre-existing `UniverseApproval` record. For the fast-path flow, liquid funds (`registered_us`, `etf`, `ucits_eu`, `money_market`) should be approvable directly from the screener with one click — no pre-existing record required. Private funds and BDCs still require DD completion before approval.

## Deliverable

Refactor `POST /universe/approve` to support a fast-track path:

1. Accept `fund_ids: list[UUID]` + `block_id: UUID | None` + `source: str = "screener_fast_path"`
2. For each fund, check its `universe` field:
   - If `universe IN ('registered_us', 'etf', 'ucits_eu', 'money_market')` → approve immediately: create `instruments_org` row with `approval_status='approved'`, `fast_track=true`, `approved_at=now()`, `approved_by=actor`
   - If `universe IN ('private_us', 'bdc')` → reject with 409: `{error: "dd_required", message: "Private funds and BDCs require a completed DD report before universe approval"}`
3. Idempotent: if the fund is already approved for this org, return success without re-inserting (no duplicate rows)
4. Write audit event via `write_audit_event()` per approval
5. Return `{approved: [...], rejected_dd_required: [...]}`

**Per Stability Guardrails P5:** use `@idempotent` decorator + `pg_advisory_xact_lock(zlib.crc32(b"universe_approve", org_id_bytes, fund_id_bytes))` per fund.

## Verification

1. Approve 3 liquid funds → 201 with `approved: [3 items]`
2. Approve same 3 again → 200 with same result (idempotent, no duplicate rows)
3. Attempt to approve 1 private fund → 409 with `dd_required` error
4. Mixed batch (2 liquid + 1 private) → partial: `approved: [2], rejected_dd_required: [1]`
5. `make test` green with new tests
6. Audit events written for each approval

---

# COMMIT 5 — refactor(screener): keyset pagination replacing offset-based

## Problem

Offset-based pagination degrades at high page numbers because Postgres must scan and discard N rows before returning the page. At 9k+ funds with arbitrary sorts, page 100 takes 10× longer than page 1. Keyset pagination is O(1) per page regardless of page number.

## Deliverable

Refactor `catalog_sql.py` (or wherever the pagination logic lives):

1. Replace `OFFSET :offset LIMIT :limit` with `WHERE (sort_key, tiebreaker) > (:cursor_sort, :cursor_tiebreaker) LIMIT :limit`
2. The cursor is a base64-encoded tuple of `(last_sort_value, last_aum_usd, last_external_id)` — three-column tiebreaker for stable sort across pages
3. First page: no cursor param → no WHERE clause beyond filters
4. Subsequent pages: frontend sends `cursor` from the last row of the previous page
5. Response includes `next_cursor: str | None` — NULL if no more rows

**Backwards compatibility:** keep the offset-based params (`page`, `page_size`) as DEPRECATED fallback for any consumer that hasn't migrated. If both `cursor` AND `page` are provided, cursor wins.

**Sort stability:** every ORDER BY must append `external_id ASC` as the final tiebreaker column. This is already in the master plan's data plane spec.

## Verification

1. First page with no cursor → returns limit rows + `next_cursor`
2. Second page with cursor → returns next limit rows, no overlap with page 1
3. Last page → returns remaining rows + `next_cursor: null`
4. Sort change → cursor invalidated (frontend must re-fetch from page 1)
5. Offset-based fallback still works (deprecated but functional)
6. `EXPLAIN ANALYZE` on page 50 with keyset shows no sequential scan (uses index)
7. `make test` green

---

# COMMIT 6 — test(screener): integration tests for catalog, elite, sparkline, approve routes

## Deliverable

New test file `backend/tests/wealth/routes/test_screener_integration.py`:

1. **Catalog test:** POST `/screener/catalog` with fixture data → assert `elite_flag`, `in_universe`, `approval_status` fields present in response, assert row count matches fixture
2. **Elite filter test:** POST `/screener/catalog` with `elite_only: true` → assert all returned rows have `elite_flag: true`, assert count ≤ 300
3. **Sparkline batch test:** POST `/screener/sparklines` with 5 instrument IDs → assert 5 keys in response, each has ≤ 60 monthly points
4. **Universe approval test:** POST `/universe/approve` with liquid funds → assert 201, then GET catalog → verify `in_universe: true` on those funds
5. **DD gate test:** POST `/universe/approve` with private fund → assert 409 `dd_required`
6. **Keyset pagination test:** fetch 3 pages via cursor chaining → assert no row overlap, assert final `next_cursor: null`
7. **Sanitization test:** POST `/screener/catalog` → grep response body for banned jargon substrings (CVaR, DTW, RISK_ON, etc.) → assert zero matches

**Test fixture:** use the existing dev DB fixture data. If fixture data is insufficient (e.g., no ELITE flagged funds), add a small fixture setup in the test file that inserts test data and cleans up after.

## Verification

1. `pytest backend/tests/wealth/routes/test_screener_integration.py -v` → all green
2. `make test` → all green including new tests
3. `make lint` → clean

---

# FINAL FULL-TREE VERIFICATION

1. `make check` → green (lint + architecture + typecheck + test)
2. `make loadtest` → screener ELITE p95 still < 300ms (verify refactoring didn't regress)
3. Response body grep for banned jargon → zero
4. `EXPLAIN ANALYZE` on keyset pagination query → no sequential scan on page 50

# SELF-CHECK

- [ ] Commit 1: catalog query builder refactored, MV JOINs in EXPLAIN plan
- [ ] Commit 2: `elite_flag`, `elite_rank_within_strategy`, `in_universe`, `approval_status` in response
- [ ] Commit 3: sparkline batch endpoint works for 5-100 instruments, returns monthly NAV
- [ ] Commit 4: fast-track liquid approval works, DD gate blocks private/BDC, idempotent
- [ ] Commit 5: keyset pagination works across 3+ pages, offset fallback preserved
- [ ] Commit 6: 7 integration tests all green
- [ ] No files outside screener backend scope touched
- [ ] No frontend files modified
- [ ] Sanitized response — zero jargon leakage
- [ ] Parallel session files untouched

# VALID ESCAPE HATCHES

1. `catalog_sql.py` does not exist — the query is built inline in the route. Refactor inline, note the difference.
2. `v_screener_org_membership` JOIN requires explicit RLS SET LOCAL that isn't set by the route — investigate, add if missing. The view's `security_barrier=true` should handle this but verify.
3. `POST /universe/approve` doesn't have an `@idempotent` decorator imported — add it, referencing existing patterns in other routes.
4. Keyset cursor encoding conflicts with existing URL param structure — use a simple `|`-delimited string encoded in base64 instead of complex JSON cursor.
5. Batch sparkline endpoint exceeds 500ms for 100 instruments — investigate whether `nav_monthly_returns_agg` needs an additional index on `instrument_id` for the `ANY(:ids)` predicate.

# REPORT FORMAT

1. Six commit SHAs with messages
2. Per commit: files modified, verification output, EXPLAIN plans where relevant
3. Commit 5 extra: keyset pagination demo output (3 pages, no overlap)
4. Commit 6 extra: test output (7 tests, all green)
5. Full-tree verification including `make loadtest` output
6. Any escape hatches hit

Begin by reading overview + this brief + audit. Verify Phase 2 MVs exist in local DB. Start commit 1.
