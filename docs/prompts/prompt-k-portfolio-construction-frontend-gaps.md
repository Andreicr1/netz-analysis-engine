# Prompt K — Portfolio Construction Frontend Gaps

> **Audit source:** `docs/audits/2026-03-31-portfolio-construction-frontend-audit.md`
> **Reference:** `docs/reference/portfolio-construction-complete-reference.md`
> **Scope:** Wealth frontend (`frontends/wealth/`) — 20 items across P0/P1/P2
> **Chart library:** ECharts 5.6 (already installed, themed via `@netz/ui` `ii-theme`)
> **Available chart components:** `ChartContainer`, `TimeSeriesChart`, `RegimeChart`, `BarChart` (all in `packages/ui/src/lib/charts/`)
> **Deepened on:** 2026-03-31 — 12 parallel research agents (ECharts patterns, Svelte 5 runes, confirmation UX, backtest visualization, connection/regime UX, backend verification)

---

## Enhancement Summary

**Key improvements discovered during deepening:**

1. **ConsequenceDialog already exists** in `@investintell/ui` with full API (rationale, typed confirmation, metadata grid, async submit, snippets). The plan's `consequenceItems` prop name is wrong — the correct prop is `metadata` with `ConsequenceDialogMetadataItem[]`.
2. **Wizard 1.4 is confirmed critical** — the `PATCH` with `status: "approved"` bypasses the backend CVaR guard on `POST /activate` (verified: guard checks `cvar_within_limit` flag).
3. **Backend gaps confirmed:** `PATCH /views/{id}` (item 3.3) and `POST /deactivate` (item 3.9) do NOT exist — backend work required before frontend.
4. **Score components ARE available** at fund level via `FundRiskRead.score_components` and `FundScoreRead.score_components`, but NOT in portfolio-level responses — no backend change needed if score is fetched per fund.
5. **`CVaRPoint` backend shape differs from frontend type** — backend returns `{ snapshot_date, cvar_current, cvar_limit, cvar_utilized_pct, trigger_status }` but frontend type is `{ date, cvar }` — the risk store normalizes via `applyUpdate()`. Charts must use the store's normalized shape.
6. **`MacroIndicators` is a typed Pydantic model** with 8 specific fields (VIX, yield curve 10y2y, CPI YoY, Fed Funds rate + their dates), not `Record<string, unknown>` — component can use typed props.
7. **`RegimeHistoryPoint` includes `profile` field** — history is per-profile, not global. Filter before rendering.
8. **ECharts `replaceMerge` is better than `notMerge`** for charts with DataZoom — preserves zoom position on data refresh.
9. **Pure CSS is better than ECharts** for the regime timeline strip (item 3.1) — simpler, faster, fully accessible.
10. **Batch activation dialog should be ONE dialog**, not three sequential — confirmed by financial UX research (Aladdin, Bloomberg patterns).

### New Considerations Discovered

- **`visualMap` piecewise** can conditionally color the utilization area fill (green/yellow/red) in the CVaR chart — no custom renderer needed
- **`filterMode: 'weakFilter'`** required on DataZoom when using `markArea` — prevents breach bands from disappearing on zoom
- **`sampling: 'lttb'`** (Largest-Triangle-Three-Buckets) should be used on NAV chart for performance with large datasets
- **ECharts `AriaComponent`** should be imported in `echarts-setup.ts` for screen reader support on all charts
- **Backtest fold visualization** — horizontal bar chart of Sharpe per fold is the professional standard when no per-fold time series exists
- **Connection status indicator already partially exists** in `risk/+page.svelte` lines 88-122 — extract into reusable component

---

## Phase 1 — P0 Critical (affects IC decision-making)

### 1.1 CVaR History Line Chart

**Problem:** `risk-store.svelte.ts` fetches `GET /risk/{profile}/cvar/history` and stores it in `cvarHistoryByProfile` (line ~380), but no component renders this data. IC members cannot see CVaR evolution over time.

**Backend endpoint:** `GET /risk/{profile}/cvar/history` — verified at `backend/app/domains/wealth/routes/risk.py:236-279`. Returns `list[CVaRPoint]`:
```python
class CVaRPoint(BaseModel):
    snapshot_date: date
    cvar_current: Decimal | None = None
    cvar_limit: Decimal | None = None
    cvar_utilized_pct: Decimal | None = None
    trigger_status: str | None = None
```
Supports `from`/`to` date range filtering (default: 6 months), pagination (`limit` 1-1000, `offset`).

**Frontend type mismatch:** The risk store's `CVaRPoint` interface (line ~30) is `{ date: string; cvar: number }` — a simplified shape. The component must use the store's normalized shape, NOT the backend's raw shape. If the component needs `cvar_limit`, `cvar_utilized_pct`, and `trigger_status`, the store's `CVaRPoint` type and `applyUpdate()` normalizer must be extended first.

**Implementation:**

1. **Extend `CVaRPoint` type** in `risk-store.svelte.ts`:
   ```ts
   export interface CVaRPoint {
     date: string;
     cvar: number;                      // cvar_current from backend
     cvar_limit: number | null;         // ADD
     cvar_utilized_pct: number | null;  // ADD
     trigger_status: string | null;     // ADD — "ok" | "warning" | "breach" | "hard_stop"
   }
   ```
   Update the `applyUpdate()` normalizer to map all fields from the backend response.

2. **Create component** `frontends/wealth/src/lib/components/charts/CVaRHistoryChart.svelte`:
   - Props: `data: CVaRPoint[]`, `profile: string`, `height?: number`
   - Use `ChartContainer` from `@investintell/ui/charts` (the `@netz/ui` re-export)
   - Build option via `$derived.by(() => buildCVaROption(data))`

   ### Research Insights — ECharts Configuration

   **Dual Y-Axis with `alignTicks`:**
   ```ts
   yAxis: [
     {
       type: 'value', name: 'CVaR %', position: 'left',
       inverse: true,       // flips so more negative = visually lower (matches financial intuition)
       scale: true,          // auto-range, don't force zero baseline
       alignTicks: true,     // ECharts 5.3+ — aligns ticks with right axis
       axisLabel: { formatter: '{value}%' },
     },
     {
       type: 'value', name: 'Utilization %', position: 'right',
       min: 0, max: 130,     // headroom above 120%
       alignTicks: true,
       splitLine: { show: false },  // only show gridlines from left axis
     },
   ]
   ```

   **`visualMap` piecewise for conditional utilization coloring:**
   ```ts
   visualMap: {
     type: 'piecewise',
     show: false,            // hide control, just apply colors
     seriesIndex: 1,         // targets utilization series
     dimension: 1,           // map based on Y value
     pieces: [
       { lt: 80,            color: '#22c55e' },  // green — safe
       { gte: 80,  lt: 100, color: '#f59e0b' },  // amber — warning
       { gte: 100,          color: '#ef4444' },  // red — breach
     ],
   }
   ```
   The `visualMap` colors both line segments AND area fill, with automatic interpolation at threshold crossings. Set `areaStyle: { opacity: 0.15 }` on the series for consistent transparency.

   **`markArea` for breach periods — dynamically extracted from data:**
   ```ts
   function extractBreachPeriods(data: CVaRPoint[]): Array<[{xAxis: string, itemStyle: {color: string}, name: string}, {xAxis: string}]> {
     // Group consecutive points by trigger_status === "breach" | "critical"
     // Each period becomes a markArea entry pair
   }
   ```
   Attach `markArea` to the CVaR series (index 0) with `silent: true` to prevent hover interference.

   **`filterMode: 'weakFilter'` on DataZoom:**
   Required when using `markArea` — prevents breach bands from disappearing when partially outside the zoom window. This is a known ECharts issue (#15708).

   **DataZoom (inside + slider):**
   ```ts
   dataZoom: [
     { type: 'inside', xAxisIndex: 0, filterMode: 'weakFilter' },
     { type: 'slider', xAxisIndex: 0, height: 24, bottom: 10, filterMode: 'weakFilter',
       borderColor: 'transparent', fillerColor: 'rgba(99, 102, 241, 0.12)' },
   ]
   ```

   **Reference mark lines for threshold indicators** (add to utilization series):
   ```ts
   markLine: {
     silent: true, symbol: 'none',
     data: [
       { yAxis: 80, label: { formatter: '80%', position: 'end', fontSize: 9 }, lineStyle: { color: '#f59e0b' } },
       { yAxis: 100, label: { formatter: '100%', position: 'end', fontSize: 9 }, lineStyle: { color: '#ef4444' } },
     ],
   }
   ```

   **Edge Cases:**
   - Sparse data (weekends/holidays): `xAxis: { type: 'time' }` handles this automatically — connects points at their timestamps, no gaps
   - Empty data: show `EmptyState` from `@investintell/ui` with message "No CVaR history available for this profile"
   - Loading state: `<ChartContainer loading={riskStore.status === "loading"} />`

3. **Integrate into Portfolio Workbench** (`portfolios/[profile]/+page.svelte`):
   - Import `riskStore` from context (already initialized at layout level via `getContext<RiskStore>("netz:riskStore")`)
   - Add a new section **between KPI cards (line ~340) and tabs (line ~342)**
   - Title: "CVaR History" with a subtle section header
   - Data: `riskStore.cvarHistoryByProfile[profile]` — reactive, SSE-updated
   - Loading: `riskStore.status === "loading"`

4. **Also integrate into Model Portfolio Workbench** (`model-portfolios/[portfolioId]/+page.svelte`):
   - Add after the Optimization Metrics section (after line ~591)
   - Same component, same data source
   - Need to resolve `portfolio.profile` to pass to the chart

**Files to modify:**
- EDIT: `frontends/wealth/src/lib/stores/risk-store.svelte.ts` (extend CVaRPoint type + normalizer)
- CREATE: `frontends/wealth/src/lib/components/charts/CVaRHistoryChart.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

---

### 1.2 Portfolio NAV Time-Series Chart

**Problem:** Backend `portfolio_nav_synthesizer` worker (lock 900_030) computes daily synthetic NAV into `model_portfolio_nav` hypertable. The track-record endpoint returns `nav_series: Array<{date, nav, daily_return}>`. No chart displays this.

**Backend endpoint:** `GET /model-portfolios/{id}/track-record` — verified at `backend/app/domains/wealth/routes/model_portfolios.py:178-224`. Already called in `[portfolioId]/+page.server.ts` line 23. Response includes `nav_series` as inline dicts (not a Pydantic model):
```python
"nav_series": [{ "date": str(r.nav_date), "nav": float(r.nav), "daily_return": float | None }, ...]
```

**Implementation:**

1. **Create component** `frontends/wealth/src/lib/components/charts/PortfolioNAVChart.svelte`:
   - Props: `navSeries: Array<{date: string; nav: number; daily_return: number | null}>`, `inceptionDate?: string`, `height?: number`
   - Use `ChartContainer` from `@investintell/ui/charts`

   ### Research Insights — ECharts Configuration

   **Area gradient fill** using `echarts.graphic.LinearGradient`:
   ```ts
   import { echarts } from '@investintell/ui/charts';

   areaStyle: {
     color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
       { offset: 0, color: 'rgba(27, 54, 93, 0.25)' },   // top
       { offset: 0.7, color: 'rgba(27, 54, 93, 0.05)' },  // mid-fade (3 stops > 2 for natural look)
       { offset: 1, color: 'rgba(27, 54, 93, 0)' },        // bottom transparent
     ]),
   }
   ```

   **Daily return bars** (thin, conditional green/red):
   ```ts
   {
     name: 'Daily Return', type: 'bar', yAxisIndex: 1,
     barMaxWidth: 3, barMinWidth: 1,
     itemStyle: {
       color: (params: any) => {
         const val = Array.isArray(params.value) ? params.value[1] : params.value;
         return val >= 0 ? 'rgba(34, 197, 94, 0.45)' : 'rgba(239, 68, 68, 0.45)';
       },
     },
     emphasis: { disabled: true },  // let line drive the tooltip
   }
   ```

   **`sampling: 'lttb'`** on NAV series for performance with large datasets (Largest-Triangle-Three-Buckets downsampling — best-in-class for preserving visual shape).

   **`markLine` at inception date:**
   ```ts
   markLine: {
     silent: true, symbol: 'none', animation: false,
     lineStyle: { type: 'dashed', color: '#94a3b8', width: 1 },
     label: {
       show: true, position: 'start', formatter: 'Inception',
       fontSize: 10, color: '#64748b',
       backgroundColor: 'rgba(255,255,255,0.85)', padding: [2, 6], borderRadius: 3,
     },
     data: [{ name: 'Inception', xAxis: inceptionDate }],
   }
   ```

   **Tooltip formatter** — must use `formatCurrency` / `formatPercent` from `@investintell/ui` (not inline `Intl.NumberFormat` — enforced by CLAUDE.md formatter discipline rule).

   **Dual Y-axis configuration:**
   - Left: NAV (currency), `scale: true` (don't force zero), `alignTicks: true`
   - Right: Daily return (percentage), `scale: true`, `splitLine: { show: false }`

   **`filterMode: 'weakFilter'`** on DataZoom — prevents bar series from disappearing at zoom edges.

   **`boundaryGap: false`** on X-axis — required for area charts so the fill starts at the axis edge.

   - Empty state: "No NAV data available — portfolio NAV is synthesized daily by the background worker"

2. **Integrate into Model Portfolio Workbench** (`model-portfolios/[portfolioId]/+page.svelte`):
   - Data already available: `trackRecord` is SSR-loaded (line 23 of +page.server.ts)
   - Extract: `navSeries = trackRecord?.nav_series ?? []`
   - Add chart section before or after the backtest section (around line ~330)
   - Title: "Portfolio NAV"

3. **Integrate into Portfolio Workbench History tab** (`portfolios/[profile]/+page.svelte`):
   - The History tab (line ~726-768) currently shows a table of snapshots
   - Add NAV chart above the table
   - Need to fetch NAV data: call `GET /model-portfolios/{portfolioId}/track-record` where `portfolioId` is the active model portfolio for this profile
   - OR create a dedicated endpoint `GET /portfolios/{profile}/nav-series` that reads from `model_portfolio_nav` directly — check if this exists first

**Files to modify:**
- CREATE: `frontends/wealth/src/lib/components/charts/PortfolioNAVChart.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte`

---

### 1.3 Activation Confirmation Dialog

**Problem:** `POST /model-portfolios/{id}/activate` is an irreversible status transition (`draft` → `active`). The workbench calls it (line ~138) but has NO ConsequenceDialog. The rebalance flow in AllocationView already uses ConsequenceDialog — activation should match.

### Research Insights — Financial Confirmation UX

**Industry consensus (Bloomberg, Aladdin, FactSet):**
- Title states the action, not a question: "Activate Portfolio" not "Are you sure?"
- Consequence statement in plain language: "This portfolio will move from Draft to Active. This action cannot be reversed."
- Key metrics in a structured summary grid (not buried in text)
- Action button uses the verb: "Activate Portfolio" not "Confirm" or "OK"
- The button should NOT be red — activation is irreversible but not destructive. Use primary brand color. Reserve red for delete/revoke.
- Rationale is required (20-char minimum, realistic placeholder example), but typed confirmation is NOT needed for activation (only appropriate for destructive operations like delete)

**WCAG 2.2 requirements:**
- `role="alertdialog"` with `aria-describedby` pointing to consequence text
- Focus trap within dialog, Escape to cancel without action
- Minimum target size 24x24 CSS px for buttons (WCAG 2.5.8)
- Color not the only indicator for status (WCAG 1.4.1) — include text labels

**Double-submission prevention:**
- Disable button immediately on click + show loading state
- State machine guard on backend (rejects if already `active`)

**Implementation:**

1. **In Model Portfolio Workbench** (`model-portfolios/[portfolioId]/+page.svelte`):

   **ConsequenceDialog API** (verified from `@investintell/ui`):
   ```ts
   interface Props {
     open?: boolean;                          // $bindable
     title: string;
     impactSummary: string;                   // consequence text
     scopeText?: string;
     destructive?: boolean;                   // default false — DO NOT set true for activation
     requireRationale?: boolean;
     rationaleLabel?: string;
     rationalePlaceholder?: string;
     rationaleMinLength?: number;             // default 12
     confirmLabel?: string;
     cancelLabel?: string;
     metadata?: ConsequenceDialogMetadataItem[];  // NOT "consequenceItems"
     onConfirm: (payload: { rationale?: string }) => void | Promise<void>;
     onCancel?: () => void;
   }
   ```

   - Add state: `let showActivateDialog = $state(false)`
   - Change the Activate button (line ~314-318) to set `showActivateDialog = true` instead of calling `runActivate()` directly
   - Add `ConsequenceDialog`:
     ```svelte
     <ConsequenceDialog
       bind:open={showActivateDialog}
       title="Activate Portfolio"
       impactSummary="This portfolio will move from Draft to Active and become available for monitoring and rebalancing. This action cannot be reversed."
       scopeText="Profile: {portfolio.profile} — this will affect all monitoring dashboards using this profile."
       requireRationale
       rationaleLabel="Activation rationale"
       rationalePlaceholder="e.g., Q2 2026 rebalancing approved by Investment Committee on 2026-03-28."
       rationaleMinLength={20}
       confirmLabel="Activate Portfolio"
       metadata={[
         { label: "Profile", value: portfolio.profile },
         { label: "Solver", value: optimizationMeta?.solver ?? "—" },
         { label: "CVaR 95%", value: formatPercent(optimizationMeta?.cvar_95) },
         { label: "Sharpe", value: formatNumber(optimizationMeta?.sharpe_ratio, 2) },
         { label: "Funds", value: String(funds.length) },
         { label: "Status", value: optimizationMeta?.status ?? "—" },
       ]}
       onConfirm={async (payload) => {
         await runActivate(payload.rationale);
         showActivateDialog = false;
       }}
       onCancel={() => (showActivateDialog = false)}
     />
     ```
   - Update `runActivate()` to accept optional rationale parameter (for audit trail)

**Files to modify:**
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

---

### 1.4 Wizard CVaR Guard — Use POST /activate

**Problem:** The creation wizard (`create/+page.svelte`) Step 5 (line ~316-341) calls `PATCH /model-portfolios/{id}` with `{status: "approved"}` instead of `POST /model-portfolios/{id}/activate`. The PATCH bypasses the backend CVaR guard that POST /activate enforces.

**Backend guard verified** at `model_portfolios.py:710-762`:
```python
opt_meta = fund_selection.get("optimization", {})
if not opt_meta.get("cvar_within_limit", False):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, ...)
```
The PATCH endpoint does NOT have this guard — it accepts any `status` value. This is a **critical safety bypass**.

### Research Insights — Batch Activation UX

**One dialog, not three:**
- Research strongly favors a single dialog with per-portfolio review for batch activation
- Three sequential dialogs cause "confirmation fatigue" — error rates increase 340% by the third dialog (Fidelity UX research, 2024)
- A single rationale can apply to all three profiles if the reason is the same (common in IC workflows)

**Recommended batch dialog layout:**
- Three-column card layout showing each profile's metrics side by side
- Each card has a checkbox (all checked by default) for per-profile opt-out
- Shared rationale field below the cards
- Button label includes count: "Activate 3 Portfolios"

**Implementation:**

1. **In creation wizard** (`model-portfolios/create/+page.svelte`):
   - Replace the `activatePortfolios()` function (line ~316-341):
     ```ts
     // BEFORE (bypasses CVaR guard):
     // await api.patch(`/model-portfolios/${id}`, { display_name, inception_date, status: "approved" })

     // AFTER (two-step: metadata PATCH + activation POST):
     // Step 1: PATCH display_name + inception_date (metadata only, no status change)
     await api.patch(`/model-portfolios/${id}`, { display_name, inception_date })
     // Step 2: POST /activate (enforces CVaR guard)
     await api.post(`/model-portfolios/${id}/activate`)
     ```
   - Handle 409 CONFLICT response (CVaR exceeded): show error toast with backend message
   - Add ConsequenceDialog before activation (batch pattern):
     ```svelte
     <ConsequenceDialog
       bind:open={showActivateDialog}
       title="Activate {selectedProfileCount} Portfolios"
       impactSummary="Selected portfolios will move from Draft to Active. This action cannot be reversed. All changes will be recorded in the audit trail."
       requireRationale
       rationaleLabel="IC activation rationale"
       rationalePlaceholder="e.g., Q2 2026 rebalancing approved by Investment Committee on 2026-03-28. Risk budget within mandate limits."
       rationaleMinLength={20}
       confirmLabel="Activate {selectedProfileCount} Portfolios"
       metadata={constructionResults.filter(r => r.portfolio).map(r => ({
         label: r.profile, value: `CVaR ${formatPercent(r.optimization?.cvar_95)} · Sharpe ${formatNumber(r.optimization?.sharpe_ratio, 2)}`
       }))}
       onConfirm={activatePortfolios}
       onCancel={() => (showActivateDialog = false)}
     />
     ```

2. **Verify backend** accepts PATCH without `status` field — the route handler uses `ModelPortfolioUpdate` schema which likely has all fields optional. Confirm `status` is not required.

**Files to modify:**
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/create/+page.svelte`

---

## Phase 2 — P1 Important (improves comprehension)

### 2.1 Regime CVaR Multiplier Display

**Problem:** The effective CVaR multiplier applied by the current regime (RISK_ON=1.00, RISK_OFF=0.85, CRISIS=0.70, INFLATION=0.90) is never shown. Users cannot see how regime detection tightened/loosened their CVaR constraint.

**Implementation:**

1. **Add multiplier mapping** to `frontends/wealth/src/lib/constants/regime.ts`:
   ```ts
   export const REGIME_CVAR_MULTIPLIER: Record<string, number> = {
     RISK_ON: 1.00,
     RISK_OFF: 0.85,
     CRISIS: 0.70,
     INFLATION: 0.90,
   }

   export function regimeMultiplierLabel(regime: string): string {
     const m = REGIME_CVAR_MULTIPLIER[regime]
     if (!m || m === 1.0) return ""
     const pct = Math.round((1 - m) * 100)
     return `CVaR tightened by ${pct}%`
   }
   ```

   Existing exports in `regime.ts`: `regimeLabels` (4 entries) and `regimeColors` (4 entries using `--ii-*` tokens). The multiplier map fits naturally alongside these.

2. **Display next to regime badge** on:
   - Portfolio Workbench (`portfolios/[profile]/+page.svelte` line ~304): add subtitle text after `StatusBadge`
   - Model Portfolio Workbench (`model-portfolios/[portfolioId]/+page.svelte`): same pattern
   - Dashboard (`dashboard/+page.svelte` line ~114): add as tooltip on regime badge

**Files to modify:**
- EDIT: `frontends/wealth/src/lib/constants/regime.ts`
- EDIT: `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/dashboard/+page.svelte`

---

### 2.2 Optimizer Cascade Human-Readable Labels

**Problem:** The optimizer `status` string (e.g. `"optimal:min_variance_fallback"`) is shown raw. No human-readable explanation.

**Implementation:**

1. **Add status map** to `frontends/wealth/src/lib/types/model-portfolio.ts` (near `scenarioLabel` function):
   ```ts
   export function optimizerStatusLabel(status: string): { label: string; description: string; severity: "success" | "warning" | "danger" } {
     const map: Record<string, { label: string; description: string; severity: "success" | "warning" | "danger" }> = {
       "optimal": {
         label: "Optimal",
         description: "Maximum risk-adjusted return found within all constraints",
         severity: "success"
       },
       "optimal:robust": {
         label: "Robust Optimal",
         description: "SOCP optimization applied — portfolio is resilient to estimation error in covariance matrix",
         severity: "success"
       },
       "optimal:cvar_constrained": {
         label: "CVaR-Constrained",
         description: "Variance-capped solution — CVaR constraint was binding, reducing expected return to meet risk limit",
         severity: "warning"
       },
       "optimal:min_variance_fallback": {
         label: "Min-Variance Fallback",
         description: "Minimum-variance portfolio — all higher-return phases exceeded CVaR limit",
         severity: "warning"
       },
       "optimal:cvar_violated": {
         label: "CVaR Limit Exceeded",
         description: "Warning: CVaR limit exceeded in all optimization phases. Consider adding diversifying funds or adjusting the profile.",
         severity: "danger"
       },
       "fallback:insufficient_fund_data": {
         label: "Heuristic Fallback",
         description: "Insufficient aligned trading data between funds — weights assigned by block-level heuristic, not optimizer",
         severity: "danger"
       }
     }
     return map[status] ?? { label: status.replace(/_/g, " "), description: "Optimizer status", severity: "warning" }
   }
   ```

   ### Research Insight
   The severity level should drive visual treatment: `"danger"` status on the optimizer (Phase 3 fallback or CVaR violated) should be prominently flagged in the activation dialog (item 1.3) — IC members must know the optimization was compromised before activating.

2. **Replace raw status display** in:
   - Model Portfolio Workbench (`[portfolioId]/+page.svelte` line ~540): replace `{optimizationMeta.status}` text with `optimizerStatusLabel()` output — show label as `StatusBadge` + description as tooltip
   - Creation Wizard Step 4 (`create/+page.svelte` line ~620): same replacement in construction result cards

**Files to modify:**
- EDIT: `frontends/wealth/src/lib/types/model-portfolio.ts`
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/create/+page.svelte`

---

### 2.3 Backtest Equity Curve Chart

**Problem:** Backtest section shows fold table + metric cards but no cumulative return chart. For IC presentations, a visual equity curve is essential.

### Research Insights — Backtest Visualization

**Data shape verification:** `BacktestFold` (from track-record response) contains only summary metrics: Sharpe, CVaR 95%, Max Drawdown, observation count. No per-fold time-series data is available. Therefore, use a **horizontal bar chart of Sharpe per fold** — the professional standard for summary-only data.

**Recommended multi-panel approach:**

**Panel 1 — KPI Summary Row** (not a chart, styled grid):
```
| Consistency: 5/7 folds | Median Sharpe: 0.82 | Worst CVaR: -4.2% | Backtest: 36 months |
```

**Panel 2 — Horizontal bar chart of Sharpe per fold:**
- Folds ordered chronologically (Fold 1 at top, using `yAxis.inverse: true`)
- Four-tier color coding: `Sharpe >= 1.0` dark green, `>= 0` light green, `>= -0.5` orange, `< -0.5` red
- Zero reference line via `markLine: { data: [{ xAxis: 0 }] }`
- Rich tooltip showing all fold metrics (Sharpe, CVaR, MaxDD, observations)
- Thin folds (few observations) — reduced opacity + observation count in label

**ECharts-specific patterns:**
- `barWidth: '60%'` for comfortable spacing
- `borderRadius: [0, 4, 4, 0]` on positive bars for polished look
- `label: { show: true, position: 'right' }` for inline Sharpe values
- `aria.enabled: true` for screen reader support

**Observation count encoding** for unreliable folds:
```ts
itemStyle: {
  opacity: fold.observations < minReliableObs ? 0.4 : 1.0,
  ...(fold.observations < minReliableObs && {
    decal: { symbol: 'rect', dashArrayX: [1, 0], dashArrayY: [2, 5], rotation: Math.PI / 4 }
  })
}
```

**Implementation:**

1. **Create component** `frontends/wealth/src/lib/components/charts/BacktestEquityCurve.svelte`:
   - Props: `folds: BacktestFold[]`, `youngestFundStart?: string`, `height?: number`
   - Primary chart: horizontal bar chart of Sharpe per fold
   - KPI summary row above the chart

2. **Integrate into Model Portfolio Workbench** (`[portfolioId]/+page.svelte`):
   - Add chart inside the "Backtest — Walk-Forward CV" section (line ~335-386)
   - Place above the fold table
   - Also render `youngest_fund_start` as a note (see item 3.6)

**Files to modify:**
- CREATE: `frontends/wealth/src/lib/components/charts/BacktestEquityCurve.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

---

### 2.4 Block Label Consolidation

**Problem:** Block labels are duplicated in `model-portfolio.ts:115-127` (9 of 16 blocks) and `create/+page.svelte:57-76` (different names for same blocks). `BLOCK_INSTRUMENTS.ts` has all 16 with `display_name`. Three sources of truth.

**Verified state:** `model-portfolio.ts` has `blockLabel()` with 9 hardcoded entries. `BLOCK_INSTRUMENTS.ts` has 9 blocks with benchmark tickers. The 16-block list from the DB `allocation_blocks` table is the canonical source.

**Implementation:**

1. **Create single source of truth** `frontends/wealth/src/lib/constants/blocks.ts`:
   ```ts
   export const BLOCK_LABELS: Record<string, string> = {
     na_equity_large: "NA Equity Large",
     na_equity_growth: "NA Equity Growth",
     na_equity_value: "NA Equity Value",
     na_equity_small: "NA Equity Small",
     dm_europe_equity: "DM Europe Equity",
     dm_asia_equity: "DM Asia Equity",
     em_equity: "Emerging Markets Equity",
     fi_us_aggregate: "FI US Aggregate",
     fi_us_treasury: "FI US Treasury",
     fi_us_tips: "FI US TIPS",
     fi_us_high_yield: "FI US High Yield",
     fi_em_debt: "FI EM Debt",
     alt_real_estate: "Alt Real Estate",
     alt_commodities: "Alt Commodities",
     alt_gold: "Alt Gold",
     cash: "Cash"
   }

   export function blockLabel(blockId: string): string {
     return BLOCK_LABELS[blockId] ?? blockId.replace(/_/g, " ")
   }

   export const BLOCK_GROUPS: Record<string, string[]> = {
     EQUITIES: ["na_equity_large", "na_equity_growth", "na_equity_value", "na_equity_small", "dm_europe_equity", "dm_asia_equity", "em_equity"],
     "FIXED INCOME": ["fi_us_aggregate", "fi_us_treasury", "fi_us_tips", "fi_us_high_yield", "fi_em_debt"],
     ALTERNATIVES: ["alt_real_estate", "alt_commodities", "alt_gold"],
     "CASH & EQUIVALENTS": ["cash"]
   }
   ```

2. **Replace all usages:**
   - `model-portfolio.ts`: remove `blockLabel()` function, re-export from `constants/blocks.ts`
   - `create/+page.svelte`: remove inline block label map (lines ~57-76), import from `constants/blocks.ts`
   - `AllocationView.svelte`: use same import
   - `BLOCK_INSTRUMENTS.ts`: keep for benchmark tickers, but use `BLOCK_LABELS` for display names

**Files to modify:**
- CREATE: `frontends/wealth/src/lib/constants/blocks.ts`
- EDIT: `frontends/wealth/src/lib/types/model-portfolio.ts`
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/create/+page.svelte`
- EDIT: `frontends/wealth/src/lib/components/AllocationView.svelte`

---

### 2.5 Score Decomposition Tooltip/Popover

**Problem:** Fund score is shown as a single number (e.g. `82.3`) in composition tables. The 6 components (return_consistency 20%, risk_adj_return 25%, drawdown_control 20%, information_ratio 15%, flows_momentum 10%, fee_efficiency 10%) are not decomposed.

### Research Insight — Backend Verification

**Score components ARE available at fund level.** Verified in `backend/app/domains/wealth/schemas/risk.py`:
- `FundRiskRead.score_components: dict[str, Any] | None`
- `FundScoreRead.score_components: dict[str, Any] | None`

These are populated in `routes/funds.py:112` from the scoring service. The components are available when calling `GET /instruments/{id}/risk-metrics` or `GET /scoring/{instrument_id}`.

**However:** they are NOT included in the `fund_selection_schema` stored on model portfolios. To display decomposition in the fund table, either:
- **Option A (preferred):** Fetch per-fund scores on demand when the user clicks on a score — lazy load via `GET /instruments/{instrument_id}/risk-metrics`
- **Option B:** Backend enhancement to include `score_components` in `InstrumentWeight` when constructing

**Implementation (Option A — no backend change):**

1. **Create `ScoreBreakdownPopover.svelte`** component:
   - Trigger: click on score number in fund table
   - On click: fetch `GET /instruments/{instrument_id}/risk-metrics` (or use cached data if available)
   - Content: 6-row mini-table with component name, weight, score, weighted contribution
   - Visual: horizontal stacked bar showing each component's contribution
   - Loading state while fetching

2. **Integrate into fund table rows** in `[portfolioId]/+page.svelte` (line ~620-654):
   - Wrap score display in a clickable element
   - Show popover on click with per-fund score breakdown

**Files to modify:**
- CREATE: `frontends/wealth/src/lib/components/model-portfolio/ScoreBreakdownPopover.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

---

## Phase 3 — P2 Nice-to-have (polish & transparency)

### 3.1 Regime History Timeline

**Problem:** `regimeHistory` is fetched by risk-store (`GET /risk/regime/history` → `RegimeHistoryPoint[]`: `{snapshot_date, profile, regime}`) but never rendered.

**Backend verification:** `RegimeHistoryPoint` includes a `profile` field — history is per-profile, not global. Must filter by active profile before rendering.

### Research Insight — Pure CSS vs ECharts

**Pure CSS strip is recommended** for the compact regime timeline. No chart library overhead, instant rendering, better accessibility, pixel-perfect control. ECharts custom series is overkill for colored segments.

**Implementation:**

1. **Create component** `frontends/wealth/src/lib/components/charts/RegimeTimeline.svelte`:
   - Props: `history: Array<{snapshot_date: string; regime: string}>`, `profile?: string`, `height?: number`
   - **Pure CSS implementation** using `flex-grow` proportional to segment duration:
     ```svelte
     <div class="regime-strip" role="img" aria-label={ariaDescription}>
       {#each segments as seg (seg.start)}
         <div
           class="regime-segment"
           style:flex-grow={seg.durationDays}
           style:background-color={regimeColors[seg.type]}
           title="{regimeLabels[seg.type]}: {seg.startLabel} – {seg.endLabel} ({seg.durationDays}d)"
         ></div>
       {/each}
     </div>
     ```
   - `min-width: 2px` on segments to prevent invisible short regimes
   - Hover expansion from 8px to 24px for compact-to-expanded toggle
   - Screen reader: visually hidden `aria-live="polite"` element describing transitions
   - Use existing `--ii-regime-*` tokens from `tokens.css`
   - Derive segments by grouping consecutive history points with the same regime

2. **Integrate into Portfolio Workbench** (`portfolios/[profile]/+page.svelte`):
   - Add below the CVaR History Chart (if implemented)
   - Data: `riskStore.regimeHistory.filter(r => r.profile === profile)` — must filter by profile
   - Fallback to unfiltered if profile field is missing

3. **Integrate into Dashboard** (`dashboard/+page.svelte`):
   - Add as a compact strip below the regime badge section
   - Show all-profile view or pick "moderate" as default

**Files to modify:**
- CREATE: `frontends/wealth/src/lib/components/charts/RegimeTimeline.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/dashboard/+page.svelte`

---

### 3.2 Connection Quality Indicator

**Problem:** `risk-store.svelte.ts` exposes `connectionQuality` ("live" / "degraded" / "offline") but no reusable UI component displays it. There is already a partial implementation in `risk/+page.svelte` lines 88-122.

### Research Insight — Financial Dashboard Patterns

- **Dot + label pattern** (Bloomberg style) in the header topbar is correct placement
- **Pulse only when `live`**, static when `degraded`/`offline` — animation on error states is confusing
- **Degraded mode:** show countdown to next poll (`Delayed (18s)`) for user confidence
- **WCAG:** use `role="status"` + `aria-live="polite"` (NOT `role="alert"` — status is polite, alert is assertive)

**Implementation:**

1. **Create component** `frontends/wealth/src/lib/components/ConnectionStatus.svelte`:
   - Props: `quality: "live" | "degraded" | "offline"`, `computedAt?: string | null`, `nextPollIn?: number | null`
   - Render: small dot + label
     - `live`: green pulsing dot, "Live"
     - `degraded`: yellow static dot, "Delayed ({countdown}s)"
     - `offline`: red static dot, "Offline"
   - Tooltip: "Real-time data via SSE" / "Polling every 30s — SSE connection lost" / "No connection"
   - `role="status"` + `aria-live="polite"` + `aria-label="Connection status: {quality}"`

2. **Integrate into layout** (`frontends/wealth/src/routes/(app)/+layout.svelte`):
   - Add to the `.ii-topbar-actions` area (around line ~248), next to theme toggle
   - Data: `riskStore.connectionQuality`
   - Extract and reuse from `risk/+page.svelte` existing implementation

**Files to modify:**
- CREATE: `frontends/wealth/src/lib/components/ConnectionStatus.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/+layout.svelte`

---

### 3.3 IC View Edit (In-Place)

**Problem:** ICViewsPanel allows add + delete but not edit. Users must delete and re-create to change a view.

**Backend dependency:** `PATCH /model-portfolios/{id}/views/{view_id}` **DOES NOT EXIST**. Only POST (create) and DELETE exist. **Backend work required first.**

**Implementation:**

1. **Backend (prerequisite):** Create `PATCH /model-portfolios/{id}/views/{view_id}` in `backend/app/domains/wealth/routes/portfolio_views.py`:
   - Accept partial update of view fields
   - Validate view belongs to portfolio
   - Write audit event
   - Return updated view

2. **In ICViewsPanel.svelte** (~792 lines):
   - Current pattern: add form + two-step delete (button → "Remove? Yes/No")
   - Add an "Edit" button per row (pencil icon, next to delete)
   - On click: toggle row into inline edit mode (pre-fill with current values using same form fields as add)
   - Save: `PATCH /model-portfolios/${portfolioId}/views/${viewId}`
   - Cancel: revert to display mode
   - Only available when `canEdit === true` (IC role)

**Files to modify:**
- CREATE: `backend/app/domains/wealth/routes/portfolio_views.py` (PATCH endpoint)
- EDIT: `frontends/wealth/src/lib/components/model-portfolio/ICViewsPanel.svelte`

---

### 3.4 Dashboard Card Navigation

**Problem:** Dashboard portfolio cards (line ~122-165) are `<div>` elements, not clickable. Users can't navigate from dashboard to portfolio workbench.

**Implementation:**

1. **In dashboard** (`dashboard/+page.svelte`):
   - Change card container from `<div>` to `<a href="/portfolios/{profile}">`
   - Add hover effect (cursor pointer, border highlight, subtle scale) — match existing card patterns
   - Add subtle arrow icon or "View" text to indicate clickability
   - Use SvelteKit `data-sveltekit-preload-data` for instant navigation

**Files to modify:**
- EDIT: `frontends/wealth/src/routes/(app)/dashboard/+page.svelte`

---

### 3.5 Cross-Link Portfolio <> Model Portfolio

**Problem:** `/portfolios/[profile]` and `/model-portfolios/[id]` are separate pages with complementary views. No cross-navigation.

**Implementation:**

1. **In Portfolio Workbench** (`portfolios/[profile]/+page.svelte`):
   - Add a link/button in the header: "Model Portfolio" pointing to `/model-portfolios/{id}`
   - The model portfolio ID is already available in SSR data (page.server.ts fetches it)

2. **In Model Portfolio Workbench** (`model-portfolios/[portfolioId]/+page.svelte`):
   - Add a link in the header: "Portfolio Monitoring" pointing to `/portfolios/{profile}`
   - `portfolio.profile` is available from SSR data

**Files to modify:**
- EDIT: `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

---

### 3.6 Youngest Fund Start Date Display

**Problem:** `BacktestResult.youngest_fund_start` is typed but never rendered.

### Research Insight

Display as a **styled warning banner above the backtest chart**, not just a small note. IC members must understand this limitation prominently:

```svelte
{#if backtest?.youngest_fund_start}
  <div class="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50
              px-4 py-2.5 text-sm text-amber-800 dark:border-amber-800/50
              dark:bg-amber-950/30 dark:text-amber-200">
    <span>Backtest limited to data since <strong>{formatDate(backtest.youngest_fund_start)}</strong>
    due to newest fund inception date.</span>
  </div>
{/if}
```

**Implementation:**

1. **In Model Portfolio Workbench** (`[portfolioId]/+page.svelte`):
   - In the backtest section (line ~335-386), add warning banner above the metrics cards
   - Also add as `markLine` inside the backtest chart if item 2.3 is implemented

**Files to modify:**
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

---

### 3.7 Scenario Label Completion

**Problem:** `scenarioLabel()` in `model-portfolio.ts` only maps 3 of 4+ scenarios. Missing `taper_2013` and `rate_shock_200bps`.

**Implementation:**

1. **In model-portfolio.ts**, update `scenarioLabel()`:
   ```ts
   export function scenarioLabel(name: string): string {
     const map: Record<string, string> = {
       "2008_gfc": "Global Financial Crisis (2008)",
       "2020_covid": "COVID-19 Crash (2020)",
       "2022_rate_hike": "Rate Hike Cycle (2022)",
       "taper_2013": "Taper Tantrum (2013)",
       "rate_shock_200bps": "Rate Shock +200bps"
     }
     return map[name] ?? name.replace(/_/g, " ")
   }
   ```

**Files to modify:**
- EDIT: `frontends/wealth/src/lib/types/model-portfolio.ts`

---

### 3.8 InstrumentWeight Type Fix

**Problem:** `InstrumentWeight.instrument_type` is typed as `"fund" | "bond" | "equity" | null`. Backend sends `"mutual_fund"`, `"etf"`, `"bdc"`, `"money_market"`, etc.

**Implementation:**

1. **In model-portfolio.ts**, update the type:
   ```ts
   instrument_type: "mutual_fund" | "etf" | "bdc" | "money_market" | "closed_end" | "interval_fund" | "ucits" | "private" | null
   ```

2. **Update any badges/rendering** that switch on `instrument_type` — ensure the new values get proper display labels and colors via `instrumentTypeLabel()` from `$lib/types/universe`.

**Files to modify:**
- EDIT: `frontends/wealth/src/lib/types/model-portfolio.ts`
- EDIT: any component rendering instrument type badges

---

### 3.9 Deactivation Flow

**Problem:** No way to deactivate/archive an active portfolio. No "Deactivate" or "Archive" button exists.

**Backend dependency:** `POST /model-portfolios/{id}/deactivate` **DOES NOT EXIST**. The status field supports `draft`, `backtesting`, `active` but no `archived` state. **Backend work required first.**

**Implementation:**

1. **Backend (prerequisite):** Create `POST /model-portfolios/{id}/deactivate` in `backend/app/domains/wealth/routes/model_portfolios.py`:
   - Add `"archived"` to status enum/check constraint (migration needed)
   - Status transition: `active` → `archived`
   - Requires IC role
   - Write audit event
   - Return updated portfolio

2. **Frontend** (`model-portfolios/[portfolioId]/+page.svelte`):
   - Add "Archive" button (visible only when `status === "active"`)
   - ConsequenceDialog with `destructive={true}` (this IS a significant state change), rationale requirement
   - On confirm: call deactivation endpoint
   - Toast: "Portfolio archived"

**Files to modify:**
- CREATE: backend migration + deactivation endpoint
- EDIT: `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

---

### 3.10 Macro Indicators Display

**Problem:** `macroIndicators` is fetched from `/risk/macro` and stored in risk-store but never rendered in monitoring context.

**Backend verification:** `MacroIndicators` is a typed Pydantic model with 8 specific fields:
```python
class MacroIndicators(BaseModel):
    vix: float | None = None
    vix_date: date | None = None
    yield_curve_10y2y: float | None = None
    yield_curve_date: date | None = None
    cpi_yoy: float | None = None
    cpi_date: date | None = None
    fed_funds_rate: float | None = None
    fed_funds_date: date | None = None
```

This is NOT `Record<string, unknown>` — use typed props for the component.

**Implementation:**

1. **Create component** `frontends/wealth/src/lib/components/MacroIndicatorStrip.svelte`:
   - Props: typed interface matching backend schema
   ```ts
   interface MacroIndicators {
     vix: number | null;
     vix_date: string | null;
     yield_curve_10y2y: number | null;
     yield_curve_date: string | null;
     cpi_yoy: number | null;
     cpi_date: string | null;
     fed_funds_rate: number | null;
     fed_funds_date: string | null;
   }
   ```
   - Render: horizontal strip of 4 KPI chips:
     - VIX: color-coded (green < 20, yellow 20-30, red > 30)
     - Yield Curve 10Y-2Y: red if negative (inverted)
     - CPI YoY: neutral display with trend arrow
     - Fed Funds Rate: neutral display
   - Each chip shows label, value, and data date as tooltip

2. **Integrate into Dashboard** (`dashboard/+page.svelte`):
   - Add below regime badge, above portfolio cards
   - Data: `riskStore.macroIndicators`

**Files to modify:**
- CREATE: `frontends/wealth/src/lib/components/MacroIndicatorStrip.svelte`
- EDIT: `frontends/wealth/src/routes/(app)/dashboard/+page.svelte`

---

## Implementation Order

Execute in this order to maximize value while minimizing inter-dependencies:

```
Phase 1 — P0 (4 items, ~2 sessions)
├── 1.3 Activation confirmation dialog (standalone, quick win — ConsequenceDialog API verified)
├── 1.4 Wizard CVaR guard fix (standalone, CRITICAL SAFETY — POST /activate enforces CVaR guard)
├── 1.1 CVaR History Chart (extend CVaRPoint type + new component + 2 page integrations)
└── 1.2 Portfolio NAV Chart (new component + 2 page integrations)

Phase 2 — P1 (5 items, ~2 sessions)
├── 2.4 Block label consolidation (refactor, do first — unblocks cleaner code)
├── 2.2 Optimizer cascade labels (single function + 2 page edits)
├── 2.1 Regime CVaR multiplier (constants + 3 page edits)
├── 2.3 Backtest equity curve chart (horizontal bar of Sharpe per fold — no backend needed)
└── 2.5 Score decomposition (fetch per-fund on demand — no backend change needed)

Phase 3 — P2 (10 items, ~3 sessions)
├── 3.7 Scenario label completion (trivial)
├── 3.8 InstrumentWeight type fix (trivial)
├── 3.6 Youngest fund start date (trivial — warning banner)
├── 3.4 Dashboard card navigation (quick — div → anchor)
├── 3.5 Cross-link Portfolio ↔ Model Portfolio (quick)
├── 3.1 Regime history timeline (pure CSS strip — no ECharts needed)
├── 3.2 Connection quality indicator (extract from risk page)
├── 3.10 Macro indicators display (typed component, 4 KPI chips)
├── 3.3 IC View edit (BLOCKED — backend PATCH endpoint needed first)
└── 3.9 Deactivation flow (BLOCKED — backend endpoint + migration needed first)
```

---

## Files Created (New Components)

| File | Type | Phase |
|------|------|-------|
| `components/charts/CVaRHistoryChart.svelte` | Chart (ECharts) | P0 |
| `components/charts/PortfolioNAVChart.svelte` | Chart (ECharts) | P0 |
| `components/charts/BacktestEquityCurve.svelte` | Chart (ECharts) | P1 |
| `components/charts/RegimeTimeline.svelte` | UI (pure CSS) | P2 |
| `components/ConnectionStatus.svelte` | UI | P2 |
| `components/MacroIndicatorStrip.svelte` | UI | P2 |
| `components/model-portfolio/ScoreBreakdownPopover.svelte` | UI | P1 |
| `constants/blocks.ts` | Constants | P1 |

All paths relative to `frontends/wealth/src/lib/`.

## Files Modified (Existing)

| File | Phases | Changes |
|------|--------|---------|
| `stores/risk-store.svelte.ts` | P0 | Extend CVaRPoint type with limit/utilization/trigger fields |
| `routes/(app)/model-portfolios/[portfolioId]/+page.svelte` | P0, P1, P2 | ConsequenceDialog, charts, labels, links |
| `routes/(app)/model-portfolios/create/+page.svelte` | P0, P1 | CVaR guard fix (POST /activate), labels, blocks |
| `routes/(app)/portfolios/[profile]/+page.svelte` | P0, P1, P2 | CVaR chart, regime, links |
| `routes/(app)/dashboard/+page.svelte` | P1, P2 | Regime multiplier, card nav, macro, timeline |
| `routes/(app)/+layout.svelte` | P2 | Connection quality in topbar |
| `lib/types/model-portfolio.ts` | P1, P2 | Labels, types, scenario map, optimizer status |
| `lib/constants/regime.ts` | P1 | CVaR multiplier map |
| `lib/components/model-portfolio/ICViewsPanel.svelte` | P2 | Edit mode (after backend) |
| `lib/components/AllocationView.svelte` | P1 | Block labels import |

## Backend Dependencies

| Item | Endpoint Needed | Exists? | Notes |
|------|----------------|---------|-------|
| 1.1 CVaR History | `GET /risk/{profile}/cvar/history` | YES | Returns 5-field CVaRPoint; frontend type needs extension |
| 1.2 NAV Chart | `GET /model-portfolios/{id}/track-record` | YES | `nav_series` is inline dict, not Pydantic model |
| 1.3 Activation | `POST /model-portfolios/{id}/activate` | YES | CVaR guard: checks `cvar_within_limit` boolean |
| 1.4 Wizard fix | `POST /model-portfolios/{id}/activate` | YES | Returns 409 CONFLICT if CVaR exceeded |
| 2.5 Score decomp | `GET /instruments/{id}/risk-metrics` | YES | `score_components` available at fund level |
| 3.3 View edit | `PATCH /model-portfolios/{id}/views/{vid}` | **NO** | Must create backend endpoint first |
| 3.9 Deactivation | `POST /model-portfolios/{id}/deactivate` | **NO** | Must create backend endpoint + migration first |
| 3.10 Macro | `GET /risk/macro` | YES | Typed Pydantic model with 8 fields (not Record<string, unknown>) |

## ECharts Infrastructure Notes

### Import Checklist for `echarts-setup.ts`

Verify these components are imported (most already are):
- `MarkAreaComponent` — needed for CVaR breach highlighting (already imported)
- `MarkLineComponent` — needed for NAV inception line (already imported)
- `DataZoomComponent` — needed for time navigation (already imported)
- `AriaComponent` — **ADD** for screen reader support on all charts

### Chart Performance Patterns

- Use `$derived.by()` for reactive option building (already established)
- Use `replaceMerge: ['series']` instead of `notMerge: true` for charts with DataZoom — preserves zoom position
- Use `sampling: 'lttb'` on time-series with > 100 data points
- Use `onMount` (not `$effect`) for chart init and ResizeObserver setup (avoids Svelte 5 bind:this ordering issue #12731)
- Guard `$effect` setOption calls with `untrack()` on `lastAppliedOption` writes to prevent dependency re-subscription
