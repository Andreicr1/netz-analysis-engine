# Phase 5B — Dead Code Removal (lipper_service + fred_service)

**Status:** Ready
**Estimated scope:** ~50 lines removed
**Risk:** Low (removing unused code)
**Prerequisite:** None

---

## Context

Two `quant_engine` services are dead code:

1. **`quant_engine/lipper_service.py`** — Lipper fund data service. YFinance + ESMA + SEC cover the fund universe; Lipper is a paid service and redundant. Never called in production.

2. **`quant_engine/fred_service.py`** — Direct FRED API client. Replaced by DB-first pattern (`macro_data` hypertable + `macro_ingestion` worker). CLAUDE.md already documents it as eliminated. The `FredService` class was used in `macro_ingestion.py` but should have been replaced by direct DB reads.

---

## Task 1: Remove `lipper_service.py`

### Step 1.1 — Verify no active consumers

Search the entire codebase for imports of `lipper_service`:

```
grep -r "lipper_service" backend/
grep -r "LipperService" backend/
grep -r "from quant_engine.lipper" backend/
```

If any active imports exist (not in tests), understand the dependency before removing.

### Step 1.2 — Delete file

```
rm backend/quant_engine/lipper_service.py
```

### Step 1.3 — Clean up references

- Remove from `backend/quant_engine/__init__.py` if exported
- Remove from any test files that import it
- Remove from any `pyproject.toml` or requirements references

---

## Task 2: Remove `fred_service.py`

### Step 2.1 — Verify no active consumers

Search for imports:

```
grep -r "fred_service" backend/
grep -r "FredService" backend/
grep -r "from quant_engine.fred" backend/
grep -r "FredObservation" backend/
```

**Known reference:** `macro_ingestion.py` lines ~143-149 used to import `FredService` and `FredObservation`. This should have been replaced already. If not, it needs to be refactored to use the `macro_data` hypertable directly.

### Step 2.2 — If `macro_ingestion.py` still imports FredService

This means the worker still calls FRED API directly. This contradicts CLAUDE.md ("zero FRED API calls"). If this is the case:
- The worker should be using `macro_data` hypertable directly
- The FRED API calls should have been removed in a prior refactoring
- **Do not remove `fred_service.py` until `macro_ingestion.py` is refactored** — flag this as a blocker

### Step 2.3 — If no active consumers

```
rm backend/quant_engine/fred_service.py
```

### Step 2.4 — Clean up references

- Remove from `backend/quant_engine/__init__.py` if exported
- Remove from any test files
- Remove stale test fixtures

---

## Task 3: Verify Clean Build

```bash
make check  # lint + typecheck + test + architecture
```

All gates must pass:
- **lint:** No unused imports referencing deleted files
- **typecheck:** No missing module errors
- **test:** No test files reference deleted services
- **architecture:** No import-linter violations

---

## Files Removed

| File | Reason |
|------|--------|
| `backend/quant_engine/lipper_service.py` | Redundant — YFinance + ESMA + SEC cover fund universe |
| `backend/quant_engine/fred_service.py` | Replaced by DB-first pattern (macro_data hypertable) |

## Files Modified

| File | Change |
|------|--------|
| `backend/quant_engine/__init__.py` | Remove deleted exports |
| Any test files importing deleted services | Remove/update tests |
| `backend/app/domains/wealth/workers/macro_ingestion.py` | Remove FredService import if still present |

## Acceptance Criteria

- [ ] Both files deleted
- [ ] Zero remaining imports of `lipper_service` or `fred_service`
- [ ] No test files reference deleted services
- [ ] `make check` passes (lint + typecheck + test + architecture)

## Gotchas

- `fred_service.py` may still be actively imported by `macro_ingestion.py` — check first
- If `macro_ingestion.py` still uses `FredService`, this is a separate refactoring task (the worker should read from `macro_data` hypertable, not call FRED API)
- `fred_client.py` in `vertical_engines/credit/market_data/` is a DIFFERENT file (credit's FRED client, also should have been eliminated) — check if it still exists too
- Don't remove test files that test functionality that was refactored (not deleted) — only remove tests for truly dead code
