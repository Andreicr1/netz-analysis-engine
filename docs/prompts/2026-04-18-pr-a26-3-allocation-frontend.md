# PR-A26.3 — Allocation Page Frontend (Propose / Approve / Override UI)

**Date**: 2026-04-18
**Status**: P0 PRODUCT — operator-facing UI that activates the propose→approve→realize loop shipped in A26.1 + A26.2.
**Branch**: `feat/pr-a26-3-allocation-frontend`
**Predecessors merged**: A21 #207, A22 #209, A23 #210, A24 #212, A25 #213, A26.0 #215, #216 label patch, A26.1 #214, A26.2 #217.

---

## Context — product model

Allocation governance moves from 162 IC-set parameters per org (54 per profile × 3 profiles) to ~3-8 human inputs per org (CVaR limits + ad-hoc overrides + mandate exclusions). IC's role shifts from "specify the bands" to "approve / iterate on the optimizer's proposal."

The page this PR builds is the **IPS governance surface** — where operator:
1. Reviews current Strategic allocation (approved IPS anchor).
2. Triggers propose (CVaR-optimal reallocation).
3. Reviews the proposal as a diff vs current Strategic.
4. Approves atomically OR applies per-block overrides + re-proposes.
5. Inspects approval history (who approved what when).

Distinct from `/portfolio` Builder, which consumes the approved Strategic to run realize per individual portfolio. Allocation page = IC governance (quarterly). Builder = portfolio management (monthly).

Route: `/portfolio/profiles/{profile}/allocation` (standalone). Accessible from TopNav breadcrumb AND contextual links in Builder / realize results.

---

## Scope

**In scope (9 sections, A–I):**
- 2 new backend GET endpoints + types generation.
- Svelte 5 page shell with layout cage compliance.
- 4 new Svelte 5 components: `StrategicAllocationTable`, `ProposalReviewPanel`, `ProposeButton`, `OverrideBandsEditor`, `ApprovalHistoryTable`.
- SSE-wired propose trigger (`fetch` + `ReadableStream`, NOT `EventSource`).
- Atomic approve flow with confirm modal for `cvar_feasible=false`.
- Override modal with rationale.
- Donut chart + diff bars via `svelte-echarts`.
- Navigation wiring from TopNav + contextual links from Builder.
- Playwright e2e smoke of the full propose→approve cycle in browser.

**Out of scope:**
- Do NOT touch A26.1/A26.2 backend behavior beyond the 2 new read endpoints.
- Do NOT modify Builder beyond adding one contextual link.
- Do NOT rewire `drift_check` worker (that's A26.4).
- Do NOT add CVaR limit editing UI — that's a future PR (operator edits `portfolio_calibration` indirectly).
- Do NOT implement "Rebalance Now" action — drift-triggered rebalance lives separately.
- Do NOT build a history drill-down (clicking a past approval to see its bands) — v1 shows tabular summary only.

---

## Vocabulary convention

IC-technical terms allowed in labels (operator audience) WITH tooltips giving plain-English definition:

| Term | Allowed | Tooltip text |
|---|---|---|
| CVaR | yes | "Expected loss in the worst 5% of scenarios over a 1-year horizon." |
| Drift band | yes | "Tolerance around target weight before rebalancing is triggered." |
| Override | yes | "Ad-hoc constraint on a block's weight for the next proposal." |
| Strategic allocation | yes | "Approved IPS anchor — the target + drift for each asset class." |
| Proposal | yes | "Optimizer's suggested reallocation given current CVaR limit." |
| Excluded | yes | "Mandate-level exclusion — block forced to zero regardless of optimizer output." |

Forbidden in user-visible labels (implementation jargon):
- `winner_signal`, `phase_1_ru_max_return`, `regime=RISK_OFF`, `Ledoit-Wolf`, `mu_sanity_gate`, `historical_1y`, `CLARABEL`, `run_mode`, `kappa`, `factor_model_partial_fit`, etc.

Use `@netz/ui` formatters (`formatPercent`, `formatCurrency`, `formatDate`, `formatDateTime`) — NEVER `.toFixed()` or inline `Intl.NumberFormat`.

---

## Execution Spec

### Section A — Backend read endpoints + OpenAPI regen

**File:** `backend/app/domains/wealth/routes/model_portfolios.py` (append to `portfolio_meta_router`).

Endpoint 1:
```python
@router.get(
    "/profiles/{profile}/strategic-allocation",
    response_model=StrategicAllocationResponse,
)
async def get_strategic_allocation(
    profile: str, db: AsyncSession, ...,
) -> StrategicAllocationResponse:
    """Return the 18 canonical rows for (org, profile) with their current
    approved target/drift bands, override_min/max, excluded flag, and
    last-approval metadata.
    """
```

Response shape:
```python
class StrategicAllocationBlock(BaseModel):
    block_id: str
    block_name: str  # humanized (e.g., "US Large-Cap Equity")
    target_weight: float | None
    drift_min: float | None
    drift_max: float | None
    override_min: float | None
    override_max: float | None
    excluded_from_portfolio: bool
    approved_from_run_id: UUID | None
    approved_at: datetime | None
    approved_by: str | None

class StrategicAllocationResponse(BaseModel):
    organization_id: UUID
    profile: str
    cvar_limit: float  # from portfolio_calibration
    has_active_approval: bool  # True if any row has approved_at IS NOT NULL
    last_approved_at: datetime | None
    last_approved_by: str | None
    blocks: list[StrategicAllocationBlock]  # 18 rows, stable order (matches A25 canonical set)
```

Block name humanization: hardcode mapping in a small helper module (`backend/app/domains/wealth/utils/block_display.py`) — `na_equity_large` → "US Large-Cap Equity", `fi_us_aggregate` → "US Aggregate Bond", etc. 18 entries, one-time hardcode.

Endpoint 2:
```python
@router.get(
    "/profiles/{profile}/approval-history",
    response_model=ApprovalHistoryResponse,
)
async def get_approval_history(
    profile: str, db: AsyncSession,
    limit: int = 10, offset: int = 0,
) -> ApprovalHistoryResponse:
    """Paginated list of allocation_approvals rows for (org, profile),
    newest first, with cvar/E[r] snapshots.
    """
```

Response:
```python
class ApprovalHistoryEntry(BaseModel):
    approval_id: UUID
    run_id: UUID
    approved_by: str
    approved_at: datetime
    superseded_at: datetime | None
    cvar_at_approval: float | None
    expected_return_at_approval: float | None
    cvar_feasible_at_approval: bool
    operator_message: str | None
    is_active: bool  # computed: superseded_at IS NULL

class ApprovalHistoryResponse(BaseModel):
    organization_id: UUID
    profile: str
    total: int
    entries: list[ApprovalHistoryEntry]
```

**Integration tests:**
- `test_get_strategic_allocation.py`: seed allocation with partial approvals, assert 18 rows returned in stable order with correct approval metadata.
- `test_get_approval_history.py`: seed 3 approvals (1 active + 2 superseded), assert order newest-first, `is_active` computed correctly, pagination works.

After endpoints merged, regenerate TS types:
```bash
make types
```
Generated types land in `packages/ui-types/` or equivalent — grep for existing type-generation output dir.

### Section B — Page shell + layout cage

**File:** `frontends/wealth/src/routes/(app)/portfolio/profiles/[profile]/allocation/+page.svelte` (create path).

Also a `+page.server.ts` or `+page.ts` loader that fetches both endpoints in parallel + the A26.1 `latest-proposal` endpoint.

Layout cage pattern (per `feedback_layout_cage_pattern.md`):
```svelte
<div class="h-[calc(100vh-88px)] p-6 overflow-y-auto">
  <!-- page content -->
</div>
```

Page structure (top to bottom):
1. Breadcrumb row: "Portfolio > Allocations > {Profile Name}" (uses existing TopNav breadcrumb primitive).
2. KPI row (4 cards, horizontal): `CVaR Limit` / `Current Expected Return` / `Last Approved` / `Allocation Status` (badge: Active / Never Approved / Pending Proposal).
3. Main grid (2-column):
   - Left column: `StrategicAllocationTable` + inline donut chart of approved block weights.
   - Right column: `ProposalReviewPanel` (if latest-proposal exists) OR `ProposeButton` CTA panel (if no pending proposal).
4. Full-width below: `ApprovalHistoryTable` (collapsible, default collapsed).

Use Svelte 5 runes. Props via `$props()`. Reactive state via `$state` + `$derived`. Never `localStorage`; use in-memory state + refetch on actions.

Breadcrumb + navigation wiring is Section H — keep Section B focused on layout + data loading.

**Acceptance:**
- Page loads without console errors for each of the 3 profiles against the dev DB canonical org.
- All formatters from `@netz/ui` — ESLint rule (per `CLAUDE.md`) must pass.
- Layout cage respected — no content overflow past the bottom margin.

### Section C — `StrategicAllocationTable.svelte`

**File:** `frontends/wealth/src/lib/components/allocation/StrategicAllocationTable.svelte`.

18 rows × 5 columns (per `feedback_datagrid_vs_viewer.md` "4-6 cols max"):

| Col | Content | Tooltip |
|---|---|---|
| Asset Class | Humanized block name + excluded badge if applicable | — |
| Target | `formatPercent(target_weight)` or "—" if NULL | "Approved target weight from last IPS approval." |
| Drift Band | `{formatPercent(drift_min)} - {formatPercent(drift_max)}` or "—" | "Tolerance before rebalance triggers." |
| Override | `{formatPercent(override_min)} - {formatPercent(override_max)}` or "—" | "Operator-set constraint for the next proposal." |
| Actions | Icon button "Edit Override" opening the Section F modal | — |

Excluded badge: small pill "Excluded" when `excluded_from_portfolio = true`. Corresponding row is dimmed.

Row click: no navigation (no drill-down in v1).

Donut chart integration: small `<svelte-echarts>` component alongside the table showing current approved `target_weight` distribution (18 slices, grouped by asset class family: Equity / FI / Alt / Cash — use grouping color palette from `@netz/ui` tokens). When NO approval exists (all targets NULL), show empty-state "Awaiting first approval" instead of empty donut.

**Acceptance:** component renders all 18 rows against mock response from Section A; tooltips visible on hover; override edit button fires a `dispatch('edit-override', { block_id })` event.

### Section D — `ProposalReviewPanel.svelte`

**File:** `frontends/wealth/src/lib/components/allocation/ProposalReviewPanel.svelte`.

Renders only when a pending `latest-proposal` exists (either no approval yet OR latest-proposal `requested_at` > last `approved_at`).

Layout:
- Header: "Proposal generated {formatRelativeTime(requested_at)}" + metrics row (Proposed E[r], Proposed CVaR, Target CVaR, Feasible badge).
- Diff chart: horizontal bars, one per block, showing `proposed_target - current_target` (positive right, negative left). `svelte-echarts`. Zero line visible. Bars colored by direction (green increase, red decrease) — colors from `@netz/ui` semantic tokens, no hex.
- Table (expandable, default collapsed): 18 blocks with columns `Asset Class | Current | Proposed | Delta`.
- Action footer: `Approve Allocation` primary button + `Dismiss Proposal` tertiary link.

**Approve flow:**
1. Click `Approve Allocation`.
2. If proposal's `cvar_feasible === false`: open confirm modal with warning "Proposal did not reach the CVaR target; best achievable was X%. Approve anyway?" + `Confirm Approval` destructive button. Only on confirm click, proceed.
3. POST `/portfolio/profiles/{profile}/approve-proposal/{run_id}` with `confirm_cvar_infeasible: true` when applicable.
4. On success: toast "Allocation approved", refetch strategic-allocation + approval-history endpoints, hide this panel.
5. On 409 / 500: toast error with server message.

**Dismiss flow:**
- Just re-query latest-proposal with a filter; or simply leave the proposal in DB and let the user trigger a new propose to supersede. v1 simplest: "Dismiss" is cosmetic — hides the panel locally via `$state`, reappears on page refresh. Document this in a code comment.

**Acceptance:** given a mocked feasible proposal, approve button fires POST with correct body; given an infeasible proposal, confirm modal appears first.

### Section E — `ProposeButton.svelte`

**File:** `frontends/wealth/src/lib/components/allocation/ProposeButton.svelte`.

Renders as CTA panel when no pending proposal exists:
- Headline: "Generate New Proposal"
- Body text: "The optimizer will propose a CVaR-optimal allocation given your current {formatPercent(cvar_limit)} risk limit and any active overrides."
- Button: `Propose Allocation` (primary).

**Propose flow (SSE):**

1. Click → disable button, swap label to "Proposing..." with spinner.
2. `fetch` POST `/portfolio/profiles/{profile}/propose-allocation` (JSON body per A26.1 spec).
3. Response returns `{ job_id, sse_url }`.
4. Open SSE stream via `fetch(sse_url)` + `ReadableStream` (NEVER `EventSource` — per `CLAUDE.md`). Parse events line-by-line.
5. Map event types to progress UI:
   - `propose_started` → "Preparing universe..."
   - `optimizer_started` → "Optimizing..."
   - `optimizer_phase_complete` → "Phase {phase} complete"
   - `propose_ready` / `propose_cvar_infeasible` → "Proposal ready"
   - `completed` → close stream, toast success, refetch `latest-proposal`, re-render page (Section D panel should now appear).
6. On stream error: toast "Proposal failed — {error message}". Re-enable button.

Use a simple progress bar or spinner with rolling text — no full-screen modal. User can navigate away and come back; proposal completes in DB regardless.

**Acceptance:** E2E playwright test (Section I) verifies full SSE flow end-to-end with real optimizer run against dev DB.

### Section F — `OverrideBandsEditor.svelte`

**File:** `frontends/wealth/src/lib/components/allocation/OverrideBandsEditor.svelte`.

Modal triggered by row action in Section C. Props: `block_id`, `block_name`, `current_override_min`, `current_override_max`.

Form fields:
- `Override Min` — numeric input, 0-100%, optional.
- `Override Max` — numeric input, 0-100%, optional.
- `Rationale` — textarea, required, min 10 chars. Stored in `strategic_allocation.rationale` column (already exists per schema).

Validation:
- At least one of min/max provided (both NULL = clear override via dedicated button).
- If both provided: min ≤ max.
- Informative notice: "Override takes effect on next proposal. Current holdings are unaffected."

Actions:
- `Clear Override` — sets both to NULL, POSTs set-override.
- `Save Override` — POSTs set-override with provided values.

On success: toast, close modal, refetch strategic-allocation.

**Acceptance:** validation errors block save; successful save refetches + closes modal.

### Section G — `ApprovalHistoryTable.svelte`

**File:** `frontends/wealth/src/lib/components/allocation/ApprovalHistoryTable.svelte`.

Collapsible section, default collapsed. When expanded, shows paginated table (max 5 rows visible, paginated):

| Col | Content |
|---|---|
| Status | `Active` badge (green) if `is_active`, else `Superseded` (muted) |
| Approved At | `formatDateTime(approved_at)` |
| Approved By | operator id |
| CVaR | `formatPercent(cvar_at_approval)` |
| Expected Return | `formatPercent(expected_return_at_approval)` |
| Feasible | checkmark or warning badge based on `cvar_feasible_at_approval` |
| Message | truncated to 60 chars, tooltip for full |

Pagination: `Previous` / `Next` using `offset` query param. Default `limit=5`.

No drill-down in v1.

**Acceptance:** renders mocked history response; pagination works; active badge logic correct.

### Section H — Navigation wiring

1. **TopNav → Portfolio → Allocations** (menu item). Links to `/portfolio/profiles` — list of 3 profile cards, each linking to `/portfolio/profiles/{profile}/allocation`.

   New route: `frontends/wealth/src/routes/(app)/portfolio/profiles/+page.svelte` (simple list page, 3 cards).

2. **Builder contextual link:** in `frontends/wealth/src/routes/(app)/portfolio/...` (grep for Builder entry point), each portfolio card gets footer text `Profile: {Profile Name} — last approved {formatRelativeTime}` with `[View Allocation →]` link.

3. **Realize results contextual link:** wherever realize run results are rendered, add footer "Based on {Profile} allocation approved by {user} on {date} [View →]".

**Acceptance:** all 3 entry points route to the same allocation page; breadcrumbs reflect hierarchy.

### Section I — Playwright e2e smoke

**File:** `frontends/wealth/tests/e2e/allocation-propose-approve.spec.ts` (or equivalent path — grep existing playwright configs).

Test scenario (against dev DB docker):
1. Navigate to `/portfolio/profiles/moderate/allocation`.
2. Assert page renders with 18-row Strategic table (may show "—" placeholders if no prior approval).
3. Click `Propose Allocation` button.
4. Wait for progress UI; assert final state shows `ProposalReviewPanel` with 18 diff bars.
5. Click `Approve Allocation`.
6. Assert toast "Allocation approved" appears.
7. Assert Strategic table now shows populated `target_weight` + `drift_min/max`.
8. Assert `ApprovalHistoryTable` (expanded) shows a new `Active` row with today's timestamp.

Test MUST run against a real backend (the dev DB smoke already validated propose→approve works end-to-end in A26.2).

**Acceptance:** test passes in CI or local `playwright test`. Screenshots captured on failure for debugging.

---

## Ordering inside this PR

A (backend + types) → B (page shell) → C (table) → D (proposal review) → E (propose button) → F (override editor) → G (history) → H (navigation) → I (e2e smoke).

One commit per Section. Section A can land with its own backend tests before frontend starts.

## Global guardrails

- `CLAUDE.md` rules. Svelte 5 runes only. `fetch` + `ReadableStream` for SSE. No `localStorage`. No Chart.js; `svelte-echarts`. All formatters from `@netz/ui`.
- No new npm dependencies (verify `svelte-echarts` + playwright already in package.json).
- `make types` after Section A before starting Section B.
- `make check-all` green (pnpm check + pnpm lint + pnpm build).
- **Visual validation** per `feedback_visual_validation.md` — before declaring done, start the wealth dev server and navigate to the page for all 3 profiles. Confirm: no console errors; 18 rows render; propose button triggers optimizer; review panel appears; approve works; donut chart renders; diff bars render; history table paginates.

## Final report format

1. Backend test output + snippets of generated TS types for the 2 new endpoints.
2. Component unit test output (Vitest + @testing-library/svelte).
3. Playwright e2e output (success trace + any screenshots).
4. Manual browser validation checklist (screenshots for each profile):
   - Conservative allocation page with no approval → KPI shows "Never Approved", donut empty state.
   - Moderate allocation page after approve → KPI shows date, donut populated.
   - Proposal pending view with diff bars.
   - Override modal open with validation error.
   - Approval history expanded with 1+ row.
5. Confirm `make check-all` green.
6. List deviations from spec.
