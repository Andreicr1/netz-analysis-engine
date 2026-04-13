# TAA Regime Global Scoping — Split Raw Regime from Org-Scoped Bands

**Date:** 2026-04-13
**Branch:** `fix/taa-regime-global-scoping` (off `main`)
**Depends on:** `fix/taa-regime-signals` already merged (PR #139 — provides `build_regime_inputs()`)
**Scope:** Backend — 1 migration, worker refactor, new route, model change
**Risk:** MEDIUM — migration + worker resequencing, but zero frontend schema break if denormalized copies maintained
**Priority:** MEDIUM — correctness issue (redundant per-org computation, new orgs get 404)

---

## Problem Statement

`taa_regime_state` is org-scoped (`OrganizationScopedMixin`, RLS enabled, unique constraint includes `organization_id`). But raw regime classification (VIX, spreads, yield curve, CFNAI, etc.) is **global** — market conditions don't change per organization.

**Consequences:**
1. Every org runs identical regime classification — N orgs = N redundant computations
2. New orgs that haven't run `risk_calc` get 404 on `GET /allocation/{profile}/regime-bands` even though the regime is global
3. Two orgs running `risk_calc` minutes apart could theoretically get different classifications if `macro_ingestion` inserts data between runs (consistency risk)

**What's global vs org-scoped:**

| Field | Should be | Reason |
|---|---|---|
| `raw_regime`, `stress_score`, `signal_details` | GLOBAL | Derived from macro_data (no org context) |
| `smoothed_centers` | ORG-SCOPED | EMA depends on org's previous state + TAA config (halflife, max_shift) |
| `effective_bands` | ORG-SCOPED | Intersection of regime bands with org's IPS bounds from StrategicAllocation |
| `transition_velocity` | ORG-SCOPED | Derived from org-specific smoothed center deltas |

---

## Solution: New Global Table + Worker Split

### Step 1 — Migration: Create `macro_regime_snapshot` (global)

**File:** `backend/app/core/db/migrations/versions/0130_macro_regime_snapshot.py`

Chain from current head `0129_elite_regime_flags` (verified 2026-04-13).

```python
"""Global daily regime snapshot — market conditions shared across all tenants.

One row per as_of_date. Computed by global_regime_detection worker after
macro_ingestion. Read by risk_calc worker to avoid redundant per-org
classification.

Revision ID: 0130_macro_regime_snapshot
Revises: 0129_elite_regime_flags
"""

def upgrade():
    op.create_table(
        "macro_regime_snapshot",
        Column("id", UUID, primary_key=True, server_default=text("gen_random_uuid()")),
        Column("as_of_date", Date, nullable=False, unique=True),
        Column("raw_regime", String(20), nullable=False),
        Column("stress_score", Numeric(5, 1)),
        Column("signal_details", JSONB, nullable=False),  # Full reasons dict from classify_regime_multi_signal
        Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    )

    # Index for fast latest-row lookup
    op.create_index(
        "ix_macro_regime_snapshot_date_desc",
        "macro_regime_snapshot",
        [text("as_of_date DESC")],
    )

    # NO RLS — this is global data (like macro_data, benchmark_nav, etc.)
    # No organization_id column
```

**CRITICAL: NO RLS on this table.** It is in the same category as `macro_data`, `benchmark_nav`, `treasury_data`, `fund_risk_metrics` — shared across all tenants.

### Step 2 — Model: `MacroRegimeSnapshot`

**File:** `backend/app/domains/wealth/models/allocation.py`

Add new model BEFORE `TaaRegimeState`:

```python
class MacroRegimeSnapshot(Base):
    """Global daily regime snapshot. One row per date, no org_id, no RLS.

    Computed by regime_detection worker. Read by risk_calc for TAA band
    computation and by GET /allocation/regime for global regime display.
    """
    __tablename__ = "macro_regime_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    raw_regime: Mapped[str] = mapped_column(String(20), nullable=False)
    stress_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    signal_details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
```

**Do NOT remove `raw_regime` or `stress_score` from `TaaRegimeState`.** Keep them as denormalized copies. This prevents any frontend break — `RegimeBandsRead` schema stays identical.

### Step 3 — Schema: `GlobalRegimeRead`

**File:** `backend/app/domains/wealth/schemas/allocation.py`

Add new response schema:

```python
class GlobalRegimeRead(BaseModel):
    """Global regime snapshot — no org context needed."""
    as_of_date: date
    raw_regime: str
    stress_score: Decimal | None = None
    signal_details: dict = {}
```

### Step 4 — Worker: `regime_detection` function

**File:** `backend/app/domains/wealth/workers/risk_calc.py`

Add a new top-level async function `run_global_regime_detection(eval_date: date | None = None)`:

```python
async def run_global_regime_detection(eval_date: date | None = None) -> None:
    """Compute global regime and persist to macro_regime_snapshot.

    Called AFTER macro_ingestion, BEFORE risk_calc.
    Uses advisory lock 900_130 (convention: 900_XXX where XXX = migration number).
    """
```

This function:
1. Acquires advisory lock `900_130` (convention: `900_` prefix + migration number `130`)
2. Creates a raw asyncpg session (no RLS — global table)
3. Calls `build_regime_inputs(db, as_of_date=eval_date or date.today())`
4. Calls `classify_regime_multi_signal(**inputs)`
5. Calls `extract_stress_score(reasons)`
6. Upserts into `macro_regime_snapshot` on conflict `(as_of_date)`:
   ```python
   upsert = pg_insert(MacroRegimeSnapshot).values(
       as_of_date=eval_date,
       raw_regime=regime,
       stress_score=stress_score,
       signal_details=reasons,
   ).on_conflict_do_update(
       index_elements=["as_of_date"],
       set_={
           "raw_regime": ...,
           "stress_score": ...,
           "signal_details": ...,
       },
   )
   ```
7. Commits and logs

**IMPORTANT:** This function does NOT need `organization_id`. It uses a non-RLS session. Use `from app.core.db.engine import async_session_factory as async_session` then `async with async_session() as db:` — this is the pattern used by ALL global workers (see `macro_ingestion.py` line 15, `bis_ingestion.py` line 15, `esma_ingestion.py` line 22). Do NOT call `set_rls_context()` — the table has no RLS.

### Step 5 — Refactor `_compute_and_persist_taa_state()` in `risk_calc.py`

Modify the function to READ from `macro_regime_snapshot` instead of computing regime inline.

**Current code (lines 1172-1176, AFTER signal fix PR #139):**
```python
    # ── 1. Fetch macro inputs and classify regime (once, global) ──
    inputs = await build_regime_inputs(db, as_of_date=eval_date)
    regime, reasons = classify_regime_multi_signal(**inputs)
    stress_score = extract_stress_score(reasons)
    logger.info("taa_regime_classified", regime=regime, stress_score=stress_score)
```

**Replace with:**
```python
    # ── 1. Read global regime snapshot (computed by regime_detection worker) ──
    from app.domains.wealth.models.allocation import MacroRegimeSnapshot

    snapshot_stmt = (
        select(MacroRegimeSnapshot)
        .where(MacroRegimeSnapshot.as_of_date <= eval_date)
        .order_by(MacroRegimeSnapshot.as_of_date.desc())
        .limit(1)
    )
    snapshot_result = await db.execute(snapshot_stmt)
    snapshot = snapshot_result.scalar_one_or_none()

    if snapshot is None:
        logger.warning(
            "taa_no_regime_snapshot — regime_detection worker may not have run. "
            "Falling back to inline classification.",
        )
        # Graceful fallback: compute inline (same as before)
        inputs = await build_regime_inputs(db, as_of_date=eval_date)
        regime, reasons = classify_regime_multi_signal(**inputs)
        stress_score = extract_stress_score(reasons)
    else:
        regime = snapshot.raw_regime
        stress_score = float(snapshot.stress_score) if snapshot.stress_score is not None else None
        reasons = snapshot.signal_details or {}
        logger.info(
            "taa_using_global_snapshot",
            regime=regime,
            stress_score=stress_score,
            snapshot_date=str(snapshot.as_of_date),
        )
```

**Note:** The `build_regime_inputs` and `classify_regime_multi_signal` imports on line 1164 must be kept (used by fallback path). Add `MacroRegimeSnapshot` to the import from `app.domains.wealth.models.allocation` on line 1162.

**Key design: graceful fallback.** If the global worker hasn't run (first deploy, worker failure), `risk_calc` falls back to inline computation. This makes the migration non-breaking — both old and new behavior produce the same result.

### Step 6 — Route: `GET /allocation/regime`

**File:** `backend/app/domains/wealth/routes/allocation.py`

Add new endpoint BEFORE the existing `get_regime_bands`:

```python
@router.get(
    "/allocation/regime",
    response_model=GlobalRegimeRead,
    summary="Current global market regime",
    description="Returns the latest global regime snapshot. No org context needed — "
    "market conditions are the same for all tenants.",
)
async def get_global_regime(
    db: AsyncSession = Depends(get_db_with_rls),  # Auth required but regime is global
    user: CurrentUser = Depends(get_current_user),
) -> GlobalRegimeRead:
    stmt = (
        select(MacroRegimeSnapshot)
        .order_by(MacroRegimeSnapshot.as_of_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No regime snapshot available. The regime_detection worker may not have run yet.",
        )

    return GlobalRegimeRead(
        as_of_date=snapshot.as_of_date,
        raw_regime=snapshot.raw_regime,
        stress_score=snapshot.stress_score,
        signal_details=snapshot.signal_details,
    )
```

**Note:** This uses `get_db_with_rls` (auth required — users must be logged in) but the SELECT on `macro_regime_snapshot` is unaffected by RLS since the table has no RLS policy. This is the same pattern used by `fund_risk_metrics` queries.

### Step 7 — Make `run_global_regime_detection` a standalone worker module

Workers in this codebase are standalone modules with `asyncio.run()` in `if __name__ == "__main__"`. There is NO central scheduler or registry.

Add a `__main__` block at the bottom of `risk_calc.py` (where the function lives) OR create a thin wrapper `backend/app/domains/wealth/workers/regime_detection.py`:

```python
"""Global regime detection worker — computes macro_regime_snapshot.

Usage:
    python -m app.domains.wealth.workers.regime_detection

Must run AFTER macro_ingestion (lock 43) and BEFORE risk_calc (lock 900_007).
Schedule at 02:30 UTC (macro_ingestion ~02:00, risk_calc ~03:00).

Advisory lock ID = 900_130.
"""
from __future__ import annotations

import asyncio

from app.domains.wealth.workers.risk_calc import run_global_regime_detection

if __name__ == "__main__":
    asyncio.run(run_global_regime_detection())
```

The natural ordering is:
```
macro_ingestion (lock 43, daily ~02:00 UTC)
  → regime_detection (lock 900_130, daily ~02:30 UTC)
    → risk_calc per org (lock 900_007, daily ~03:00 UTC)
```

Pattern reference: see `macro_ingestion.py` line 374, `brochure_ingestion.py` bottom — all use `asyncio.run()` in `__main__`.

### Step 8 — Tests

**File:** `backend/tests/quant_engine/test_regime_global_scoping.py` (new)

Test 1 — `test_global_regime_snapshot_no_rls`:
- Insert a `MacroRegimeSnapshot` row
- Query WITHOUT setting `app.current_organization_id`
- Assert row is accessible (no RLS blocking)

Test 2 — `test_taa_state_reads_global_snapshot`:
- Insert a `MacroRegimeSnapshot` for today
- Call `_compute_and_persist_taa_state(db, org_id, today)`
- Assert the persisted `taa_regime_state.raw_regime` matches the snapshot's regime
- Assert no call to `build_regime_inputs` was made (mock and verify not called)

Test 3 — `test_taa_state_fallback_without_snapshot`:
- Do NOT insert any `MacroRegimeSnapshot`
- Call `_compute_and_persist_taa_state(db, org_id, today)`
- Assert it still works (fallback to inline computation)
- Assert warning logged about missing snapshot

Test 4 — `test_global_regime_route`:
- Insert a `MacroRegimeSnapshot`
- GET `/allocation/regime`
- Assert 200 with correct `raw_regime`, `stress_score`, `signal_details`

Test 5 — `test_global_regime_route_404_without_data`:
- GET `/allocation/regime` with empty table
- Assert 404

Test 6 — `test_regime_bands_still_works`:
- Insert both `MacroRegimeSnapshot` and `taa_regime_state` for an org
- GET `/allocation/{profile}/regime-bands`
- Assert existing response schema unchanged (regression)

---

## Files Modified

| File | Action |
|---|---|
| `backend/app/core/db/migrations/versions/0130_macro_regime_snapshot.py` | NEW — migration creating global table |
| `backend/app/domains/wealth/models/allocation.py` | ADD `MacroRegimeSnapshot` model |
| `backend/app/domains/wealth/schemas/allocation.py` | ADD `GlobalRegimeRead` schema |
| `backend/app/domains/wealth/routes/allocation.py` | ADD `GET /allocation/regime` route |
| `backend/app/domains/wealth/workers/risk_calc.py` | ADD `run_global_regime_detection()`, MODIFY `_compute_and_persist_taa_state()` lines 1172-1176 to read snapshot with fallback |
| `backend/app/domains/wealth/workers/regime_detection.py` | NEW — thin wrapper module with `asyncio.run()` for standalone execution |
| `backend/tests/quant_engine/test_regime_global_scoping.py` | NEW — 6 tests |

## Files NOT Modified

- `taa_regime_state` table — NO migration to remove `organization_id` or RLS. The table stays org-scoped (smoothed_centers and effective_bands ARE legitimately per-org). `raw_regime` and `stress_score` remain as denormalized copies.
- Frontend types (`taa.ts`) — `RegimeBands` interface unchanged
- Frontend components — zero changes
- `RegimeBandsRead` schema — unchanged

---

## Validation Sequence

```bash
# 1. Run migration
make migrate

# 2. Verify table exists, no RLS
psql -c "SELECT relname, relrowsecurity FROM pg_class WHERE relname = 'macro_regime_snapshot';"
# Expected: relrowsecurity = false

# 3. Type check
make typecheck

# 4. Run new tests
make test ARGS="-k test_regime_global_scoping -v"

# 5. Run existing TAA tests (regression)
make test ARGS="-k taa -v"
make test ARGS="-k regime -v"

# 6. Full gate
make check
```

---

## Impact Assessment

| Component | Impact |
|---|---|
| Frontend `RegimeBandsRead` | NONE — denormalized copies maintained |
| Construction pipeline (`resolve_effective_bands`) | NONE — reads from `taa_regime_state` which still has `raw_regime` |
| Model portfolio routes | NONE — same read path |
| Worker ordering | LOW — new worker slots between existing ones |
| New orgs | FIXED — `GET /allocation/regime` works without `risk_calc` having run |
| Audit trail | `taa_regime_transition` audit events still fire per-org in `risk_calc` |

---

## Commit Message

```
feat(quant): global macro_regime_snapshot — decouple raw regime from org scope

Raw regime classification (VIX, spreads, CFNAI, etc.) is global market
data — same for all tenants. Previously computed redundantly per-org
inside risk_calc worker.

New macro_regime_snapshot table (no RLS, no org_id) stores one row per
date. New regime_detection worker runs after macro_ingestion. risk_calc
reads snapshot instead of recomputing, with graceful fallback.

New GET /allocation/regime endpoint for global regime display.
taa_regime_state stays org-scoped for smoothed centers + effective bands.
```
