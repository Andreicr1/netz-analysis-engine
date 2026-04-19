# PR-A26.2 — Approval Flow + Strategic IPS Refactor + Override Overrides + Realize Gate

**Date**: 2026-04-18
**Status**: P0 STRATEGIC — completes the propose-approve-realize loop. A26.1 ships propose; A26.2 ships approval + overrides + realize gate.
**Branch**: `feat/pr-a26-2-approval-flow`
**Predecessors merged**: A21 #207, A22 #209, A23 #210, A24 #212, A25 #213, A26.0 #215, #216 label patch, A26.1 #214.

---

## Context — product model

After this PR the full flow is:

1. Operator triggers `POST /portfolio/profiles/{profile}/propose-allocation` (A26.1 — done).
2. Optimizer returns proposed bands + metrics in `portfolio_construction_runs` with `run_mode='propose'`.
3. Operator reviews via `GET /latest-proposal`.
4. Operator either:
   - **Approves atomically** via `POST /approve-proposal/{run_id}` → bands snapshotted to `strategic_allocation`; becomes the **Strategic IPS anchor**.
   - **Rejects / modifies** by setting ad-hoc `override_min/override_max` on one or more blocks via `POST /set-override`, then re-proposing (operator disagrees with optimizer's concentration in one block → constrain it, re-run, see the consequence on E[r] and other blocks).
5. Realize mode (future construction runs that allocate to instruments) refuses-to-run until a Strategic has been approved. Once approved, realize composes the 18-block weights into per-instrument holdings subject to a 15% per-instrument concentration cap.
6. Rebalance triggers (existing `drift_check` worker) compare actual holdings drift vs Strategic `(target_weight, drift_min, drift_max)`. Alerts fire when actual drifts outside the approved band.

**Strategic IPS = approved snapshot of a propose run.** Not a pre-run IC constraint. Governance without bureaucracy.

---

## Scope

**In scope (7 sections):**
- Migration 0155: `strategic_allocation` schema refactor — drop `min_weight, max_weight`; add `drift_min, drift_max, override_min, override_max, approved_from_run_id, approved_at, approved_by`; all nullable.
- `allocation_approvals` table (global, no RLS — audit log of who approved what when).
- `POST /portfolio/profiles/{profile}/approve-proposal/{run_id}` — atomic snapshot of proposed bands into the 18 strategic_allocation rows; inserts allocation_approvals row; marks prior approval `superseded_at`.
- `POST /portfolio/profiles/{profile}/set-override` — body `{block_id, override_min, override_max, rationale}`. Writes override on single strategic_allocation row. Does NOT affect live portfolios; takes effect on next propose run.
- A26.1 optimizer propose mode update: respect `override_min/override_max` when set on any block. Pass as constraints to CLARABEL.
- `execute_construction_run` realize mode: refuse-to-run if no approved Strategic for the (org, profile). Emit `winner_signal='no_approved_allocation'`.
- Per-instrument 15% cap at realize composition stage. If composition would require any single instrument > 15%, fail with explicit error signaling which block/instrument breached.
- `WinnerSignal.NO_APPROVED_ALLOCATION`, `WinnerSignal.INSTRUMENT_CONCENTRATION_BREACH`.
- Unit + integration tests.

**Out of scope:**
- Frontend (A26.3).
- BL code deletion (still plan B bypass).
- New drift thresholds — `drift_check` worker already exists and will be rewired in A26.4 (separate sprint).
- Modification of A22 coverage gate or A25 template gate — continue to fire unchanged.
- Rebalance action generation / trade tickets (separate sprint).
- Approval of proposals with `winner_signal='proposal_cvar_infeasible'` — require explicit operator confirmation parameter for this PR. If not confirmed, endpoint rejects.

---

## Execution Spec

### Section A — Alembic migration 0155: `strategic_allocation` refactor

**File:** `backend/app/core/db/migrations/versions/0155_strategic_allocation_approved_state.py`

Down_revision: `0154_portfolio_construction_run_mode`.

Transactional. Steps:

1. **ADD columns:**
   ```sql
   ALTER TABLE strategic_allocation
     ADD COLUMN drift_min NUMERIC(6,4),
     ADD COLUMN drift_max NUMERIC(6,4),
     ADD COLUMN override_min NUMERIC(6,4),
     ADD COLUMN override_max NUMERIC(6,4),
     ADD COLUMN approved_from_run_id UUID,
     ADD COLUMN approved_at TIMESTAMPTZ,
     ADD COLUMN approved_by TEXT;
   ```

2. **DROP legacy optimizer-bound columns:**
   ```sql
   ALTER TABLE strategic_allocation
     DROP COLUMN min_weight,
     DROP COLUMN max_weight;
   ```
   `target_weight` is preserved (becomes "approved target" semantic — NULL until first approval).

3. **Backfill existing rows to NULL approved state:**
   - The 54 existing rows (18 blocks × 3 profiles × 1 org) were populated by A25 trigger with `target_weight=NULL`. Leave them as-is. `approved_at IS NULL` means "never approved — realize mode must refuse".
   - If any row has non-NULL `target_weight` from older seeds, do NOT clear it — it becomes a soft historical marker (can be cleared manually by operator if desired).

4. **Add index for efficient realize-mode "is approved?" check:**
   ```sql
   CREATE INDEX ix_strategic_allocation_approval_state
     ON strategic_allocation (organization_id, profile, approved_at);
   ```

5. **Add CHECK constraint: drift and override must be internally consistent when set:**
   ```sql
   ALTER TABLE strategic_allocation
     ADD CONSTRAINT chk_drift_bounds
       CHECK (drift_min IS NULL OR drift_max IS NULL OR drift_min <= drift_max),
     ADD CONSTRAINT chk_override_bounds
       CHECK (override_min IS NULL OR override_max IS NULL OR override_min <= override_max);
   ```

Down-migration: reverse each step in reverse order. Re-create `min_weight, max_weight` columns as nullable (cannot restore original values — document warning in down function).

**Acceptance:**
- `make migrate` up + down round-trip clean.
- Post-migration: `SELECT approved_at, drift_min FROM strategic_allocation` returns NULL for all rows.
- `make check` green.

### Section B — `allocation_approvals` table

**File:** same migration 0155.

```sql
CREATE TABLE allocation_approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL,  -- no FK; historical integrity via superseded_at
  organization_id UUID NOT NULL,
  profile VARCHAR(20) NOT NULL,
  approved_by TEXT NOT NULL,
  approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  superseded_at TIMESTAMPTZ,  -- NULL = currently active
  cvar_at_approval NUMERIC(6,4),  -- snapshot of the target CVaR at approval time
  expected_return_at_approval NUMERIC(8,6),  -- snapshot of E[r]
  cvar_feasible_at_approval BOOLEAN NOT NULL DEFAULT TRUE,
  operator_message TEXT
);
CREATE INDEX ix_allocation_approvals_org_profile_active
  ON allocation_approvals (organization_id, profile, superseded_at)
  WHERE superseded_at IS NULL;
```

Global table (no RLS) — audit history is admin-visible.

**Acceptance:** table exists, at most one row per (org, profile) with `superseded_at IS NULL` after migration (but initially empty — no approvals yet).

### Section C — Approval endpoint

**File:** `backend/app/domains/wealth/routes/model_portfolios.py` (attach to `portfolio_meta_router`).

```python
@router.post("/profiles/{profile}/approve-proposal/{run_id}", status_code=200)
async def approve_proposal(
    profile: str,
    run_id: UUID,
    body: ApproveProposalRequest,  # {confirm_cvar_infeasible: bool = False, operator_message: str | None = None}
    db: AsyncSession,
    ...
) -> ApprovalResponse:
    ...
```

Transaction steps (ALL atomic — one transaction, one commit):

1. Fetch the run. 404 if not found, not belonging to org, or `run_mode != 'propose'`.
2. Check `winner_signal`:
   - `proposal_ready` → proceed.
   - `proposal_cvar_infeasible` → proceed only if `body.confirm_cvar_infeasible=True`. Otherwise 409 Conflict with message "proposal was infeasible — set confirm_cvar_infeasible=true to approve anyway".
   - Any other → 409 Conflict.
3. Parse `cascade_telemetry.proposed_bands` (list of 18 blocks). Assert exactly 18 blocks covering the canonical set (template completeness already enforced by A25 gate). If not 18, 500 Internal Error (bug in propose run).
4. For each proposed band, UPDATE the corresponding `strategic_allocation` row:
   ```sql
   UPDATE strategic_allocation
      SET target_weight = :target,
          drift_min = :drift_min,
          drift_max = :drift_max,
          approved_from_run_id = :run_id,
          approved_at = now(),
          approved_by = :approver
    WHERE organization_id = :org
      AND profile = :profile
      AND block_id = :block_id
   ```
   Do NOT touch `override_min, override_max` — those are operator-set and persist across approvals.
5. Mark any prior active approval for this (org, profile) as superseded:
   ```sql
   UPDATE allocation_approvals SET superseded_at = now()
    WHERE organization_id = :org AND profile = :profile AND superseded_at IS NULL
   ```
6. Insert new `allocation_approvals` row with:
   - `run_id, organization_id, profile, approved_by = X-DEV-ACTOR or Clerk user id`
   - `cvar_at_approval = cascade_telemetry.proposal_metrics.target_cvar`
   - `expected_return_at_approval = cascade_telemetry.proposal_metrics.expected_return`
   - `cvar_feasible_at_approval = cascade_telemetry.proposal_metrics.cvar_feasible`
   - `operator_message = body.operator_message`
7. Return `ApprovalResponse { approval_id, run_id, approved_at, strategic_snapshot: [18 blocks with target+drift] }`.

**Acceptance tests** (`backend/tests/wealth/test_approve_proposal_endpoint.py`):
- Approve a proposal_ready run → strategic_allocation rows updated, allocation_approvals row inserted, prior approval marked superseded.
- Approve a proposal_cvar_infeasible run without confirm flag → 409.
- Approve a proposal_cvar_infeasible run with confirm flag → success, `cvar_feasible_at_approval=false` recorded.
- Approve a non-propose run (run_mode='realize') → 404 or 409 (depending on which check fires first; be explicit in spec).
- Approve across orgs → RLS blocks cross-tenant access.

### Section D — Override endpoint + optimizer integration

**File:** same router + `quant_engine/optimizer_service.py` propose path.

**Endpoint:**
```python
@router.post("/profiles/{profile}/set-override", status_code=200)
async def set_override(
    profile: str,
    body: SetOverrideRequest,  # {block_id, override_min: float | None, override_max: float | None, rationale: str | None}
    db: AsyncSession,
    ...
) -> StrategicAllocationRow:
    ...
```

Behavior:
- Validate block_id is canonical (is_canonical=true in allocation_blocks).
- Validate `0 <= override_min <= override_max <= 1` when both set. Allow setting just one side (e.g., only override_max).
- UPDATE the single row.
- Return the updated row.

**Optimizer integration (A26.1 update):**

In `construction_run_executor.py` propose mode (Section B of A26.1), when building block constraints:
```python
# Before A26.2:
blocks.append(BlockConstraint(block_id=b, min_weight=0.0, max_weight=1.0))

# After A26.2:
override = await _load_override(db, org, profile, b)
min_w = override.override_min if override.override_min is not None else 0.0
max_w = override.override_max if override.override_max is not None else 1.0
if excluded: min_w = max_w = 0.0  # excluded trumps override
blocks.append(BlockConstraint(block_id=b, min_weight=min_w, max_weight=max_w))
```

Overrides apply to propose mode runs. Realize mode reads approved Strategic separately (Section E).

**Acceptance tests** (`test_set_override_endpoint.py` + extensions to `test_propose_mode.py`):
- Set override on na_equity_large with override_max=0.15 → propose run honors cap (resulting target ≤ 0.15).
- Set override with override_min > override_max → 400.
- Excluded block: override has no effect (block still zeroed).
- Override persists across runs until explicitly cleared (set to NULL via endpoint).

### Section E — Realize mode gate

**File:** `construction_run_executor.py`

Add as a pre-cascade gate in realize mode (propose_mode=False), AFTER template completeness (A25) and coverage (A22) but BEFORE optimizer:

```python
if not propose_mode:
    approved_count = await _count_approved_blocks(db, org, profile)
    if approved_count < 18:  # not all blocks have approved_at set
        raise NoApprovedAllocationError(...)
```

`_count_approved_blocks`:
```sql
SELECT COUNT(*) FROM strategic_allocation
 WHERE organization_id = :org AND profile = :profile
   AND approved_at IS NOT NULL
```

On error, persist run with `status='failed'`, `winner_signal='no_approved_allocation'`, operator message explaining that operator must run propose+approve cycle first.

Add `WinnerSignal.NO_APPROVED_ALLOCATION = 'no_approved_allocation'`.

**Acceptance test:** dispatch realize run (existing pr_a12_smoke.py pattern) against org without approval → fails with `winner_signal='no_approved_allocation'`. After approving via Section C, realize run succeeds.

### Section F — Per-instrument 15% cap at composition

**File:** `candidate_screener.py` or wherever block→instrument composition happens (grep `compose`, `instrument_weights`, `weights_proposed`).

After the optimizer returns block-level weights, the composition layer distributes each block's weight across approved instruments in that block. Apply a **hard 15% per-instrument cap**:

- For each block `b` with `block_weight = w_b`:
  - Count approved instruments in that block: `n_b`.
  - Max realizable per-instrument weight: `15% absolute`.
  - Minimum instruments needed: `ceil(w_b / 0.15)`.
  - If `n_b < ceil(w_b / 0.15)`: raise `InstrumentConcentrationBreachError(block_id=b, required=ceil(w_b/0.15), available=n_b)`.

- Otherwise distribute weight across top-N instruments (by AUM or risk-adjusted criterion) subject to `instrument_weight <= 0.15`.

Add `WinnerSignal.INSTRUMENT_CONCENTRATION_BREACH`.

**Acceptance tests:**
- Realize with block weight 30% and 2 approved instruments (15% each) → composition succeeds.
- Realize with block weight 30% and 1 approved instrument → fails with `instrument_concentration_breach`.
- Realize with block weight 15% and 1 approved instrument → succeeds with 15% in that instrument.

### Section G — Schema + enum updates

**Files:**
- `backend/app/domains/wealth/schemas/model_portfolio.py`: add `ApproveProposalRequest`, `ApprovalResponse`, `SetOverrideRequest`, `StrategicAllocationRow`, updated proposed-bands schemas.
- `backend/app/domains/wealth/schemas/sanitized.py`: add enum values `NO_APPROVED_ALLOCATION`, `INSTRUMENT_CONCENTRATION_BREACH`.
- Update existing `strategic_allocation` ORM model to reflect new columns + dropped columns.

---

## Ordering inside this PR

A (migration) → B (table, same migration) → G (schemas + enum) → C (approve endpoint) → D (override endpoint + optimizer wiring) → E (realize gate) → F (composition cap). One commit per Section.

## Global guardrails

- `CLAUDE.md` rules. Async-first, RLS via `SET LOCAL` for strategic_allocation (tenant-scoped); allocation_approvals is global but still joined with org_id in queries.
- No new Python dependencies.
- `make check` green.
- Do NOT touch: BL code, block_mapping, A22 validator, A25 trigger, optimizer cascade internals.

## Final report format

1. Migration up + down round-trip verified.
2. Unit + integration test output (all new test files).
3. End-to-end dev DB smoke:
   - Dispatch propose for all 3 profiles via A26.1 endpoint → 3 successful proposals.
   - Approve each via the new endpoint → strategic_allocation rows updated; allocation_approvals rows inserted.
   - Dispatch realize for all 3 → succeed this time (previously would fail with no_approved_allocation).
   - Paste: allocation_approvals query showing 3 active approvals + strategic_allocation summary showing approved_at populated.
4. Override smoke:
   - Set override_max=0.10 on na_equity_large for moderate profile.
   - Re-dispatch propose → observe proposal respects the cap.
   - Paste proposed_bands showing na_equity_large target ≤ 0.10.
5. Per-instrument cap smoke:
   - Dispatch realize for a profile where one block has a single candidate but block_weight > 0.15 (engineer this via a test fixture if needed).
   - Confirm fails with `instrument_concentration_breach`.
6. List any deviations from spec.
