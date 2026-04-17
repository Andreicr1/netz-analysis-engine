# PR-A11 — Cascade Telemetry & Phase-Attempt Audit Trail

**Date:** 2026-04-16
**Executor:** Opus 4.6 (1M)
**Branch:** `feat/pr-a11-cascade-telemetry` (cut from `main` HEAD post PR-A9 #189 squash-merge, commit at origin/main 2026-04-17 00:30 UTC)
**Scope:** Close the optimizer-cascade observability gap. Today the 4-phase cascade (Phase 1 → 1.5 → 2 → 3 → heuristic) collapses every successful path into `status=succeeded` with a single `solver` label, and there is no per-phase audit trail on the run row. Operators cannot tell that a `succeeded` run actually fell to Phase 3 (`min_variance_fallback`) because the configured CVaR limit is infeasible against the universe. PR-A11 introduces a new `cascade_telemetry` JSONB column on `portfolio_construction_runs` that records per-phase outcomes, the Phase 2 variance ceiling, the universe min-achievable variance, the feasibility gap, the cascade summary, and a sanitized `operator_signal` block. A new SSE event `cascade_telemetry_completed` surfaces the operator-facing subset live. The existing `binding_constraints` column is left untouched (Andrei Option B). Future feasibility-frontier UX (separate PR) consumes the persisted payload.

## Empirical evidence (live local DB, 2026-04-17 00:12 UTC, post PR-A9.1)

org_id `403d8392-ebfa-5890-b740-45da49c556eb`, alembic head `0141_portfolio_status_degraded`. Three canonical model_portfolios rebuilt via `/portfolios/{id}/construct`:

| Portfolio | id | profile | status | solver | n_w | κ_sample | wall_ms | CVaR | port_vol | E[r] |
|---|---|---|---|---|---|---|---|---|---|---|
| Conservative Preservation | `3945cee6-f85d-4903-a2dd-cf6a51e1c6a5` | conservative | succeeded | min_variance_fallback | 13 | 24172 | 10650 | -3.58% | 2.95% | 9.97% |
| Balanced Income | `e5892474-7438-4ac5-85da-217abcf99932` | moderate | succeeded | min_variance_fallback | 10 | 24172 | 10632 | -4.10% | 3.10% | 10.43% |
| Dynamic Growth | `3163d72b-3f8c-427e-9cd2-bead6377b59c` | growth | succeeded | CLARABEL | 8 | 30446 | 10567 | -4.31% | 4.21% | 13.20% |

Cascade trace reconstructed from `portfolio_construction_runs.event_log` (the SSE retrospective phase emit at executor:899):

- Dynamic Growth → Phase 2 (`variance_capped`) **succeeded**, objective=0.131991. Phases 3 + heuristic skipped.
- Balanced Income → Phase 2 **infeasible**, Phase 3 (`min_variance`) succeeded, objective=0.104328. Heuristic skipped.
- Conservative → Phase 2 **infeasible**, Phase 3 succeeded, objective=0.099727. Heuristic skipped.

For all three runs `pcr.binding_constraints` is `[]` and the only signal that Conservative + Balanced reached Phase 3 instead of Phase 2 is the `solver` string `min_variance_fallback`. There is no record of `max_var`, the variance-cap value, or the `cf_normal_ratio` that produced it.

## The two coupled defects

1. **Phase 2 silent infeasibility, Phase 3 invisible promotion to "succeeded".** Phase 2 derives a variance ceiling from the (regime-adjusted) CVaR limit:
   ```
   max_var = (|phase2_limit| / cvar_coeff) ** 2     # optimizer_service.py:691
   ```
   For Conservative (cvar_limit ≈ 5%) the ceiling is tighter than the universe's achievable min-variance, so CLARABEL returns infeasible and the cascade silently drops to Phase 3, which is *pure variance minimization with no return objective*. The run is reported as `succeeded` even though the operator's CVaR guardrail is biting and the resulting weights are concentrated in the lowest-volatility instruments without any return preference. An asset allocator signing the IPS deserves to see "your CVaR ceiling forced min-variance fallback" before activation.

2. **No structured cascade audit trail.** The optimizer logs the relevant numbers via `logger.warning("cvar_violation_re_optimizing", ..., max_vol_target=...)` at `optimizer_service.py:693` but never returns them, and the run row has no column to receive them. PR-A10's cascade panel and the planned feasibility-frontier feature (`project_feasibility_frontier_feature.md`) both need a structured per-phase trail to render. PR-A11 introduces the new `cascade_telemetry` JSONB column to fill that gap. The existing `binding_constraints` column is **not** repurposed — Andrei Option B preserves its existing list-of-strings semantics so PR-A9 / validation paths are not disturbed.

## Mandates

1. **`mandate_high_end_no_shortcuts.md`** — the cascade is an audit surface; no skipped fields, no string-only signals
2. **`feedback_smart_backend_dumb_frontend.md`** — backend persists structured numeric data; sanitized SSE payload uses operator vocabulary, never "Phase 2 variance-capped infeasible"
3. **Preserve PR-A9 / PR-A8 telemetry shape** — `statistical_inputs` JSONB stays additive; this PR introduces a sibling key, not a rewrite
4. **Minimum schema churn (Andrei Option B)** — one new JSONB column `cascade_telemetry` on `portfolio_construction_runs`. `binding_constraints` keeps its existing list-of-strings semantics — do not repurpose.
5. **No optimizer math change** — Phase 1/1.5/2/3 solvers stay byte-identical. PR-A11 only changes what the optimizer *returns* about its work.

## Section A — Diagnosis & decision tree

### A.1 — Promote Phase 3 fallback to a first-class run status

When the cascade reaches Phase 3 (`min_variance_fallback`) the run **succeeds in producing weights** but **fails to honor the operator's stated risk objective** (CVaR limit forced a return-blind solution). Treat this as a distinct outcome:

| Cascade winner | Run `status` (column) | `cascade_summary` (new column) | Operator interpretation |
|---|---|---|---|
| Phase 1 (`optimal`) | `succeeded` | `phase_1_succeeded` | Risk-adjusted return, no constraint binding |
| Phase 1.5 (`optimal:robust`) | `succeeded` | `phase_1_5_robust_succeeded` | Robust SOCP with ellipsoidal uncertainty |
| Phase 2 (`optimal:cvar_constrained`) | `succeeded` | `phase_2_succeeded` | Variance-capped from CVaR limit; CVaR is the binding constraint |
| Phase 3 (`optimal:min_variance_fallback`) | `degraded` | `phase_3_fallback` | CVaR limit infeasible vs. universe — pure min-var, no return objective |
| Heuristic (`optimal:cvar_violated` or solver_failed) | `degraded` | `heuristic_fallback` | All convex phases failed — block-level heuristic |
| No weights produced | `failed` | `cascade_exhausted` | Operator must reconfigure |

The `degraded` status already exists (per migration `0141_portfolio_status_degraded` referenced in the head). PR-A11 starts using it for the Phase 3 case. **The activation flow must continue to allow `degraded` runs to be activated** (they have valid weights), but the Activation modal in the future PR-A10 will surface a confirmation dialog. For PR-A11 backend-only: do not block activation, just persist the new status.

### A.2 — Per-phase audit trail (lives in NEW `cascade_telemetry` column)

Persist the full cascade trace to the new `cascade_telemetry` JSONB column (added by migration 0142). The existing `binding_constraints` column is **untouched** — it keeps its current list-of-strings semantics. The exact persisted shape, calibrated to Conservative-derived numbers (port_vol ≈ 2.95% → variance ≈ 0.000868; phase2 ceiling derived from CVaR limit):

```json
{
  "phase_attempts": [
    {
      "phase": "phase_1",
      "status": "succeeded",
      "solver": "CLARABEL",
      "objective_value": 0.131991,
      "wall_ms": 4321,
      "infeasibility_reason": null
    },
    {
      "phase": "phase_1_5_robust",
      "status": "skipped",
      "solver": null,
      "objective_value": null,
      "wall_ms": 0,
      "infeasibility_reason": null
    },
    {
      "phase": "phase_2_variance_capped",
      "status": "infeasible",
      "solver": "CLARABEL",
      "objective_value": null,
      "max_var": 0.000071,
      "wall_ms": 217,
      "infeasibility_reason": "max_var below universe min-variance floor"
    },
    {
      "phase": "phase_3_min_variance",
      "status": "succeeded",
      "solver": "CLARABEL",
      "objective_value": 0.099727,
      "wall_ms": 89,
      "infeasibility_reason": null
    }
  ],
  "cascade_summary": "phase_3_fallback",
  "phase2_max_var": 0.000071,
  "min_achievable_variance": 0.000868,
  "feasibility_gap_pct": 91.8,
  "operator_signal": {
    "kind": "constraint_binding",
    "binding": "risk_budget",
    "message_key": "cvar_limit_below_universe_floor"
  }
}
```

Field semantics:

- `phase_attempts[]` always contains **one entry per cascade phase including skipped ones** (so `jsonb_array_length >= 4` for the standard cascade; heuristic fallback adds a 5th).
- `cascade_summary` is one of: `phase_1_succeeded`, `phase_1_5_robust_succeeded`, `phase_2_succeeded`, `phase_3_fallback`, `heuristic_fallback`, `cascade_exhausted`. Same enum as A.1.
- `phase2_max_var` is the CVaR-derived variance ceiling that Phase 2 attempted; `min_achievable_variance` is the universe's actual minimum-variance solution from Phase 3. When Phase 3 fired, `feasibility_gap_pct = (1 - phase2_max_var / min_achievable_variance) * 100` quantifies how far below the universe floor the configured risk budget sits. When Phase 1 or 2 won and Phase 3 never ran, both `min_achievable_variance` and `feasibility_gap_pct` are `null`.
- `operator_signal` is the **smart-backend payload** that PR-A10's `metric-translators.ts` will translate to human language. Backend never emits "Phase 2 infeasible" or solver names to the client. `kind` is `"constraint_binding"` whenever Phase 2 was infeasible (or the heuristic fallback fired); `binding` ∈ `{"risk_budget", "concentration", "block_band", "solver"}`; `message_key` is a stable identifier the frontend maps to copy. When Phase 1/2 won cleanly, `operator_signal` is `null`.

## Section B — Scope (single phase, ~3-5h Opus work)

### B.1 — Files that change

| File | Lines (approx.) | Change |
|---|---|---|
| `backend/quant_engine/optimizer_service.py` | 309-323, 458-485, 487-493, 540-749 | Extend `FundOptimizationResult` with `phase_attempts: list[PhaseAttempt]` + `winning_phase: str`. Record per-phase metadata in every Phase 1/1.5/2/3/heuristic branch. |
| `backend/app/domains/wealth/services/quant_queries.py` | wherever `FundOptimizationResult` flows out | Pass-through (add to result dict if currently flattened). |
| `backend/app/domains/wealth/routes/model_portfolios.py` | 2194-2233, 2272-2289 | Capture `fund_result.phase_attempts` + `winning_phase` and add to the returned `result` dict under key `cascade`. |
| `backend/app/domains/wealth/workers/construction_run_executor.py` | 304-310, 313-357, 865-905, 1029, 1034-1040 | (1) Read `cascade` block from `base_result`; (2) build `cascade_telemetry` JSONB per A.2 (NEW column); (3) decide `run.status` per A.1 table; (4) persist `cascade_telemetry`; (5) leave `binding_constraints` untouched (existing list-of-strings semantics, may stay `[]`); (6) emit sanitized SSE event `cascade_telemetry_completed` carrying `operator_signal` + `cascade_summary`. |
| `backend/app/domains/wealth/models/model_portfolio.py` | wherever `PortfolioConstructionRun` is declared | Add `cascade_telemetry: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"))`. Do NOT touch the existing `binding_constraints` column or its mapping. |
| `backend/app/core/db/migrations/versions/0142_construction_cascade_telemetry.py` | NEW | Add `cascade_telemetry jsonb NOT NULL DEFAULT '{}'::jsonb` column to `portfolio_construction_runs`. No backfill (existing rows pick up the default `{}`). Optional partial GIN/expression index on `(cascade_telemetry->>'cascade_summary')` for the operator dashboard query. **Do NOT touch `binding_constraints`** — that column keeps its existing JSONB list-of-strings semantics. |
| `backend/tests/quant_engine/test_cascade_telemetry.py` | NEW | Unit tests per Section E. |
| `backend/tests/wealth/test_construction_run_executor_cascade.py` | NEW | Integration test asserting `cascade_telemetry` JSONB shape end-to-end against testcontainer DB. |

### B.2 — One new JSONB column, one new migration (Option B)

Andrei chose **Option B**: introduce a brand-new `cascade_telemetry jsonb NOT NULL DEFAULT '{}'::jsonb` column on `portfolio_construction_runs`. Rationale:

- **Preserve `binding_constraints` semantics.** The existing column is a JSONB list of constraint-name strings (e.g. `["block_max", "single_fund_cap"]`) consumed by the validation gate and downstream code. Repurposing it into a structured dict would force every existing reader to branch on shape and risks regressions in PR-A9 / validation paths. Leave it alone.
- **Single home for cascade observability.** All new telemetry — per-phase attempts, summary, feasibility metrics, operator signal — lives under `cascade_telemetry`. One column, one schema, one consumer contract.
- **No backfill.** Default `'{}'::jsonb` means historical rows transparently expose an empty cascade telemetry block; new runs write the full payload.
- **Operator dashboard query** filters on `cascade_telemetry->>'cascade_summary' IN ('phase_3_fallback','heuristic_fallback')`. An optional expression index can be added if/when the dashboard query becomes hot.

## Section C — Implementation guidance

### C.1 — Optimizer dataclass extension (`optimizer_service.py`)

Add at module scope:

```python
@dataclass
class PhaseAttempt:
    phase: str                         # "primary"|"robust"|"variance_capped"|"min_variance"
    status: str                        # "succeeded"|"infeasible"|"solver_failed"|"skipped"
    solver: str | None
    objective_value: float | None
    wall_ms: int
    infeasibility_reason: str | None   # raw CVXPY status string when status != "succeeded"
    # Phase-specific (None when N/A):
    cvar_at_solution: float | None = None
    cvar_limit_effective: float | None = None
    cvar_within_limit: bool | None = None
    max_var: float | None = None
    max_vol_target: float | None = None
    cvar_coeff: float | None = None
    cf_normal_ratio: float | None = None
    phase2_limit: float | None = None
    min_achievable_variance: float | None = None
    min_achievable_vol: float | None = None
    kappa_used: float | None = None    # robust phase only
```

Extend `FundOptimizationResult`:

```python
@dataclass
class FundOptimizationResult:
    # ... existing fields unchanged ...
    phase_attempts: list[PhaseAttempt] = field(default_factory=list)
    winning_phase: str | None = None   # one of the phase keys above, or None on total failure
```

`field(default_factory=list)` requires `from dataclasses import field`. Default `None` for `winning_phase` keeps backward compatibility with existing call sites.

### C.2 — Recording per-phase metadata in `optimize_fund_portfolio`

Wrap each `_solve_problem` call in a `time.perf_counter()` window. After each solve, append a `PhaseAttempt` to a local `attempts: list[PhaseAttempt] = []`. Pass `attempts` into `_build_result` and `_empty_result` so the returned dataclass carries the trace.

Concrete sites:

- **Phase 1 (lines 511-538):** record `phase="primary"`, `objective_value=float(prob1.value) if prob1.value is not None else None`, `cvar_at_solution=cvar_neg`, `cvar_limit_effective=effective_cvar_limit`, `cvar_within_limit=cvar_ok`. Status `"succeeded"` if branch at 557 taken (CVaR ok), `"succeeded"` also if Phase 1 returns from line 558 — distinguish by whether subsequent phases ran.
- **Phase 1.5 (lines 568-641):** if `robust=False`, append `PhaseAttempt(phase="robust", status="skipped", ...)`. If enabled, record `kappa_used=kappa`, `solver="CLARABEL:robust"`.
- **Phase 2 (lines 643-720):** ALWAYS record when reached. Capture `max_var`, `max_vol_target=abs(phase2_limit)/cvar_coeff`, `cvar_coeff`, `cf_normal_ratio=_cf_normal_ratio`, `phase2_limit`. If `status2 not in ("optimal", "optimal_inaccurate")`, set `status="infeasible"`, `infeasibility_reason=str(status2)`. Crucial: extract `prob2.value` (the objective) only when succeeded.
- **Phase 3 (lines 722-741):** record `min_achievable_variance=float(prob3.value)`, `min_achievable_vol=float(np.sqrt(prob3.value))`. Status `"succeeded"` when extract works.
- **Total failure (lines 743-749):** mark Phase 3 as `"solver_failed"` with reason from `status3`.

`winning_phase` is derived at each return point: `_build_result` accepts a `winning_phase` argument matching the branch.

### C.3 — Route propagation (`model_portfolios.py`)

After line 2203 (`fund_result = await optimize_fund_portfolio(...)`), and before the `if fund_result.status.startswith("optimal")` block, add:

```python
cascade_block = {
    "phase_attempts": [asdict(a) for a in fund_result.phase_attempts],
    "winning_phase": fund_result.winning_phase,
}
```

(`from dataclasses import asdict` at top of function.)

In the result dict at 2272-2286, add:

```python
result["cascade"] = cascade_block
```

When the heuristic fallback fires (line 2256), construct a synthetic `cascade_block` with `winning_phase="heuristic"` and a single `PhaseAttempt(phase="heuristic", status="succeeded", solver="heuristic_fallback", ...)` so the executor always has a uniform shape to consume.

### C.4 — Executor: build `cascade_telemetry` JSONB (`construction_run_executor.py`)

After line 905 (post-`_emit_cascade_phase_events`), insert a new helper call:

```python
cascade_telemetry, derived_status = _build_cascade_telemetry(
    cascade_block=base_result.get("cascade") or {},
    optimizer_trace=optimizer_trace,
    cvar_limit=calibration_snapshot.get("cvar_limit"),
)
```

Define `_build_cascade_telemetry` as a module-private function. Decision tables:

```python
_STATUS_BY_SUMMARY: dict[str, str] = {
    "phase_1_succeeded": "succeeded",
    "phase_1_5_robust_succeeded": "succeeded",
    "phase_2_succeeded": "succeeded",
    "phase_3_fallback": "degraded",
    "heuristic_fallback": "degraded",
    "cascade_exhausted": "failed",
}

_SUMMARY_BY_WINNING_PHASE: dict[str, str] = {
    "primary": "phase_1_succeeded",
    "robust": "phase_1_5_robust_succeeded",
    "variance_capped": "phase_2_succeeded",
    "min_variance": "phase_3_fallback",
    "heuristic": "heuristic_fallback",
}
```

The helper returns `(cascade_telemetry_dict, derived_run_status_str)`. The dict matches the A.2 shape exactly: `phase_attempts[]` (one entry per cascade phase including skipped, normalized to the public phase keys `phase_1`, `phase_1_5_robust`, `phase_2_variance_capped`, `phase_3_min_variance`, `heuristic`), `cascade_summary`, `phase2_max_var`, `min_achievable_variance`, `feasibility_gap_pct`, `operator_signal`.

`operator_signal` derivation:
- Phase 1 / Phase 2 winner with no infeasibility upstream → `null`
- Phase 3 winner (Phase 2 was infeasible) → `{"kind": "constraint_binding", "binding": "risk_budget", "message_key": "cvar_limit_below_universe_floor"}`
- Heuristic winner → `{"kind": "constraint_binding", "binding": "solver", "message_key": "convex_phases_exhausted"}`
- `cascade_exhausted` → `{"kind": "cascade_failure", "binding": "solver", "message_key": "no_feasible_allocation"}`

`feasibility_gap_pct` is computed only when Phase 2 was infeasible AND Phase 3 succeeded: `(1 - phase2_max_var / min_achievable_variance) * 100`. Otherwise `null`.

Replace the persistence site (around lines 1029-1040):

```python
# binding_constraints stays untouched — keep existing semantics (likely [] or
# whatever the validation gate produces). Do NOT overwrite it with cascade data.
run.optimizer_trace = optimizer_trace
run.cascade_telemetry = cascade_telemetry      # NEW column

# Defer run.status assignment until after validation gate to allow `failed`
# overrides; if validation rejects, status="failed" wins.
if not validation_result.passed:
    run.status = "failed"
elif derived_status == "degraded":
    run.status = "degraded"
else:
    run.status = "succeeded"
```

(Find the existing `run.status = ...` line and replace it with this gated assignment. Verify the existing happy-path logic and adapt.)

**Do NOT modify `narrative_payload` to inject cascade data into `binding_constraints`** — `narrative_templater.py` does not need adapter changes because `binding_constraints` semantics are unchanged. If the templater needs cascade context for the operator-caveat copy, pass `cascade_telemetry` as a separate key in `narrative_payload` (additive, no breaking change).

### C.5 — Sanitized SSE event `cascade_telemetry_completed`

After `cascade_telemetry` is built and persisted, emit ONE consolidated SSE event `cascade_telemetry_completed` with this sanitized payload:

```python
{
    "cascade_summary": cascade_telemetry["cascade_summary"],   # e.g. "phase_3_fallback"
    "operator_signal": cascade_telemetry["operator_signal"],   # null OR {kind, binding, message_key}
    "feasibility_gap_pct": cascade_telemetry["feasibility_gap_pct"],  # number or null
}
```

Raw `phase_attempts[]` is **persisted in the column but NOT emitted on SSE** — too verbose, internals-leaking, and PR-A10's UI consumes the persisted column via the run-detail endpoint, not the live event stream.

Allowed vocabulary on SSE: the `message_key` strings (which PR-A10 maps to copy via `metric-translators.ts`), `cascade_summary` enum values, `operator_signal.binding` enum values (`risk_budget`, `concentration`, `block_band`, `solver`). Never solver names, phase numbers, math jargon, Greek letters, or coefficient names. The mapping from internal phase status to `operator_signal` lives in `_build_cascade_telemetry`, not on the SSE boundary.

### C.6 — Migration `0142_construction_cascade_telemetry.py`

Verified: current alembic head per `backend/app/core/db/migrations/versions/` is `0141_portfolio_status_degraded` (PR-A9 / current branch `feat/pr-a9-kappa-calibration` did not add a migration). Next number is **0142**.

```python
"""Add cascade_telemetry column to portfolio_construction_runs.

Revision ID: 0142_construction_cascade_telemetry
Revises: 0141_portfolio_status_degraded
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0142_construction_cascade_telemetry"
down_revision = "0141_portfolio_status_degraded"

def upgrade() -> None:
    op.add_column(
        "portfolio_construction_runs",
        sa.Column(
            "cascade_telemetry",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Optional expression index to keep operator-dashboard queries cheap once UI ships.
    op.execute("""
        CREATE INDEX ix_pcr_cascade_summary
        ON portfolio_construction_runs ((cascade_telemetry->>'cascade_summary'), requested_at DESC)
        WHERE cascade_telemetry->>'cascade_summary' IN ('phase_3_fallback', 'heuristic_fallback')
    """)

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pcr_cascade_summary")
    op.drop_column("portfolio_construction_runs", "cascade_telemetry")
```

`NOT NULL DEFAULT '{}'::jsonb` lets historical rows pick up an empty object transparently — no backfill script required. **Do NOT touch `binding_constraints` in this migration** — it keeps its existing list-of-strings semantics (Section G.1).

## Section D — Smart-backend / dumb-frontend translation

The backend payload defined in A.2 (persisted to `cascade_telemetry`) is the **structured truth**. The SSE event `cascade_telemetry_completed` (see C.5) emits only the operator-facing subset: `cascade_summary`, `operator_signal`, `feasibility_gap_pct`. PR-A10's `metric-translators.ts` maps `operator_signal.message_key` to display copy; it is out of scope here, but A11 must guarantee the SSE event NEVER carries:

- Solver names (`CLARABEL`, `SCS`, `min_variance_fallback`)
- Phase numbers (`Phase 2`, `Phase 1.5`) or internal phase keys (`phase_2_variance_capped`)
- Math jargon (`variance ceiling`, `Cornish-Fisher`, `psd_violation`, `infeasible`)
- Greek letters or coefficient names (`κ`, `λ`, `cvar_coeff`)
- Raw `phase_attempts[]` (persist-only)

Allowed SSE vocabulary: the `cascade_summary` enum, the `operator_signal.binding` enum (`risk_budget`, `concentration`, `block_band`, `solver`), and stable `message_key` identifiers. The mapping table lives in the executor helper, not the frontend.

The persisted `cascade_telemetry` column is the unsanitized truth — it is for IC audit and for the run-detail endpoint that PR-A10's UI consumes. Distinguish: the column is for *auditability*, the SSE is for *live operator awareness*.

## Section E — Tests

### E.1 — Unit: every phase records an attempt

`test_phase_attempts_recorded_for_phase1_success` — minimal 3-fund universe, well-conditioned cov, no CVaR limit. Assert `len(result.phase_attempts) == 1`, `result.phase_attempts[0].phase == "primary"`, `result.phase_attempts[0].status == "succeeded"`, `result.winning_phase == "primary"`.

### E.2 — Unit: Phase 2 success recorded

`test_phase_attempts_records_phase2_success` — set `cvar_limit` such that Phase 1 violates and Phase 2 succeeds. Assert `len(result.phase_attempts) >= 2`, second attempt is `phase="variance_capped"`, `status="succeeded"`, `max_var > 0`, `cvar_coeff > 0`. `winning_phase == "variance_capped"`.

### E.3 — Unit: Phase 3 fallback recorded with infeasibility metadata

`test_phase_attempts_records_phase3_fallback` — synthetic universe + impossibly tight `cvar_limit` (e.g. `-0.005`) so Phase 2 is infeasible. Assert:
- Three attempts: primary (`succeeded` or `infeasible`), variance_capped (`infeasible`), min_variance (`succeeded`)
- `phase_attempts[1].infeasibility_reason` is non-null and contains `"infeasible"` or similar CVXPY status
- `phase_attempts[1].max_vol_target` is populated
- `phase_attempts[2].min_achievable_vol > phase_attempts[1].max_vol_target` (the feasibility gap)
- `winning_phase == "min_variance"`

### E.4 — Integration: executor persists `cascade_telemetry` and derives status

`test_construction_run_executor_persists_cascade_telemetry` — fixture portfolio that is known to fall to Phase 3 (use the Conservative profile shape from the empirical evidence). Run `_run_construction_for_portfolio` end-to-end against testcontainer DB. Assert:
- `pcr.cascade_telemetry` is a dict
- `pcr.cascade_telemetry["cascade_summary"] == "phase_3_fallback"`
- `len(pcr.cascade_telemetry["phase_attempts"]) >= 4` (one per cascade phase including skipped)
- `pcr.cascade_telemetry["phase2_max_var"] is not None`
- `pcr.cascade_telemetry["min_achievable_variance"] is not None`
- `pcr.cascade_telemetry["feasibility_gap_pct"] > 0`
- `pcr.cascade_telemetry["operator_signal"]["kind"] == "constraint_binding"`
- `pcr.cascade_telemetry["operator_signal"]["binding"] == "risk_budget"`
- `pcr.status == "degraded"`
- `pcr.binding_constraints` is **untouched** (still a list with its existing semantics — assert it is the same shape it would be without PR-A11)

### E.5 — Integration: Phase 2 winner produces clean telemetry

`test_construction_run_executor_phase2_clean` — fixture that exercises the Dynamic Growth path (Phase 2 winner). Assert `cascade_telemetry["cascade_summary"] == "phase_2_succeeded"`, `status == "succeeded"`, `cascade_telemetry["feasibility_gap_pct"] is None`, `cascade_telemetry["operator_signal"] is None`.

### E.6 — SSE sanitization regression

`test_cascade_telemetry_completed_event_is_sanitized` — capture the `cascade_telemetry_completed` SSE event from a Phase-2-infeasible run. Assert payload contains exactly the keys `{cascade_summary, operator_signal, feasibility_gap_pct}` and does NOT contain `phase_attempts`, any solver name, any internal phase key (`phase_2_variance_capped`), or any math jargon listed in Section D. Use `payload_json = json.dumps(payload); assert "CLARABEL" not in payload_json; assert "phase_attempts" not in payload_json; assert "phase_2_variance_capped" not in payload_json`.

### E.7 — Existing tests remain green

Run `pytest backend/tests/quant_engine/ backend/tests/wealth/ -q`. All tests passing pre-merge.

## Section F — Pass criteria & verification (mandatory empirical proof)

### F.1 — Live smoke against the 3 canonical portfolios

After implementation, trigger rebuilds via Builder UI or `POST /portfolios/{id}/construct` for the IDs in the empirical evidence table. Then:

```sql
SELECT mp.display_name,
       pcr.status,
       pcr.cascade_telemetry->>'cascade_summary'                          AS cascade_summary,
       (pcr.cascade_telemetry->>'phase2_max_var')::float                  AS phase2_max_var,
       (pcr.cascade_telemetry->>'min_achievable_variance')::float         AS min_achievable_variance,
       (pcr.cascade_telemetry->>'feasibility_gap_pct')::float             AS feasibility_gap_pct,
       jsonb_array_length(pcr.cascade_telemetry->'phase_attempts')        AS n_attempts,
       pcr.cascade_telemetry->'operator_signal'->>'kind'                  AS op_signal_kind,
       pcr.cascade_telemetry->'operator_signal'->>'binding'               AS op_signal_binding,
       pcr.cascade_telemetry->'operator_signal'->>'message_key'           AS op_signal_message_key,
       pcr.optimizer_trace->>'solver'                                     AS solver,
       (SELECT COUNT(*) FROM jsonb_object_keys(pcr.weights_proposed))     AS n_weights,
       pcr.wall_clock_ms
FROM portfolio_construction_runs pcr
JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
WHERE pcr.portfolio_id IN (
    '3945cee6-f85d-4903-a2dd-cf6a51e1c6a5',
    'e5892474-7438-4ac5-85da-217abcf99932',
    '3163d72b-3f8c-427e-9cd2-bead6377b59c'
)
  AND pcr.requested_at > NOW() - INTERVAL '30 minutes'
ORDER BY mp.display_name, pcr.requested_at DESC;
```

### F.2 — Pass criteria table

| Portfolio | Expected `status` | Expected `cascade_summary` | `feasibility_gap_pct` | `n_attempts` | `op_signal_kind` | `op_signal_binding` |
|---|---|---|---|---|---|---|
| Dynamic Growth | `succeeded` | `phase_2_succeeded` | `null` | `>= 4` | `null` | `null` |
| Balanced Income | `degraded` | `phase_3_fallback` | `> 0` | `>= 4` | `constraint_binding` | `risk_budget` |
| Conservative Preservation | `degraded` | `phase_3_fallback` | `> 0` | `>= 4` | `constraint_binding` | `risk_budget` |

All three runs MUST have:
- `cascade_telemetry` is a JSONB object (not array, not empty)
- `jsonb_array_length(cascade_telemetry->'phase_attempts') >= 4` (one entry per cascade phase including skipped ones)
- For Conservative + Balanced specifically: `cascade_telemetry->'operator_signal'->>'kind' = 'constraint_binding'`
- `binding_constraints` column shape is **unchanged** vs. PR-A9 baseline (still a JSONB list — verify via `jsonb_typeof(binding_constraints) = 'array'`)
- `n_weights >= 5` (no regression vs. PR-A9 baseline)
- `wall_clock_ms` in [8_000, 30_000] (within 2x PR-A9 baseline)

Additionally, query the SSE event log:

```sql
SELECT pcr.id,
       jsonb_array_elements(pcr.event_log) ->> 'public_type' AS evt
FROM portfolio_construction_runs pcr
WHERE pcr.portfolio_id = 'e5892474-7438-4ac5-85da-217abcf99932'
  AND pcr.requested_at > NOW() - INTERVAL '30 minutes'
ORDER BY pcr.requested_at DESC
LIMIT 50;
```

Must contain at least one row with `evt = 'cascade_telemetry_completed'` for the Balanced Income run, and the corresponding event payload (parse the JSON and assert) must have `cascade_summary = 'phase_3_fallback'` and `operator_signal.kind = 'constraint_binding'`.

### F.3 — Test pass requirement

`pytest backend/tests/quant_engine/test_cascade_telemetry.py backend/tests/wealth/test_construction_run_executor_cascade.py -v` — all 7 new tests green (E.1-E.7 minus E.7 which is the regression sweep). Plus full sweep `pytest backend/tests/wealth/ backend/tests/quant_engine/ -q` green.

### F.4 — Lint + typecheck

`make lint` clean, `make typecheck` clean — no new errors. The dataclass extensions are typed; the JSONB shape is `dict[str, Any]` which is acceptable here (the schema is enforced by tests, not types).

### F.5 — Per memory `feedback_dev_first_ci_later.md`

Smoke pass against live DB is the merge gate, NOT GitHub CI green. Andrei merges when F.1+F.2 pass and tests E.1-E.6 are green locally.

## Section G — What NOT to do (explicit out-of-scope)

**G.1 Do NOT modify `binding_constraints`.** Per Andrei's Option B decision, `binding_constraints` keeps its existing JSONB list-of-strings semantics and existing readers/writers. Do NOT overwrite it with cascade data. Do NOT add cascade fields to it. Do NOT change its shape. Do NOT add a similar telemetry block to it. All cascade telemetry lives exclusively in the new `cascade_telemetry` column.

**G.2 Do NOT backfill `cascade_telemetry` for historical runs.** `NOT NULL DEFAULT '{}'::jsonb` means existing rows automatically carry an empty object — that is the acceptable end-state for the demo. No data-migration script.

**G.3 Do NOT add `narrative_templater.py` adapter logic for `binding_constraints`.** The previous draft of this prompt asked for a consumer adaptation — that is no longer needed because `binding_constraints` shape does not change. If the templater needs cascade context, pass `cascade_telemetry` as an additive key in `narrative_payload`.

Other prohibitions (carried over):

- Do NOT change Phase 1/1.5/2/3 mathematical formulation — solver calls stay identical
- Do NOT touch `cf_relaxation_factor` default or its derivation — separate decision
- Do NOT recalibrate per-profile CVaR limits — A11 surfaces that they bite, recalibration is a separate operator decision
- Do NOT block activation of `degraded` runs in this PR — backend persistence only; PR-A10 adds the confirmation modal
- Do NOT emit raw `infeasibility_reason` strings, solver names, or internal phase keys (`phase_2_variance_capped`) to SSE — sanitize at the executor boundary
- Do NOT break the existing `_emit_cascade_phase_events` retrospective emit — `cascade_telemetry_completed` is an additional event, not a replacement
- Do NOT emit `phase_attempts[]` on the SSE channel — persisted-only
- Do NOT log raw CVXPY error strings at WARNING+ in production paths — INFO with the structured `infeasibility_reason` field on the persisted attempt is sufficient
- Do NOT introduce `Literal[...]` types on the dataclass `phase` / `status` fields in this PR — matches PR-A9 dataclass discipline

## Section H — Deliverables checklist

- [ ] Branch `feat/pr-a11-cascade-telemetry` cut from `main` HEAD post PR-A9 #189
- [ ] `optimizer_service.py`: `PhaseAttempt` dataclass + `FundOptimizationResult.phase_attempts` + `winning_phase`
- [ ] Per-phase metadata captured in Phase 1, 1.5, 2, 3 branches (and skipped/synthetic in heuristic)
- [ ] `model_portfolios.py`: `cascade` block in `_run_construction_async` return dict (both optimizer-success and heuristic-fallback paths)
- [ ] `construction_run_executor.py`: `_build_cascade_telemetry` helper + `cascade_telemetry` JSONB write + gated `run.status` (succeeded/degraded/failed); `binding_constraints` left untouched
- [ ] Executor emits new SSE event `cascade_telemetry_completed` with sanitized payload `{cascade_summary, operator_signal, feasibility_gap_pct}` (no `phase_attempts`, no solver names)
- [ ] Migration `0142_construction_cascade_telemetry.py` adds `cascade_telemetry jsonb NOT NULL DEFAULT '{}'::jsonb` + optional expression index on `cascade_summary`
- [ ] `PortfolioConstructionRun` ORM model has `cascade_telemetry` mapped column (JSONB, server_default `'{}'::jsonb`); `binding_constraints` mapping unchanged
- [ ] 6 tests in `test_cascade_telemetry.py` + `test_construction_run_executor_cascade.py` green (E.1-E.6)
- [ ] Existing wealth + quant_engine test sweep green
- [ ] `make lint` clean, `make typecheck` clean
- [ ] `alembic upgrade head` clean on local
- [ ] F.1 SQL returns 3 rows matching F.2 pass-criteria table
- [ ] At least one `cascade_telemetry_completed` SSE event recorded for Balanced + Conservative with `operator_signal.kind = 'constraint_binding'`
- [ ] Commit message lists per-portfolio `cascade_summary` + `feasibility_gap_pct` + `operator_signal.binding`

## Reference files

- `C:\Users\andre\projetos\netz-analysis-engine\backend\quant_engine\optimizer_service.py:309-323` (`FundOptimizationResult` dataclass)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\quant_engine\optimizer_service.py:495-538` (Phase 1)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\quant_engine\optimizer_service.py:567-641` (Phase 1.5 robust)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\quant_engine\optimizer_service.py:643-720` (Phase 2 variance-capped — site of `max_var`, `cvar_coeff`, `cf_normal_ratio`)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\quant_engine\optimizer_service.py:722-749` (Phase 3 min-variance + total-failure tail)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\routes\model_portfolios.py:2194-2289` (`fund_result` capture site + result dict construction)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\workers\construction_run_executor.py:294-310` (`_CASCADE_PHASES` + `_STATUS_TO_WINNING_PHASE`)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\workers\construction_run_executor.py:313-357` (`_emit_cascade_phase_events` — extension site)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\workers\construction_run_executor.py:1027-1040` (current `binding_constraints = []` site)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\core\db\migrations\versions\0099_portfolio_construction_runs.py:87` (`binding_constraints jsonb` column origin)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\core\db\migrations\versions\0099_portfolio_construction_runs.py:103-128` (status CHECK + partial index style to mirror)

## Diagnostic step (if implementer needs it)

If the implementer is uncertain whether `prob.value` returns the objective at the moment of solve (CVXPY semantics vary by problem class), add a temporary `logger.debug("phase_objective", phase="variance_capped", value=prob2.value, status=status2)` at line 708 and run the Conservative portfolio once. Confirm the value type and presence before wiring it into `PhaseAttempt.objective_value`. Remove the debug line before commit.

## Expected outcome (empirical prediction)

Post PR-A11, the F.1 query produces:

```
display_name              | status    | cascade_summary    | feasibility_gap_pct | n_attempts | op_signal_kind       | op_signal_binding
--------------------------+-----------+--------------------+---------------------+------------+----------------------+-------------------
Conservative Preservation | degraded  | phase_3_fallback   | ~91.8               | 4          | constraint_binding   | risk_budget
Balanced Income           | degraded  | phase_3_fallback   | ~80-92              | 4          | constraint_binding   | risk_budget
Dynamic Growth            | succeeded | phase_2_succeeded  | null                | 4          | null                 | null
```

Operators querying `WHERE cascade_telemetry->>'cascade_summary' = 'phase_3_fallback'` get a clean list of portfolios whose CVaR limits are biting. The future feasibility-frontier UX consumes `cascade_telemetry->>'feasibility_gap_pct'` as its primary input. The Activation modal in PR-A10 reads `status='degraded'` and `cascade_telemetry->'operator_signal'` to render the confirmation dialog copy.

## PR body template (use verbatim, replacing `<...>` placeholders)

```
## Summary
- Persist optimizer cascade telemetry on every construction run via new `cascade_telemetry` JSONB column: `phase_attempts[]`, `cascade_summary`, `phase2_max_var`, `min_achievable_variance`, `feasibility_gap_pct`, `operator_signal`. `binding_constraints` column intentionally untouched (Option B).
- Promote Phase 3 (min-variance) and heuristic fallbacks from `succeeded` to `degraded` so operators can distinguish risk-budget-binding outcomes from risk-aware optima.
- Sanitize SSE: new `cascade_telemetry_completed` event emits `{cascade_summary, operator_signal, feasibility_gap_pct}` only — no solver names, no phase numbers, no math jargon, no `phase_attempts`.

## Schema
- Migration `0142_construction_cascade_telemetry`: new `cascade_telemetry jsonb NOT NULL DEFAULT '{}'::jsonb` column on `portfolio_construction_runs` + optional expression index on `cascade_telemetry->>'cascade_summary'` for degraded outcomes.
- `binding_constraints` column intentionally untouched (Option B) — keeps existing list semantics.

## Empirical smoke (live local DB, org_id 403d8392-...)

| Portfolio | status | cascade_summary | feasibility_gap_pct | operator_signal.binding | n_w |
|---|---|---|---|---|---|
| Conservative Preservation | degraded  | phase_3_fallback  | <X> | risk_budget | <N> |
| Balanced Income           | degraded  | phase_3_fallback  | <X> | risk_budget | <N> |
| Dynamic Growth            | succeeded | phase_2_succeeded | null | null | <N> |

## Tests
- 6 new unit + integration tests (E.1-E.6) green
- Full wealth + quant_engine sweep green
- `make lint` + `make typecheck` clean
- `alembic upgrade head` clean

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

**End of spec. Execute end-to-end. Report with the F.1 SQL output, the SSE event-log query output, test counts, and commit SHA. Do NOT commit until F.2 pass criteria are verified on live DB.**
