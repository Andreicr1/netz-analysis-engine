# Regime Unification — Kill Primitive, Unify on Multi-Signal

**Date:** 2026-04-14
**Branch:** `fix/regime-unification`
**Sessions:** 1
**Priority:** URGENT — Macro Desk is displaying incorrect regime data

---

## Problem

The system has TWO independent regime classifiers:

1. **Primitive (WRONG — to be REMOVED):** `classify_regional_regime()` at `backend/quant_engine/regime_service.py:454`. Per-region binary OAS credit spread threshold check. Used by `GET /macro/regime` endpoint. This is what the Macro Desk frontend currently calls.

2. **Upgraded (CORRECT — to be the ONLY one):** `classify_regime_multi_signal()` at `backend/quant_engine/regime_service.py:141`. 10-signal composite stress scoring with real economy components (CFNAI, energy shock, Sahm Rule, etc.). 55% financial + 45% real economy. Used by `run_global_regime_detection()` worker which persists to `macro_regime_snapshot` table. Also used by `GET /allocation/regime` endpoint (reads from snapshot).

**Result:** The Macro Desk shows "EXPANSION" for all 4 regions (US/EU/JP/EM) because the primitive classifier only checks if OAS < 550bp. Meanwhile, the portfolio construction system uses the upgraded multi-signal model. Two different "truths" in the same product.

**Fix:** Kill the primitive classifier entirely. Make `GET /macro/regime` read from `macro_regime_snapshot` (same source as `GET /allocation/regime`). The regime is ONE global signal, not per-region — this matches the upgraded methodology.

---

## What to Remove

### 1. Dead code in `backend/quant_engine/regime_service.py`

Remove these functions and their supporting constants (lines ~366-620):
- `REGIONAL_REGIME_SIGNALS` dict (line 372)
- `REGIONAL_OAS_THRESHOLDS` dict
- `resolve_regional_regime_config()` function
- `classify_regional_regime()` function (line 454)
- `RegionalRegimeResult` dataclass
- `compose_global_regime()` function (line 546)
- `_classify_from_oas()` helper
- Any other helpers exclusively used by the regional regime system

**DO NOT remove:**
- `classify_regime_multi_signal()` (line 141) — this is the keeper
- `build_regime_inputs()` (line 827) — this is the keeper
- `get_current_regime()` (line 923) — this is the keeper
- `detect_regime()` (line 329) — volatility fallback, still used
- `classify_regime_from_volatility()` (line 314) — still used
- `RegimeResult` dataclass — still used
- `_ramp()` helper — still used
- `_validate_plausibility()` — still used
- `REGIME_DEFINITIONS` dict — still used
- `RegimeThresholds` TypedDict — still used
- `resolve_regime_thresholds()` — still used
- `REGIME_SERIES_STALENESS` — still used by `build_regime_inputs`
- Any `_compute_*` async helpers used by `build_regime_inputs`

### 2. Delete test file `backend/tests/test_regime_regional.py`

This entire file (141 lines) tests the primitive classifier. Delete it completely. The upgraded classifier has its own tests in `backend/tests/quant_engine/test_regime_service.py` and `test_regime_signal_completeness.py`.

### 3. Remove imports in `backend/app/domains/wealth/routes/macro.py`

Remove imports of: `classify_regional_regime`, `compose_global_regime`, `REGIONAL_REGIME_SIGNALS`, `resolve_regional_regime_config`.

---

## What to Change

### 1. Rewrite `GET /macro/regime` endpoint in `backend/app/domains/wealth/routes/macro.py` (line 239-284)

**Current:** Calls `classify_regional_regime()` per region + `compose_global_regime()` → returns `RegimeHierarchyRead` with per-region labels.

**New:** Read from `macro_regime_snapshot` table (same as `GET /allocation/regime` does). Return a unified global regime with signal breakdown.

The endpoint should:
1. Query `MacroRegimeSnapshot` for the latest row (same query as `GET /allocation/regime` in `allocation.py:403-409`)
2. Return the regime + stress score + signal details
3. The `signal_details` dict from the snapshot contains the full 10-signal breakdown with human-readable reasons

**Schema change:** The response schema must change. `RegimeHierarchyRead` has `global_regime` + `regional_regimes: dict[str, str]` (per-region). The new response should be a single global regime with signal breakdown.

**Option A (simplest):** Reuse `GlobalRegimeRead` from `backend/app/domains/wealth/schemas/allocation.py:141`. This already has `raw_regime`, `stress_score`, `signal_details`. Add the sanitization mixin so `raw_regime` gets humanized.

**Option B:** Create a new schema `MacroRegimeRead` in the macro schemas file that wraps `GlobalRegimeRead` with sanitization.

Choose Option A if `GlobalRegimeRead` already has the sanitization mixin. If not, add it.

Check `GlobalRegimeRead` at `backend/app/domains/wealth/schemas/allocation.py:141`:
```python
class GlobalRegimeRead(BaseModel):
    as_of_date: date
    raw_regime: str
    stress_score: float
    signal_details: dict[str, str] = {}
```

It does NOT have the sanitization mixin. So either:
- Add `SanitizedRegimeFieldMixin` to it (but the field is `raw_regime` not `regime`, so the mixin won't fire)
- OR create a new response model that humanizes the regime

**Best approach:** Add a `@computed_field` or `@model_validator` to `GlobalRegimeRead` that humanizes `raw_regime`:

```python
from app.domains.wealth.schemas.sanitized import humanize_regime

class GlobalRegimeRead(BaseModel):
    as_of_date: date
    raw_regime: str
    stress_score: float
    signal_details: dict[str, str] = {}

    @model_validator(mode="after")
    def _humanize(self) -> "GlobalRegimeRead":
        object.__setattr__(self, "raw_regime", humanize_regime(self.raw_regime))
        return self
```

**Update the route:**

```python
@router.get(
    "/regime",
    response_model=GlobalRegimeRead,  # was RegimeHierarchyRead
    summary="Current global market regime (multi-signal)",
    tags=["macro"],
)
async def get_regime(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> GlobalRegimeRead:
    """Return the latest global regime from macro_regime_snapshot.

    Uses the 10-signal multi-factor stress model (55% financial + 45% real economy).
    Computed daily by the regime_detection worker.
    """
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

**Import changes in macro.py:**
- Add: `from app.domains.wealth.models.allocation import MacroRegimeSnapshot`
- Add: `from app.domains.wealth.schemas.allocation import GlobalRegimeRead`
- Remove: `from quant_engine.regime_service import classify_regional_regime, compose_global_regime, REGIONAL_REGIME_SIGNALS, resolve_regional_regime_config`
- Remove: `from app.domains.wealth.schemas.macro import RegimeHierarchyRead` (if imported)
- Keep: `from app.core.services.config_service import ConfigService` (still needed for other routes)

Also remove `RegimeHierarchyRead` from `backend/app/domains/wealth/schemas/macro.py` if it's no longer used elsewhere. Check first:
```
grep -r "RegimeHierarchyRead" backend/
```

### 2. Update frontend `frontends/wealth/src/routes/(terminal)/macro/+page.svelte`

The response shape changes. Currently the frontend expects:
```typescript
interface RegimeHierarchyRead {
    global_regime: string;
    regional_regimes: Record<string, string>;  // per-region
    composition_reasons: Record<string, string>;
    as_of_date: string | null;
}
```

New response from `GlobalRegimeRead`:
```typescript
interface GlobalRegimeRead {
    as_of_date: string;
    raw_regime: string;     // already humanized by backend: "Expansion" | "Cautious" | "Stress"
    stress_score: number;   // 0-100 composite stress
    signal_details: Record<string, string>;  // per-signal breakdown
}
```

**Changes needed in +page.svelte:**

1. Update the `RegimeHierarchyRead` type to `GlobalRegimeRead` (or whatever TypeScript interface name).

2. The tile assembly logic currently reads `regime.regional_regimes[key]` for per-region regime. Since regime is now GLOBAL (one label for all regions), ALL tiles should show the SAME global regime label.

   Change line ~193:
   ```typescript
   // OLD: regime: regime!.regional_regimes[key] ?? "Unknown",
   // NEW: regime: regime!.raw_regime ?? "Unknown",
   ```

3. The global regime display at line ~323 (`GLOBAL: {sanitizeRegime(regime.global_regime)}`) should read from `regime.raw_regime` instead. The backend already humanizes it, so `sanitizeRegime()` can be simplified or kept as a safety passthrough.

4. Consider showing `stress_score` somewhere on the page — e.g., next to the global regime label: `"GLOBAL: Cautious (stress: 42/100)"`. This gives the IC team a numeric sense of how stressed the market is.

5. The `signal_details` dict could be rendered below the global regime label as a signal breakdown panel. Each key-value pair is a human-readable signal description like `"vix": "VIX=19.5 (stress=9/100)"`. This replaces the `composition_reasons` which was about GDP-weighted composition.

### 3. Check and update any other consumers

Search for `RegimeHierarchyRead` and `regional_regimes` across the codebase:
```
grep -r "RegimeHierarchyRead\|regional_regimes\|classify_regional_regime\|compose_global_regime" --include="*.py" --include="*.svelte" --include="*.ts"
```

Remove or update any stale references.

---

## Constraints

- All terminal design rules apply (--terminal-* tokens, mono font, 0 radius, no hex).
- Formatters from @netz/ui exclusively.
- The `GET /allocation/regime` endpoint in allocation.py must NOT be changed — it already reads from the snapshot correctly.
- The `run_global_regime_detection()` worker in risk_calc.py must NOT be changed — it already uses the correct methodology.
- Backend tests must pass after changes. Run `make test` to verify.
- Frontend check must pass: `pnpm --filter @investintell/wealth check`.

---

## Verification

1. `make test` passes (including removal of `test_regime_regional.py`).
2. `make lint` passes.
3. `make typecheck` passes.
4. `pnpm --filter @investintell/wealth check` passes.
5. `GET /macro/regime` returns the same data as `GET /allocation/regime` (both read from `macro_regime_snapshot`).
6. No references to `classify_regional_regime`, `compose_global_regime`, or `REGIONAL_REGIME_SIGNALS` remain in non-test, non-docs Python files.
7. Frontend Macro Desk shows ONE global regime label (not per-region different labels).
8. Stress score is visible on the Macro Desk.
9. Signal breakdown is visible (shows which signals contributed to the regime).

---

## Anti-Patterns

- Do NOT create a new per-region regime system. The regime is ONE global signal.
- Do NOT keep the primitive classifier "just in case". Delete it.
- Do NOT add fallback logic that computes regime inline if the snapshot is missing. Return 404 — the worker must run first.
- Do NOT change the `macro_regime_snapshot` table or the `run_global_regime_detection` worker.
- Do NOT change `GET /allocation/regime` in allocation.py.
