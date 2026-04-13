# Phase 4 Builder — Execution Wrapper

**Date:** 2026-04-13
**Design reference:** `docs/plans/2026-04-13-phase-4-builder-design.md` (LOCKED)
**Status:** Ready for execution in 3 sessions
**Depends on:** TAA System complete (PRs #127-#130), all scoring models (PRs #118-#126)

## Architecture summary

The Builder is a 2-column command center (40% command / 60% results). Backend is 100% ready — ALL 8 endpoints exist and are tested. This is a PURE FRONTEND sprint with minor backend additions for backtest + monte carlo data.

## What exists vs what's new

**Migrate from (app)/portfolio/ (restyle to terminal):**
- CalibrationPanel → Zone B (already has Market tab from TAA Sprint 4)
- BuilderTable → WEIGHTS tab
- ConstructionNarrative → ADVISOR tab
- StressScenarioPanel → STRESS tab
- BuilderActionBar → Zone C Run Controls

**Build NEW:**
- Terminal route + page scaffold with 2-column layout
- Zone A Regime Context Strip
- Zone D Cascade Timeline (ECharts graphic pipeline — centerpiece)
- BACKTEST tab + equity curve + drawdown chart
- MONTE CARLO tab + percentile band chart
- Weight Comparison diverging bar (WEIGHTS tab)
- Risk Contribution stacked bar (RISK tab)
- Factor Exposure horizontal bar (RISK tab)
- Tab-visit tracking gate for activation
- Run comparison ghost columns
- Zone F Activation Bar with ConsequenceDialog

**NOT used (old concept):**
- UniverseColumn (no fund picking)
- PortfolioListPanel (portfolio selector is in TopNav/CommandPalette)
- ConstructionResultsOverlay (replaced by progressive Zone E reveal)

## 3-session execution

### Session 1 — Scaffold + Command Panel + Weights Tab

**Branch:** `feat/builder-session-1`
**Scope:** Terminal route, 2-column layout, left column (Zones A+B+C), WEIGHTS tab with existing BuilderTable migrated

**Deliverable:**
1. Create `frontends/wealth/src/routes/(terminal)/portfolio/[portfolioId]/builder/+page.svelte` + `+page.server.ts`
2. Activate BUILDER tab in TopNav (change from PENDING to active, href to `/portfolio/[id]/builder`)
3. 2-column shell: left 40% command panel, right 60% results panel
4. **Zone A: RegimeContextStrip.svelte** — fetch from `GET /allocation/{profile}/regime-bands`, render regime badge + stress bar + TAA bands summary + universe count. All via terminal tokens + formatPercent.
5. **Zone B:** Migrate CalibrationPanel from (app) to terminal-native styling. Keep Basic/Advanced/Expert tiers + Market tab. Restyle to monospace + hairline borders + zero radius.
6. **Zone C: RunControls.svelte** — "Run Construction" button with state machine (idle/running/complete/failed). Dropdown for "Compare with". Wire to `POST /model-portfolios/{id}/construct`.
7. **WEIGHTS tab** in right column — migrate BuilderTable (3-level tree Group→Block→Fund), add diverging bar for weight deltas, add run comparison ghost columns. Terminal-native restyle.
8. Portfolio loader in `+page.server.ts` — load portfolio by ID from URL param, fetch latest run, fetch regime bands.

**Gate:**
- Route renders at `/portfolio/{id}/builder`
- TopNav BUILDER tab is active and highlights
- Regime strip shows real TAA data
- CalibrationPanel renders with terminal styling
- Run Construction button triggers SSE stream (even if cascade viz isn't built yet — console logs events)
- WEIGHTS tab shows last run's weights (or empty state)
- `svelte-check` + `pnpm build` clean

**Instruction for Opus:**
```
Read docs/plans/2026-04-13-phase-4-builder-design.md fully (the LOCKED design reference) and docs/plans/2026-04-13-phase-4-execution-wrapper.md Session 1 section fully. Also read the existing (app)/portfolio/ components to understand what to migrate: CalibrationPanel.svelte, BuilderTable.svelte, BuilderActionBar.svelte. Create the terminal route, 2-column layout, left column (3 zones), and WEIGHTS tab with migrated BuilderTable. Wire Run Construction to POST /model-portfolios/{id}/construct. Report.
```

### Session 2 — Cascade Timeline + SSE Wiring + Stress/Risk/Advisor Tabs

**Branch:** `feat/builder-session-2`
**Depends on:** Session 1 merged
**Scope:** Zone D cascade visualization, SSE stream consumption, 3 more result tabs

**Deliverable:**
1. **Zone D: CascadeTimeline.svelte** — the centerpiece. ECharts `graphic` component with 5 pill nodes (Optimal→Robust→Variance-Capped→Minimum Risk→Fallback). States: pending/running/succeeded/failed/skipped. Connector line fills left-to-right. SSE drives state transitions via `createTerminalStream`. Objective value + duration labels. Solver badge (CLARABEL/SCS).
2. **SSE wiring** — connect `GET /jobs/{id}/stream` to CascadeTimeline + progressive tab population. Parse sanitized event types (run_started, optimizer_phase_start/complete, stress_started, validation_gate, narrative_ready, run_complete). Update Zone D pills + Zone E tabs as events arrive.
3. **STRESS tab** — migrate StressScenarioPanel + add Stress Fan Chart (new pattern: line + confidence bands, 4 scenarios). Wire to `POST /model-portfolios/{id}/stress-test` result (already computed during construction run).
4. **RISK tab** — Risk Contribution stacked bar (CVaR per fund) + Factor Exposure horizontal bar (PCA factors). Data from construction run result's `risk_decomposition` and `factor_exposure` fields.
5. **ADVISOR tab** — migrate ConstructionNarrative. Render Jinja2 narrative output with TAA section. Plain institutional text.
6. Tab-visit tracking — `$state` Set tracking which tabs the PM has viewed. All 6 must be visited before Zone F activation unlocks.

**Gate:**
- Construction run streams SSE events to the Builder
- Cascade pills animate in real-time (pending→running→succeeded per phase)
- STRESS tab shows fan chart after run
- RISK tab shows CVaR contribution + factor bars
- ADVISOR tab shows narrative
- Tab-visit gate: activation bar hidden until all tabs viewed
- `svelte-check` + `pnpm build` clean

**Instruction for Opus:**
```
Read docs/plans/2026-04-13-phase-4-builder-design.md Zone D, Zone E, and Charts sections fully. Read docs/plans/2026-04-13-phase-4-execution-wrapper.md Session 2 fully. Verify Session 1 merged (Builder route exists, Run Construction button works). Implement CascadeTimeline with ECharts graphic pipeline, SSE wiring via createTerminalStream, STRESS/RISK/ADVISOR tabs with charts, tab-visit tracking gate. The cascade timeline is the centerpiece — it must animate phase transitions in real-time from SSE events. Report including cascade state descriptions per phase.
```

### Session 3 — Backtest + Monte Carlo + Activation + Polish

**Branch:** `feat/builder-session-3`
**Depends on:** Session 2 merged
**Scope:** Last 2 tabs, activation flow, backend endpoints for backtest/MC if missing, polish

**Deliverable:**
1. **Backend: backtest endpoint** — if `POST /model-portfolios/{id}/backtest` doesn't exist, create it. Uses `backtest_service.py` (exists) to compute historical equity curve + drawdown + metrics for the proposed portfolio weights. Returns `{ dates, nav_series, drawdown_series, metrics: { sharpe, max_dd, ann_return, calmar } }`. Period param: 1Y/3Y/5Y/10Y.
2. **Backend: monte carlo endpoint** — if `POST /model-portfolios/{id}/monte-carlo` doesn't exist, create it. Uses `monte_carlo_service.py` (exists) to simulate 1000 paths. Returns `{ horizon_months, percentiles: { p5, p25, p50, p75, p95 } }`.
3. **BACKTEST tab** — equity curve line chart (pattern #1 NAV) + inverted area drawdown (pattern #2). Metrics sidebar: Sharpe, MaxDD, Ann. Return, Calmar. Period selector 1Y/3Y/5Y/10Y.
4. **MONTE CARLO tab** — area bands with median line. 5 stacked translucent percentile areas. X: months (12-60). Y: portfolio value delta (%).
5. **Zone F: ActivationBar.svelte** — appears when run complete + all 6 tabs visited. "Save as Draft" (secondary) + "Activate Portfolio" (primary amber). Activate opens ConsequenceDialog: type "ACTIVATE" to confirm. Calls `POST /model-portfolios/{id}/activate`. Success: badge changes to "LIVE", banner links to Live Workbench.
6. **Run comparison polish** — ghost columns in WEIGHTS tab showing previous run's values (via `GET /model-portfolios/{id}/construction/runs/{runId}/diff`). Visual: muted color for previous, delta column.
7. **Allocation Bands** in Zone B or as sub-panel: reuse AllocationBandChart from TAA Sprint 4 with added "proposed" diamond marker.
8. **Integration smoke test** — end-to-end: open Builder → review regime → adjust calibration → Run Construction → watch cascade → review all 6 tabs → compare with previous → Activate. Visual validation in browser.

**Gate:**
- Backtest tab shows equity curve + drawdown + metrics for proposed portfolio
- Monte Carlo tab shows percentile bands over 5Y horizon
- Activation flow works end-to-end (draft → type ACTIVATE → live)
- Run comparison shows deltas in WEIGHTS tab
- All 8 chart visualizations render correctly
- Full smoke test passes
- `svelte-check` + `pnpm build` clean
- `make test` green (new backend endpoints tested)

**Instruction for Opus:**
```
Read docs/plans/2026-04-13-phase-4-builder-design.md fully and docs/plans/2026-04-13-phase-4-execution-wrapper.md Session 3 fully. Verify Session 2 merged (cascade timeline works, STRESS/RISK/ADVISOR tabs render). Check if backtest and monte-carlo endpoints exist — if not, create them using existing backtest_service.py and monte_carlo_service.py. Implement BACKTEST tab (equity curve + drawdown + metrics), MONTE CARLO tab (percentile bands), ActivationBar with ConsequenceDialog, run comparison ghost columns, AllocationBandChart with proposed marker. End-to-end smoke test. Report including screenshot descriptions of the full Builder flow.
```

## Post-Phase-4 validation

After all 3 sessions merge, the Builder should support this complete PM workflow:

1. Open `/portfolio/{id}/builder` → see regime context + last run
2. Adjust calibration if needed (risk tolerance, views, constraints)
3. Click "Run Construction" → watch cascade animate (5 phases, SSE real-time)
4. Review WEIGHTS tab (proposed vs current, deltas)
5. Review RISK tab (CVaR contribution, factor exposure)
6. Review STRESS tab (fan chart, 4 scenarios)
7. Review BACKTEST tab (how this portfolio would have done historically)
8. Review MONTE CARLO tab (probability distribution of future outcomes)
9. Review ADVISOR tab (narrative + notes)
10. All 6 tabs visited → Activation Bar appears
11. Click "Activate Portfolio" → type "ACTIVATE" → portfolio goes live
12. Banner appears: "Portfolio activated — view in Live Workbench"

This is the moment where months of infrastructure converge into one operational surface.
