---
title: "FastAPI Route Shadowing and SQL LIMIT Bias in Multi-Instrument Queries"
date: 2026-03-17
category: logic-errors
tags:
  - fastapi
  - route-ordering
  - sql-limit-bias
  - correlation-matrix
  - silent-data-corruption
  - code-review
  - wealth-vertical
  - time-series
  - forward-fill
modules:
  - backend/app/domains/wealth/routes/strategy_drift.py
  - backend/app/domains/wealth/routes/correlation_regime.py
severity: P1
problem_type: silent-correctness-failure
branch: feat/wealth-senior-analyst-engines
fix_commit: f486091
---

# FastAPI Route Shadowing and SQL LIMIT Bias in Multi-Instrument Queries

Two P1 silent correctness bugs found during 8-agent code review of Sprint 6 Senior Analyst Engines. Both produce valid HTTP responses with wrong data — no errors, no 500s, no test failures. Discovered only through multi-agent review (security-sentinel, performance-oracle, kieran-python-reviewer all flagged independently).

---

## Pattern 1: FastAPI Parameterized Route Shadows Literal Routes

### Symptom

`GET /analytics/strategy-drift/alerts` returns HTTP 422 "value is not a valid uuid" even though the route handler exists and works in isolation.

### Root Cause

FastAPI evaluates routes in registration order. `@router.get("/{instrument_id}")` was registered BEFORE `@router.get("/alerts")`. Any request to `/alerts` was captured by `/{instrument_id}`, which tried to parse `"alerts"` as a UUID.

### Why It Is Silent

- Tests call endpoints with valid UUIDs — they never hit the literal path conflict
- 422 is a "valid" HTTP error, not a 500 — monitoring doesn't flag it
- The `/alerts` handler exists and would work if reached

### Working Fix

Register all literal routes BEFORE parameterized routes at the same depth:

```python
# ── Literal routes FIRST (FastAPI matches top-down) ─────────────
@router.post("/scan", ...)
async def trigger_drift_scan(...): ...

@router.get("/alerts", ...)
async def list_drift_alerts(...): ...

# ── Parameterized route MUST come after literal routes ──────────
# FastAPI matches top-to-bottom; /{instrument_id} would capture
# "alerts" as UUID and fail with 422.
@router.get("/{instrument_id}", ...)
async def get_instrument_drift(...): ...
```

### Anti-Pattern Warning

Do NOT fix with regex constraints on the path parameter (e.g., `Path(pattern="^[0-9a-f-]{36}$")`). It technically works but is fragile — you still get 422 instead of 404 for non-UUID strings, and every new literal route requires remembering the ordering rule. Route ordering discipline is the correct fix.

### Prevention

**Rule:** In any FastAPI router, literal path segments (`/alerts`, `/scan`, `/summary`) MUST be declared before parameterized segments (`/{id}`) at the same path depth.

**Detection heuristic:** In any route file, if a `/{param}` route appears before a `/literal` route on the same router, it is a bug.

**Regression test:**

```python
@pytest.mark.parametrize("literal_path", ["/alerts", "/scan"])
async def test_literal_routes_not_shadowed(async_client, auth_headers, literal_path):
    """No literal sub-route should return 422 due to UUID parsing."""
    resp = await async_client.get(
        f"/api/v1/wealth/analytics/strategy-drift{literal_path}",
        headers=auth_headers,
    )
    assert resp.status_code != 422, f"{literal_path} shadowed by parameterized route"
```

**Code review checklist item:**
- [ ] Are all literal path segments declared BEFORE any `/{param}` route at the same depth?

---

## Pattern 2: SQL LIMIT Bias in Multi-Instrument Time-Series Queries

### Symptom

Correlation matrix returns noisy or incorrect values for portfolios with mixed-density instruments (e.g., daily US equities + weekly Brazilian funds). The route may also return false "insufficient data" 422 errors for portfolios that have plenty of data.

### Root Cause

The query used `.limit(total_days * len(instrument_ids))` as a global cap. SQL LIMIT is applied to the entire result set, not per-instrument. Dense instruments (daily NAV) exhaust the row budget before sparse instruments (weekly/monthly) contribute meaningful data.

**Causal chain:** Biased LIMIT → incomplete per-instrument date sets → artificially small date intersection → degraded correlation matrix or false 422.

The downstream date intersection logic (`set.intersection(*date_sets)`) was correct — it follows plan decision G4. But it operated on incomplete date sets because the LIMIT already truncated rows for sparse instruments.

### Why It Is Silent

- The code never errors — it produces a mathematically valid but factually wrong matrix
- A 10-instrument portfolio might silently use 30 common dates instead of 200
- Test data is uniform (same density for all instruments) so tests pass

### Working Fix

Replace LIMIT with a date floor filter:

```python
# WRONG — global LIMIT biases toward dense instruments
nav_stmt = (
    select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
    .where(NavTimeseries.instrument_id.in_(instrument_ids))
    .order_by(NavTimeseries.nav_date.desc())
    .limit(total_days * len(instrument_ids))  # ← silent data loss
)

# CORRECT — date floor bounds equally for all instruments
date_floor = date.today() - timedelta(days=total_days + 30)  # +30 buffer for weekends/holidays
nav_stmt = (
    select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
    .where(
        NavTimeseries.instrument_id.in_(instrument_ids),
        NavTimeseries.nav_date >= date_floor,
        NavTimeseries.return_1d.isnot(None),
    )
    .order_by(NavTimeseries.nav_date)
    # No LIMIT — date floor bounds the result set naturally
)
```

### Anti-Pattern Warning: Never Forward-Fill Financial Returns

DO NOT fix sparse data with forward-fill (`fillna(method="ffill")`). Forward-fill creates artificial zero-return days that:

1. **Fabricate zero-volatility periods** — deflates true volatility
2. **Inflate correlation toward 1.0** — "flat" segments in multiple instruments appear correlated
3. **Distort CVaR and drawdown** — suppresses the actual return distribution

**Correct approach:** Date intersection only — use dates where ALL instruments have actual observed data. Accept a smaller matrix rather than fabricate observations. This is plan decision G4/D9.

### Prevention

**Rule:** Never use SQL `LIMIT` on multi-entity queries where entities have different data densities. Use a date floor (`WHERE date >= ?`) to bound equally by calendar time, then intersect dates in application code.

**Detection heuristic:** Any query with `.limit(X * len(ids))` or `.limit(N * count)` where the intent is "N rows per entity" is almost certainly biased.

**Code review checklist item:**
- [ ] Does any query fetch time-series data for multiple entities using a single `LIMIT`? Replace with date-floor filter. Verify downstream uses date intersection, NOT forward-fill.

---

## Summary: Code Review Checklist Additions

| Check | Signal | Pattern |
|-------|--------|---------|
| Route ordering | `GET /literal-path` returns 422 | `/{param}` registered before `/literal` in same router |
| LIMIT bias | Sparse instrument gets fewer rows than calendar range | `.limit(N * entity_count)` on multi-entity time-series query |
| Forward-fill | Correlation inflated, volatility deflated | Returns matrix built with `ffill` instead of `set.intersection` |

## Related Documentation

- **Plan G4:** `docs/plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md` line 38 — "Forward-fill NAV gaps creates zero returns → distorts correlation"
- **Decision D9:** `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md` line 109 — authoritative decision record for date intersection over forward-fill
- **Prior route conflict:** `docs/solutions/architecture-patterns/wealth-os-design-refresh-multi-agent-review-patterns.md` — exposure router double prefix causing 404s
- **Todo files:** `todos/137-complete-p1-route-ordering-alerts-shadowed-by-instrument-id.md`, `todos/138-complete-p1-correlation-route-unbounded-limit-incorrect-results.md`
