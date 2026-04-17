# PR-A7 — Universe Pre-Filter (Layer 0 + Layer 2)

**Date:** 2026-04-16
**Executor:** Opus 4.6 (1M)
**Branch:** `feat/pr-a7-universe-prefilter` (from `main` HEAD post PR-A6 merge)
**Scope:** Add deterministic pre-filter cascade between `instruments_org` (~3,184 post-auto-import) and `compute_fund_level_inputs`. Without this, optimizer fails with `insufficient_fund_data` → `heuristic_fallback` because `_align_returns_with_ffill` cannot find common dates across 3,184 funds with heterogeneous NAV histories. Also fix the `succeeded` false-positive when solver falls back.

## Empirical evidence from 6 builds (2026-04-16)

All 3 portfolios (Conservative, Balanced, Dynamic Growth) returned status=`succeeded` with:
- `optimizer_trace.status = 'fallback:insufficient_fund_data'`
- `optimizer_trace.solver = 'heuristic_fallback'`
- `weights_proposed`: 18-21 funds (of 3,184 input)
- wall_clock 35-43s

DB verification:
- 3,184 funds in `instruments_org` (post-auto-import) ✓
- 3,184/3,184 have `fund_risk_metrics` + `manager_score` + NAV ≥ 1,260 days ✓
- **Only 2,506/3,184 have recent NAV (≤10 days)**; 678 stale
- Daily overlap window: avg 3,073/day, **min = 1/day** — kills `_align_returns_with_ffill` intersection

Root cause: `compute_fund_level_inputs` receives 3,184 `fund_instrument_ids` → `_sanitize_returns` drops stale → `_align_returns_with_ffill` needs common dates across survivors → insufficient → ValueError → caught in `_run_construction_async:1994` try/except → fallback path. CLARABEL never runs.

## Mandates

1. **`mandate_high_end_no_shortcuts.md`** — no skips, no mocks, 30/30 tests green before commit
2. **`feedback_no_emojis.md`** — zero emojis
3. **`feedback_smart_backend_dumb_frontend.md`** — SSE `metrics` emits `{universe_size_before, universe_size_after_layer_0, universe_size_after_layer_2}` as numbers; frontend composes the human label
4. **DB-first** — pre-filter is SQL, not post-hoc Python filter over 3,184 Python dicts
5. **Infra before visual** — no frontend changes in this PR
6. **Single commit, tight scope** — one file touched in backend (`model_portfolios.py` — `_load_universe_funds` signature + SQL) + one test file

## Section A — Filter cascade

### A.1 — Layer 0: Strategic block filter

Current `_load_universe_funds` (backend/app/domains/wealth/routes/model_portfolios.py:2300) does not filter by profile. Strategic allocation varies per profile:
- `conservative`: 11 blocks (FI-heavy: fi_us_aggregate, fi_us_treasury, fi_us_tips, cash dominant)
- `moderate`: 14 blocks
- `growth`: 14 blocks (equity-heavy)

Add signature param `profile: str` and add JOIN:

```python
from app.domains.wealth.models.allocation import StrategicAllocation

# ... inside the function, after existing query scaffolding:
stmt = (
    select(
        Instrument.instrument_id,
        Instrument.name,
        InstrumentOrg.block_id,
    )
    .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
    .join(
        FundRiskMetrics,
        (FundRiskMetrics.instrument_id == Instrument.instrument_id)
        & (FundRiskMetrics.organization_id.is_(None)),
    )
    .join(
        latest_risk,
        (latest_risk.c.instrument_id == FundRiskMetrics.instrument_id)
        & (latest_risk.c.max_date == FundRiskMetrics.calc_date),
    )
    # A.1 Layer 0: only blocks active in the strategic allocation for this profile
    .join(
        StrategicAllocation,
        (StrategicAllocation.block_id == InstrumentOrg.block_id)
        & (StrategicAllocation.profile == profile)
        & (
            StrategicAllocation.effective_to.is_(None)
            | (StrategicAllocation.effective_to > sa_func.current_date())
        ),
    )
    .where(
        Instrument.is_active == True,
        InstrumentOrg.block_id.isnot(None),
    )
)
```

**Caveat honest:** current `instruments_org` populates only 7 blocks (na_equity_large 1719, fi_us_aggregate 623, alt_real_estate 394, fi_us_high_yield 255, na_equity_small 123, cash 44, alt_gold 26). All 7 are present in all 3 profiles' strategic allocations. Layer 0 is a near-no-op in current state BUT future-proofs for when more block types are auto-imported or when profile strategic allocations diverge.

### A.2 — Layer 2: Top-N per block via manager_score

Cardinality target: ~350 (≈7 blocks × 50). Use a CTE with ROW_NUMBER:

```python
LAYER_2_TOP_N_PER_BLOCK = 50

# Wrap the existing query in a CTE and add ROW_NUMBER:
ranked_cte = (
    select(
        Instrument.instrument_id.label("instrument_id"),
        Instrument.name.label("name"),
        InstrumentOrg.block_id.label("block_id"),
        FundRiskMetrics.manager_score.label("manager_score"),
        sa_func.row_number().over(
            partition_by=InstrumentOrg.block_id,
            order_by=[
                FundRiskMetrics.manager_score.desc().nulls_last(),
                Instrument.instrument_id.asc(),  # deterministic tiebreak
            ],
        ).label("rn"),
    )
    # ... (existing joins, filters, StrategicAllocation join from A.1)
).cte("ranked_universe")

stmt = select(
    ranked_cte.c.instrument_id,
    ranked_cte.c.name,
    ranked_cte.c.block_id,
    ranked_cte.c.manager_score,
).where(ranked_cte.c.rn <= LAYER_2_TOP_N_PER_BLOCK)
```

### A.3 — Remove the now-redundant second risk query

The current function runs a second query (line 2368) to populate `score_map`. With the CTE approach the `manager_score` is already in the main rowset. Delete the second query and use the row field directly.

### A.4 — Caller update

`_run_construction_async:1859` calls `_load_universe_funds(db, org_id, regime=current_regime)`. Update to pass `profile` (already in scope at line 1824 as function param):

```python
universe_funds = await _load_universe_funds(
    db, org_id, profile=profile, regime=current_regime,
)
```

Keep `regime` param as-is. Keep default `regime="RISK_ON"` for callers that don't pass it. Add `profile` as REQUIRED param (no default) — explicit, fail fast if missing.

## Section B — Fix `succeeded` false positive

### B.1 — `_run_construction_async` status gate

Search for the code that sets final run `status = 'succeeded'` in `construction_run_executor.py` or `model_portfolios.py`. When `optimizer_trace.solver == 'heuristic_fallback'` AND all 4 CLARABEL phases returned status `failed` or `skipped`, set final status to `degraded` (not `succeeded`).

Schema check: `portfolio_construction_runs.status` currently accepts `'succeeded'`, `'failed'`, `'cancelled'`. Add `'degraded'` to the allowed values — check if there's a CHECK constraint or enum. If CHECK constraint exists, migration 0141 extends it. If it's free text, just emit the new value.

### B.2 — SSE terminal event payload

When status is `degraded`, SSE terminal event label changes from `"Construction succeeded"` to `"Construction completed with fallback"`. Frontend `_applyBuildEvent` in `portfolio-workspace.svelte.ts` treats `degraded` the same as `succeeded` for UI (load the run) but displays a warning badge. **Frontend not in scope for this PR** — backend emits `degraded` and stores it; frontend rendering of the badge is PR-A8. Just do NOT break the existing `phase === "COMPLETED"` client mapping.

## Section C — Tests

Target location: `backend/tests/wealth/test_load_universe_funds_prefilter.py` (new file).

### C.1 — Integration test with real docker-compose DB

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_prefilter_reduces_to_target_cardinality():
    """Pre-filter cascade reduces 3,184 → ~350 for conservative profile."""
    async with async_session_factory() as db:
        funds = await _load_universe_funds(
            db,
            org_id="403d8392-ebfa-5890-b740-45da49c556eb",
            profile="conservative",
        )
    # Layer 2 caps 50 per block × 7 populated blocks ≈ 350
    # (some blocks have <50 funds, so actual is slightly below)
    assert 200 <= len(funds) <= 400, f"Got {len(funds)} funds, expected 200-400"
```

### C.2 — Layer 0 profile filtering

Seed a test org with 2 instruments_org rows — one with block_id in `conservative` profile, one in a block NOT in `conservative`. Call `_load_universe_funds(profile='conservative')`. Assert the non-matching block is filtered out.

### C.3 — Layer 2 top-N cap

Seed 100 funds in a single block with manager_score 0.01 to 1.00. Call with `profile` that includes that block. Assert exactly `LAYER_2_TOP_N_PER_BLOCK=50` rows returned, sorted by manager_score DESC, tie-broken by instrument_id ASC.

### C.4 — Deterministic ordering

Run the same query twice. Assert results are identical (not dependent on query planner choices).

### C.5 — `succeeded → degraded` unit test

Mock optimizer_trace with `solver=heuristic_fallback` + all 4 phases `failed/skipped`. Assert `run.status == 'degraded'`.

### C.6 — Existing tests must still pass

30 tests from PR-A6 + construction executor tests. Run `pytest backend/tests/wealth/ -q` before commit. Zero regressions.

## Section D — Verification

### D.1 — Migration apply

If `status` CHECK constraint needs extending, new migration `0141_portfolio_status_degraded.py` updates the CHECK. Otherwise skip migration. Be explicit in commit message about whether migration was needed.

### D.2 — Live DB smoke test

Before committing, run against the 3 existing portfolios via the admin endpoint or direct worker call:

```bash
curl -X POST http://localhost:8000/api/v1/portfolios/3945cee6-f85d-4903-a2dd-cf6a51e1c6a5/build \
  -H "X-DEV-ACTOR: {...}" -H "Idempotency-Key: $(uuidgen)"
```

Expected outcome:
- `optimizer_trace.solver` NOT `heuristic_fallback` (CLARABEL real)
- `optimizer_trace.status` = `optimal` or `feasible` (not `fallback:*`)
- `weights_proposed`: 20-100 funds (real optimizer output, not heuristic 18-21)
- `wall_clock_ms` between 30,000 and 90,000 (not 35-43s of fallback; real SOCP takes longer)
- `status` = `succeeded` (not `degraded`)

If output still shows `heuristic_fallback` after the filter, investigate second-order: NAV overlap still insufficient even at 350 funds? If so, flag for PR-A8 (Layer 3 correlation dedup) — don't try to fix in this PR.

### D.3 — Verification SQL post-build

```sql
SELECT mp.display_name,
       pcr.status,
       pcr.optimizer_trace->>'solver' as solver,
       pcr.optimizer_trace->>'status' as opt_status,
       (SELECT COUNT(*) FROM jsonb_object_keys(pcr.weights_proposed)) as n_weights,
       pcr.wall_clock_ms
FROM portfolio_construction_runs pcr
JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
WHERE pcr.started_at > NOW() - INTERVAL '10 minutes'
ORDER BY pcr.started_at DESC;
```

Expect all 3 rows to show `solver != 'heuristic_fallback'` and `n_weights >= 20`.

## Section E — What NOT to do

- Do NOT skip the `order_by instrument_id ASC` tiebreaker — non-deterministic Top-N breaks reproducibility
- Do NOT remove the `FundRiskMetrics.organization_id IS NULL` filter — global metrics are authoritative, org overrides are not wanted in construction universe
- Do NOT implement Layer 1 (quality quartile) or Layer 3 (correlation dedup) in this PR — scope creep; tackle in PR-A8 if needed
- Do NOT change `LAYER_2_TOP_N_PER_BLOCK=50` without empirical basis — 50 gives 7×50=350 which is within quant-architect's tractable band
- Do NOT convert `_load_universe_funds` to async generator or pagination — it's already bounded
- Do NOT touch frontend — the `degraded` status rendering is PR-A8
- Do NOT `# type: ignore` mypy errors — the StrategicAllocation join is straightforward SQLAlchemy
- Do NOT skip the `C.1` integration test — it's the smoke test that justifies the PR

## Section F — Deliverables checklist

- [ ] Branch `feat/pr-a7-universe-prefilter` from `main`
- [ ] `model_portfolios.py:_load_universe_funds` — Layer 0 + Layer 2 CTE
- [ ] `_run_construction_async:1859` updated to pass `profile`
- [ ] Status `degraded` path wired (Section B)
- [ ] Migration 0141 if CHECK constraint needs extending; else documented as "no migration"
- [ ] `test_load_universe_funds_prefilter.py` with 5+ tests (C.1-C.5)
- [ ] All existing wealth tests green
- [ ] `make lint` clean
- [ ] `make typecheck` clean (zero new `# type: ignore`)
- [ ] Smoke test (D.2) run against 3 portfolios; attach `optimizer_trace` output of each
- [ ] Commit message describes: Layer 0+2 cardinality reduction observed, 3 portfolios with CLARABEL real

## Reference files

- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\routes\model_portfolios.py:1818` (`_run_construction_async`)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\routes\model_portfolios.py:1859` (caller of `_load_universe_funds`)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\routes\model_portfolios.py:2300` (`_load_universe_funds` definition)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\models\allocation.py` (StrategicAllocation model)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\services\quant_queries.py:1092` (`compute_fund_level_inputs` — do NOT modify, just understand input contract)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\workers\construction_run_executor.py:579` (`execute_construction_run` — Section B may need edit here for status)

## Constants

```python
# backend/app/domains/wealth/routes/model_portfolios.py
LAYER_2_TOP_N_PER_BLOCK = 50  # ≈ 7 blocks × 50 = 350 CLARABEL inputs
```

## Expected cardinality after filter (current DB state)

| Block | Current count | After Layer 2 (top 50) |
|---|---|---|
| na_equity_large | 1,719 | 50 |
| fi_us_aggregate | 623 | 50 |
| alt_real_estate | 394 | 50 |
| fi_us_high_yield | 255 | 50 |
| na_equity_small | 123 | 50 |
| cash | 44 | 44 (cap not hit) |
| alt_gold | 26 | 26 (cap not hit) |
| **Total** | **3,184** | **~320** |

Target lands squarely in quant-architect's tractable band [200, 400].

---

**End of spec. Execute end-to-end. Report with: 3 portfolio rerun outputs + SQL of Section D.3 + test counts + commit SHA. Do NOT commit until live smoke test passes.**
