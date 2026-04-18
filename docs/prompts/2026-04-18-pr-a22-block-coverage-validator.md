# PR-A22 — Block Coverage Validator (Operator-Facing Pre-Run Check)

**Date**: 2026-04-18
**Status**: P0 STRUCTURAL — replaces the silent fallback that hid 19.79% uncovered allocation weight in the moderate profile of org `403d8392-...`.
**Branch**: `feat/pr-a22-block-coverage-validator`
**Predecessors merged**: PR-A21 (org universe sanitization).

---

## Context — what this PR fixes

Post-A19.1 + A20 empirical finding (dev DB, org `403d8392-...`, profile `moderate`, 2026-04-18):

| block_id | target_weight | n_candidates in `instruments_org` (approved) |
|---|---|---|
| na_equity_large | 22.08% | 1553 |
| fi_us_aggregate | 14.04% | 558 |
| na_equity_growth | **8.97%** | **0** |
| dm_europe_equity | 7.68% | 44 |
| na_equity_value | **7.68%** | **0** |
| fi_us_treasury | 7.23% | 13 (post-A21 consolidation) |
| em_equity | 5.46% | 93 |
| alt_real_estate | 5.14% | 394 |
| fi_us_high_yield | 4.43% | 284 |
| fi_us_tips | 4.43% | 3 |
| alt_gold | 4.09% | 26 |
| dm_asia_equity | 3.64% | 38 |
| **alt_commodities** | **3.14%** | **0** |
| cash | 2.00% | 44 |

Three blocks with zero candidates total **19.79%** of the mandate. Construction runs currently succeed anyway — the cascade silently redistributes that weight across blocks with candidates. This is the bug: the optimizer returns a portfolio that violates the declared mandate, and the operator has no signal.

The fix is a **pre-run validator** that hard-fails the cascade with a structured `block_coverage_insufficient` signal **before** the optimizer ever receives data. The operator sees exactly which blocks are uncovered, how much weight is at risk, and which catalog candidates they could import. No silent substitution. No automatic backfill.

---

## Scope

**In scope:**
- New validator function `validate_block_coverage(db, organization_id, profile) -> CoverageReport` in `backend/quant_engine/block_coverage_service.py`.
- Pydantic schema `CoverageReport` with per-block gap detail and suggested catalog candidates.
- Wire the validator into `backend/app/domains/wealth/workers/construction_run_executor.py` as the first step of the run, before any quant code executes.
- New `WinnerSignal` enum value `block_coverage_insufficient` and update to `cascade_telemetry.operator_message` templating.
- Unit + integration tests.
- Minimal frontend surface: extend the existing run-result rendering to display the coverage report when `winner_signal = 'block_coverage_insufficient'`. **Do not build a new import flow** — the frontend only displays the report and a link to the existing approved-universe editor. Operator action is out of this PR's scope.

**Out of scope:**
- Do NOT implement "import from catalog" button. Operator goes to the existing universe editor manually. A future PR can automate if needed.
- Do NOT modify the optimizer cascade, candidate screener, or block_mapping.
- Do NOT re-classify any instruments. Coverage is computed from current state.
- Do NOT add a threshold for "minor gaps" — any block with `target_weight > 0` and `n_candidates = 0` fails the validator. If operator wants to run with a gap, they must set the block's target_weight to 0 in their StrategicAllocation (explicit mandate decision).

---

## Execution Spec

### Section A — `block_coverage_service.py`

**File:** `backend/quant_engine/block_coverage_service.py` (new).

Pure function, no side effects, receives `AsyncSession` + `organization_id` + `profile` and returns a `CoverageReport`.

Algorithm:
1. Load all rows from `strategic_allocation` where `profile = <profile>` and `target_weight > 0`.
2. For each block, count approved candidates:
   ```sql
   SELECT COUNT(*) FROM instruments_org io
   WHERE io.organization_id = :org_id
     AND io.block_id = :block_id
     AND io.approval_status = 'approved'
   ```
3. For each block with `n_candidates = 0`, compute suggested catalog candidates:
   - Look up `strategy_labels_for_block(block_id)` from `vertical_engines.wealth.model_portfolio.block_mapping`.
   - Query `instruments_universe` for count of instruments whose `attributes->>'strategy_label'` matches any of those labels.
   - Return top-5 tickers by AUM (`attributes->>'aum_usd'::numeric DESC NULLS LAST`) as examples. Use `is_active = true` and `is_institutional = true` filters.

Return shape:
```python
class BlockCoverageGap(BaseModel):
    block_id: str
    target_weight: float
    suggested_strategy_labels: list[str]
    catalog_candidates_available: int
    example_tickers: list[str]  # top-5 by AUM

class CoverageReport(BaseModel):
    organization_id: UUID
    profile: str
    is_sufficient: bool  # True iff all blocks have >= 1 candidate
    total_target_weight_at_risk: float  # sum of target_weight for uncovered blocks
    gaps: list[BlockCoverageGap]
```

**Acceptance:** unit test in `backend/tests/quant_engine/test_block_coverage_service.py` covers:
- All blocks have candidates → `is_sufficient=True`, empty `gaps`.
- One block has zero candidates, catalog has 50 candidates for it → `gaps` has one entry, `catalog_candidates_available=50`, `example_tickers` has 5 entries.
- One block has zero candidates, catalog also has zero for its strategy labels → `gaps` entry with `catalog_candidates_available=0`, `example_tickers=[]`.
- Profile has duplicate rows in `strategic_allocation` (current bug — one row per block is what validator should see; DISTINCT on block_id with max target_weight) — validator does NOT crash and counts distinct blocks.

### Section B — Integration into `construction_run_executor.py`

**File:** `backend/app/domains/wealth/workers/construction_run_executor.py`

First step of the run body (after acquiring advisory lock, before loading universe stats):

```python
coverage = await validate_block_coverage(db, organization_id, profile)
if not coverage.is_sufficient:
    await _persist_coverage_failure(db, run_id, coverage)
    await _emit_sse_event(run_id, "block_coverage_insufficient", coverage.model_dump())
    return  # do not proceed to optimizer
```

`_persist_coverage_failure` writes to `portfolio_construction_runs`:
- `status = 'failed'`
- `cascade_telemetry.winner_signal = 'block_coverage_insufficient'`
- `cascade_telemetry.operator_message` = human-readable summary using the coverage report (template below)
- `cascade_telemetry.coverage_report = <full CoverageReport JSON>`

Operator message template:
```
Portfolio construction aborted: {total_target_weight_at_risk:.1%} of the
declared mandate is uncovered. The following blocks have zero approved
candidates in your universe:

{for each gap}
  • {block_id} (target {target_weight:.1%}): {catalog_candidates_available}
    candidates available in the global catalog. Examples: {example_tickers}.
{endfor}

Action: review your approved universe and either import candidates for
the uncovered blocks or adjust the StrategicAllocation to set their
target_weight to zero.
```

Lock release, SSE completion event emission, idempotency: follow the existing patterns in the file — do not invent new ones.

**Acceptance:**
- Integration test in `backend/tests/wealth/test_construction_run_coverage_gate.py`: seed an org with an allocation that has one uncovered block, dispatch a run, assert `status='failed'`, `winner_signal='block_coverage_insufficient'`, SSE event emitted with correct payload, optimizer never invoked (assert via mock that optimizer_service entry point is not called).

### Section C — Enum + schema updates

**Files:**
- `backend/app/domains/wealth/schemas/construction.py` (or wherever `WinnerSignal` lives — grep for existing enum): add `BLOCK_COVERAGE_INSUFFICIENT = "block_coverage_insufficient"`.
- `backend/app/core/db/migrations/versions/0150_winner_signal_block_coverage.py`: if `winner_signal` is stored as a CHECK-constrained string or Postgres ENUM, extend the allowed values. If it's a free-form string, no migration needed — document the decision in the migration file header.

**Acceptance:** `make check` passes. Existing `WinnerSignal`-consuming code (frontend types, other services) accepts the new value without runtime errors.

### Section D — Frontend surface (minimal)

**File:** `frontends/wealth/src/lib/components/portfolio/ConstructionRunResult.svelte` (or wherever the run result is rendered — grep for existing `winner_signal` rendering).

Add a conditional render branch for `winner_signal === 'block_coverage_insufficient'`:
- Headline: "Coverage insufficient — {total_target_weight_at_risk} of mandate uncovered"
- Table of gaps: block name (humanize block_id), target weight, count of catalog candidates, example tickers
- CTA: link to the existing approved-universe page with `?highlight=<block_id>` query param (the target page can ignore the param for now — PR-A22 only emits the link).

Use existing `@netz/ui` components and formatters (`formatPercent`, `formatNumber`). No new styling primitives.

**Acceptance:**
- Manual: run the dev server, dispatch a construction run with an uncovered block, verify the result page renders the gap table and CTA link.
- Type check: `make check-all` green.
- No new npm dependencies.

---

## Global guardrails

- Respect `CLAUDE.md`. Async-first, `expire_on_commit=False`, `lazy="raise"`, RLS via `SET LOCAL`.
- Do not touch optimizer, candidate_screener, classifier, or any existing migration.
- `make check` and `make check-all` before declaring done.
- One commit per Section (A/B/C/D).

## Final report format

1. Unit + integration test output (pytest -v).
2. End-to-end dev smoke: run the validator against org `403d8392-...` profile `moderate` (post-A21 state) and paste the resulting `CoverageReport` JSON — should show 3 gaps (`na_equity_growth`, `na_equity_value`, `alt_commodities`) totaling ~19.79%.
3. Construction run dispatch against same org/profile: confirm it fails with `block_coverage_insufficient` and does not invoke the optimizer.
4. Screenshot of the frontend gap view.
5. List of any unexpected behaviors or follow-ups.
