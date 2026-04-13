# Phase 4 Builder — Session 2: Cascade Timeline + SSE Wiring + Stress/Risk/Advisor Tabs

## Context

This is Phase 4 of a 10-phase Terminal Unification plan documented at
`docs/plans/2026-04-11-terminal-unification-master-plan.md`. Phases 0-3 are
COMPLETE and merged to main. The master plan's Phase 4 section (lines 159-181)
described a 3-column drag-drop builder — that design was REJECTED by the
product owner after implementation in (app)/portfolio proved it was poor UX.
The LOCKED replacement design is at `docs/plans/2026-04-13-phase-4-builder-design.md`
(2-column command center, no drag-drop, PM sets POLICY not PORTFOLIO). When
the master plan and the LOCKED design conflict, the LOCKED design wins.

Session 1 (PR #131, merged) delivered: terminal route at `/portfolio/builder`,
2-column layout, Zone A (RegimeContextStrip), Zone B (CalibrationPanel),
Zone C (RunControls), WEIGHTS tab, TopNav BUILDER tab activation.

## Sanitization — Mandatory Label Mapping

No raw quant jargon may appear in any user-facing label, tooltip, tab name,
or status text. Use the sanitized terms from master plan Appendix D (lines
398-443). Key mappings for Session 2:

| Internal term | Terminal label |
|---|---|
| Phase 1 | Primary Objective |
| Phase 1.5 robust SOCP | Robust Optimization |
| Phase 2 variance-capped | Variance-Capped |
| Phase 3 min-variance | Minimum Variance |
| heuristic fallback | Heuristic Recovery |
| CVaR 95 / cvar_95_conditional | Tail Loss (95% confidence) |
| CLARABEL solver | *never shown — internal only* |
| SCS solver | *never shown — internal only* |
| PCA factor model | Factor Decomposition |
| PC1 / PC2 / PC3 | Market / Style / Sector Factors |
| stress scenario GFC / COVID / TAPER / RATE_SHOCK | Global Financial Crisis / COVID / Taper Tantrum / Rate Shock |
| validation gate | Readiness Check |
| solver infeasible | Could not meet all constraints |
| advisor remediation | Construction Note |

If you encounter any term from the left column in API responses, UI labels,
or component props — replace with the right column. Zero exceptions.

## Audit Support

If at any point during implementation you are uncertain about the current
state of a file, endpoint response shape, or component API — do NOT guess.
Read the file directly. The codebase is the source of truth, not this prompt.
The master plan was ~40% wrong when audited; assume nothing about file
existence or API shapes without verification.

## Branch

`feat/builder-session-2` (already created from main)

## Mission

Implement the construction cascade timeline (centerpiece), SSE stream wiring
with per-phase optimizer events, and 3 more result tabs (STRESS, RISK, ADVISOR).
Add tab-visit tracking gate for future activation unlock (Session 3).

## MANDATORY: Read these files FIRST before writing ANY code

1. `docs/plans/2026-04-13-phase-4-builder-design.md` — LOCKED design reference (entire file), especially Zone D, Zone E, Charts sections
2. `docs/plans/2026-04-13-phase-4-execution-wrapper.md` — Session 2 section
3. `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte` — Session 1 builder shell (the 2-column layout you'll extend)
4. `frontends/wealth/src/lib/components/terminal/builder/RunControls.svelte` — Zone C, will wire to cascade
5. `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` — Workspace state (1711 lines). Focus on: `runPhase` state machine (L362), `runConstructJob()` method, `ConstructRunEvent` interface (L127-139), `constructionRun` (L349), the SSE stream parsing in `_applyRunEvent()`
6. `frontends/wealth/src/lib/components/terminal/runtime/stream.ts` — `createTerminalStream` factory (284 lines)
7. `backend/app/domains/wealth/workers/construction_run_executor.py` — SSE event publication. CRITICAL: read lines 165-289 (event helpers) and 582-896 (run phases) to understand what events exist today
8. `backend/app/core/jobs/tracker.py` — `publish_event()` and `publish_terminal_event()` methods
9. `backend/app/domains/wealth/schemas/sanitized.py` — `humanize_event_type()` and `sanitize_payload()` functions
10. `frontends/wealth/src/lib/components/portfolio/ConstructionNarrative.svelte` — 294 lines, migrate to ADVISOR tab
11. `frontends/wealth/src/lib/components/portfolio/StressScenarioPanel.svelte` — 95 lines, migrate to STRESS tab
12. `frontends/wealth/src/lib/components/portfolio/StressScenarioMatrixTab.svelte` — 165 lines, stress matrix rendering
13. `frontends/wealth/src/lib/components/portfolio/StressCustomShockTab.svelte` — 195 lines, custom shock form
14. `frontends/wealth/src/lib/components/portfolio/charts/FactorExposureBarChart.svelte` — factor exposure chart (existing)
15. `frontends/wealth/src/lib/types/taa.ts` — RegimeBands types + regime label mappings
16. `packages/investintell-ui/src/lib/tokens/terminal.css` — All terminal semantic tokens

## ARCHITECTURE RULES (non-negotiable)

- Svelte 5 runes only: `$state`, `$derived`, `$effect`, `$props`, `$bindable`. No Svelte 4 reactivity.
- All formatting via `@investintell/ui` formatters (`formatPercent`, `formatNumber`, `formatCurrency`, `formatDate`). Never `.toFixed()`, `.toLocaleString()`, or inline Intl.
- CSS uses terminal tokens from `terminal.css` exclusively. Never hex values. Never Tailwind utilities for terminal components.
- `fetch()` + `ReadableStream` for SSE, never EventSource (auth headers needed).
- No localStorage — in-memory state only.
- `<svelte:boundary>` with PanelErrorState fallback on every async-dependent section.
- Monospace font (`var(--terminal-font-mono)`), 1px borders (`var(--terminal-border-hairline)`), zero radius (`var(--terminal-radius-none)`).
- svelte-echarts for all chart visualizations. No Chart.js.

## CRITICAL DESIGN DECISION: CascadeTimeline is Svelte DOM, NOT ECharts graphic

The LOCKED design doc says "ECharts graphic component". After specialist review,
this is WRONG for this use case. The CascadeTimeline is a STATUS PIPELINE (5 discrete
states, text labels, a progress bar), not a data visualization. Reasons to use Svelte DOM:

1. Native CSS `@keyframes` for amber pulse animation (ECharts graphic has no native loop)
2. `clip-path` / `scaleX` for progressive connector fill (ECharts requires full rebuild)
3. Semantic HTML (`role="group"`, `aria-current="step"`) — canvas has no ARIA
4. Svelte 5 `$derived` updates individual pills without re-rendering everything
5. Terminal tokens via CSS variables directly (no `readTerminalTokens()` indirection)
6. Container width handled by CSS flex (ECharts needs manual pixel layout + ResizeObserver)

Build CascadeTimeline as a pure Svelte 5 component with CSS animations. Do NOT use ECharts.

## CRITICAL SSE GAP: Backend needs per-phase optimizer events

**Current state (verified via audit):**

The backend publishes these SSE events:
- `run_started` → "Construction started"
- `optimizer_started` → "Optimizer started"
- `stress_started` → "Stress tests started"
- `advisor_started` → "Advisor started"
- `validation_started` → "Validation gate started"
- `narrative_started` → "Narrative generation started"
- `run_succeeded` / `run_failed` / `run_cancelled` → terminal events

**Problem:** There are NO per-optimizer-phase events. The optimizer runs a 4-phase
cascade (Phase 1 → 1.5 → 2 → 3 → heuristic), but the SSE stream only emits a
single `optimizer_started` event. The cascade timeline needs granular events:
- `optimizer_phase_start` → { phase: "primary" | "robust" | "variance_capped" | "min_variance" | "heuristic" }
- `optimizer_phase_complete` → { phase: ..., status: "succeeded" | "failed" | "skipped", objective_value?: number, duration_ms?: number, solver?: string }

**Frontend event mapping gap:** The frontend `ConstructRunEvent` interface expects
`done` and `error` as terminal events, but the backend publishes `run_succeeded`,
`run_failed`, `run_cancelled`. These need to be aligned.

## DELIVERABLES (6 items)

### 1. Backend: Enrich optimizer SSE events

In `construction_run_executor.py`, find the optimizer cascade section (the code that
calls the CLARABEL 4-phase cascade). Add per-phase SSE publications:

Before each optimizer phase starts:
```python
await publish_event(job_id, "optimizer_phase_start", {
    "phase": "primary",  # or "robust", "variance_capped", "min_variance", "heuristic"
    "phase_label": "Primary Objective",  # sanitized label
})
```

After each optimizer phase completes:
```python
await publish_event(job_id, "optimizer_phase_complete", {
    "phase": "primary",
    "phase_label": "Primary Objective",
    "status": "succeeded",  # or "failed" or "skipped"
    "objective_value": result.objective_value,  # float or null
    "duration_ms": elapsed_ms,  # int
    "solver": "CLARABEL",  # or "SCS" — BUT this is internal-only, do NOT include
})
```

IMPORTANT: Do NOT include solver name in the SSE event payload — it's internal
jargon per the sanitization glossary. The solver is for the event_log only.

Also fix the terminal event mapping: ensure the SSE stream handler translates
`run_succeeded` → `done` and `run_failed`/`run_cancelled` → `error` so the
frontend's existing `ConstructRunEvent` interface works without changes.

Read the actual optimizer cascade code carefully to find where each phase runs.
The optimizer may be in `backend/quant_engine/optimizer_service.py` — verify.

### 2. Zone D: `frontends/wealth/src/lib/components/terminal/builder/CascadeTimeline.svelte`

**Pure Svelte 5 component. NO ECharts.**

Props:
```typescript
interface CascadePhase {
    key: string;           // "primary" | "robust" | "variance_capped" | "min_variance" | "heuristic"
    label: string;         // Sanitized: "Primary Objective", "Robust Optimization", etc.
    status: "pending" | "running" | "succeeded" | "failed" | "skipped";
    objectiveValue?: number | null;
    durationMs?: number | null;
}

interface Props {
    phases: CascadePhase[];
}
```

**Visual structure (160px fixed height):**
```
┌──────────────────────────────────────────────────────────┐
│  [Primary    ]──[Robust     ]──[Variance   ]──[Min Var  ]──[Heuristic]  │
│  [Objective  ]  [Optimization]  [Capped     ]  [         ]  [Recovery ]  │
│  [ 0.0423    ]  [ 0.0389    ]  [           ]  [         ]  [         ]  │
│  [ 1.2s      ]  [ 0.8s      ]  [           ]  [         ]  [         ]  │
└──────────────────────────────────────────────────────────┘
     ✓ green        ✓ green       amber pulse    dim          dim
     ══════════════════════════════▓▓▓▓▓░░░░░░░░░░░░░░░░░░░
                                  ↑ connector fill progress
```

**States per pill (CSS classes):**
- `pending`: opacity 0.35, muted border, muted text
- `running`: amber border, CSS `@keyframes` pulse (1.5s ease-in-out infinite, opacity 1→0.5→1), amber label
- `succeeded`: green border, full opacity, checkmark icon, shows objective value + duration
- `failed`: red border, strikethrough label, X icon
- `skipped`: opacity 0.25, dashed border, italic label

**Connector rail:**
- Background: 2px `var(--terminal-fg-muted)` line spanning full width behind pills
- Fill: 2px `var(--terminal-status-success)` line, width transitions from 0% to N% as phases complete
- Fill width = `((completedIndex + 1) / totalPhases) * 100%`

**CSS only — no JavaScript animation loops, no timers, no requestAnimationFrame.**

### 3. SSE Wiring: Connect cascade to real-time events

In `+page.svelte`, add cascade state management:

```typescript
// Default 5 phases — updated by SSE events
const DEFAULT_PHASES: CascadePhase[] = [
    { key: "primary", label: "Primary Objective", status: "pending" },
    { key: "robust", label: "Robust Optimization", status: "pending" },
    { key: "variance_capped", label: "Variance-Capped", status: "pending" },
    { key: "min_variance", label: "Minimum Variance", status: "pending" },
    { key: "heuristic", label: "Heuristic Recovery", status: "pending" },
];

let cascadePhases = $state<CascadePhase[]>(structuredClone(DEFAULT_PHASES));
```

**Update phases from SSE events.** The workspace's `runConstructJob()` already
streams events. You need to either:
- (a) Extend the workspace to expose per-phase events (preferred), or
- (b) Subscribe to the SSE stream directly from the builder page

Option (a): Add to `portfolio-workspace.svelte.ts`:
- A new `$state` field: `optimizerPhases: CascadePhase[]` initialized with the 5 default phases
- In `_applyRunEvent()`, handle the new `optimizer_phase_start` and `optimizer_phase_complete` events to update the phases array
- Reset `optimizerPhases` to defaults on each new `runConstructJob()` call

Then in `+page.svelte`, derive cascade phases from workspace:
```typescript
const cascadePhases = $derived(workspace.optimizerPhases);
```

**Insert CascadeTimeline into the right column**, between the tab bar and tab content,
visible only when a run is in progress or just completed:

```svelte
{#if workspace.runPhase !== "idle"}
    <CascadeTimeline phases={cascadePhases} />
{/if}
```

### 4. STRESS Tab: Migrate + add stress results display

Migrate content from `StressScenarioPanel.svelte` (95L), `StressScenarioMatrixTab.svelte`
(165L), and `StressCustomShockTab.svelte` (195L).

Create `frontends/wealth/src/lib/components/terminal/builder/StressTab.svelte`.

**Content:**
- Display stress results from `workspace.constructionRun?.stress_results` (array of
  `ConstructionStressResult` — scenario name, nav_impact_pct, cvar_impact_pct, per_block_impact)
- Table format: one row per scenario (Global Financial Crisis, COVID, Taper Tantrum, Rate Shock)
- Columns: Scenario | Portfolio Impact | Worst Block | Best Block
- Color-code impact: red for negative > 5%, amber for 2-5%, green for < 2%
- Use sanitized scenario names (see mapping table above)
- Empty state if no construction run: "Run construction to see stress analysis"
- Terminal styling: mono, hairline borders, zero radius

**Do NOT port the custom shock form** from StressCustomShockTab — that's a separate
interaction that goes in Session 3 or later. Keep Session 2 focused on displaying
results from the construction run.

### 5. RISK Tab: CVaR contribution + Factor exposure

Create `frontends/wealth/src/lib/components/terminal/builder/RiskTab.svelte`.

**Two sections:**

**A) Risk Contribution (top):**
- Source: `workspace.constructionRun?.ex_ante_metrics` and the weights from `workspace.funds`
- Single horizontal 100% stacked bar showing each fund's CVaR contribution as a segment
- Use terminal dataviz palette (`var(--terminal-dataviz-1)` through `var(--terminal-dataviz-8)`)
- Tooltip: fund name + absolute contribution + % of total
- This IS a chart — use svelte-echarts with `createTerminalChartOptions()`
- Chart height: 48px (compact stacked bar, not a tall chart)

**B) Factor Exposure (bottom):**
- Source: `workspace.constructionRun?.factor_exposure`
- Horizontal bar chart grouped by category (Market/Style/Sector — sanitized from PC1/PC2/PC3)
- Bar length = loading magnitude, color = positive (cyan) / negative (amber)
- Use svelte-echarts with `createTerminalChartOptions()`
- Chart height: 200px

**Empty state for both:** "Run construction to see risk analysis"

Read the existing `FactorExposureBarChart.svelte` in `portfolio/charts/` for reference
on how factor data is structured, but build a NEW terminal-native component — do NOT
import from (app) components.

### 6. ADVISOR Tab: Migrate ConstructionNarrative

Create `frontends/wealth/src/lib/components/terminal/builder/AdvisorTab.svelte`.

Migrate content from `ConstructionNarrative.svelte` (294L). This renders:
- Headline + key points (from `workspace.constructionRun?.narrative`)
- Ex-ante metrics strip (from `workspace.constructionRun?.ex_ante_metrics`)
- Holding changes list (from `workspace.constructionRun?.narrative?.holding_changes`)
- Advisor notes (from `workspace.constructionRun?.advisor`)

**Terminal restyling:**
- Headline: `var(--terminal-text-14)`, `var(--terminal-fg-primary)`, font-weight 700
- Key points: bulleted list, `var(--terminal-text-11)`, `var(--terminal-fg-secondary)`
- Metrics strip: 4 inline stat blocks (Tail Loss, Expected Return, Tracking Error, Turnover)
  using terminal stat slab pattern (label above, value below, delta badge if `ex_ante_vs_previous` available)
- Holding changes: terminal table (fund | from weight | to weight | delta)
- All text plain institutional — no markdown rendering, no rich text

**Empty state:** "Run construction to see advisor analysis"

### 7. Tab-visit tracking gate

In `+page.svelte`, add visit tracking for the activation unlock (Session 3):

```typescript
// Track which tabs the PM has visited
let visitedTabs = $state<Set<TabId>>(new Set());

// Mark tab as visited when selected
$effect(() => {
    visitedTabs.add(activeTab);
});

// All 6 must be visited before activation unlocks (Session 3)
const allTabsVisited = $derived(visitedTabs.size === 6);
```

Export `allTabsVisited` or make it accessible for Session 3's ActivationBar.

## FILE STRUCTURE (new + modified files)

```
backend/app/domains/wealth/workers/
  construction_run_executor.py     ← MODIFY: add per-phase optimizer events

frontends/wealth/src/
  routes/(terminal)/portfolio/builder/
    +page.svelte                   ← MODIFY: add CascadeTimeline, wire tabs, visit tracking
  lib/components/terminal/builder/
    CascadeTimeline.svelte         ← NEW: Zone D (Svelte DOM, not ECharts)
    StressTab.svelte               ← NEW: Zone E STRESS tab
    RiskTab.svelte                 ← NEW: Zone E RISK tab (2 charts)
    AdvisorTab.svelte              ← NEW: Zone E ADVISOR tab
  lib/state/
    portfolio-workspace.svelte.ts  ← MODIFY: add optimizerPhases state + event handlers
```

## GATE CRITERIA (all must pass before commit)

1. Construction run streams SSE events with per-phase optimizer progress
2. CascadeTimeline animates in real-time: pending → running (amber pulse) → succeeded/failed per phase
3. Connector rail fills left-to-right as phases complete
4. STRESS tab shows scenario results table after construction run
5. RISK tab shows CVaR contribution stacked bar + factor exposure horizontal bar
6. ADVISOR tab shows narrative headline, key points, metrics strip, holding changes
7. Tab-visit tracking: Set accumulates visited tab IDs
8. All 3 new tabs show proper empty state when no construction run
9. `cd frontends/wealth && pnpm exec svelte-check` — zero errors
10. `cd frontends/wealth && pnpm build` — clean
11. `cd backend && python -m pytest tests/ -x -q` — green (new SSE events)
12. No TypeScript `any` types
13. All formatters from `@investintell/ui`, zero `.toFixed()` / inline Intl
14. Zero hex color values — all from terminal.css tokens
15. Zero raw quant jargon in any user-facing text (check labels against sanitization table)

## IMPORTANT WARNINGS

- Do NOT use ECharts `graphic` for the CascadeTimeline — use pure Svelte 5 + CSS
- Do NOT delete or refactor existing (app)/portfolio/ components — they serve the legacy route
- Do NOT install new npm packages
- Do NOT create mock data — wire to real endpoints or show empty state
- When modifying `portfolio-workspace.svelte.ts`, ADD new fields/methods only — do NOT refactor existing code
- When modifying `construction_run_executor.py`, ADD new publish_event() calls at the appropriate points in the optimizer cascade — do NOT refactor the existing execution flow
- The workspace method `runConstructJob()` already handles POST /construct + SSE stream — extend it, don't rewrite it
- Solver names (CLARABEL, SCS) are internal-only — NEVER include in SSE payloads or UI labels

## Post-Session Checklist

After commit and push, verify these manually in the browser at
http://localhost:5173/portfolio/builder:

1. Select a portfolio with an existing construction run
2. Click "Run Construction" — cascade timeline appears with 5 pills
3. Pills animate: pending → running (amber pulse) → succeeded (green check) in real-time
4. Connector rail fills left-to-right as each phase completes
5. After run completes, switch to STRESS tab — see scenario table
6. Switch to RISK tab — see stacked bar (CVaR) and horizontal bar (factors)
7. Switch to ADVISOR tab — see narrative with headline, metrics, holding changes
8. Switch back to WEIGHTS — weights updated from the new run
9. All 6 tabs visited — verify visitedTabs.size === 6 in console
10. No console errors during the entire flow

If any check fails, fix before considering the session complete.
Visual validation is mandatory — backend tests alone give false confidence.

## What NOT to do

- Do NOT modify `RegimeContextStrip.svelte`, `WeightsTab.svelte`, or `RunControls.svelte` from Session 1
- Do NOT modify existing (app)/portfolio/ components
- Do NOT add drag-drop anywhere
- Do NOT install new npm packages
- Do NOT create mock data or placeholder API calls
- Do NOT put any hex color value in any .svelte file under terminal/
- Do NOT expose solver names (CLARABEL/SCS) in any user-facing text
- Do NOT use ECharts graphic component for the CascadeTimeline

## COMMIT

When all gate criteria pass, commit with:
```
feat(builder): Session 2 — cascade timeline, SSE wiring, stress/risk/advisor tabs

Svelte 5 CascadeTimeline with real-time SSE animation (5-phase optimizer
cascade). Backend enriched with per-phase optimizer events. STRESS tab
(scenario results), RISK tab (CVaR stacked bar + factor exposure), ADVISOR
tab (narrative + metrics + holding changes). Tab-visit tracking for
activation gate.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Push to origin/feat/builder-session-2.
