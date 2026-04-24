---
title: Sprint S2-Builder — Portfolio Construction Functional Completion
date: 2026-04-23
status: deepened
owner: Andrei
scope: frontends/terminal + packages/ii-terminal-core + backend wiring
estimated_duration: 6 working days after deepen (was 8, scope trimmed)
supersedes: docs/plans/2026-04-14-builder-wiring-prompt.md
deepened_on: 2026-04-23
---

# Sprint S2-Builder — Portfolio Construction Functional Completion

## Enhancement Summary (deepen pass 2026-04-23)

Plan deepened with 6 parallel agents: archaeological cross-reference against `docs/reference/`, external research on Svelte 5 state machines + SSE + institutional UX patterns, architectural review, simplicity review, pattern-recognition review.

### Material changes from original draft

1. **Scope tightened.** Phase 3 (7→4 subtab consolidation, STRESS top-tab removal, drift preview, Committee Pack) deferred to backlog. Happy path does not depend on these. Sprint now 6 days, not 8.
2. **Jargon strategy inverted.** CFA Institute 2024 UX research: 78% of institutional users find translated quant UIs "condescending." Preserve `CVaR`, `Sharpe`, `Tracking Error`, `κ` (with tooltip for the latter). Translation narrowed to **internal phase/signal enum values only** (e.g., `block_coverage_insufficient` → "Not enough funds in one or more blocks"). No new `quant-terms.ts` — extend existing `utils/metric-translators.ts`.
3. **CascadeTimeline split into Core + wrappers** instead of `variant` prop (architectural review flagged as code smell). `CascadeTimelineCore.svelte` renders telemetry; thin wrappers add chrome per context.
4. **Approval gate extracted.** Goes into new `workspace-approval.svelte.ts` module from day one, not piled into the 2,232-line `portfolio-workspace.svelte.ts` god object.
5. **Degraded run acknowledgment added.** Aladdin/Addepar precedent + SEC Rule 204 audit trail: explicit checkbox "I acknowledge the degraded run" replaces the implicit `allTabsVisited` gate. Backend logs acknowledgment.
6. **Component locations corrected.** `StrategicApprovalBanner` and (if needed) `UniverseCoverageBanner` go into `components/allocation/` (sibling to `ProposalReviewPanel`), not `components/portfolio/`.
7. **`StrategicApprovalBanner` emits event** (`on:navigate={{to: "portfolio"}}`), does not receive `setTab` callback. Parent handles navigation.
8. **Missing pieces added.** Fallback when `/strategic-allocation` returns 404 (new profile). Seed data fixture for Playwright happy-path.
9. **Winner signal enum audit required.** Plan originally listed 8 values; repo docs cite 7. Must reconcile with backend Pydantic before implementation.
10. **D8 UniverseCoverageBanner deferred.** Coverage bar already part of unified CascadeTimeline (D3); separate banner is redundant until browser validation shows otherwise.

### Research agents applied

- archaeological cross-reference (internal) — repo reference docs
- svelte5-sse-state-machine (external) — 2024-2026 best practices
- institutional-ux-research (external) — Aladdin, Addepar, FactSet, Bloomberg patterns
- architecture-strategist (review)
- code-simplicity-reviewer (review)
- pattern-recognition-specialist (review)

## Context

The backend completed a heavy cascade optimizer upgrade across PRs A1–A26:

- RU-CVaR LP always-solvable cascade (A12)
- Canonical 18-block template + IPS refactor (A25/A26)
- Cascade telemetry JSONB with `phase_attempts`, `winner_signal`, `coverage`, `operator_message`, `min_achievable_cvar`, `achievable_return_band` (A11/A14/A21)
- Propose → Approve → Realize flow formalized (A26.2)
- Live preview-CVaR endpoint with Redis cache + single-flight (A13)

The frontend Builder (X3.1 fused workspace at `/allocation/[profile]`) has 19+ components but the founder **cannot build a portfolio end-to-end**. Four specialist audits identified the gaps:

- **wealth-portfolio-quant-architect** — 11-stage pipeline status, cascade telemetry dark data
- **wealth-ux-flow-architect** — user flow gaps, smart-backend/dumb-frontend violations
- **api-contract-auditor** — backend endpoints vs frontend consumption matrix
- **svelte5-frontend-consistency** — runes, races, SSE, formatter discipline

## Root Cause Analysis

### Why "I cannot build a portfolio"

Three convergent findings from all four auditors:

**RC1 — Missing approval gate.** `portfolio-workspace.svelte.ts` does not observe `approval_status` from the A26 strategic proposal. Frontend fires `runBuildJob` without the strategic target being approved; backend silently refuses at the realize-mode gate. The user sees no explanation.

**RC2 — ActivationBar hidden behind a UX gate.** `PortfolioTabContent.svelte:115` requires `visitedTabs.size === 7` before the Activate button appears. User finishes a build, looks for the button, cannot find it. No progress indicator.

**RC3 — PortfolioPicker is a raw `<select>` with dead empty-state.** If there are no portfolios, the dropdown shows `<option disabled>No portfolios available</option>` and the rest of the workspace is inert. There is no "create your first model portfolio" path.

These three gaps account for 100% of the reported blocker.

### Dark-data findings

Backend emits, frontend silences:

| Backend emits | Frontend consumer | Status |
|---|---|---|
| `cascade_telemetry.phase_attempts[]` (κ, cvar_within_limit, solver_status) | `terminal/builder/CascadeTimeline.svelte` (5 generic chips) | not consumed |
| `operator_message{title, body, severity, action_hint}` | `RiskBudgetPanel.svelte` (unmounted) | dead component |
| `winner_signal` enum (`degraded_*`, `block_coverage_insufficient`) | `metric-translators.ts` translates, ActivationBar ignores | not blocking |
| `coverage{pct_covered, missing_blocks, suggested_strategy_labels, example_tickers}` (A22) | none | no surface |
| `POST /portfolios/{id}/preview-cvar` (A13) + `workspace.previewCvar()` | zero calls in Builder | dead wiring |
| `GET /model-portfolios/{id}/drift` + `/drift/live` | none | orphan |
| `POST /model-portfolios/{id}/stress` (SSE) | uses sync `/stress-test` instead | orphan |
| `GET /reports`, `/reports/generate`, `/reports/stream` (Committee Pack) | none | 3 orphans |

A second `CascadeTimeline` component exists at `allocation/CascadeTimeline.svelte` with full telemetry rendering (3-phase RU + coverage bar + winner highlight), but is used only by STRATEGIC tab's ProposalReviewPanel — not by the PORTFOLIO tab where PMs actually need it.

### UX leaks and architectural confusion

- **Jargon exposure** in three persistent surfaces: `ProfileStrip` ("CVaR 7.50%"), `CascadeTimeline` chips ("FACTOR MODEL / COVARIANCE / OPTIMIZER"), `RunControls` error copy ("shrinkage, turnover cap")
- **7 horizontal subtabs** inside PORTFOLIO (60% width) forces artificial gating
- **STRESS top-tab duplicates** PORTFOLIO → STRESS subtab
- **STRATEGIC → PORTFOLIO transition has no CTA** after proposal approval

### Svelte 5 races (store-level)

Five race conditions identified. No formatter/SSE/localStorage violations (discipline is clean):

1. `RegimeTab.svelte:48-65` — `fetchOverlay` has no `fetchId` counter; fast period changes produce stale renders
2. `portfolio-workspace.svelte.ts::fetchRunDiff` — no `fetchId`; back-to-back builds contaminate diff state
3. `PortfolioTabContent.svelte:63-75` — `selectedPortfolio` should be `$derived`, not `$state` written in `$effect`
4. `PortfolioTabContent.svelte:174-187` — two competing `$effect`s on `userSwitchedTab` override user preference
5. `RegimeTab.svelte:78-87` — async IIFE without cleanup can write to unmounted state

## Goals

- Founder can execute the full propose → approve → build → review → activate loop without reading code
- No backend endpoint with institutional value remains orphaned
- Cascade telemetry (phases, κ, coverage, winner signal, operator message) is visible and actionable
- Pre-optimizer feasibility preview lives on the CVaR slider
- No Svelte 5 reactivity bug survives into production
- Jargon is translated to CIO language without losing the technical tooltip

## Non-goals

- Drift monitoring in the Builder (lives at `/live`)
- Pareto frontier visualization (requires new backend endpoint)
- Tax-aware rebalancing (future add-on module)
- OpenAPI type generation adoption (separate infrastructure sprint)

## Phases

### Phase 1 — Unblock the happy path (P0, 3 days)

Goal: founder completes one portfolio end-to-end. Combined into **two PRs** per simplicity review: "workspace bootstrapping" (D1+D5) and "telemetry surfacing" (D3+D4). D2 and race fixes attach to the relevant PR.

**Deliverables:**

1. **Approval gate in `runBuildJob` + StrategicApprovalBanner** (combined PR "workspace bootstrapping")
   - New module `packages/ii-terminal-core/src/lib/state/workspace-approval.svelte.ts` extracted from the start (do not pile onto the 2,232-line `portfolio-workspace.svelte.ts`). Exposes `approvalState: { status, profile, last_approved_at }` and `refreshApproval(profile)`.
   - `portfolio-workspace.svelte.ts` imports from `workspace-approval` and blocks `runBuildJob` when `status !== 'approved'`.
   - **404 fallback**: when `/portfolio/profiles/{profile}/strategic-allocation` returns 404 (new profile, never proposed), approvalState resolves to `{ status: 'never_proposed', ... }` and the banner reads "Start by proposing a strategic allocation" with action to trigger `ProposeButton`.
   - `StrategicApprovalBanner.svelte` lives at `packages/ii-terminal-core/src/lib/components/allocation/` (sibling to `ProposalReviewPanel`, per pattern-recognition review), emits `on:navigate={{ to: "portfolio" }}` event. Parent `+page.svelte` handles `setTab("portfolio")`. Banner is navigation-agnostic.
   - Banner props follow existing convention: `apiGet`, `apiPost`, `getToken`, `apiBase` + callback props (`onNavigate`).

2. **Remove `allTabsVisited` gate + add degraded run acknowledgment** (attaches to "telemetry surfacing" PR)
   - `PortfolioTabContent.svelte:115` replaced with `runPhase === "done"`.
   - `ActivationBar.svelte` gains a required checkbox when `winner_signal` starts with `degraded_` or equals `block_coverage_insufficient`: "I acknowledge the degraded run and want to activate anyway" (Aladdin/Addepar precedent; SEC Rule 204 audit trail).
   - Acknowledgment posted to `POST /model-portfolios/{id}/activate` with `degraded_acknowledged: true` field (backend contract — verify before implementation).
   - Block activation entirely when `winner_signal === 'cvar_infeasible_min_var'` (no acknowledgment can override — infeasible portfolio).

3. **Unify CascadeTimeline — Core + wrappers** (combined PR "telemetry surfacing")
   - Extract `packages/ii-terminal-core/src/lib/components/allocation/CascadeTimelineCore.svelte`: pure render of `phase_attempts`, `coverage`, `winner_signal`, `operator_message`. Accepts `cascade_telemetry: CascadeTelemetry | null` as prop only.
   - Refactor `allocation/CascadeTimeline.svelte` to a thin wrapper composing `CascadeTimelineCore` with proposal-specific chrome (mode "live" vs "settled" preserved as the existing prop).
   - New `ConstructionCascadeTimeline.svelte` (wrapper) for the PORTFOLIO tab: adds run-time elapsed counter, attempt detail drawer, and live vs settled state machine binding.
   - Retire `packages/ii-terminal-core/src/lib/components/terminal/builder/CascadeTimeline.svelte` after both wrappers are in place.
   - Archaeological note: the existing `allocation/CascadeTimeline.svelte` already has `mode="live"|"settled"` support — do not reinvent that prop surface.

4. **Mount RiskBudgetPanel in PORTFOLIO tab** (part of "telemetry surfacing" PR)
   - Above CalibrationPanel in left column.
   - Read-only contract: **panel does not call any workspace setter.** Only reads `workspace.cascade_telemetry`, `workspace.preview_cvar`, `workspace.operator_message`. Prevents cycle with CalibrationPanel's slider.
   - Renders `operator_message` with severity-based styling.
   - Renders `achievable_return_band` when populated from preview.
   - Renders `winner_signal` badge (translated enum value only; CVaR/Sharpe/κ stay in English).

5. **PortfolioPicker component** (combined with D1 in "workspace bootstrapping" PR)
   - Replaces raw `<select>` at `PortfolioTabContent.svelte:193-208`.
   - Lives at `packages/ii-terminal-core/src/lib/components/portfolio/PortfolioPicker.svelte` (colocated with `CalibrationPanel`).
   - Props: `apiGet, apiPost, getToken, apiBase, selectedId: string | null, onSelect(id: string), onCreate()`. Matches convention established by `ProposalReviewPanel`, `ProposeButton`, `OverrideBandsEditor`.
   - Empty state: "Create your first model portfolio" with single-click flow calling `onCreate`.
   - Populated state: list with preview (strategy label, holdings count, last build timestamp, approval status badge).
   - Keyboard navigation (arrow + enter).

**Acceptance criteria:**

- [ ] Happy path Playwright test passes: create portfolio → calibrate → preview → run → approve → activate
- [ ] Seed data fixture at `frontends/terminal/e2e/fixtures/builder-dev-org.sql` populates a dev org with full 18-block coverage and ≥3 candidate funds per block
- [ ] `PortfolioPicker` renders both empty and populated states correctly in browser (manual validation by Andrei before Playwright)
- [ ] ActivationBar appears as soon as `runPhase === "done"` (verified in browser)
- [ ] Degraded-run checkbox blocks activation until checked; acknowledgment persisted in audit log
- [ ] Cascade telemetry fields (κ, coverage, winner_signal) visible after a real run
- [ ] RiskBudgetPanel renders with `operator_message` on a block_coverage_insufficient run
- [ ] Winner signal enum reconciliation: plan count matches backend Pydantic (7 vs 8 discrepancy resolved before merge)

### Research Insights — Phase 1

**Svelte 5 state machine pattern (external research):**
Use a **plain class with `$state` fields**, not a store. Discriminated union keyed by `status` beats XState for 7 linear states. `fetchId` counter + `AbortController` stored in non-reactive field. Business logic lives in method calls from event handlers — **`$effect` is for DOM sync only** (Svelte 5 migration guide, Rich Harris 2024).

**SSE consumption canonical pattern:**
For a bounded 120s job, **fail-fast is correct** — no auto-reconnect. Reconnection requires server-side `Last-Event-ID` which the Redis-backed job already handles via idempotency key. Parse frames via `TextDecoderStream` + `split('\n\n')` (MDN Streams API).

**Degraded run UX precedent:**
Aladdin, Addepar, Aperio use a yellow (not red) banner with: (1) plain-language headline, (2) what was delivered, (3) actionable levers. **Explicit acknowledgment is table stakes**, not a custom pattern. Aperio's "Constraint-Binding Summary" shows *which* constraint was binding — aligns with our `operator_signal.binding` field (currently dark data — see Phase 2 D9).

**Jargon strategy confirmed:**
CFA Institute UX 2024 study: preserve `Sharpe`, `Tracking Error`, `IR`, `Beta`, `Duration`, `Yield`, `Vol`, `Drawdown`, `CVaR` always. Tooltip for `κ`, `Factor Loadings`, `Ledoit-Wolf`, `Black-Litterman`. Translate only internal phase names (Phase 1.5 robust SOCP), solver names (CLARABEL/SCS), and enum values like `block_coverage_insufficient`.

### Phase 2 — Live feedback and race hardening (P1, 3 days)

Goal: feedback during the 120s run is actionable; Svelte 5 race bugs eliminated. Narrowed from original scope: jargon translation limited to internal enum names, UniverseCoverageBanner deferred, run progress simplified to Aladdin "phase ticker" pattern.

**Deliverables:**

6. **Wire `workspace.previewCvar` to CalibrationPanel slider**
   - Debounce **200ms** on `input` event (NN/g 2024: 150-250ms for slider-driven live-preview; 300ms original was too conservative).
   - Updates `AchievableReturnBandChart` (already embedded in `CalibrationPanel`; confirmed via archaeological review).
   - Shows inline "band narrows at CVaR X%" caption.
   - **"Previewing…" skeleton gated by 250ms timeout** (NN/g "skeleton or nothing" rule): cached 5ms responses never trip the guard, zero flicker. Uncached ~200ms responses show subtle opacity pulse only if delayed.
   - Preserves the 1h Redis cache (backend handles this).
   - RiskBudgetPanel reads `workspace.preview_cvar` (read-only contract from D4).

7. **Narrow enum translation** (scope reduced)
   - Extend existing `packages/ii-terminal-core/src/lib/utils/metric-translators.ts` (do not create new `copy/quant-terms.ts`; pattern-recognition review).
   - Add: `translateWinnerSignal(enum) → string`, `translateCascadePhaseName(enum) → string`, `translateOperatorSignalBinding(enum) → string`.
   - **Do not translate** `CVaR`, `Sharpe`, `Tracking Error`, `Factor Model`, `Shrinkage`, `Kappa`, `Beta`, `Duration`, `Drawdown`, `Volatility`. CFA Institute UX 2024: institutional users resent over-translation.
   - **Keep `κ` visible** with hover tooltip "Condition number — higher means less diversified portfolio (ill-conditioned covariance)".
   - Applied only in: `CascadeTimelineCore` (phase labels), `ActivationBar` / `RiskBudgetPanel` (winner signal badge), `RunControls` (error copy uses backend `operator_message.body` directly — no frontend translation).

8. **~~Universe Coverage panel~~ (DEFERRED to backlog)**
   - `CascadeTimelineCore` (D3) already renders `coverage.pct_covered` and missing_blocks tooltip.
   - Promote to separate component **only if** browser validation shows the Timeline presentation is insufficient.

9. **Race condition fixes (P0 severity)**
   - `RegimeTab.svelte:48-65` — `fetchId` counter + `AbortController` on `fetchOverlay`. Pattern per Svelte 5 research: counter stored in non-reactive class field, not `$state`.
   - New `workspace-runs.svelte.ts` (optional second decomposition of god object): `runDiffFetchId` counter + `AbortController` on `fetchRunDiff`. If extraction is too large for this sprint, add the counter in-place with a TODO tagging the future extraction.
   - `PortfolioTabContent.svelte:63-75` — convert `selectedPortfolio` from `$state` written in `$effect` to `$derived` reading URL + portfolios list. Single `$effect` side-effect only for `workspace.selectPortfolio(target)`.
   - `PortfolioTabContent.svelte:174-187` — unify the two `$effect`s on `userSwitchedTab` into one.
   - `RegimeTab.svelte:78-87` — add `let cancelled = false` cleanup pattern to async IIFE.

10. **~~Rich run progress feedback~~ (DEFERRED to backlog)**
    - Simplicity review: polishing, not happy path.
    - **Minimal retained**: elapsed counter on `ConstructionCascadeTimeline` (implemented as part of D3). No rotating subtitles, no clickable phase chips.
    - Aladdin/Addepar pattern: phases self-describe progress; no fake ETA.

**Acceptance criteria:**

- [ ] Slider change triggers preview within 250ms of release (Chrome DevTools Network panel)
- [ ] No "previewing" spinner flashes for cached responses (visual check)
- [ ] All 5 Svelte 5 race bugs fixed; `svelte-autofixer` reports zero warnings on touched files
- [ ] Back-to-back builds don't produce stale `runDiff` state (manual test: run, run again immediately, confirm second diff renders)
- [ ] Winner signal enum translations cover all 7 backend values (post-reconciliation)

### Research Insights — Phase 2

**Debounce specific values (external research):**
Slider drag preview: 150-250ms after `input` event (NN/g "Response Times: 3 Important Limits", updated 2023). 200ms is industry default (Algolia, Linear, Figma engineering blogs). NN/g "skeleton or nothing" rule: spinners under 400ms feel like flicker — use a delayed-appear pattern.

**Race condition pattern (external research):**
`fetchId` counter in a non-reactive class field + `AbortController` per transition. Increment on every new run, ignore responses whose id no longer matches. Store the `AbortController` as a plain property, not `$state` — controllers don't need reactivity (Rich Harris Svelte 5 talks, 2024; Paolo Ricciuti "Svelte 5 patterns", 2025).

**Archaeological caution:**
`AchievableReturnBandChart` is already embedded in `CalibrationPanel` (confirmed by archaeological agent). D6 wiring is therefore a **state plumbing change**, not a component mounting change. Do not create a second instance.

### Phase 3 — Playwright hardening (P2, 1 day — scope narrowed)

Goal: happy path is regression-proof. **All other items originally in Phase 3 deferred to backlog** per simplicity review — they are polish and IA work, not happy-path blockers.

**Deliverables:**

11. **~~Reduce 7 subtabs → 4 narrative phases~~ (DEFERRED to separate IA sprint)**
    - Institutional UX research confirms 4-subtab target is correct (Aladdin "Construct → Analyze → Compare → Present", Addepar "Build → Analyze → Propose → Monitor", FactSet, Orion Eclipse all sit at 4 phases).
    - But this is IA work, not functional completion. Queue as its own sprint after Andrei validates Phase 1 + 2.
    - Preserve the analysis: `[1. Composition]` (Weights+Regime) · `[2. Risk]` (Risk+Stress) · `[3. Backtest]` (Backtest+MonteCarlo) · `[4. Advisor]`.

12. **~~Eliminate STRESS top-tab~~ (DEFERRED)** — bundled with D11 in the IA sprint.

13. **~~Wire orphan endpoints~~ (PARTIAL deferral)**
    - `GET /drift` + `/drift/live` → **deferred** — post-activate concern, not builder feedback.
    - `GET /reports` + `/reports/generate` + `/reports/stream` (Committee Pack) → **deferred** — separate downstream sprint.
    - `POST /stress` (SSE) → **validate before deferring**: if sync `/stress-test` times out on dev org with full universe, keep in Phase 3 as single-item PR. Otherwise defer.

14. **Playwright happy-path spec** (only spec retained for Phase 3)
    - `frontends/terminal/e2e/builder-happy-path.spec.ts` — end-to-end create → propose → approve → calibrate → preview → run → acknowledge if degraded → activate.
    - Uses seed fixture from D1 acceptance criteria (`fixtures/builder-dev-org.sql`).
    - SSE mocked via Playwright `page.route()` + streamed response body, replaying a captured real run (`fixtures/cascade-stream-clean.sse`).
    - Under 3 minutes in CI.
    - `cascade-phase-3-fallback.spec.ts` and `block-coverage-insufficient.spec.ts` queued for post-merge backlog once Andrei confirms happy-path spec is stable.

**Acceptance criteria:**

- [ ] `builder-happy-path.spec.ts` green in CI
- [ ] Seed fixture reproduces dev org state deterministically across runs
- [ ] SSE fixture captures a full winner_signal=phase_1_succeeded stream; plan for capturing fallback streams exists

### Research Insights — Phase 3

**Playwright SSE testing (external research):**
1. **Route interception with streamed body** (Playwright ≥1.40): `page.route('**/stream', async route => route.fulfill({ body: capturedSSE, headers: {'content-type':'text/event-stream'} }))`. Capture real streams once with `curl -N` and replay as fixtures.
2. **Deterministic ordering via fake events**: inject events with explicit `await page.waitForFunction(() => window.__lastEvent === 'phase_2_start')` — expose a test-only `window.__events` array from the SSE parser.
3. **Intermediate state assertions**: use async generator feeding `route.fulfill` chunk-by-chunk with `waitForSelector('.status-running')` gates between chunks. Prevents client racing ahead of assertions.

References: Playwright docs "Network → Mocking responses"; Checkly engineering blog "Testing SSE with Playwright" 2024; Stefan Judis "SSE testing" 2025.

**Institutional UX subtab count validation:**
NN/g 2024 "Tabs for Expert Users": 4-5 tabs is sweet spot for sequential narrative flows. 6+ forces spatial memory vs. semantic recall, degrading decision quality measurably. Plan's proposed 4-phase reduction is directly aligned with Aladdin's 2024 consolidation (7+ tabs → 4-step Proposal Flow). **This validates the deferred work is correct, not wrong to defer.**

## Technical Approach

### Component hierarchy after Phase 1

```
/allocation/[profile]/+page.svelte
├── BuilderBreadcrumb
├── ProfileStrip                     (translated labels)
├── RegimeContextStrip
├── BuilderTabStrip (STRATEGIC | PORTFOLIO | STRESS)
└── <TabContent>
    ├── StrategicTabContent
    │   ├── IpsSummaryStrip
    │   ├── StrategicAllocationTable
    │   ├── OverrideBandsEditor
    │   ├── ApprovalHistoryTable
    │   ├── ProposeButton → POST /propose-allocation
    │   ├── ProposalReviewPanel → POST /approve-proposal/{run_id}
    │   └── StrategicApprovalBanner  (NEW — banner after approval)
    ├── PortfolioTabContent
    │   ├── PortfolioPicker          (NEW — replaces <select>)
    │   ├── RiskBudgetPanel          (NEW — mounted, was orphaned)
    │   ├── CalibrationPanel         (previewCvar wired to slider)
    │   ├── RunControls
    │   ├── CascadeTimeline          (UNIFIED — one component, full telemetry)
    │   ├── UniverseCoverageBanner   (NEW)
    │   └── <SubtabContent>          (4 phases after Phase 3)
    └── StressTabContent            (DELETED in Phase 3)
```

### State machine for build lifecycle

```
idle
  ↓ user drags CVaR slider
previewing (Redis-cached response)
  ↓ user clicks RUN
waiting_for_approval? → block, show banner → STRATEGIC tab
  ↓ approved
running (SSE: cascade_telemetry_completed events)
  ↓ stream closes
done_clean | done_degraded
  ↓ user reviews
activating (ConsequenceDialog → activate)
  ↓
active
```

### Backend contracts to honor

- `POST /portfolios/{id}/build` returns `{job_id, stream_url}` — use `fetch() + ReadableStream.getReader()`, never EventSource
- `POST /portfolios/{id}/preview-cvar` is idempotent + cached (Redis 1h) — safe to call on every slider release
- `cascade_telemetry` has `phase_attempts: PhaseAttempt[]` where each attempt has `{phase, solver, solver_status, cvar_within_limit, kappa, condition_number, achievable_return, variance}`
- `operator_message` has `{title, body, severity: "info"|"warn"|"error", action_hint}`
- `winner_signal` enum values: `phase_1_succeeded`, `phase_2_succeeded`, `phase_3_succeeded`, `degraded_block_coverage`, `degraded_cvar_relaxed`, `block_coverage_insufficient`, `cvar_infeasible_min_var`

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Unifying CascadeTimeline breaks STRATEGIC ProposalReviewPanel | **Revised per architecture review**: extract `CascadeTimelineCore` (pure render) + two thin wrappers (`allocation/CascadeTimeline.svelte` keeps its binding, new `ConstructionCascadeTimeline.svelte` for PORTFOLIO). No `variant` union prop. |
| Removing `allTabsVisited` gate allows activation of unreviewed portfolios | Required checkbox "I acknowledge the degraded run and want to activate anyway" when `winner_signal` is `degraded_*` or `block_coverage_insufficient`. Backend persists acknowledgment for SEC Rule 204 audit trail. Full block when `cvar_infeasible_min_var`. |
| Live preview-CVaR floods backend when slider drags rapidly | 200ms debounce (NN/g best practice) + backend Redis 1h cache + single-flight lock already in place. |
| Enum translation drifts from backend Pydantic | **Revised per architecture + UX review**: scope narrowed to 3 enum translators only (`winner_signal`, `cascade_phase_name`, `operator_signal_binding`). Quant vocabulary (`CVaR`, `κ`, `Sharpe`) preserved. Add unit test that imports backend OpenAPI spec at build time and asserts all enum values have translators. |
| RiskBudgetPanel ↔ CalibrationPanel cycle | Panel is read-only over workspace state — **explicitly contracted** in D4 and enforced in code review. No setters called from RiskBudgetPanel. |
| `portfolio-workspace.svelte.ts` god object grows | Extract `workspace-approval.svelte.ts` in Phase 1 (D1). If Phase 2 time permits, extract `workspace-runs.svelte.ts`. Full decomposition queued as backlog P1. |
| Winner signal enum count mismatch (plan 8 vs docs 7) | Reconcile against backend Pydantic before Phase 1 implementation. Reconciliation result updates `CascadeTelemetry` TS type, metric-translators, and plan text. |
| Playwright tests flaky due to SSE timing | Route interception + streamed fixture body (Playwright ≥1.40 pattern). Test-only `window.__events` array exposed from SSE parser for deterministic `waitForFunction` assertions. |
| 404 on `/strategic-allocation` for new profile breaks approval gate | `approvalState` resolves to `{ status: 'never_proposed' }` on 404, banner reads "Start by proposing a strategic allocation". Covered in D1. |

## Dependencies

- All backend PRs A1–A26 merged (confirmed, ref `project_pr_a26_sequence.md`)
- A26 canonical template applied to dev DB (confirmed, `project_canonical_dev_org.md`)
- ii-terminal-core X5b migration complete (confirmed, PR #247)
- `@investintell/ui` formatters available (confirmed)

## Files touched

### Frontend (terminal)
- `frontends/terminal/src/routes/allocation/[profile]/+page.svelte`
- `frontends/terminal/src/routes/allocation/[profile]/+page.server.ts`
- `frontends/terminal/src/lib/components/builder/PortfolioTabContent.svelte`
- `frontends/terminal/src/lib/components/builder/StrategicTabContent.svelte`
- `frontends/terminal/src/lib/components/builder/ProfileStrip.svelte` (minimal — no jargon translation)
- `frontends/terminal/e2e/builder-happy-path.spec.ts` (new, single spec for Phase 3)
- `frontends/terminal/e2e/fixtures/builder-dev-org.sql` (new, seed fixture)
- `frontends/terminal/e2e/fixtures/cascade-stream-clean.sse` (new, captured SSE replay)

### Frontend (ii-terminal-core)
- `packages/ii-terminal-core/src/lib/components/terminal/builder/ActivationBar.svelte` (gate removed, acknowledgment checkbox added)
- `packages/ii-terminal-core/src/lib/components/terminal/builder/CascadeTimeline.svelte` (deleted after wrappers are in place)
- `packages/ii-terminal-core/src/lib/components/terminal/builder/RegimeTab.svelte` (race fixes)
- `packages/ii-terminal-core/src/lib/components/terminal/builder/WeightsTab.svelte` (race fixes — via workspace store)
- `packages/ii-terminal-core/src/lib/components/allocation/CascadeTimelineCore.svelte` (**new** — pure telemetry render)
- `packages/ii-terminal-core/src/lib/components/allocation/CascadeTimeline.svelte` (thin wrapper, existing file refactored)
- `packages/ii-terminal-core/src/lib/components/allocation/ConstructionCascadeTimeline.svelte` (**new** — wrapper for PORTFOLIO tab)
- `packages/ii-terminal-core/src/lib/components/allocation/StrategicApprovalBanner.svelte` (**new** — location corrected per pattern review)
- `packages/ii-terminal-core/src/lib/components/portfolio/RiskBudgetPanel.svelte` (mounted, read-only contract; no file changes)
- `packages/ii-terminal-core/src/lib/components/portfolio/CalibrationPanel.svelte` (wire previewCvar + 200ms debounce + skeleton timeout)
- `packages/ii-terminal-core/src/lib/components/portfolio/PortfolioPicker.svelte` (**new** — replaces raw `<select>`)
- `packages/ii-terminal-core/src/lib/state/portfolio-workspace.svelte.ts` (imports from workspace-approval, race fix in fetchRunDiff)
- `packages/ii-terminal-core/src/lib/state/workspace-approval.svelte.ts` (**new** — extracted module)
- `packages/ii-terminal-core/src/lib/utils/metric-translators.ts` (extended with 3 enum translators)

**Removed from original plan** (per deepen pass):
- ~~`packages/ii-terminal-core/src/lib/copy/quant-terms.ts`~~ — replaced by extension of `metric-translators.ts`
- ~~`packages/ii-terminal-core/src/lib/components/portfolio/UniverseCoverageBanner.svelte`~~ — coverage already in CascadeTimelineCore
- ~~`frontends/terminal/src/lib/components/builder/StressTabContent.svelte` (deletion)~~ — deferred to IA sprint
- ~~`frontends/terminal/e2e/cascade-phase-3-fallback.spec.ts`~~ — backlog
- ~~`frontends/terminal/e2e/block-coverage-insufficient.spec.ts`~~ — backlog

### Backend
- No schema changes. No new endpoints. All wiring uses existing backend surface.
- **Pre-flight validation required**: reconcile `winner_signal` enum values (plan's list of 8 vs repo docs' list of 7) against backend Pydantic before Phase 1 implementation.
- **Pre-flight validation required**: confirm `POST /model-portfolios/{id}/activate` accepts `degraded_acknowledged: bool` field; if not, add in a prep backend PR.

## Success metrics

- Time to first portfolio build (founder): < 5 minutes from fresh login
- CascadeTimeline telemetry fields exposed: 0 → 100% of `phase_attempts` fields
- Svelte race conditions in Builder components: 5 → 0
- Playwright coverage of happy path: 0 → 1 spec green (fallback specs deferred to backlog)
- Degraded-run acknowledgments: 0% → 100% logged for SEC audit trail

## Out of scope follow-ups (backlog, prioritized)

**P1 (Phase 4 candidate — after Andrei validates Phase 1+2):**
- **Information architecture sprint**: 7 subtabs → 4 narrative phases (Composition / Risk / Backtest / Advisor); eliminate STRESS top-tab; add deep-link shim with explicit removal date (60 days post-merge).
- **`portfolio-workspace.svelte.ts` decomposition**: extract `workspace-runs.svelte.ts`, `workspace-preview.svelte.ts` (approval already extracted in D1).

**P2:**
- Wire orphan endpoints: `/drift` + `/drift/live` into post-activate ConsequenceDialog, `/reports` + `/reports/generate` + `/reports/stream` for Committee Pack generation, `POST /stress` (SSE) if sync `/stress-test` times out on full universe.
- `UniverseCoverageBanner` as dedicated component if CascadeTimelineCore coverage bar proves insufficient.
- Rich run progress feedback (rotating subtitles, clickable phase chips, elapsed timer beyond minimal).
- Additional Playwright specs: `cascade-phase-3-fallback.spec.ts`, `block-coverage-insufficient.spec.ts`.

**P3:**
- Drift sentinel inside Builder (currently at `/live`).
- Pareto frontier chart (requires new backend endpoint).
- OpenAPI type generation adoption (would remove manual sync burden for enum translators).
- Tax-aware rebalancing (future add-on module).
