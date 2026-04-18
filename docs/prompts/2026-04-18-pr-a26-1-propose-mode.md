# PR-A26.1 — Propose Mode Optimizer + Endpoint + `run_mode` Column

**Date**: 2026-04-18
**Status**: P0 STRATEGIC — introduces optimizer "propose mode" that runs unconstrained by `strategic_allocation` bounds. Foundation for A26.2 (approval flow) and A26.3 (frontend review UI).
**Branch**: `feat/pr-a26-1-propose-mode`
**Predecessors merged**: A21 #207, A22 #209, A23 #210, A24 #212, A25 #213.

---

## Context — product decision

Per product owner (Andrei, 2026-04-18): CVaR limit is the **only mandatory human input** to the optimizer. IC views, pre-set block bands, and IC-block-caps are eliminated. The optimizer has maximum freedom subject only to:
1. `CVaR(w) ≤ cvar_limit` from `portfolio_calibration` (per profile)
2. `sum(w_i) = 1`, `0 ≤ w_i ≤ 1`
3. `w_i = 0` for blocks with `excluded_from_portfolio = true`

The `strategic_allocation` table stops acting as a pre-run IC constraint. It becomes the **Strategic IPS anchor** — the approved target + drift bands that govern rebalancing (populated by A26.2 approval flow). In propose mode, the optimizer **ignores** `strategic_allocation.(target_weight, min_weight, max_weight)` entirely.

Per-instrument 15% concentration cap is deferred to A26.2 (applies at realize/composition stage when mapping block weights to instruments). A26.1 is pure block-level propose.

BL views (Black-Litterman posterior with P/Ω matrices) are bypassed in propose mode via explicit flag — same code path as `legacy_historical_1y=True` already in production. Full BL deletion is deferred; A26.1 uses plan B (bypass not delete).

---

## Scope

**In scope:**
- `run_mode` column on `portfolio_construction_runs` (VARCHAR(20) NOT NULL DEFAULT 'realize', CHECK constraint IN ('realize', 'propose')).
- Optimizer `propose_mode: bool` flag in the entry point (`execute_construction_run` or sibling). When true:
  - Skip BL posterior step — use historical_1y μ prior + Ledoit-Wolf Σ directly.
  - Override `constraints.blocks[*].min_weight = 0` and `max_weight = 1` regardless of what `strategic_allocation` says (effective removal of that layer as a constraint).
  - Still honor `excluded_from_portfolio = true` → force `max_weight = 0` for that block.
  - Still run the 4-phase cascade (max return → robust → min variance → min CVaR fallback).
- Hybrid drift band derivation: `drift = max(0.02, 0.15 × target_weight)`. Applied symmetrically: `drift_min = max(0, target - drift)`, `drift_max = min(1, target + drift)`.
- Proposal payload in `cascade_telemetry`:
  ```json
  {
    "proposed_bands": [
      {"block_id": "na_equity_large", "target_weight": 0.32, "drift_min": 0.272, "drift_max": 0.368, "rationale": "..."}
    ],
    "proposal_metrics": {
      "expected_return": 0.087,
      "expected_cvar": 0.029,
      "expected_sharpe": 1.4,
      "target_cvar": 0.03,
      "cvar_feasible": true
    },
    "run_mode": "propose",
    "winner_signal": "proposal_ready" | "proposal_cvar_infeasible"
  }
  ```
- `WinnerSignal.PROPOSAL_READY` + `WinnerSignal.PROPOSAL_CVAR_INFEASIBLE` enum values.
- New endpoint `POST /portfolio/profiles/{profile}/propose-allocation` → 202 + `job_id` + SSE URL. Async job dispatches `execute_construction_run(..., propose_mode=True)`.
- SSE event types: `propose_started`, `optimizer_started`, `optimizer_phase_complete` (per phase), `propose_ready` OR `propose_cvar_infeasible`, `completed`.
- Fetch endpoint `GET /portfolio/profiles/{profile}/latest-proposal` returns the most recent `run_mode='propose'` run for the (org, profile) combo, ordered by `requested_at DESC`.
- Unit + integration tests.
- Template completeness + block coverage gates (from A25/A22) still fire first — propose mode uses same pre-run gates as realize.

**Out of scope:**
- Do NOT introduce per-instrument 15% cap. That is A26.2.
- Do NOT introduce `override_min/override_max` columns. That is A26.2.
- Do NOT implement approval flow, `allocation_approvals` table, or Strategic snapshot. That is A26.2.
- Do NOT touch frontend. That is A26.3.
- Do NOT delete BL code. Bypass via `propose_mode` flag only.
- Do NOT touch realize-mode behavior beyond adding the `run_mode` column with default='realize'.
- Do NOT modify template completeness validator or coverage validator — they continue to fire in both modes.

---

## Execution Spec

### Section A — Alembic migration 0154: `run_mode` column + enum addition

**File:** `backend/app/core/db/migrations/versions/0154_portfolio_construction_run_mode.py`

Down_revision: `0153_canonical_allocation_template`.

Steps:

1. `ALTER TABLE portfolio_construction_runs ADD COLUMN run_mode VARCHAR(20) NOT NULL DEFAULT 'realize'`.
2. Add CHECK constraint: `CHECK (run_mode IN ('realize', 'propose'))`.
3. Create btree index `ix_pcr_run_mode_requested_at` on `(run_mode, requested_at DESC)` for the latest-proposal query.

Down: drop index, drop constraint, drop column.

**Acceptance:**
- `make migrate` up + down round-trip clean.
- Existing runs have `run_mode = 'realize'` (default applied retroactively to backfilled column).
- `SELECT DISTINCT run_mode FROM portfolio_construction_runs` returns at most `{'realize', 'propose'}`.

### Section B — Optimizer propose mode flag

**File:** `backend/quant_engine/optimizer_service.py` and `backend/app/domains/wealth/workers/construction_run_executor.py`.

Add `propose_mode: bool = False` parameter to `execute_construction_run` and downstream functions that need it.

Behavior when `propose_mode = True`:

1. **Statistical inputs stage:**
   - Force μ prior to `historical_1y` (skip BL posterior computation; no call to BL view integration). If memory confirms `legacy_historical_1y=True` is already the prod path, this may be already the default — verify and document.
   - Use Ledoit-Wolf Σ (already default).
   - `_load_ic_views(db, ...)` MUST not be called. If called incidentally, must return empty list without querying `portfolio_views` table.

2. **Constraints stage:**
   - For each block in the canonical template, build `BlockConstraint(block_id, min_weight=0.0, max_weight=1.0)` regardless of what `strategic_allocation` rows contain.
   - For blocks with `strategic_allocation.excluded_from_portfolio = true`, force `max_weight = 0.0` (preserved).
   - Do NOT read `target_weight`, `min_weight`, or `max_weight` from `strategic_allocation` rows.

3. **Cascade stage:**
   - Run the existing 4-phase CLARABEL cascade unchanged. All existing fallback logic (phase 2 robust, phase 3 min variance, phase 4 min CVaR) applies.
   - Determine `cvar_feasible`:
     - If the winning phase is `phase_1_ru_max_return` or `phase_2_ru_robust`, feasible=True.
     - If the cascade fell through to min-CVaR fallback (phase 4), feasible=False (the proposal's achievable CVaR exceeds the target, but it's the best possible given the universe).

4. **Band derivation:**
   - For each block with `target > 0`, compute `drift = max(0.02, 0.15 * target)`.
   - `drift_min = max(0.0, target - drift)`.
   - `drift_max = min(1.0, target + drift)`.
   - Include rationale string per block: short natural-language one-liner describing the optimizer's reasoning (e.g., "Maximum Sharpe contribution at 32% weight given CVaR 3% and Ledoit-Wolf Σ"). Keep generic — per-block narrative detail is A26.3 concern.

5. **Telemetry output:**
   - Populate `cascade_telemetry.proposed_bands` as list per Section "Proposal payload" above.
   - Populate `cascade_telemetry.proposal_metrics`.
   - Set `cascade_telemetry.winner_signal` to `proposal_ready` (feasible) or `proposal_cvar_infeasible` (fallback).
   - Persist with `run_mode = 'propose'`.

**Unit tests** (`backend/tests/quant_engine/test_propose_mode.py`):
- Mock `execute_construction_run(propose_mode=True)`. Assert `_load_ic_views` is not called (spy/mock).
- Seed `strategic_allocation` with target=0.5/min=0.4/max=0.6 on `na_equity_large`. Run propose. Assert proposal's `na_equity_large` weight is NOT constrained to [0.4, 0.6] — can be any value.
- Seed one block with `excluded_from_portfolio = true`. Assert that block has weight=0 in proposal.
- Seed CVaR limit at an infeasibly low value. Assert `winner_signal = 'proposal_cvar_infeasible'` and `cvar_feasible = false`.
- Hybrid band derivation: target=0.05 → drift=0.02 (floor), drift_min=0.03, drift_max=0.07. Target=0.40 → drift=0.06 (15% rel), drift_min=0.34, drift_max=0.46.

### Section C — Endpoint + SSE

**File:** `backend/app/domains/wealth/routes/model_portfolios.py` (or wherever profile-scoped routes live — grep first).

New route:
```python
@router.post("/profiles/{profile}/propose-allocation", status_code=202)
async def propose_allocation(profile: str, db: AsyncSession, ...) -> JobCreatedResponse:
    ...
```

Validates `profile ∈ {'conservative', 'moderate', 'growth'}`. Dispatches `execute_construction_run(db, profile=profile, organization_id=..., propose_mode=True)` as a background job via the existing job infrastructure (SSE bridge). Returns `{job_id, sse_url}`.

SSE bridge must emit the listed event types (from existing `_publish_event_sanitized` helper) with payload shapes matching the operator-facing event types used by realize mode. Do NOT invent new event machinery; reuse.

Fetch endpoint:
```python
@router.get("/profiles/{profile}/latest-proposal", response_model=LatestProposalResponse)
async def latest_proposal(profile: str, db: AsyncSession, ...) -> LatestProposalResponse:
    ...
```

Returns the most recent `run_mode='propose'` run for the (org, profile) combo. 404 if no propose run exists yet. Pydantic response model includes run_id, requested_at, winner_signal, proposed_bands list, proposal_metrics.

**Integration tests** (`backend/tests/wealth/test_propose_allocation_endpoint.py`):
- POST endpoint → 202 + job_id. Wait for SSE completion. Assert final run has `run_mode='propose'`.
- GET latest-proposal after a run → returns the run's proposed_bands + metrics.
- GET before any propose run → 404.
- Excluded block is zeroed in proposal.
- CVaR infeasibility surfaces `proposal_cvar_infeasible` in SSE event + response.

### Section D — Schema / enum updates

**Files:**
- `backend/app/domains/wealth/schemas/construction.py` (or wherever `WinnerSignal` lives): add `PROPOSAL_READY = "proposal_ready"` and `PROPOSAL_CVAR_INFEASIBLE = "proposal_cvar_infeasible"`.
- Add Pydantic models: `ProposedBand(block_id, target_weight, drift_min, drift_max, rationale)`, `ProposalMetrics(expected_return, expected_cvar, expected_sharpe, target_cvar, cvar_feasible)`, `LatestProposalResponse(run_id, requested_at, winner_signal, proposed_bands, proposal_metrics)`, `JobCreatedResponse(job_id, sse_url)`.

No enum migration needed if `winner_signal` is stored free-form in JSONB.

### Section E — Pre-run gates still fire in propose mode

Verify in `construction_run_executor` that the order is:
1. Template completeness (A25) — fires for both realize and propose modes.
2. Block coverage (A22) — fires for both realize and propose modes.
3. Then branch on `propose_mode`.

Propose mode must still fail with `template_incomplete` if canonical template is broken, and still fail with `block_coverage_insufficient` if a non-excluded block has zero approved candidates. These are universe/governance gates, not optimizer constraints.

**Acceptance:** existing A25/A22 integration tests still pass. Propose mode against an org with incomplete template aborts with `template_incomplete`.

---

## Ordering inside this PR

A → B → C → D → E. One commit per Section.

## Global guardrails

- `CLAUDE.md` rules. Async-first, RLS via `SET LOCAL`, `expire_on_commit=False`, `lazy="raise"`.
- No new Python dependencies.
- `make check` green (tolerating pre-existing lint).
- One commit per Section.
- Do NOT touch: candidate_screener (realize-only concern), frontend (A26.3), `strategic_allocation` schema (A26.2), BL code itself (bypass only, no deletion).

## Final report format

1. Migration 0154 up/down round-trip + distinct run_mode values post-migration.
2. Unit test output (propose mode mocks + band derivation).
3. Integration test output (endpoint + SSE + latest-proposal).
4. Dev DB smoke:
   - `POST /portfolio/profiles/conservative/propose-allocation` for org `403d8392-...`.
   - Wait for SSE completion.
   - `GET /portfolio/profiles/conservative/latest-proposal`.
   - Paste the returned proposal payload. Expected: 18 blocks in `proposed_bands`, `proposal_metrics.cvar_feasible=true` if coverage gate is passed (operator must have imported candidates for na_equity_value first — if coverage still insufficient, propose will abort at coverage gate; report that outcome).
5. Regression: run A25 template gate test + A22 coverage gate test against the branch. Assert no regression.
6. List any deviations from spec discovered during implementation.
