# Phase 4 Builder — Consolidated Design Reference

**Date:** 2026-04-13
**Status:** LOCKED — approved by Andrei, designed by 3 specialist agents
**Source agents:** wealth-ux-flow-architect, wealth-platform-architect, wealth-echarts-specialist

## Core Concept

The Builder is a **construction command center**, not a fund picker. The PM sets POLICY (risk tolerance, turnover budget, views, constraints), the TAA system sets allocation BANDS (regime-responsive), and the CLARABEL optimizer fills the portfolio from the FULL universe (~5,400 instruments). Zero drag-drop. Zero manual fund-to-block assignment.

## Layout: Two-Column Fixed Split (40/60)

### Left Column (40%) — Command Panel

Three zones stacked, always visible, no tabs:

**Zone A: Regime Context Strip (120px fixed)**
- Regime badge (Defensive/Balanced/Growth/Stress — OD-22 translated labels, never raw RISK_OFF)
- Stress score bar (0-100, regime-colored, animated)
- TAA bands summary (equity/FI/alt/cash as range bars min→target→max)
- Universe count ("5,412 instruments across 4 classes")
- Updates via SSE if regime changes mid-session

**Zone B: Calibration Controls (280px fixed)**
- Risk tolerance slider (Conservative/Moderate/Aggressive — maps to lambda internally)
- Turnover budget (% slider, label "Maximum portfolio change")
- Active views toggle (expands BL views mini-table, label "Market views" — never "BL views")
- Constraint overrides (sector caps, single-fund max, min cash — collapsible fieldset)
- Each control shows current value + last run value in muted (delta visual)

**Zone C: Run Controls (80px fixed)**
- Primary button "Run Construction" (pill 32px, amber accent)
- Dropdown "Compare with: [last run / specific date]"
- Button states: idle → running (pulse) → complete (green check) → failed (red)
- Keyboard: Enter triggers run
- Button disabled until dirty state detected (policy change or data staleness)

### Right Column (60%) — Results Panel

**Pre-Run State:**
Last completed run (or empty state "No construction runs yet"). Header with timestamp + regime of last run. Weight table grouped by asset class. Narrative summary footer.

**Post-Run State (cascade active):**

**Zone D: Cascade Timeline (160px fixed)**
5-pill horizontal pipeline: Optimal → Robust → Variance-Capped → Minimum Risk → Fallback. ECharts `graphic` component (not a chart — status pipeline on canvas). States per pill: pending (dim) → running (amber pulse) → succeeded (green check) → failed (muted strikethrough) → skipped (ghost). Connector line fills left-to-right. One-liner status below active pill. SSE stream drives state transitions.

**Zone E: Results Tabs (flex, scrollable)**
6 mandatory tabs — ALL must be visited before Activation unlocks:

| Tab | Content | Chart Pattern |
|---|---|---|
| WEIGHTS | Proposed vs current weights, grouped by asset class. Delta column color-coded. | Diverging horizontal bar |
| RISK | CVaR contribution per position + factor exposure (Market/Style/Sector) | Stacked bar + horizontal bar |
| STRESS | 4 parametric scenarios + custom. Portfolio drawdown per scenario. | Fan chart (line + confidence bands) |
| BACKTEST | Historical equity curve + drawdown for proposed portfolio (1/3/5/10Y). Sharpe, MaxDD, Ann. Return. | Line + inverted area (patterns #1 + #2) |
| MONTE CARLO | 1000 simulated paths with 5th/25th/50th/75th/95th percentile bands over 1-5Y horizon. | Area bands + median line |
| ADVISOR | Construction advisor notes + narrative summary (Jinja2 output with TAA section). | Plain text |

**Zone F: Activation Bar (48px fixed footer)**
Appears only when run completes successfully AND all 6 tabs visited. Two buttons:
- "Save as Draft" (secondary, hairline border)
- "Activate Portfolio" (primary, amber accent)
Activate opens ConsequenceDialog: type "ACTIVATE" to confirm. `approved_by` field in run record for future 4-eyes.

## Strategic Decisions (Platform Architect, locked)

1. **PM sets POLICY, not PORTFOLIO.** No fund picking, no drag-drop. TAA defines blocks, optimizer fills them.
2. **Single "Run Construction" button.** Policy panel IS the confirmation. No parameter dialog.
3. **6 mandatory review tabs** before activation unlocks (tab-visit tracking).
4. **NO manual weight overrides** post-construction. Lock/exclude specific funds + re-run is the override mechanism. Audit trail integrity non-negotiable.
5. **ConsequenceDialog with typed "ACTIVATE"** for v1. `approved_by` DB field ready for future 4-eyes.
6. **Builder and Live stay SEPARATE routes.** Construction mode (quarterly/monthly) vs monitoring mode (daily). Same portfolio selector, two lenses. Banner in Builder links to Live.
7. **Run comparison** via dropdown in Zone C. Ghost columns show previous run's weights. Max 2 runs visible simultaneously. Full history via CommandPalette.

## Chart Visualizations (8 total)

### 1. Construction Cascade (NEW — centerpiece)
ECharts `graphic` pipeline, NOT a chart. 5 connected pill nodes on horizontal rail. Phase name + objective value + solver badge (CLARABEL/SCS). States: pending/running/succeeded/failed/skipped. Connector fills left-to-right. Running pulse via `animateStyle`.

Data: `{ phases: [{ id, name, status, solver, objective_value, duration_ms }], selected_phase }`

### 2. Allocation Bands (REUSE AllocationBandChart from TAA Sprint 4)
3-layer bar: grey IPS, colored regime bands, white dot current. Add diamond "proposed" marker for post-construction comparison.

### 3. Stress Fan Chart (NEW)
Line chart with confidence area bands. One line per scenario fanning from current. X: forward horizon (days). Y: portfolio delta (%). Scenario-semantic colors (GFC=red, COVID=amber, Taper=blue, Rate Shock=purple).

Data: `{ scenarios: [{ name, path: number[], severity }], horizon_days: number[] }`

### 4. Weight Comparison — Diverging Bar (NEW)
Horizontal bar diverging from zero. Funds on Y, delta weight on X. Positive right (green), negative left (red). Sorted by |delta| descending.

Data: `{ deltas: [{ fund_name, ticker, delta_weight, new_weight }] }`

### 5. Risk Contribution — Stacked Bar (REUSE pattern)
Single horizontal 100% stacked bar. Each segment = fund's CVaR contribution. Tooltip: fund + absolute CVaR + % of total.

Data: `{ contributions: [{ fund_name, cvar_contribution, pct_of_total }] }`

### 6. Factor Exposure — Horizontal Bar
Horizontal bar grouped by category (Market/Style/Sector). Length = loading magnitude. Color = positive/negative. Not radar (factor count variable).

Data: `{ factors: [{ name, category, loading }] }`

### 7. Backtest Equity Curve + Drawdown (REUSE patterns #1 + #2)
Top: NAV line chart showing historical portfolio performance. Bottom: inverted area drawdown. Metrics sidebar: Sharpe, MaxDD, Ann. Return, Calmar. Period selector: 1Y/3Y/5Y/10Y.

Data: `{ dates, nav_series, drawdown_series, metrics: { sharpe, max_dd, ann_return, calmar } }`

### 8. Monte Carlo Simulation (NEW)
Area bands with median line. 5 stacked translucent areas (5th-25th, 25th-50th, 50th-75th, 75th-95th percentile ranges). Solid line at 50th. X: forward months (12-60). Y: portfolio value delta (%).

Data: `{ horizon_months, percentiles: { p5, p25, p50, p75, p95 } }`

## URL Structure

`/terminal/portfolio/{portfolio_id}/builder` — portfolio_id in path. Run ID as query param: `?run=uuid`. Reload-safe.

## Existing Components to Migrate

From `(app)/portfolio/` to terminal-native:
- BuilderActionBar → Zone C Run Controls (restyle)
- BuilderColumn → Zone E Results Tabs (restyle + add Backtest/MonteCarlo tabs)
- UniverseColumn → NOT USED (no fund picking in command center)
- CalibrationPanel → Zone B Calibration Controls (restyle, already has Market tab from TAA)
- ConstructionNarrative → ADVISOR tab content
- ConstructionResultsOverlay → Replaced by Zone E progressive reveal
- StressScenarioPanel → STRESS tab content
- BuilderTable → WEIGHTS tab content (restyle)
- BuilderRightStack → Zone E right side (restructure as tabs)

## What's NEW (not migration)

1. Terminal route + page scaffold
2. Zone A Regime Context Strip
3. Zone D Cascade Timeline (ECharts graphic pipeline)
4. Tab-visit tracking gate for activation unlock
5. BACKTEST tab + chart
6. MONTE CARLO tab + chart
7. Weight Comparison diverging bar
8. Risk Contribution stacked bar
9. Factor Exposure horizontal bar
10. Run comparison ghost columns
