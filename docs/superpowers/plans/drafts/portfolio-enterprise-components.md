# Portfolio Vertical — Svelte 5 Enterprise Component Architecture

> **Scope:** This document covers ONLY the Svelte 5 component architecture for `frontends/wealth/src/routes/(app)/portfolio/` and `frontends/wealth/src/lib/components/portfolio/`. DB schema, quant engine semantics, ECharts specs and routing flows are owned by sibling specialists. Reference for format and quality bar: `docs/superpowers/plans/2026-04-07-discovery-fcl-analysis-page.md`.

> **Author:** svelte5-frontend-consistency consultant
> **Date:** 2026-04-08
> **Branch context:** `feat/discovery-fcl` (Discovery Phase 2.2 will move `FlexibleColumnsLayout` → `FlexibleColumnLayout` neutral primitive in `@netz/ui` — Portfolio Builder rides on the same migration).

---

## Executive Summary

Andrei's three top complaints all map to **data-flow gaps** that the current component tree masks behind plausible-looking UI:

1. **Sliders are dead.** `PolicyPanel.svelte` binds to local `$state` and calls `workspace.updatePolicy()` — and that store method is a literal NO-OP (line 684-688 of `portfolio-workspace.svelte.ts`). Moving the slider mutates nothing, fetches nothing, displays nothing. The whole calibration surface is theatrical.
2. **Stress test UI ≠ engine.** Backend ships 4 named scenarios (`gfc_2008`, `covid_2020`, `taper_2013`, `rate_shock_200bps` — `vertical_engines/wealth/model_portfolio/stress_scenarios.py`). UI exposes a generic 3-input custom form (equity/rates/credit). The named scenarios are unreachable from any button.
3. **Construct returns no narrative.** Backend `/construct` returns 8 numeric fields under `optimization` (expected_return, vol, Sharpe, solver, status, cvar\_\*). No binding constraints, no phase explanation, no critic, no per-holding rationale. UI consumes only `cvar_within_limit`. The "Run Construct" experience is "spinner → table refreshes → no story".

These three problems aren't visual; they're a contract gap between the smart backend and the dumb frontend (per Andrei's `feedback_smart_backend_dumb_frontend` rule). The component redesign below assumes the backend will be enriched in parallel — this doc specifies what the **frontend contracts** must look like once that lands, plus the workbench-grade primitives needed for the Live phase.

**Big architectural calls:**
1. Split portfolio into **3 distinct surfaces** (Builder / Analytics / Live Workbench) with three different layout primitives — FCL is the wrong shape for live monitoring.
2. **Calibration becomes the spine of the Builder column 3.** Every quant input the engine accepts must be reachable from one panel, with explicit "Apply" gating (not reactive sliders) and a SSE-driven preview metrics strip.
3. **`ConstructionNarrative.svelte`** is the missing component that converts the backend's enriched response into the IC-grade explanation Andrei wants. Until backend enriches, ship it with a single "Insufficient explainability — backend payload missing fields X, Y, Z" empty state — never with mock data.

---

## Part A — Audit of Current State (the load-bearing section)

### A.1 — Component table

| # | Component | File | Status | Issues |
|---|---|---|---|---|
| 1 | `+layout.svelte` (portfolio) | `routes/(app)/portfolio/+layout.svelte` | REAL | OK. Pill nav (Builder / Model / Analytics & Risk / Advanced). Reactivity via `$derived.by` over `$page.url.pathname`. Hardcoded hex `#0177fb`, `#0e0f13` — should migrate to tokens. |
| 2 | `+page.svelte` (Builder) | `routes/(app)/portfolio/+page.svelte` | PARTIAL | Layout orchestrator. Mounts `FlexibleColumnLayout` (Discovery migration target). **"New Portfolio" button (line 115-118) has NO `onclick` handler — pure stub.** Sub-pills (Models/Universe/Policy) work. |
| 3 | `+page.server.ts` (Builder) | `routes/(app)/portfolio/+page.server.ts` | REAL | Loads `/model-portfolios`. Plain `api.get` with `.catch(() => [])` — silent failure, no `RouteData<T>` contract. |
| 4 | `BuilderColumn.svelte` | `lib/components/portfolio/BuilderColumn.svelte` | REAL | Action bar + `BuilderTable`. `<svelte:boundary>` + `PanelErrorState` correctly applied. Hardcoded hex palette. View Chart / Construct / Stress Test buttons all wired. |
| 5 | `BuilderTable.svelte` | `lib/components/portfolio/BuilderTable.svelte` | REAL | 3-level tree table (Group → Block → Fund), drag-drop, weight rendering. **Violation: `value.toFixed(0)` at line 233.** |
| 6 | `UniverseColumn.svelte` | `lib/components/portfolio/UniverseColumn.svelte` | REAL | Wraps `UniverseTable` + reverse drop target. `<svelte:boundary>` applied. |
| 7 | `UniverseTable.svelte` | `lib/components/portfolio/UniverseTable.svelte` | REAL | Enterprise-density 12-col table, formatters all from `@netz/ui`. Comment confirms zero `.toFixed`. **This is the canonical base for the Discovery `EnterpriseTable` extraction.** |
| 8 | `UniversePanel.svelte` | `lib/components/portfolio/UniversePanel.svelte` | DEAD | Legacy table replaced by `UniverseColumn` + `UniverseTable`. Zero importers in `frontends/wealth/src` (grep confirmed). **Delete in cleanup PR.** |
| 9 | `PortfolioOverview.svelte` | `lib/components/portfolio/PortfolioOverview.svelte` | DEAD | Replaced by `BuilderTable`. Imported only by `routes/(app)/portfolio/model/+page.svelte` (line 13) but rendered inside the Holdings tab — so it's actually the Holdings rendering on the Model page. **Status flips to "REAL but misnamed" on the Model page.** Should be renamed `ModelHoldingsTree.svelte` or absorbed by a new `WeightVectorTable`. |
| 10 | `ModelListPanel.svelte` | `lib/components/portfolio/ModelListPanel.svelte` | REAL | List of model portfolios with `selectPortfolio` action. Tailwind classes inline (`bg-[#0177fb]/10`) — not enforced via tokens. |
| 11 | `PolicyPanel.svelte` | `lib/components/portfolio/PolicyPanel.svelte` | **MOCK** | **Critical bug.** CVaR and concentration sliders bind to local `$state` (`cvarLimit`, `maxConcentration`), call `workspace.updatePolicy(key, value)` — and that store method ignores the value entirely (`portfolio = { ...portfolio }`). No fetch, no recompute, no persistence. This is the #1 source of Andrei's "MOCK confusion". Exposes only **2 of ~12** real optimizer inputs (see A.2). |
| 12 | `AnalyticsColumn.svelte` | `lib/components/portfolio/AnalyticsColumn.svelte` | PARTIAL | Drives Estado C of FCL. "fund" mode is a placeholder showing only 3 metadata fields (asset_class, block, geography) — comment says "Phase C arrives". "portfolio" mode hosts `MainPortfolioChart` and works. Esc handler is global `window` keydown, should be scoped. |
| 13 | `MainPortfolioChart.svelte` | `lib/components/portfolio/MainPortfolioChart.svelte` | REAL | Backtest equity curve via `workspace.trackRecord`. ECharts theme tokens read from `getComputedStyle` (acceptable pattern). |
| 14 | `StressTestPanel.svelte` | `lib/components/portfolio/StressTestPanel.svelte` | **PARTIAL** | Custom 3-input shock form. **Cannot reach the 4 named backend scenarios.** Maps macro shocks → block shocks via `mapMacroShocksToBlocks`. Backend supports `scenario_name: "gfc_2008" \| "covid_2020" \| "taper_2013" \| "rate_shock_200bps" \| "custom"` — UI only sends `"custom"`. The "Test the engine's ability" claim fails because the engine's preset library is invisible. |
| 15 | `RebalanceSimulationPanel.svelte` | `lib/components/portfolio/RebalanceSimulationPanel.svelte` | PARTIAL | Real `executeTrades` POST. **Violations: `.toFixed(1)` and `.toFixed(2)` at lines 259, 265, 290.** Holdings-input UX is manual entry (anti-pattern for live portfolios — should pull from custodian). |
| 16 | `OverlapScannerPanel.svelte` | `lib/components/portfolio/OverlapScannerPanel.svelte` | REAL | Reads `workspace.localOverlap`. Empty/loading/data states all present. |
| 17 | `FactorAnalysisPanel.svelte` | `lib/components/portfolio/FactorAnalysisPanel.svelte` | REAL | Donut + bar charts on `workspace.localFactorAnalysis`. ECharts theme via `getComputedStyle` with `MutationObserver`. Note in code admits donut for 2-5 slices is "sub-institutional". |
| 18 | `analytics/+page.svelte` | `routes/(app)/portfolio/analytics/+page.svelte` | REAL | 4 sub-tabs (Attribution / Factor / Drift / Risk Budget). All wired to workspace. SSR seed pattern with profile-match guard (good). 6 KPI cards. |
| 19 | `model/+page.svelte` | `routes/(app)/portfolio/model/+page.svelte` | PARTIAL | 6 sub-tabs (Holdings/Factor/Stress/Overlap/Rebalance/Reporting). Activate Portfolio button wired with `ConsequenceDialog` + rationale + audit trail — **this is the cleanest "Approval → Live" path in the codebase**, but it's hidden inside the Model page rather than promoted as a primary workflow. `cvarViolated` auto-fetches advisor (good). |
| 20 | `advanced/+page.svelte` | `routes/(app)/portfolio/advanced/+page.svelte` | REAL | Entity-level analytics for funds in the portfolio. Real API. Window pills work. **Mostly redundant with Discovery's standalone Analysis page** — should be deprecated once Discovery ships. |
| 21 | `model-portfolio/ConstructionAdvisor.svelte` | `lib/components/model-portfolio/ConstructionAdvisor.svelte` | REAL | Receives advice from `workspace.advice` or own internal state. Auto-shown when CVaR violated. **This IS the "Advisor function" Andrei thinks is invisible — it's only visible inside Model > Holdings tab and only when CVaR is violated. Not surfaced from Builder.** |
| 22 | `model-portfolio/ICViewsPanel.svelte` | `lib/components/model-portfolio/ICViewsPanel.svelte` | REAL | Manages Black-Litterman views. Imported by ??? (grep needed before deletion). |
| 23 | `model-portfolio/JobProgressTracker.svelte` | `lib/components/model-portfolio/JobProgressTracker.svelte` | REAL | SSE job tracker for report generation. |
| 24 | `model-portfolio/RebalancePreview.svelte` | `lib/components/model-portfolio/RebalancePreview.svelte` | REAL | Probably consumed by `RebalanceSimulationPanel` — verify before refactor. |
| 25 | `model-portfolio/ScoreBreakdownPopover.svelte` | `lib/components/model-portfolio/ScoreBreakdownPopover.svelte` | REAL | Score component breakdown — used in `BuilderTable`/`UniverseTable`. |
| 26 | `model-portfolio/StrategyDriftAlerts.svelte` | `lib/components/model-portfolio/StrategyDriftAlerts.svelte` | REAL | Drift alert list (also rendered in analytics page). |
| 27 | `model-portfolio/DriftGauge.svelte` | `lib/components/model-portfolio/DriftGauge.svelte` | REAL | Per-instrument drift gauge. |
| 28 | `model-portfolio/FundSelectionEditor.svelte` | `lib/components/model-portfolio/FundSelectionEditor.svelte` | UNKNOWN | Need to confirm consumers — likely dead post-Builder migration. |
| 29 | `model-portfolio/GeneratedReportsPanel.svelte` | `lib/components/model-portfolio/GeneratedReportsPanel.svelte` | REAL | Report list. Possibly superseded by `ReportVault` — verify before deletion. |

### A.2 — Verification of Andrei's claims

**Claim: "Sliders don't wire to anything."** — **CONFIRMED.**
Trace:
- `PolicyPanel.svelte` line 47-54: `<input type="range" oninput={handleCvarChange}>`
- `handleCvarChange` calls `workspace.updatePolicy("cvar_limit", val)`.
- `portfolio-workspace.svelte.ts` line 684-688:
  ```ts
  updatePolicy(key: "cvar_limit" | "max_single_fund_weight", value: number) {
      if (!this.portfolio) return;
      // Policy updates are local UI state — the backend reads policy from StrategicAllocation table
      this.portfolio = { ...this.portfolio };
  }
  ```
  The `key` and `value` parameters are received and **discarded**. No fetch, no state mutation, no recompute. The `{ ...this.portfolio }` line just creates a new reference to trigger reactivity for... nothing.
- The local `cvarLimit` and `maxConcentration` `$state` in PolicyPanel are visual-only.
- **Conclusion:** every time Andrei moves a slider, zero work happens anywhere. The display number updates in the local panel only because `$state` is local. Nothing reaches the backend. Nothing recomputes.

**Claim: "Calibration only exposes 2 of many engine inputs."** — **CONFIRMED.**
The `optimize_fund_portfolio` signature in `backend/quant_engine/optimizer_service.py` and the constraints dataclass take, at minimum:
- `min_weight`, `max_weight` (per block — currently driven by `StrategicAllocation` rows, not exposed in UI)
- `cvar_limit`
- `risk_aversion` / `lambda_risk` (Black-Litterman tradeoff)
- `regime_cvar_multiplier` (regime conditioning)
- `turnover_penalty` (L1 slack)
- robust uncertainty radius (Phase 1.5 SOCP)
- BL prior strength + view confidence
- Ledoit-Wolf shrinkage intensity (currently auto)
- GARCH window
- Stress severity coupling
- Per-block `min_weight` / `max_weight` overrides

UI exposes: `cvar_limit` and `max_single_fund_weight` — and **neither is wired**. The remaining ~10 inputs are simply unreachable.

**Claim: "Stress test UI doesn't match the 4 engine scenarios."** — **CONFIRMED.**
- Backend (`stress_scenarios.py:129`): `PRESET_SCENARIOS = { "gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps" }`.
- Frontend (`StressTestPanel.svelte:18-21`): equity/rates/credit number inputs only. `workspace.runStressTest` always sends `scenario_name: "custom"` (line 844).
- The engine's curated scenario library is **invisible**.

**Claim: "Create new portfolio button is a placeholder."** — **CONFIRMED.**
`+page.svelte:115-118`:
```html
<button type="button" class="bld-pill bld-pill--new">
    <Plus size={16} />
    <span>New Portfolio</span>
</button>
```
No `onclick`. No handler. Pure HTML.

**Claim: "Run Construct gives zero narrative output."** — **CONFIRMED.**
- `model_portfolios.py:1553-1562`: backend builds `result["optimization"]` with `expected_return`, `portfolio_volatility`, `sharpe_ratio`, `solver`, `status`, `cvar_95`, `cvar_limit`, `cvar_within_limit`, plus optional `factor_exposures`.
- `optimization` payload includes **no** binding constraints, **no** phase-by-phase trace (only embedded in `status` string like `"optimal:min_variance_fallback"`), **no** turnover delta, **no** regime context, **no** critic review, **no** per-holding rationale.
- Frontend consumes **only** `cvar_within_limit` (`workspace.cvarViolated`) to gate the activate button and trigger the Construction Advisor. No component renders any of the 8 fields as narrative.
- The "spinner → silent table refresh" experience Andrei describes is an exact match.

**Claim: "Advisor function is invisible."** — **PARTIALLY CONFIRMED.**
- `ConstructionAdvisor.svelte` exists, is wired, and works.
- It only renders inside `routes/(app)/portfolio/model/+page.svelte` line 196-204 — i.e. **only on the Model page, only inside the Holdings tab, only when `cvarViolated` is true**.
- From the Builder (where Andrei runs Construct), the advisor is unreachable. He has to (a) run construct, (b) navigate to Model, (c) be on the Holdings tab, (d) have a CVaR violation. If any of those fail, the advisor is dead UI.

**Claim: "Approval → Live process is unclear."** — **CONFIRMED, but the building blocks exist.**
- Activation button lives in Model page action bar (line 178-189). Wired to `workspace.activatePortfolio` → POST `/model-portfolios/{id}/activate` → `ConsequenceDialog` with rationale capture → `Toast` confirmation. This is the **best-implemented** workflow in the portfolio surface.
- Problem: it's hidden in a sub-tab. There's no journey from Builder → Activate. No status badge in Builder showing "draft / active / archived". No state-machine visualization.

### A.3 — Architectural smells beyond Andrei's list

- **Two competing column primitives.** `BuilderColumn` and `UniverseColumn` re-implement the same `<svelte:boundary>` + header + body shell. Both should compose a neutral `WorkbenchColumn` from `@netz/ui` once Discovery extraction lands.
- **Hardcoded hex everywhere.** `BuilderColumn.svelte` line 138-149 explicitly says "Hardcoded dark palette … Zero var() fallbacks". Violates `feedback_tokens_vs_components` and breaks light-mode tokens (`feedback_light_mode_tokens`). Each component is a barrier to theme switching.
- **`workspace` is a giant module-level singleton** (`portfolio-workspace.svelte.ts`, 877 lines, 30+ pieces of state). This works for now but fights Svelte 5 scoping rules; should evolve into per-page Svelte context with the singleton as a backwards-compat bridge.
- **`MutationObserver` on `document.documentElement` in chart panels.** Three components (StressTestPanel, FactorAnalysisPanel, MainPortfolioChart) duplicate the "read CSS var, observe theme change" pattern. Should be a `useChartTheme()` rune helper in `@netz/ui/charts`.
- **Manual holdings entry in `RebalanceSimulationPanel`.** Live portfolios should never require typing holdings by hand. This panel is "test drive" only — needs a clear "DEMO MODE" affordance or replacement by a custodian-backed feed.

---

## Part B — Component Architecture for the New Portfolio

Three distinct surfaces, each with the right layout primitive for its job. Routing flow is sibling specialist's responsibility — this section describes the component tree only.

### B.1 — Builder (FCL pattern, reuses Discovery primitives)

**Page:** `routes/(app)/portfolio/+page.svelte` + `+page.server.ts` (existing path, refactored).

**Top-level layout:** `FlexibleColumnLayout` from `@netz/ui` (post-Discovery Phase 2.2 migration).

**Tree:**
```
+page.svelte
└── FlexibleColumnLayout (state="expand-3" | "expand-2")
    ├── leftColumn  → ApprovedUniverseColumn (composes UniverseColumn + L3 score filter rail)
    │                  └── UniverseTable
    ├── centerColumn → BuilderCanvas
    │                   ├── BuilderActionBar (New / Construct / View Chart / Stress / Approve)
    │                   ├── BuilderTable (3-level tree, drag-drop targets)
    │                   └── ConstructionStatusStrip (live since last construct: regime, solver, cvar status)
    └── rightColumn  → BuilderRightStack (vertical tabs)
                        ├── CalibrationPanel       (NEW — see Part C)
                        ├── ConstructionNarrative  (NEW — see Part D)
                        └── PortfolioPreviewChart  (compact NAV + ex-ante risk strip)
```

**State ownership:**
- Page-level: layout state (`expand-2 | expand-3`) is `$derived` from observable facts in workspace store, never written.
- `workspace` singleton continues to own portfolio identity, funds, optimization meta. To be wrapped behind `getPortfolioWorkspace()` Svelte context for per-page injection — singleton stays as the default implementation.
- `CalibrationPanel` owns its own draft state in a child Svelte context (`getCalibrationDraft()`) — this isolates draft from committed snapshot.
- URL drives: `?portfolio=<id>&right=calibration|narrative|preview` (deep-linkable).

**Data fetching:**
- `+page.server.ts` returns `RouteData<{portfolios, defaultCalibration}>` per stability guardrails — never `throw error()`.
- Client-side `$effect` with `AbortController` re-fetches universe + portfolio detail on `portfolioId` change. Cleanup function aborts on unmount.

**SSE integration points:**
- Construction progress: `POST /model-portfolios/{id}/construct` returns 202 + `job_id` (Job-or-Stream pattern) → client opens `/jobs/{job_id}/stream` SSE. Parsed in `BuilderActionBar` and broadcast to `ConstructionNarrative` via context.
- Calibration preview: optional SSE channel for `POST /model-portfolios/{id}/calibration/preview` (cheap recompute, see Part C).

**Stability patterns:**
- `<svelte:boundary>` per column with `PanelErrorState` failed snippet (existing pattern, kept).
- `RouteData<T>` load contract on `+page.server.ts` (replace `.catch(() => [])` silent failure).
- `createTickBuffer<T>` not needed in Builder — events are low-frequency.

### B.2 — Analytics (reuse Discovery standalone Analysis page)

**Page:** `routes/(app)/portfolio/analytics/+page.svelte` (existing path, refactored to reuse Discovery's `AnalysisGrid` + `ChartCard` + `FilterRail`).

**Decision:** **deprecate the four sub-tabs** (Attribution / Factor / Drift / Risk Budget) and replace with a portfolio-level standalone analysis page using the **same primitives** as `/discovery/funds/{id}/analysis`. The current analytics page is functional but its layout language is bespoke; converging on Discovery primitives means one less primitive set to maintain.

**Tree:**
```
+page.svelte
└── StandaloneAnalysisLayout (FilterRail | AnalysisGrid)
    ├── FilterRail (left, 260px)  → window pills, benchmark selector, regime filter
    └── AnalysisGrid (3×2 charts)
        ├── tab="Attribution"  → BrinsonFachlerCard, AllocVsSelectionCard, ContribTimeline, …
        ├── tab="Factor"        → RiskDecompCard, StyleExposuresCard, FactorReturnsCard, …
        ├── tab="Drift"         → DriftAlertsCard, DriftHeatmap, …
        └── tab="RiskBudget"    → MctrTable, MctrSunburst, …
```

All chart cards reuse `ChartCard` from `@netz/ui` (Discovery extraction). Tab routing via URL hash.

### B.3 — Live Workbench (NEW, terminal-style, full-width)

**Page:** `routes/(app)/portfolio/live/+page.svelte` + `+page.server.ts` (NEW route).

**Top-level layout:** `WorkbenchLayout` (NEW primitive — see Part E) — full-bleed CSS Grid, terminal aesthetic, no FCL.

**Tree:**
```
+page.svelte
└── WorkbenchLayout (12-col grid, --workbench-gap: 4px)
    ├── header   (full-width) → PortfolioSwitcherDock (see E.4)
    ├── col 1-3  (rows 1-2)   → AlertsFeedPanel       (SSE feed)
    ├── col 4-9  (row 1)      → LiveNavChart          (intraday + 1y toggle)
    ├── col 10-12 (row 1)     → ExAnteRiskStrip       (CVaR / Vol / Sharpe live)
    ├── col 4-12 (row 2)      → WeightVectorTable     (live prices, drift bps)
    ├── col 1-12 (row 3)      → RebalanceSuggestionPanel (advisor output)
    └── footer    (full-width) → BottomTabDock         (reuse Discovery primitive)
```

**State ownership:**
- `workspace.live` namespace (new sub-store) holds: `livePrices: Map<string, PriceTick>`, `alertsBuffer: TickBuffer<Alert>`, `lastRebalanceSuggestion`. All in-memory only.
- `LiveWorkbenchContext` Svelte context wraps the workspace plus a `tickBuffer` per high-frequency stream — passed down to `WeightVectorTable`, `LiveNavChart`, `AlertsFeedPanel`.

**Data fetching:**
- `+page.server.ts` loads portfolio + last NAV snapshot via `RouteData<T>`.
- Client-side: persistent SSE connection to `/portfolios/{id}/live/stream` (multiplexed: prices, regime, alerts, drift). Parsed in a single `streamReader` scoped to a `$effect` with `AbortController` cleanup.
- Polling fallback: 30s `GET /portfolios/{id}/live/snapshot` if SSE drops.

**SSE integration points:** see WeightVectorTable in Part E.

**Stability patterns:**
- `RateLimitedBroadcaster` on the SSE message bus (charter §3).
- `createTickBuffer<PriceTick>` for price stream (>10 events/s expected during market hours) — never `$state` spreads.
- `<svelte:boundary>` per panel; failure of one panel doesn't kill the workbench.
- Reconnection: exponential backoff with jitter, surfaced via a connection-status pill in the header.

---

## Part C — `CalibrationPanel.svelte` Architecture

**File:** `frontends/wealth/src/lib/components/portfolio/CalibrationPanel.svelte`
**Goal:** make every quant input the optimizer accepts reachable, group them sensibly, and **never lie about wiring**.

### C.1 — Categories (coordinate with quant specialist for the canonical list)

```
Optimizer
  - Risk aversion (λ)              [number, 0.5–10]
  - Tracking error budget          [pct, 0–10%]
  - Turnover penalty               [number, 0–5]
  - Per-block min/max overrides    [block grid → min/max sliders]
  - Solver preference              [Clarabel | SCS]

Black-Litterman
  - Prior strength (τ)             [number]
  - View confidence default        [number]
  - Active IC views                [link → ICViewsPanel]

CVaR / Risk
  - CVaR limit (95%)               [pct, -25 to -2]
  - Single-fund max weight         [pct, 5–40%]
  - Single-block max weight        [pct, 10–60%]

Regime
  - Regime detection on/off        [toggle]
  - Manual regime override         [select: NORMAL | RISK_OFF | CRISIS]
  - Regime CVaR multipliers        [3 numbers, defaults 1.0 / 0.85 / 0.70]
  - Covariance window short/long   [days]

Stress
  - Default scenario               [select: gfc_2008 | covid_2020 | taper_2013 | rate_shock_200bps]
  - Stress severity coupling       [toggle]
```

### C.2 — Component contract

```ts
interface Props {
  portfolioId: string;
  snapshot: CalibrationSnapshot;        // from server load
  onApply: (draft: CalibrationDraft) => Promise<void>;
  onPreview?: (draft: CalibrationDraft) => void;  // SSE preview trigger
}
```

### C.3 — State model

- `draft` is owned by a child Svelte context `getCalibrationDraft()` — isolates dirty state from the committed `snapshot`.
- `dirty = $derived(!deepEqual(draft, snapshot))` drives the Apply button enable.
- Per-section `reset = () => { draft.<section> = snapshot.<section> }`.

### C.4 — Reactive preview vs explicit Apply — RECOMMENDATION

**Recommend: explicit "Preview" + "Apply".**

| Approach | Pros | Cons |
|---|---|---|
| Reactive `$effect` | Feels live, no extra clicks | Every drag of a slider triggers recompute → optimizer takes 10–30s → cascade of stale results, wasted compute, frustrating UX. Violates `feedback_smart_backend_dumb_frontend` (frontend orchestrates work the backend doesn't want). |
| **Explicit Preview button** | Single recompute per intended change. SSE progress visible. User intent explicit. Survives the calibration flicker problem. | One extra click. |
| Explicit Apply button | Same as Preview but persists snapshot. | n/a |

**Pattern:** drag sliders → `dirty = true` → Preview button enabled → click Preview → SSE job → ex-ante metrics strip updates → user sees impact → click Apply to persist → snapshot becomes the new baseline → Run Construct uses the snapshot.

**Anti-pattern caught:** the current `PolicyPanel` pretends to be reactive while doing nothing. Replace with explicit gates so the user always knows whether their change has been computed.

### C.5 — Visual structure

```
<CalibrationPanel>
  <CalibrationHeader>
    <span>Calibration</span>
    <DirtyDot visible={dirty} />
    <button onclick={preview} disabled={!dirty || previewing}>Preview</button>
    <button onclick={apply} disabled={!dirty || applying}>Apply</button>
  </CalibrationHeader>
  <ExAnteMetricsStrip metrics={previewMetrics} stale={dirty && !previewing} />
  <CalibrationSection title="Optimizer" defaultOpen> … </CalibrationSection>
  <CalibrationSection title="Black-Litterman"> … </CalibrationSection>
  <CalibrationSection title="CVaR / Risk"> … </CalibrationSection>
  <CalibrationSection title="Regime"> … </CalibrationSection>
  <CalibrationSection title="Stress"> … </CalibrationSection>
</CalibrationPanel>
```

`CalibrationSection` is a tiny accordion with per-section `Reset to defaults`.

### C.6 — Persistence

- `Apply` calls `PUT /model-portfolios/{id}/calibration` → snapshot persisted in DB (backend table required — quant specialist's work).
- `Run Construct` sends the persisted snapshot, never the in-memory draft.
- On entering the page, snapshot loaded via `+page.server.ts` and seeded into the context.

---

## Part D — `ConstructionNarrative.svelte`

**File:** `frontends/wealth/src/lib/components/portfolio/ConstructionNarrative.svelte`
**Goal:** convert the backend's enriched construct payload into the IC-grade explanation Andrei expects.

### D.1 — Backend contract dependency

The backend currently returns 8 numeric fields under `optimization`. For this component to be useful, the backend must enrich the payload to include (specific shapes are quant specialist's call, this is the frontend's *minimum requirement*):

```ts
interface ConstructionResult {
  optimization: {
    // existing
    expected_return: number;
    portfolio_volatility: number;
    sharpe_ratio: number;
    solver: "clarabel" | "scs";
    status: string;
    cvar_95: number | null;
    cvar_limit: number | null;
    cvar_within_limit: boolean;
    // NEW — required for narrative
    phases_executed: Array<{
      phase: "phase_1" | "phase_1_5_robust" | "phase_2_variance_capped" | "phase_3_min_variance" | "fallback_heuristic";
      status: "optimal" | "infeasible" | "skipped";
      objective_value: number | null;
      solver_used: "clarabel" | "scs";
      duration_ms: number;
    }>;
    binding_constraints: Array<{
      kind: "cvar_limit" | "block_max" | "block_min" | "single_fund_max" | "turnover" | "tracking_error";
      block_id?: string;
      fund_id?: string;
      target: number;
      actual: number;
    }>;
    regime_context: {
      detected: "NORMAL" | "RISK_OFF" | "CRISIS";
      cvar_multiplier_applied: number;
      effective_cvar_limit: number | null;
    };
    turnover: {
      l1_distance: number;
      previous_weights: Record<string, number> | null;
      new_weights: Record<string, number>;
    };
    metrics_before: { sharpe: number; vol: number; cvar_95: number; max_dd: number } | null;
    metrics_after:  { sharpe: number; vol: number; cvar_95: number; max_dd: number };
    critic_review: {
      passed: boolean;
      issues: Array<{ severity: "info" | "warning" | "error"; message: string }>;
    } | null;
    per_holding_rationale: Array<{
      fund_id: string;
      fund_name: string;
      action: "added" | "removed" | "increased" | "decreased" | "held";
      delta_weight_pct: number;
      reasons: string[];
    }>;
  };
}
```

**If the backend cannot enrich:** the component renders a single empty state — **never** mocks. Andrei's `feedback_yagni_agent_danger` and `feedback_smart_backend_dumb_frontend` rules both apply.

### D.2 — Component contract

```ts
interface Props {
  result: ConstructionResult["optimization"] | null;
  portfolioName: string;
  onRerun?: () => void;
}
```

### D.3 — Layout — recommend **2-col narrative + sticky metrics**

Tried in mental simulation:
- Accordion: too much clicking, hides the story.
- Timeline: dramatic but wastes space; bad for IC review reading speed.
- **2-col with sticky right metrics rail**: narrative on the left flows top-to-bottom, key numbers always visible on the right. Print-friendly.

```
<ConstructionNarrative>
  <NarrativeHeader>
    <kicker>CONSTRUCTION RESULT</kicker>
    <title>{portfolioName}</title>
    <SolverBadge solver={result.solver} fallback={result.solver === "scs"} />
    <CriticBadge passed={result.critic_review?.passed} />
  </NarrativeHeader>

  <NarrativeBody> // 2-col CSS grid
    <NarrativeColumn>
      <NarrativeSection icon={Layers} title="Optimization phases">
        <PhaseTrace phases={result.phases_executed} />
      </NarrativeSection>

      <NarrativeSection icon={Lock} title="Binding constraints">
        <BindingConstraintsList constraints={result.binding_constraints} />
      </NarrativeSection>

      <NarrativeSection icon={Activity} title="Regime context">
        <RegimeBlock regime={result.regime_context} />
      </NarrativeSection>

      <NarrativeSection icon={ArrowLeftRight} title="Turnover">
        <TurnoverDelta from={result.turnover.previous_weights} to={result.turnover.new_weights} l1={result.turnover.l1_distance} />
      </NarrativeSection>

      <NarrativeSection icon={List} title="Per-holding rationale">
        <HoldingRationaleList items={result.per_holding_rationale} />
      </NarrativeSection>

      {#if result.critic_review && !result.critic_review.passed}
        <NarrativeSection icon={AlertCircle} title="Critic review issues" tone="warning">
          <CriticIssuesList issues={result.critic_review.issues} />
        </NarrativeSection>
      {/if}
    </NarrativeColumn>

    <MetricsRail sticky>
      <MetricBeforeAfter label="Sharpe"   before={metrics_before?.sharpe}  after={metrics_after.sharpe} />
      <MetricBeforeAfter label="Vol"      before={metrics_before?.vol}     after={metrics_after.vol} fmt="pct" />
      <MetricBeforeAfter label="CVaR 95%" before={metrics_before?.cvar_95} after={metrics_after.cvar_95} fmt="pct" />
      <MetricBeforeAfter label="Max DD"   before={metrics_before?.max_dd}  after={metrics_after.max_dd} fmt="pct" />
    </MetricsRail>
  </NarrativeBody>

  <NarrativeFooter>
    <button onclick={onRerun}>Re-run with current calibration</button>
  </NarrativeFooter>
</ConstructionNarrative>
```

All numeric formatting via `@netz/ui` formatters — **no `.toFixed()` anywhere**.

### D.4 — Empty / loading states

- **Loading:** skeleton with "Solving … phase X of Y" hooked to SSE progress events from the construct job.
- **No previous run:** "No construction yet — run Construct to see the engine's reasoning."
- **Backend payload incomplete:** "Insufficient explainability — backend returned partial payload. Missing fields: {list}" (debug-mode only) plus a friendlier "Engine explanation unavailable for this run" for production.

---

## Part E — Live Workbench Primitives

### E.1 — `WorkbenchLayout.svelte` — `@netz/ui` (NEW)

**File:** `packages/ui/src/lib/layouts/WorkbenchLayout.svelte` (NEW, neutral primitive).

**Goal:** terminal-style 12-col CSS Grid full-width, dense spacing, less rounded.

**Design tokens (admin-config'd, not hex):**
```css
:root[data-density="workbench"] {
  --workbench-border-radius: 2px;
  --workbench-gap: 4px;
  --workbench-font-size: 12px;
  --workbench-cell-padding: 6px 8px;
  --workbench-header-height: 28px;
  --workbench-row-height: 22px;
}
```

These are added to the existing token system; never hardcoded in panels.

**Props:**
```ts
interface Props {
  cells: Array<{
    id: string;
    col: string;        // grid-column shorthand "1 / 4"
    row: string;        // grid-row shorthand "1 / 3"
    component: Snippet;
  }>;
  density?: "comfortable" | "workbench";
}
```

**Stability patterns:** `<svelte:boundary>` per cell, cell errors render a 1-line `PanelErrorState` so the rest of the workbench stays alive.

### E.2 — `AlertsFeedPanel.svelte` — wealth-specific

**File:** `frontends/wealth/src/lib/components/portfolio/live/AlertsFeedPanel.svelte`

**Props:**
```ts
interface Props {
  portfolioId: string;
}
```

**Reactivity model:**
- Subscribes to `getLiveWorkbenchContext().alertsBuffer` (TickBuffer of `Alert`).
- Group by severity (critical / warning / info) — `$derived` over the buffer's snapshot.
- Click row → POST `/portfolios/{id}/alerts/{alert_id}/acknowledge` (uses `@idempotent` decorator on backend).
- Acknowledged alerts fade in 200ms then drop from the buffer.

**Stability:** `createTickBuffer<Alert>(maxLength: 500, batchInterval: 100)` to coalesce bursts.

### E.3 — `WeightVectorTable.svelte` — wealth-specific

**File:** `frontends/wealth/src/lib/components/portfolio/live/WeightVectorTable.svelte`

**Columns:** Instrument | Strategic % | Tactical % | Effective % | Drift bps | Live Price | Day Δ% | Day Δ value

**Reactivity model:**
- Per-row data merges 3 sources: portfolio snapshot (strategic/tactical/effective weights), live price tick stream, computed drift.
- High-frequency price updates (>10/s during market hours) → use `createTickBuffer<PriceTick>` keyed by `instrument_id`.
- A single `$effect` reads the buffer's snapshot via `requestAnimationFrame` and writes a `displayRows: Map<string, RowView>` `$state.raw` for the table to render. **Never `$state` spreads on each tick.**
- Drift bps is `$derived` (cheap math).

**Visual:**
- Row turns green/red on price tick for 80ms (CSS animation, not Svelte reactivity).
- Drift bps cell colors via tokens (`text-success` / `text-warning` / `text-danger`).
- Tabular numerals via `font-variant-numeric: tabular-nums`.

**Formatters:** all `@netz/ui` (`formatPercent`, `formatCurrency`, `formatNumber`, `formatBps`).

### E.4 — `PortfolioSwitcherDock.svelte` — REUSE `BottomTabDock`

**Decision:** reuse Discovery's `BottomTabDock` from `@netz/ui`. Tab format: `[Portfolio Name] · [Status]`. Add a "+" tab at the end for new portfolios. Persists in URL hash, no localStorage.

If `BottomTabDock` lives in `@netz/ui` it's already neutral — no fork. If Discovery only has it as a wealth-local component at the time of writing, **promote it to `@netz/ui` first** (single PR), then both Discovery and the workbench import it.

### E.5 — `RebalanceSuggestionPanel.svelte` — wealth-specific

**File:** `frontends/wealth/src/lib/components/portfolio/live/RebalanceSuggestionPanel.svelte`

**Props:**
```ts
interface Props {
  portfolioId: string;
}
```

**Behavior:**
- Reads `workspace.live.lastRebalanceSuggestion` (populated by SSE rebalance event).
- Three affordances: `Preview` (open diff modal), `Queue` (POST `/rebalance/queue`), `Execute` (POST `/rebalance/execute` — guarded by `ConsequenceDialog` with rationale).
- Idle state: "No rebalance suggestion. Strategy drift below threshold."

---

## Part F — Formatter Discipline + MOCK Elimination Plan

### F.1 — Formatter violations to fix

| File | Line | Violation | Fix |
|---|---|---|---|
| `RebalanceSimulationPanel.svelte` | 259 | `(trade.delta_weight * 100).toFixed(1)` | `formatPercent(trade.delta_weight, 1)` |
| `RebalanceSimulationPanel.svelte` | 265 | `trade.estimated_quantity.toFixed(2)` | `formatNumber(trade.estimated_quantity, 2)` |
| `RebalanceSimulationPanel.svelte` | 290 | `wc.delta_pp.toFixed(1)` | `formatNumber(wc.delta_pp, 1)` (or `formatBps` if pp = percentage points) |
| `BuilderTable.svelte` | 233 | `value.toFixed(0)` | `formatNumber(value, 0)` |
| `analytics/+page.svelte` | 60-61 | `(s.allocation_effect * 10000).toFixed(1)` | move into chart formatter callback using `formatBps` |

ESLint config in `frontends/eslint.config.js` should already catch these — **why isn't it?** Check if rule is configured but the file is in an exception list, or if the rule is missing entirely. Sibling task: ensure the lint rule fires.

### F.2 — MOCK elimination plan (dependency-ordered)

Stages, top-down. Each stage unblocks the next.

**Stage 0 — Backend contract enrichment (sibling tasks)**
- [ ] Add `phases_executed`, `binding_constraints`, `regime_context`, `turnover`, `metrics_before/after`, `critic_review`, `per_holding_rationale` to `/construct` response (quant specialist).
- [ ] Add `PUT /model-portfolios/{id}/calibration` endpoint + `model_portfolio_calibrations` table (DB specialist + quant).
- [ ] Add 4 named scenario routes: `POST /stress-test/{scenario_name}` or extend body validation (already exists in router, just needs UI).
- [ ] Live workbench SSE: `GET /portfolios/{id}/live/stream` (multiplexed prices/regime/alerts/drift).

**Stage 1 — Builder calibration** (depends on Stage 0 calibration endpoint)
- [ ] Replace `PolicyPanel.svelte` with `CalibrationPanel.svelte` per Part C.
- [ ] Delete `workspace.updatePolicy()` (the no-op).
- [ ] Wire `Run Construct` to send the persisted calibration snapshot.

**Stage 2 — Construction narrative** (depends on Stage 0 enrichment)
- [ ] Build `ConstructionNarrative.svelte` per Part D.
- [ ] Mount in Builder right column as default tab after a successful construct.
- [ ] Surface advisor inline when `cvarViolated` (kill the "advisor only on Model > Holdings" trap).

**Stage 3 — Stress scenarios** (depends on backend already supporting — UI-only)
- [ ] Extend `StressTestPanel.svelte`: scenario select dropdown with the 4 presets + "Custom". On preset select, fields become read-only and show preset values; on Custom, fields become editable.
- [ ] Or split into `ScenarioStressPanel` (preset matrix view, runs all 4 with one click) + `CustomShockPanel` (the existing form).

**Stage 4 — Builder action wiring** (UI-only)
- [ ] Wire "New Portfolio" button to a `NewPortfolioDialog` (POST `/model-portfolios` with required fields).
- [ ] Add `Approve / Activate` button to BuilderActionBar (mirror Model page implementation, lift `ConsequenceDialog` flow).
- [ ] Status pill in BuilderActionBar (draft / active / archived) — derived from `workspace.portfolio.status`.

**Stage 5 — Live workbench scaffolding** (depends on Stage 0 SSE)
- [ ] `WorkbenchLayout` primitive in `@netz/ui`.
- [ ] `/portfolio/live` route with `+page.server.ts` + `+page.svelte`.
- [ ] `WeightVectorTable`, `AlertsFeedPanel`, `RebalanceSuggestionPanel`, `LiveNavChart`, `ExAnteRiskStrip`.
- [ ] Promote `BottomTabDock` to `@netz/ui` if not already there.

**Stage 6 — Formatter lint cleanup** (UI-only, can run in parallel with anything)
- [ ] Fix the 4 formatter violations listed in F.1.
- [ ] Verify `frontends/eslint.config.js` rule is firing.

**Stage 7 — Dead code removal** (after all stages green)
- [ ] Delete `UniversePanel.svelte` (zero importers).
- [ ] Either delete `PortfolioOverview.svelte` or rename to `ModelHoldingsTree.svelte` (it's the only renderer of the Holdings tab on /model).
- [ ] Confirm `FundSelectionEditor.svelte` and `GeneratedReportsPanel.svelte` consumers; delete if dead.
- [ ] Migrate `/portfolio/advanced` callers to Discovery's standalone Analysis page; deprecate the route.

**CRITICAL**: per `feedback_yagni_agent_danger`, do NOT delete anything in Stage 7 without Andrei's explicit approval. Some "dead" components may be scaffolding for sprints not yet started.

---

## Part G — Svelte 5 Patterns to Enforce

Non-negotiables for every file touched in this redesign.

1. **Runes only.** `$state`, `$derived`, `$derived.by`, `$effect`, `$effect.pre`, `$props`, `$bindable`. Zero `let` reactivity, zero `$:`, zero stores when runes resolve. Violations are blockers.
2. **No module-level state.** `workspace` singleton stays for back-compat but new state lives behind `getXxxContext()` on the page tree. Module-level `Semaphore`/`Lock` would be a stability violation per charter §3.
3. **`$derived` for computation, `$effect` for side-effects.** Never write `$state` from inside `$effect` if a `$derived` would do.
4. **SSE via `fetch()` + `ReadableStream`.** Never `EventSource` (auth headers needed). Pattern:
   ```ts
   $effect(() => {
     const ctrl = new AbortController();
     (async () => {
       const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` }, signal: ctrl.signal });
       const reader = res.body!.getReader();
       const decoder = new TextDecoder();
       let buf = "";
       while (true) {
         const { value, done } = await reader.read();
         if (done) break;
         buf += decoder.decode(value, { stream: true });
         // parse "data: ..." lines, dispatch
       }
     })();
     return () => ctrl.abort();
   });
   ```
5. **`AbortController` on every async `$effect`** — without exception. Mount/unmount races kill workbench panels first.
6. **No `localStorage` / `sessionStorage`** for domain data. URL params + Redis backend only. UI prefs (theme) go in cookies via `+layout.server.ts`.
7. **Context vs prop drilling decision rule:**
   - **Context** when 3+ levels deep AND multiple components share writes (CalibrationDraft, LiveWorkbenchContext).
   - **Props** when 1-2 levels and read-only.
8. **`<svelte:boundary>` + `RouteData<T>`** per stability guardrails. Server load functions return `{ ok: true, data } | { ok: false, error }` — never `throw error()`. Boundary `failed` snippet renders `PanelErrorState` from `@netz/ui/runtime`.
9. **Tokens, never hex.** Every hardcoded `#0177fb` / `#141519` / `#85a0bd` in the audited files is a violation. Migrate to semantic tokens (`bg-surface`, `text-primary`, `border-subtle`, `bg-brand`) defined in `@netz/ui`. The "hardcoded for theme-context-free dev" excuse in `BuilderColumn` does NOT survive the Discovery migration — Discovery already runs with the token system.
10. **Formatters from `@netz/ui` only.** ESLint enforces; ensure rule fires on all portfolio files.

---

## Part H — Open Decisions for Andrei

These need your input before the plan can ship as a `/ce:work` execution doc.

1. **Backend enrichment ownership.** The frontend redesign assumes the backend will enrich the `/construct` payload (Part D §D.1) and add `PUT /calibration` (Part C §C.6). Confirm the quant + DB sibling specialists are in scope for this sprint, or scope down the frontend to "render whatever exists today + empty states".

2. **CalibrationPanel scope.** Do you want me to expose **all ~12 inputs** in v1, or stage it (v1 = CVaR + concentration + risk aversion + turnover; v2 = regime + BL; v3 = stress)? The risk of v1-everything is overwhelming the user; the risk of staged is repeating the "sliders that don't reach the engine" trap.

3. **Stress test UX shape.** Two options:
   a. **Single panel** with scenario select dropdown (preset / custom).
   b. **Two panels** in tabs: `ScenarioMatrix` (runs all 4 presets, shows comparison grid) + `CustomShock` (existing form).
   I lean (b) — institutional users want comparison views.

4. **Live workbench route name.** `/portfolio/live` vs `/portfolio/{id}/workbench` vs `/workbench`? The third decouples it from portfolio nesting and matches Bloomberg-terminal mental model.

5. **`/portfolio/advanced` deprecation.** This route currently does fund-level analytics inside the portfolio context. Discovery's standalone Analysis page will do the same thing better. Confirm I can mark it deprecated (route exists, redirects to Discovery) once Discovery ships.

6. **`PortfolioOverview.svelte` rename.** It's not "overview" — it's the Holdings tree on the Model page. Rename to `ModelHoldingsTree.svelte` or absorb into a new `WeightVectorTable` (live workbench)? The latter saves a primitive; the former preserves the Model page's existing UX.

7. **Workbench density token.** New `--workbench-*` tokens (Part E.1) — confirm naming convention. These are admin-config'd, not hex. Should they live in a `data-density="workbench"` attribute toggle, or in a separate `@netz/ui/themes/workbench.css`?

8. **Construction Advisor surfacing.** The current "only when CVaR violated, only on Model > Holdings tab" pattern is broken. Should the advisor be:
   a. A persistent BuilderRightStack tab (always available)?
   b. An automatic full-bleed takeover modal when CVaR fails?
   c. A status banner in BuilderActionBar with a "View advice" link?
   I lean (a) for predictability + (c) for discoverability — but they're not mutually exclusive.

9. **Sliders or numeric inputs for CalibrationPanel?** Sliders are intuitive but imprecise. Numeric inputs are precise but require keyboard. Recommendation: **paired slider + bound numeric input** (slider drives the input, input drives the slider, keyboard ↑↓ on input nudges by step). Confirm this is acceptable visual density.

10. **Mock data policy in transit states.** While backend enrichment lands, do you want:
    a. Empty states ("Backend payload incomplete") — strict.
    b. Partial rendering using whatever fields exist — pragmatic but risks the "MOCK confusion" trap.
    Strict aligns with `feedback_smart_backend_dumb_frontend`. I default to (a) unless you say otherwise.

---

## Appendix — File Inventory Summary

**Existing portfolio components in scope:** 14 in `lib/components/portfolio/` + 11 in `lib/components/model-portfolio/` + 4 routes (`+page.svelte` × 4).

**Status tally:**
- REAL: 14
- PARTIAL: 5
- MOCK (critical): 1 (`PolicyPanel`)
- DEAD: 1 confirmed (`UniversePanel`), 1 ambiguous (`PortfolioOverview`)
- UNKNOWN (need verification): 3 (`FundSelectionEditor`, `GeneratedReportsPanel`, `RebalancePreview`)

**New components proposed:**
- `@netz/ui` neutral primitives: `WorkbenchLayout`, possibly promote `BottomTabDock` if not already there.
- Wealth-specific: `CalibrationPanel`, `ConstructionNarrative`, `ApprovedUniverseColumn` (composes UniverseColumn + filter rail), `BuilderRightStack`, `BuilderActionBar` (refactor of inline action bar in BuilderColumn), `ConstructionStatusStrip`, `LiveNavChart`, `ExAnteRiskStrip`, `WeightVectorTable`, `AlertsFeedPanel`, `RebalanceSuggestionPanel`, `PortfolioPreviewChart`, `ScenarioMatrix`, `NewPortfolioDialog`.

**Net component delta:** roughly +14 new, -2 to -5 deleted/renamed, ~12 refactored. Aggressive but achievable in 2-3 sprints if backend enrichment lands in parallel.
