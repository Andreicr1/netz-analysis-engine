# Phase 4 Builder — Session 3: Backtest + Monte Carlo + Activation + Polish

## Context

Phase 4 of 10-phase Terminal Unification. Sessions 1-2 merged (PRs #131, #132).
The Builder now has: 2-column layout, regime context strip, calibration panel,
run controls, CascadeTimeline (real-time SSE), WEIGHTS/STRESS/RISK/ADVISOR tabs,
tab-visit tracking. This session completes the Builder with the final 2 tabs,
activation flow, and run comparison.

Design reference: `docs/plans/2026-04-13-phase-4-builder-design.md` (LOCKED)
Execution wrapper: `docs/plans/2026-04-13-phase-4-execution-wrapper.md` (Session 3)
Master plan: `docs/plans/2026-04-11-terminal-unification-master-plan.md` (background)

## Sanitization — Mandatory Label Mapping

| Internal term | Terminal label |
|---|---|
| CVaR 95 | Tail Loss (95% confidence) |
| Sharpe ratio | Sharpe Ratio |
| max_drawdown | Maximum Drawdown |
| ann_return | Annualized Return |
| calmar | Calmar Ratio |
| validation gate | Readiness Check |
| solver infeasible | Could not meet all constraints |
| advisor remediation | Construction Note |

## Audit Support

If uncertain about any file state, endpoint shape, or component API — READ the
file. Do NOT guess. The master plan was ~40% wrong when audited. The codebase is
the single source of truth.

## Branch

`feat/builder-session-3` (already created from main)

## MANDATORY: Read these files FIRST before writing ANY code

### Backend files
1. `backend/quant_engine/backtest_service.py` — walk_forward_backtest(), _compute_fold_metrics()
2. `backend/quant_engine/monte_carlo_service.py` — run_monte_carlo(), MonteCarloResult dataclass
3. `backend/app/domains/wealth/routes/model_portfolios.py` — existing POST /{id}/backtest endpoint (search for "backtest")
4. `backend/app/domains/wealth/routes/analytics.py` — existing POST /analytics/monte-carlo endpoint
5. `backend/app/domains/wealth/workers/portfolio_nav_synthesizer.py` — synthesize_portfolio_nav(), ModelPortfolioNav model
6. `backend/app/domains/wealth/models/model_portfolio.py` — ModelPortfolio model (backtest_result JSONB, stress_result JSONB, status field, activate logic)
7. `backend/app/domains/wealth/schemas/model_portfolio.py` — existing schemas (search for ConstructionRunDiffOut, ModelPortfolioRead)

### Frontend files
8. `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte` — current builder shell (Session 2 state)
9. `frontends/wealth/src/lib/components/terminal/builder/WeightsTab.svelte` — for run comparison ghost columns
10. `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` — workspace state (search for: activatePortfolio, runPhase, allTabsVisited, constructionRun)
11. `frontends/wealth/src/lib/components/portfolio/charts/PortfolioNavHeroChart.svelte` — reference for NAV chart pattern
12. `frontends/wealth/src/lib/components/portfolio/charts/PortfolioDrawdownUnderwaterChart.svelte` — reference for drawdown chart pattern
13. `packages/investintell-ui/src/lib/charts/terminal-options.ts` — createTerminalChartOptions() factory
14. `packages/investintell-ui/src/lib/tokens/terminal.css` — terminal design tokens

## ARCHITECTURE RULES (non-negotiable)

- Svelte 5 runes only: `$state`, `$derived`, `$effect`, `$props`. No Svelte 4.
- All formatting via `@investintell/ui` formatters. Never `.toFixed()` or inline Intl.
- CSS uses terminal tokens exclusively. Never hex values.
- svelte-echarts for all charts via `createTerminalChartOptions()`.
- No localStorage. No EventSource. No Chart.js.
- `<svelte:boundary>` on async-dependent sections.
- Monospace, 1px borders, zero radius.

## DELIVERABLES (7 items)

### 1. Backend: Portfolio-scoped Monte Carlo endpoint

The global `POST /analytics/monte-carlo` exists but requires the frontend to
know the entity_id pattern. Create a convenience wrapper scoped to model portfolios.

In `backend/app/domains/wealth/routes/model_portfolios.py`, add:

```python
@router.post("/{portfolio_id}/monte-carlo", status_code=202)
async def trigger_monte_carlo(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(require_role(["INVESTMENT_TEAM", "ADMIN"])),
) -> dict:
```

**Implementation:**
- Load the portfolio (verify ownership via RLS)
- Fetch the portfolio's daily returns from `model_portfolio_nav` (same as backtest)
- Call `run_monte_carlo(daily_returns, n_simulations=1000, statistic="return", horizons=[252, 756, 1260])` — reduced from 10k default for response speed
- Return the MonteCarloResult as dict
- Cache in Redis (1h TTL, key: `mc:portfolio:{portfolio_id}:{date}`)

Read the existing `POST /analytics/monte-carlo` handler to understand the pattern,
then adapt for portfolio-scoped use.

**Response shape target for frontend:**
```json
{
    "portfolio_id": "uuid",
    "n_simulations": 1000,
    "horizons_months": [12, 36, 60],
    "percentiles": {
        "p5": [...values per horizon...],
        "p25": [...],
        "p50": [...],
        "p75": [...],
        "p95": [...]
    }
}
```

If the existing MonteCarloResult structure is different, adapt the frontend to
consume whatever it returns — do NOT restructure the backend service.

### 2. Backend: Backtest endpoint enhancement

The existing `POST /{id}/backtest` returns walk-forward CV metrics (Sharpe per fold).
The frontend needs an equity curve + drawdown series for charting.

**Option A (preferred):** Add a new `GET /{portfolio_id}/nav-history` endpoint that
reads from `model_portfolio_nav` table and returns:
```json
{
    "portfolio_id": "uuid",
    "dates": ["2021-01-04", "2021-01-05", ...],
    "nav_series": [100.0, 100.12, ...],
    "drawdown_series": [0.0, -0.0012, ...],
    "metrics": {
        "sharpe": 1.23,
        "max_dd": -0.15,
        "ann_return": 0.082,
        "calmar": 0.55
    }
}
```

Compute drawdown from NAV series: `dd_t = (nav_t / running_max) - 1`.
Compute metrics from daily returns in `model_portfolio_nav`.
Accept query param `period=1Y|3Y|5Y|10Y` to filter date range.

**Option B (if model_portfolio_nav is empty):** Use the existing backtest endpoint
and display fold-level metrics in a table format instead of charts.

Read `model_portfolio_nav` table first to check if data exists for any portfolio.
If the table schema doesn't have the columns you expect, read the model definition.

### 3. BACKTEST Tab: `frontends/wealth/src/lib/components/terminal/builder/BacktestTab.svelte`

**Layout: two charts stacked + metrics sidebar**

```
┌──────────────────────────────────────────┬──────────┐
│ Equity Curve (NAV line chart)            │ SHARPE   │
│ svelte-echarts, pattern #1 (NAV)         │ 1.23     │
│                                          │          │
│                                          │ MAX DD   │
│                                          │ -15.2%   │
├──────────────────────────────────────────┤          │
│ Drawdown (inverted area)                 │ ANN RET  │
│ svelte-echarts, pattern #2 (underwater)  │ 8.2%     │
│                                          │          │
│                                          │ CALMAR   │
│                                          │ 0.55     │
└──────────────────────────────────────────┴──────────┘
  [1Y] [3Y] [5Y] [10Y]  period selector
```

**Charts (svelte-echarts via createTerminalChartOptions):**
- **Equity curve:** line chart with gradient area fill. X: dates. Y: NAV.
  Use `createTerminalChartOptions()` + `series: [{ type: 'line', areaStyle: { opacity: 0.1 } }]`
- **Drawdown:** inverted area chart (values are negative). Same X axis aligned.
  Red-tinted area: `areaStyle: { color: 'var(--terminal-status-error)', opacity: 0.3 }`

**Metrics sidebar (120px fixed right):**
- 4 stat blocks stacked vertically
- Each: label (muted, uppercase, 10px) above value (primary, 14px, bold)
- Sharpe: `formatNumber(value, 2)`
- Max DD: `formatPercent(value, 1)` (red color if < -10%)
- Ann Return: `formatPercent(value, 1)` (green if positive)
- Calmar: `formatNumber(value, 2)`

**Period selector:** 4 buttons below charts. Default: 5Y. On click, re-fetch
with `period` query param.

**Data fetching:** On tab activation (or on mount), call the nav-history endpoint.
Use the workspace pattern — add `backtestData` state + `fetchBacktestData()` method
to `portfolio-workspace.svelte.ts`.

**Empty state:** "Run the NAV synthesizer to see historical performance" if no data.

### 4. MONTE CARLO Tab: `frontends/wealth/src/lib/components/terminal/builder/MonteCarloTab.svelte`

**Single chart: area bands with median line**

```
┌──────────────────────────────────────────────────────┐
│           Monte Carlo Simulation (1,000 paths)       │
│                                                      │
│                                          ╱ p95       │
│                                     ╱───╱            │
│                                ╱───╱                 │
│  ─────────────────────────────╱   ←── p50 (median)   │
│                           ╱───                       │
│                      ╱───╱                           │
│                 ╱───╱         ←── p5                 │
│                                                      │
│  12m         24m         36m         48m         60m  │
└──────────────────────────────────────────────────────┘
```

**Chart (svelte-echarts):**
- 5 stacked translucent areas for percentile ranges:
  - p5 → p25: lightest shade
  - p25 → p50: medium-light
  - p50 → p75: medium
  - p75 → p95: darkest shade
- Solid line at p50 (median)
- X axis: months (12-60)
- Y axis: portfolio value delta (%)
- Use terminal dataviz palette with opacity layers
- `createTerminalChartOptions()` as base

**Data fetching:** On tab activation, POST to the new monte-carlo endpoint.
Add `monteCarloData` state + `fetchMonteCarlo()` method to workspace.

**Empty state:** "Run construction to simulate future outcomes"

### 5. Zone F: ActivationBar + ConsequenceDialog

Create `frontends/wealth/src/lib/components/terminal/builder/ActivationBar.svelte`
and `frontends/wealth/src/lib/components/terminal/builder/ConsequenceDialog.svelte`.

**ActivationBar (48px fixed footer in right column):**
- Appears ONLY when: `workspace.runPhase === "done"` AND `allTabsVisited === true`
- Two buttons:
  - "Save as Draft" — secondary, hairline border. Calls workspace method to save draft.
  - "Activate Portfolio" — primary, amber accent. Opens ConsequenceDialog.
- Hidden (display:none) when conditions not met

**ConsequenceDialog:**
- Modal overlay with terminal styling (dark bg, hairline border, no radius)
- Content:
  - Title: "Activate Portfolio"
  - Warning text: "This will move the portfolio to LIVE status. Active portfolios
    are monitored daily for drift and trigger alerts."
  - Text input: "Type ACTIVATE to confirm"
  - Input validation: button disabled until input === "ACTIVATE" (case-sensitive)
  - Cancel button + Activate button (amber, disabled until typed)
- On confirm: call `workspace.activatePortfolio()` or POST directly to
  `/model-portfolios/{id}/activate`
- On success:
  - Close dialog
  - Show success banner: "Portfolio activated — view in Live Workbench" with link to `/portfolio/live`
  - Update portfolio state to "live"
- On failure: show error message in dialog, do not close

**Keyboard:** ESC closes dialog. Enter submits if ACTIVATE is typed.
**Focus trap:** Tab cycling within dialog (same pattern as FocusMode).

**Wire into +page.svelte:** Add ActivationBar after the tab content div,
conditionally rendered based on `allTabsVisited` and `workspace.runPhase`.

### 6. Run comparison ghost columns in WeightsTab

In `WeightsTab.svelte`, fill the "Previous" column that currently shows "—".

**Data source:** After a construction run completes, fetch the diff from:
`GET /model-portfolios/{id}/construction/runs/{runId}/diff`

The response (`ConstructionRunDiffOut`) contains `weight_delta` which maps
fund instrument_id to delta values.

**Implementation:**
- Add `previousWeights` state to workspace (or local to WeightsTab)
- After construction run completes, fetch the diff endpoint
- Map `weight_delta` entries to the fund rows
- Show previous weight: `current_weight - delta` (derived)
- Show delta: color-coded (green positive, red negative)
- Replace "—" ghost values with real numbers

If the diff endpoint is not available or returns empty, keep showing "—".

### 7. Integration smoke test verification

After all deliverables, verify the complete end-to-end PM workflow:

1. Open `/portfolio/builder` → see regime context + last run
2. Adjust calibration if needed
3. Click "Run Construction" → watch cascade animate (5 phases)
4. Review WEIGHTS tab (proposed vs current)
5. Review RISK tab (CVaR contribution, factor exposure)
6. Review STRESS tab (4 scenarios)
7. Review BACKTEST tab (equity curve + drawdown + metrics)
8. Review MONTE CARLO tab (percentile bands)
9. Review ADVISOR tab (narrative + holding changes)
10. All 6 tabs visited → ActivationBar appears
11. Click "Activate Portfolio" → type "ACTIVATE" → confirm
12. Success banner with link to Live Workbench

## FILE STRUCTURE (new + modified)

```
backend/app/domains/wealth/routes/
  model_portfolios.py              ← MODIFY: add monte-carlo endpoint + nav-history endpoint

frontends/wealth/src/
  routes/(terminal)/portfolio/builder/
    +page.svelte                   ← MODIFY: add ActivationBar, wire backtest/MC data
  lib/components/terminal/builder/
    BacktestTab.svelte             ← NEW: equity curve + drawdown + metrics
    MonteCarloTab.svelte           ← NEW: percentile band chart
    ActivationBar.svelte           ← NEW: Zone F (48px footer)
    ConsequenceDialog.svelte       ← NEW: typed ACTIVATE confirmation
    WeightsTab.svelte              ← MODIFY: fill ghost columns with diff data
  lib/state/
    portfolio-workspace.svelte.ts  ← MODIFY: add backtestData, monteCarloData, fetchBacktest, fetchMonteCarlo, activatePortfolio
```

## GATE CRITERIA

1. BACKTEST tab shows equity curve + drawdown + metrics (Sharpe, MaxDD, Ann Return, Calmar)
2. BACKTEST period selector (1Y/3Y/5Y/10Y) re-fetches and updates charts
3. MONTE CARLO tab shows percentile band chart (p5/p25/p50/p75/p95) over 12-60 months
4. ActivationBar appears only when run complete + all 6 tabs visited
5. ConsequenceDialog: type "ACTIVATE" → button enables → portfolio activates
6. Post-activation: success banner with "view in Live Workbench" link
7. WeightsTab Previous column shows real values from diff endpoint (or graceful "—" fallback)
8. All chart visualizations render correctly with svelte-echarts
9. `cd frontends/wealth && pnpm exec svelte-check` — zero errors
10. `cd frontends/wealth && pnpm build` — clean
11. `cd backend && python -m pytest tests/ -x -q` — green
12. No TypeScript `any` types
13. All formatters from `@investintell/ui`
14. Zero hex color values
15. Zero raw quant jargon in any user-facing text

## What NOT to do

- Do NOT modify CascadeTimeline, StressTab, RiskTab, or AdvisorTab from Session 2
- Do NOT modify existing (app)/portfolio/ components
- Do NOT install new npm packages
- Do NOT create mock data — wire to real endpoints or show empty state
- Do NOT put hex color values in any .svelte file under terminal/
- Do NOT use Chart.js — svelte-echarts mandatory
- Do NOT restructure existing backend services — add new endpoints that delegate to them
- When modifying workspace (1711+ lines), ADD only — do NOT refactor existing code

## COMMIT

When all gate criteria pass, commit with:
```
feat(builder): Session 3 — backtest, monte carlo, activation flow, run comparison

BACKTEST tab (equity curve + drawdown + Sharpe/MaxDD/AnnReturn/Calmar).
MONTE CARLO tab (percentile bands p5-p95 over 12-60 months).
ActivationBar + ConsequenceDialog (typed ACTIVATE confirmation).
WeightsTab run comparison (diff endpoint ghost columns).
Backend: portfolio-scoped monte-carlo + nav-history endpoints.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Push to origin/feat/builder-session-3.
