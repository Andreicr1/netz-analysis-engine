# PR-A14 — Universe Coverage Gate & Block Weight Renormalization

**Branch:** `feat/pr-a14-universe-coverage-gate` (cut from `main` post-PR-A12.4 at commit `08ca302a`).
**Estimated effort:** ~3-4h Opus.
**Predecessors:** PR-A12.4 #197 (winner-selection correctness).
**Parallel:** PR-A13.2 (frontend live preview) — zero code overlap.

---

## Section A — Problem statement

Post PR-A12.4, all 3 canonical portfolios degrade with `cascade_summary=phase_3_min_cvar_above_limit` at their institutional default CVaR limits. The A12.4 fix made the signal honest, but revealed a deeper structural issue: **universe narrowness**.

### A.1 Empirical evidence (from `docs/ux/logs.txt`)

```
Conservative:
  total_blocks=11, covered_blocks=6  (45% blocks empty)
  target_sum=0.6103   (optimizer targets only 61% of 1.0)
  Missing: em_equity, fi_us_treasury, na_equity_value, fi_us_tips, dm_europe_equity

Moderate (Balanced Income):
  total_blocks=14, covered_blocks=6  (57% blocks empty)
  target_sum=0.5178

Dynamic Growth:
  total_blocks=14, covered_blocks=7  (50% blocks empty)
  target_sum=0.4893
```

### A.2 Two compounding issues

**Issue 1 — Deployment gap.** LP constraint is `sum(w) = target_sum` where `target_sum = sum(covered_block.target_weight)`. For Conservative, `target_sum=0.6103`, meaning the LP allocates 61% of notional. The remaining 39% sits as uninvested capital with no cash bucket, no fallback — just missing from the portfolio. Operators looking at "weights deployed" see 61%, but there's no current UX signal explaining why.

**Issue 2 — Universe floor elevation.** Phase 3 `min_achievable_cvar` is computed only over the covered blocks and their fund intersection. With half the blocks empty, the remaining universe is heavily skewed (e.g., Conservative's remaining blocks are dominated by equity because the FI diversifiers are missing). The min-CVaR portfolio built from the narrow universe has a higher tail floor than if the universe were complete. That's why Conservative's floor is 6.5% instead of the 2-3% typical for institutional Conservative with broad FI coverage.

Both issues have the same root cause: **the approved universe (`instruments_org`) doesn't have funds for all the strategic allocation blocks.** PR-A14 addresses both with a combined fix: internal renormalization for deployment + explicit coverage signal for operator transparency.

---

## Section B — Design decision: renormalize + signal

Three candidate approaches considered (full memo in `memory/project_a12_3_wiring_learnings.md` follow-up):

- **(A) Renormalize block weights silently** → preserves deployment but hides coverage gap
- **(B) Block build pre-flight when coverage < threshold** → violates always-solvable principle (`feedback_optimizer_always_solvable.md`)
- **(C) Renormalize + surface coverage signal** → preserves deployment, surfaces gap transparently

**Lock (C).** Two-part fix:

1. **Backend renormalization:** when a strategic block has no covered funds, redistribute its `target_weight` proportionally to covered blocks (weighted by their existing targets). LP receives `target_sum = 1.0` always. Operators get 100% deployment.

2. **Coverage telemetry:** add `cascade_telemetry.coverage` block with `{pct_covered, missing_blocks[], covered_blocks[]}`. Add secondary `operator_signal.secondary` when coverage < 0.85 with `kind="universe_coverage_insufficient"` + recommendation (expand universe).

Primary signal (`cvar_limit_below_universe_floor`) stays on the `operator_signal` root; secondary is additive. Frontend (future PR-A14.1 or inherited by A13.2 automatically) renders both.

---

## Section C — Implementation

### C.1 Renormalization in `_run_construction_async`

Locate the block-weight assembly in `backend/app/domains/wealth/routes/model_portfolios.py` (search `target_sum` or `active_blocks`). Current logic:

```python
# Before (simplified)
target_sum = sum(block.target_weight for block in strategic_allocations if block.id in covered_block_ids)
active_blocks = [{"id": b.id, "min": b.min_weight, "max": b.max_weight} for b in covered]
# LP constraint: sum(w) == target_sum
```

New logic:

```python
# After — renormalize covered blocks to sum to 1.0
raw_covered_sum = sum(block.target_weight for block in strategic_allocations if block.id in covered_block_ids)
if raw_covered_sum <= 0:
    raise ValueError("Universe has no covered blocks — cannot construct")

scale_factor = 1.0 / raw_covered_sum
active_blocks = []
for b in strategic_allocations:
    if b.id not in covered_block_ids:
        continue
    active_blocks.append({
        "id": b.id,
        "min": float(b.min_weight) * scale_factor,
        "max": float(b.max_weight) * scale_factor,
        "target": float(b.target_weight) * scale_factor,   # scaled target for telemetry; LP doesn't use
        "renormalized_from": float(b.target_weight),
    })
# LP constraint: sum(w) == 1.0 (pass target_sum=1.0 or drop the constraint entirely since blocks sum to 1.0 via their max bounds)
```

**Verify the LP constraint shape** in `optimizer_service.py` — it might be `sum(w) == target_sum` or `sum(w) == 1.0`. The renormalization must be consistent. If LP currently uses `target_sum`, change to hardcoded `1.0` after renormalization. If LP uses `1.0` already, the `target_sum` was only passed for logging — just update the computation.

**Edge case:** if `raw_covered_sum > 1.0` (unlikely but possible if strategic weights overlap or were defined incorrectly), scale_factor < 1.0 still works — renormalization preserves ratios.

**Edge case:** `covered_block_ids` is empty → no portfolio possible. Return `upstream_heuristic` with `operator_signal.kind="universe_coverage_insufficient"` and empty weights. Do NOT proceed to LP (invariant violation otherwise).

### C.2 Coverage telemetry in cascade_telemetry

Extend the payload per PR-A11 section `cascade_telemetry` JSONB shape. Add a new top-level key:

```python
coverage = {
    "pct_covered": round(raw_covered_sum, 4),              # original sum before renormalization
    "n_total_blocks": len(strategic_allocations),
    "n_covered_blocks": len(covered_block_ids),
    "covered_blocks": sorted(covered_block_ids),
    "missing_blocks": sorted(block.id for block in strategic_allocations if block.id not in covered_block_ids),
    "renormalization_scale": round(scale_factor, 4),
}
```

### C.3 Secondary operator signal

Current `operator_signal` is a single dict with `kind`, `binding`, `message_key`. Extend to support a secondary (non-blocking) signal:

```python
operator_signal = {
    "kind": "cvar_limit_below_universe_floor" | "feasible" | ...,  # primary (unchanged)
    "binding": "risk_budget" | null,
    "message_key": "...",
    "secondary": {                                                  # NEW — optional
        "kind": "universe_coverage_insufficient",
        "pct_covered": 0.61,
        "missing_blocks_count": 5,
        "message_key": "expand_universe_recommended",
    } if coverage["pct_covered"] < 0.85 else None,
}
```

**Threshold:** 0.85 (85% covered). Below that, surface secondary signal. Operators with >95% coverage see nothing (implicit pass). Between 85% and 100% is acceptable — institutional target is 100% but gaps are tolerable.

This is a shape extension to the `OperatorSignal` TypeScript interface (A13 types) — backward compatible (new optional field).

### C.4 Smart-backend / dumb-frontend translation keys

New translation keys required (A13.2 auto-consumes):

| Key | EN | PT |
|---|---|---|
| `coverage.insufficient_warning` | Your approved universe covers only {pct}% of this profile's target allocation. {n} blocks have no funds. | Seu universo aprovado cobre apenas {pct}% da alocação-alvo deste perfil. {n} blocos não têm fundos. |
| `coverage.recommendation_expand` | Import funds into the missing blocks to unlock a deeper universe. | Importe fundos para os blocos ausentes para desbloquear um universo mais amplo. |
| `coverage.recommendation_open_universe` | Open Universe | Abrir Universo |

---

## Section D — Tests

### D.1 Unit tests

`backend/tests/wealth/test_universe_coverage_gate.py`:

- `test_full_coverage_no_secondary_signal`: seed a universe with funds in all 11 Conservative blocks → `coverage.pct_covered == 1.0`, `operator_signal.secondary is None`
- `test_61_percent_coverage_renormalizes`: seed Conservative with 6 covered blocks → `coverage.pct_covered == 0.6103`, LP receives renormalized `sum(w) == 1.0`, secondary signal present
- `test_missing_blocks_enumerated`: assert `coverage.missing_blocks` contains exactly the 5 uncovered block IDs, sorted
- `test_coverage_below_85_triggers_secondary`: at 0.80 coverage → secondary signal present with `kind="universe_coverage_insufficient"`
- `test_coverage_above_85_no_secondary`: at 0.90 coverage → secondary signal None
- `test_empty_universe_signals_upstream_heuristic`: zero covered blocks → no LP call, upstream_heuristic signal, empty weights, status=degraded
- `test_renormalization_preserves_block_ratios`: verify that if block A had 2× the target weight of block B pre-normalization, it still has 2× post-normalization

### D.2 Integration test (live-DB)

Extend `backend/tests/integration/test_construction_cvar_invariant.py` (added in A12.4):

- `test_conservative_coverage_matches_log`: trigger Conservative build → `cascade_telemetry.coverage.pct_covered == 0.6103 ± 1e-3` (matches logs.txt empirical)
- `test_growth_coverage_matches_log`: similar, 0.4893
- `test_moderate_coverage_matches_log`: 0.5178
- `test_lp_sum_constraint_equals_one_post_renormalization`: assert `sum(weights_proposed.values()) == 1.0 ± 1e-4` (currently delivers 0.61 for Conservative → this test MUST fail pre-fix)

### D.3 Expected smoke result post-fix

| Profile | pre-A14 target_sum | post-A14 weights_sum | coverage.pct | secondary.kind |
|---|---|---|---|---|
| Conservative | 0.61 | **1.00** | 0.61 | universe_coverage_insufficient |
| Moderate | 0.52 | **1.00** | 0.52 | universe_coverage_insufficient |
| Growth | 0.49 | **1.00** | 0.49 | universe_coverage_insufficient |

**Bonus observable:** Phase 3 `min_achievable_cvar` may DECREASE after renormalization (because covered blocks now carry the full notional, LP has more to work with). If so, that's a secondary win — operator's floor gap narrows. Not required, just observe and log.

### D.4 Regression check — A12.4 invariant

After renormalization, re-run the A12.4 `test_phase_winner_invariant` harness. The winner-selection logic MUST remain correct: Phase 1 with delivered CVaR > limit still falls to Phase 3. No behavior change expected but verify.

---

## Section E — Pass criteria

| # | Criterion | How verified |
|---|---|---|
| 1 | `sum(weights_proposed.values()) == 1.0` for all 3 canonical portfolios | integration test |
| 2 | `cascade_telemetry.coverage` populated with pct_covered, missing_blocks, covered_blocks | unit test + SQL |
| 3 | `operator_signal.secondary.kind == "universe_coverage_insufficient"` for all 3 (coverage < 0.85) | SQL |
| 4 | Renormalization preserves block ratios (unit test) | unit |
| 5 | Empty universe → upstream_heuristic, no LP call | unit |
| 6 | A12.4 winner-selection invariant still holds | integration regression |
| 7 | Frontend auto-renders secondary signal (via existing `translateOperatorSignalKind` + new keys) | Playwright screenshot |
| 8 | Full sweep green | pytest + CI |

Per `feedback_dev_first_ci_later.md`: live-DB smoke is the merge gate.

---

## Section F — Out of scope

- Changing `instruments_org` auto-import logic (PR-A6 already handles; A14 just surfaces the gap)
- Operator-facing "Import funds to missing blocks" bulk action UI (future)
- Changing strategic allocation block definitions (those are institutional policy, not engine concern)
- Fixing `factor_returns_fetch_failed` from `docs/ux/logs.txt:245` (PR-A15, separate)
- Attribution log spam (PR-A16, separate)
- Frontend cascade_telemetry coverage panel visualization (may be A14.1 follow-up if rendering gets involved; A13.2's existing signal banner inherits the new secondary key for free)
- Tightening SCS solver tolerance (A12.4 gate makes it moot)
- μ prior calibration (separate sprint)

---

## Section G — Open decisions for implementer (flag before locking)

1. **Renormalization floor (scale_factor bound):** if `raw_covered_sum` is extremely small (e.g., 0.05 — only 5% of blocks covered), scale_factor becomes 20×. That can violate individual block max_weight bounds (e.g., a block capped at 25% gets scaled to 500% target). Decision: when `scale_factor > 5.0` (i.e., coverage < 20%), hard-fail with upstream_heuristic — universe too narrow to build a meaningful portfolio. Lock 5.0 threshold unless Andrei objects.

2. **Secondary signal shape — `OperatorSignal.secondary` vs array of signals:** the A13 TypeScript interface has a single primary signal. Extending with optional `secondary` is simpler than refactoring to `signals: OperatorSignal[]`. Lock `secondary: OperatorSignal | null` as a simple optional field.

3. **Coverage threshold (0.85):** institutional rule of thumb. If empirical evidence post-ship shows that most orgs hit 0.80-0.95 naturally, lower threshold to 0.70 to avoid noise. For now, lock 0.85.

All three are pre-locked — do NOT wait for Andrei to confirm. Document the rationale in the PR body so future PRs can re-tune based on operator telemetry.

---

## Section H — Commit & PR

**Branch:** `feat/pr-a14-universe-coverage-gate`

**Commit message:**

```
feat(wealth): universe coverage gate + block weight renormalization (PR-A14)

Pre-A14: strategic allocations with missing blocks (no funds in approved
universe) caused the LP to target only sum(covered_block.target_weight),
leaving up to 39% of operator notional undeployed AND inflating the
universe tail floor because the LP operated on a narrow asset set.

Fix 1 — Renormalization: covered blocks' weights rescaled by
1/raw_covered_sum so LP receives sum(w) == 1.0 always. Block ratios
preserved. If coverage < 20%, hard-fail to upstream_heuristic — universe
too narrow to meaningfully construct.

Fix 2 — Coverage telemetry: cascade_telemetry.coverage populated with
pct_covered, n_total_blocks, n_covered_blocks, covered_blocks[],
missing_blocks[], renormalization_scale.

Fix 3 — Secondary operator signal: operator_signal.secondary emits
{kind="universe_coverage_insufficient", pct_covered, missing_blocks_count}
when coverage < 0.85. Primary signal (risk budget / below-floor) unchanged.

Closes the 61%/52%/49% deployment gap on Conservative / Moderate / Growth
canonical portfolios and surfaces the universe gap to operators without
blocking the always-solvable cascade.

Frontend (PR-A13.2 or follow-up) auto-inherits via existing
translateOperatorSignalKind pipeline + new translation keys.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

**PR title:** `feat(wealth): universe coverage gate + renormalization (PR-A14)`

**PR body:** include before/after table for the 3 canonical portfolios, coverage JSONB example, screenshot of rendered secondary signal in Builder.

---

**End of spec. Execute exactly. Renormalization is math, coverage is telemetry, secondary signal is UX — three small changes, one institutional unblock.**
