---
status: complete
priority: p1
issue_id: "138"
tags: [code-review, performance, correctness]
dependencies: []
---

# Correlation route: unbounded LIMIT produces incorrect results + interseção silenciosamente reduzida

## Problem Statement

The correlation regime route loads NAV returns with `.limit(total_days * len(instrument_ids))` applied globally (not per-instrument). SQL LIMIT is applied to the entire result set, not partitioned by instrument. If instrument A has dense data and B has sparse data, the limit may exhaust on A's rows before returning B's rows.

**Causal chain:** The biased LIMIT silently sabotages the downstream date intersection logic (lines 119-124). The intersection code itself is correct (`set.intersection(*date_sets)`) — it follows plan decision G4 exactly. But it operates on incomplete date sets because the LIMIT already truncated rows for sparse instruments. The result is an artificially small intersection (fewer common dates than actually exist), which produces either a reduced-quality correlation matrix or an outright 422 "insufficient data" error for portfolios that have plenty of data.

Additionally, there is no date lower bound filter, so the query planner cannot use the `ix_nav_timeseries_instrument_date` index for range elimination.

## Findings

- Found by: performance-oracle (CRITICAL-1), causal chain identified during synthesis
- `backend/app/domains/wealth/routes/correlation_regime.py` lines 102-112
- The query uses `.order_by(NavTimeseries.nav_date.desc()).limit(total_days * len(instrument_ids))`
- With 100 instruments and 504 days, this fetches up to 50,400 rows globally — biased toward instruments with more data
- The date intersection code (lines 119-124) is **correct** and must be preserved — it implements plan decision G4 (dropna how="any", NOT forward-fill)
- The LIMIT is the sole root cause; fixing it resolves the entire chain

## Proposed Solutions

### Option 1: Replace LIMIT with date floor filter (Recommended)

**Approach:** Add `NavTimeseries.nav_date >= date.today() - timedelta(days=total_days + 30)` and remove the LIMIT clause. The date floor bounds the result correctly and equally for all instruments. Keep the existing date intersection logic untouched.

**Pros:**
- Correct results for all instruments regardless of data density
- Enables index range elimination via `ix_nav_timeseries_instrument_date`
- Simpler query
- Preserves the correct intersection logic

**Cons:**
- None

**Effort:** 15 minutes
**Risk:** Low

### Option 2: Window function per instrument

**Approach:** Use `ROW_NUMBER() OVER (PARTITION BY instrument_id ORDER BY nav_date DESC)` to get the N most recent rows per instrument.

**Pros:** Exact per-instrument control

**Cons:** More complex SQL, harder to maintain

**Effort:** 30 minutes
**Risk:** Low

## Recommended Action

Option 1 — replace LIMIT with date floor filter.

**DO NOT use forward-fill to "fix" gaps.** If someone resolves the LIMIT by increasing the fetch but then applies forward-fill (`fillna(method="ffill")` or similar) to fill missing dates, this introduces zero returns for instruments that didn't trade on those days. Zero returns artificially inflate correlation toward zero and distort the entire regime analysis. The correct approach is to remove the LIMIT, let the date floor provide natural bounds, and keep the existing `set.intersection` logic that only uses dates where ALL instruments have real data. This is plan decision G4 / D9.

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/routes/correlation_regime.py` lines 97-115 (query) and 119-124 (intersection — preserve as-is)

**Related decisions:**
- Plan G4: "Forward-fill NAV gaps creates zero returns → distorts correlation. Use date intersection (dropna(how='any')), NOT forward-fill."
- Plan D9: Date intersection for instruments with different trading calendars (BR vs US)

## Acceptance Criteria

- [ ] Query uses date floor filter instead of LIMIT
- [ ] Date intersection logic (lines 119-124) unchanged — no forward-fill introduced
- [ ] Instruments with different data densities produce correct correlation matrix
- [ ] Tests pass

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
**Actions:** Identified by performance-oracle agent as CRITICAL-1. Causal chain (LIMIT bias → incomplete date sets → reduced intersection) documented during synthesis with user input.
