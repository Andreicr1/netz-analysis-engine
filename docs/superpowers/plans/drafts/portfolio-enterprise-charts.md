# Portfolio Enterprise Charts — Design Document

**Vertical**: Wealth OS — Portfolio workbench
**Scope**: ECharts visualization layer ONLY (chart types, option sketches, tokens, tooltip patterns, performance, update architecture)
**Out of scope**: DB schemas, route contracts, quant math, component trees, worker design
**Date**: 2026-04-08
**Parent**: `docs/superpowers/plans/2026-04-07-discovery-fcl-analysis-page.md` (establishes `chartTokens()`, `navTooltipFormatter`, `--chart-*` CSS vars, Urbanist font, `svelte-echarts` mandate)

---

## Context snapshot

Current portfolio chart layer lives in `frontends/wealth/src/lib/components/portfolio/` and `frontends/wealth/src/lib/components/charts/`. Audited state:

- `MainPortfolioChart.svelte` — single NAV line, reads `--ii-brand-primary` directly (not `chartTokens()`), no benchmark overlay, no regime bands, no tool switcher, inline tooltip HTML (not `navTooltipFormatter`), no sampling threshold tuning.
- `charts/chart-tokens.ts` + `charts/tooltips.ts` + `charts/discovery/*` — Discovery sprint primitives (`NavHeroChart`, `RollingRiskChart`, `DrawdownUnderwaterChart`, `ReturnDistributionChart`, `MonthlyReturnsHeatmap`, `RiskMetricsBulletChart`) are the canonical reference and MUST be reused by the Analytics phase.
- `charts-v2/` parallel tree exists — legacy / DO NOT extend.
- Existing `@netz/ui` primitives (`ChartContainer`, `TimeSeriesChart`, `HeatmapChart`, `ScatterChart`, `RegimeChart`) are low-level wrappers around `svelte-echarts`. Fine to reuse but extend via option generators, not by forking.

Andrei's four pain points: (1) Builder sliders do nothing visually; (2) Analytics has no Discovery-parallel standalone page for model portfolios / constituents; (3) Live Workbench does not exist — needs Bloomberg-terminal density with a central multi-tool chart driven by real-time prices; (4) Stress-test output is textual only.

This doc specifies the chart layer contract so the component-tree / route-contract specialists can wire backend shapes into the sketched options.

---

## Part A — Chart type selection per phase

### A.1 Builder phase

The Builder's job is to give an **ex-ante preview** the instant a slider moves. Every chart listed here must accept a `mode: 'current' | 'preview' | 'both'` prop and render a ghost layer for the calibrated state when `both`.

**1. Efficient Frontier Scatter + Line**

- Series types: one `line` series (the frontier curve — points computed server-side, sorted ascending by vol), two `scatter` series (`current` marker, `preview` marker). Optional third `scatter` for peer median.
- Rationale: scatter is the only ECharts series where a single highlighted point with `symbolSize: 14` + `emphasis.scale: 1.2` reads as "you are here" against a dense curve. The frontier line is not a `scatter` because we want `smooth: true` interpolation between ~50 sample points.
- Axes: x = annualized volatility (`formatPercent`), y = expected return (`formatPercent`). Log scale never appropriate here.
- Markers: two `markPoint` entries (current/preview) with dashed `markLine` connecting them — visually answers "which direction did my slider push me".
- Sharpe isoquants: optional `custom` series drawing hyperbolas `y = k * x` for k in {0.5, 1.0, 1.5}. Deferred unless Andrei asks.

**2. Ex-ante Metrics Radar**

- Series type: `radar`. Three data rows: `current`, `preview`, `peerMedian`.
- Axes (indicators): `Sharpe`, `Vol (inv)`, `CVaR95 (inv)`, `MaxDD (inv)`, `Beta (|abs|)`, `Info Ratio`. The `(inv)` axes are server-inverted so "outer = better" for all rings — the frontend must not compute inversions.
- Rationale: radar is the canonical institutional "fingerprint" visualization for ≤8 dimensions and lets preview vs current be seen as overlapping polygons. Never use for >8 axes (switch to horizontal bar).
- Fill: `current` solid 18% opacity, `preview` dashed outline only (no fill, so overlap is readable).

**3. Constraint Binding Heatmap**

- Series type: `heatmap` on a `category × category` grid. Rows = constraint groups (Sector cap, Geo cap, Single-name cap, Liquidity floor, Duration band, Turnover cap). Columns = `current utilization %`, `preview utilization %`, `limit`, `slack`.
- Visual map: diverging scale `positive → warning → negative` from `--chart-positive` through `--chart-regime-stress` to `--chart-negative`. Value = utilization / limit ratio (0–1.2, clipped).
- Rationale: heatmap scans faster than a bar chart when the user's question is "which constraint is *about to bind* as I move the slider". Color is the affordance, not the number.

**4. Weight Treemap with animated update**

- Series type: `treemap`. Hierarchy: AssetClass → Sector → Holding. `value` = weight, `colorSaturation` = performance contribution.
- Update mode: `setOption({ series: [{ data: newTree }] }, { notMerge: false, lazyUpdate: true })` with `animationDurationUpdate: 250`, `animationEasingUpdate: 'cubicOut'`. Relies on ECharts `universalTransition: true` to morph tile sizes rather than redraw.
- Never `pie`/`donut` — too many slices (20–80 holdings).

**5. Stress Scenario Comparison Bar**

- Series type: grouped `bar`. Four categories (GFC, COVID, Taper, Rate Shock). Two series per category: `current loss %`, `preview loss %`. Optional third series `policy floor %` as `markLine`.
- Rationale: grouped bar beats radar here because the question is strictly "ranked magnitude comparison across 4 discrete scenarios" — ordinal, not fingerprint.
- `label.show: true` with `formatPercent` — values must be readable without tooltip (IC meeting context).

### A.2 Analytics phase

The Analytics phase is Discovery-parallel: a standalone analysis page for a model portfolio OR a constituent fund. Max reuse of Discovery primitives.

**Reused from `charts/discovery/` (zero new code, pass model-portfolio dataset instead of fund dataset):**
- `NavHeroChart` — model portfolio NAV curve with benchmark overlay and regime bands
- `RollingRiskChart` — rolling 3m/6m/12m vol & Sharpe
- `DrawdownUnderwaterChart` — drawdown curve
- `ReturnDistributionChart` — histogram + KDE, with VaR/CVaR markers (backend-supplied)
- `MonthlyReturnsHeatmap` — calendar heatmap of monthly returns
- `RiskMetricsBulletChart` — bullet chart of current metric vs peer median vs policy limit

**New Analytics charts (portfolio-specific, not in Discovery):**

**6. Risk Attribution Stacked Bar**

- Series type: horizontal `bar` with `stack: 'risk'`. Y-axis = holdings (sorted by absolute contribution). X-axis = marginal contribution to portfolio variance (`formatPercent`).
- Two series: `systematic` (factor-explained) + `idiosyncratic` (residual). Color: `systematic` = `--chart-primary`, `idiosyncratic` = `--chart-benchmark`.
- Rationale: horizontal bar beats treemap when the question is "rank contribution" because ranking is the primary task. Stack makes the factor/idio split scannable.
- Top-N: render only top 20 contributors; rest collapsed into "Other (n)" row.

**7. Constituent Correlation Heatmap**

- Series type: `heatmap` on a symmetric matrix (constituent × constituent). Values = pairwise correlation (backend-computed, rolling 12m).
- Hierarchical clustering order — backend sends pre-ordered indices (`fund_id` list); frontend never clusters client-side.
- Visual map: diverging `-1 → 0 → +1`, center white. Three-stop color: `--chart-negative` / `--chart-tooltip-bg` / `--chart-primary`.
- Cell labels suppressed by default; tooltip shows pair + correlation via `formatNumber(value, 2)`.
- Max 40×40 before switching to the denoised absorption-ratio summary view.

**8. Factor Exposure Bar (PCA)**

- Series type: horizontal `bar`, one series. X-axis = loading (signed, `formatNumber`). Y-axis = factor name (from `factor_model_service` PCA).
- Positive bars right, negative left, zero line bold. `itemStyle.color` callback: positive → `--chart-positive`, negative → `--chart-negative`.
- Rationale: radar was rejected because PCA factors often number >8 and carry sign (radar cannot show negative loadings cleanly).

**9. Brinson Attribution Waterfall**

- Series type: ECharts stacked `bar` with a transparent placeholder series (classic ECharts waterfall pattern — no native waterfall type).
- Categories: `Benchmark return → Allocation effect → Selection effect → Interaction → Portfolio return`. Each column is a delta; ends are totals.
- Color: positive contributions `--chart-positive`, negative `--chart-negative`, totals `--chart-primary`.
- `label.show` with `formatPercent` — deltas should be readable without tooltip.
- Reference: ECharts `waterfall` demo pattern. Do not attempt a `custom` series for this — the placeholder+stack pattern is the institutional standard.

### A.3 Live Workbench phase

Terminal-grade: dense spacing, hairline borders, tight tooltips, live refresh. The centerpiece is one multi-tool chart; everything else is a satellite.

**10. Centralized Multi-Tool Chart (the centerpiece)**

Requirements: toggle between NAV curve, drawdown, rolling Sharpe, rolling Vol, rolling correlation vs benchmark, rolling tracking error, regime overlay, live intraday line. Date brush. Benchmark overlay. Event markers. Clicking any row in `WeightVectorTable` switches focus to that holding.

**Architecture recommendation**: **single `Chart` instance, option rebuild via `$derived`, update via `setOption(next, { notMerge: false, lazyUpdate: true, replaceMerge: ['series', 'markLine', 'markArea'] })`**.

Justification:
- `notMerge: true` destroys animation state (user sees a flash on every tool switch) — rejected.
- Multiple `v-if`'d Chart components force a full ECharts instance re-instantiation on every switch (~40ms cold init, memory churn) — rejected.
- State machine that rebuilds the option object and uses `replaceMerge: ['series']` keeps the ECharts instance alive, preserves axis/zoom state, and morphs only the series. This is the fastest path at 5s refresh cadence.
- Put the tool selector in a module-scoped `workbenchTool = $state<'nav' | 'drawdown' | 'rollingSharpe' | ...>('nav')` and derive `option` from `(workbenchTool, datasets, holdingFocus)`. The derived option passes through a single `setOption` call via `svelte-echarts` reactivity.
- `dataZoom` `[{ type: 'inside' }, { type: 'slider' }]` must have `filterMode: 'weakFilter'` so brush survives tool switches.

Event markers (regime change, rebalance execution, breach) are `markLine` entries on `xAxis`, rebuilt every tool switch from a single `events[]` array (shared across tools).

Benchmark overlays: each overlay is its own line series with `seriesId: 'bench:' + ticker`. Toggle on/off by excluding from series list in the `$derived` builder.

Click-to-focus: listen for `chart.on('click', ...)` on the Holdings table, dispatch to a workbench store; the chart's `$derived` rebuild reads `holdingFocus` and swaps `datasets.primary` accordingly. No direct `setOption` imperative calls from the table — everything flows through the derived option.

**11. Strategic vs Tactical vs Effective Allocation Divergence**

- Series type: grouped horizontal `bar`. Three series (strategic, tactical, effective) over N buckets (asset class or sector).
- Rationale: grouped bar beats radial because the comparison is strict magnitude delta, and negative drift (effective < strategic) needs a zero line.
- Divergence indicator: a fourth `scatter` series showing tracking error per bucket as a colored dot sized by magnitude.

**12. Live Price Sparklines (embedded in `WeightVectorTable`)**

- Series type: `line`, single series per row, NO axes, NO grid, NO tooltip (the table row owns hover). `animation: false`, `silent: true`.
- Performance: `sampling: 'lttb'`, `progressive: 500`, `progressiveThreshold: 2000`, `large: true`, `largeThreshold: 500`. Height 24px, width 80px.
- Data contract: each sparkline consumes a `Float64Array` (typed, not JS array) of last N intraday prices (N ≤ 120 — 2 hours of minute bars). Typed arrays are required — see Part G.
- **Do NOT create one `svelte-echarts` component per row.** 30+ ECharts instances will tank the workbench. Instead, use a single `<canvas>` + custom `echarts.init` instance per row pooled via `ChartInstancePool` (see Part G), OR a single SVG `path` render for sparkline-only cases. Recommendation: **SVG path sparkline, not ECharts**, because the visual is stateless, and saving 30 ECharts init costs is decisive. This is the only place in the workbench where ECharts is **NOT** mandatory — and it's justified because a sparkline with no axes/tooltip is not a "chart", it's a glyph.

**13. Alert Timeline**

- Series type: `scatter` with `symbolSize` callback (severity-proportional). X-axis = time, Y-axis = `category` with three rows: `info`, `warning`, `critical`.
- Color: three-stop tied to tokens. Click handler dispatches to alert drawer.
- Optional `markArea` bands for regime epochs behind the scatter.

**14. Rebalance Impact Before/After**

- Option A: side-by-side `treemap` (before, after). Simple, readable.
- Option B: `sankey` with left nodes = current weights, right nodes = target weights, links = deltas.
- **Recommendation: side-by-side treemap**, because rebalances are rarely "flows between holdings" — they are "old weight → new weight" independent moves. Sankey implies flow semantics that aren't real here. Reserve Sankey for capital flow visualizations (deposits/redemptions/carry).

---

## Part B — Real-time update architecture

The workbench needs to digest live price ticks without reflow storms. Four mechanisms are relevant and each has a specific use:

### B.1 Update mechanism selection

| Update type | Mechanism | When |
|---|---|---|
| Append one point to streaming series | `appendData({ seriesIndex, data })` | Intraday tick on centerpiece chart (tool = `intraday`). Does not redraw historical data. |
| Swap entire series data | `setOption({ series: [{ id, data }] }, { replaceMerge: ['series'] })` | Tool switch on centerpiece, daily data refresh. |
| Full rebuild | `setOption(opt, { notMerge: true })` | Never. Triggers full layout recompute. |
| Animate value changes | default `setOption` with `lazyUpdate: true` + `animationDurationUpdate: 250` | Builder calibration preview (treemap, radar, scatter preview point). |

**The centerpiece chart uses `setOption` with `replaceMerge: ['series']` for tool switches and `appendData` only when in live-intraday mode.** Mixing them is safe because `appendData` just pushes to whatever series currently holds the intraday id.

### B.2 Cadence

| Context | Refresh cadence | Justification |
|---|---|---|
| Workbench non-active tab | paused | `IntersectionObserver` stops updates when chart is off-screen |
| Workbench default | 5s | Human-readable tick rate, matches Yahoo rate-limit headroom |
| Hot portfolio / alert active | 1s | Only when a breach is active or user opted in |
| Sparklines | 5s (batched) | Never independent per-row; one global tick drives all |
| Builder (not calibrating) | off | Charts are static except when slider moves |
| Builder (calibrating) | 200ms debounced | See Part C |

### B.3 Reflow storm prevention

Thirty sparklines + centerpiece + alert timeline + allocation bar updating on the same 5s tick will cause layout thrash unless gathered.

**Pattern**: use `createTickBuffer<T>` from the Stability Guardrails runtime primitives (`packages/investintell-ui/src/lib/runtime/`). SSE emissions push into the buffer; the buffer flushes once per `requestAnimationFrame`. Every chart subscribes to the flush event, not the raw tick, so ECharts sees exactly one update per frame regardless of how many symbols ticked.

**Never** spread new arrays into `$state` on every tick — Svelte 5's fine-grained reactivity will still cascade, and the cost is not the Svelte notify but the 30 ECharts `setOption` calls. The buffer flush collapses N ticks into one derived snapshot.

### B.4 SSE → state → chart data path

```
backend SSE endpoint (5s cadence)
  → fetch() + ReadableStream (NEVER EventSource — Clerk JWT headers)
  → workbench store (Svelte 5 class with $state fields)
  → createTickBuffer (1 rAF flush)
  → $derived option objects in each chart component
  → svelte-echarts setOption
```

Charts read from **context** (workbench store), not props. Props force parent rerenders; context lets the chart component subscribe only to its relevant `$derived` slice.

### B.5 Sampling and progressive defaults for workbench

```
{ sampling: 'lttb',
  progressive: 500,
  progressiveThreshold: 3000,
  large: true,
  largeThreshold: 2000,
  animation: false,           // during live streaming
  animationDurationUpdate: 0  // during live streaming
}
```

Animation is toggled on (`250ms`) in Builder and Analytics phases. Disabled in Workbench because live data + animation = lag.

---

## Part C — Calibration reactive preview

The core Builder UX fix. When a slider moves, three charts must update in one coordinated pass.

### C.1 Live vs deferred

| Chart | Live on slider move | Deferred to "Run Construct" |
|---|---|---|
| Efficient Frontier preview point | yes | — |
| Ex-ante Metrics Radar (preview ring) | yes | — |
| Weight Treemap (preview tree) | yes | — |
| Constraint Binding Heatmap | yes | — |
| Stress Scenario Bars | — | yes (needs full quant engine recompute) |
| Per-holding narrative / risk attribution | — | yes (requires factor model recompute) |

Live charts read from a single `previewResponse` object delivered by a dedicated backend preview endpoint. The endpoint is expected to return ≤50KB (server specialist owns shape) and p95 < 150ms.

### C.2 Debounce strategy

- Slider `oninput` → write to `calibrationDraft = $state<Calibration>`
- `$effect` watches `calibrationDraft`, debounces 200ms (`setTimeout` + clear), fires **one** request against the preview endpoint
- In-flight request: cancel previous via `AbortController` — no race conditions
- Response → `previewResponse = result` in one assignment — Svelte 5 batches the downstream `$derived` option rebuilds
- All three charts re-derive in the same microtask — one paint, not three

Debounce of 200ms is the institutional sweet spot: long enough to coalesce a slider drag, short enough to feel reactive.

### C.3 Loading states

- **First render**: skeleton placeholders from `@netz/ui`
- **Subsequent calibration**: ghost the previous chart at 50% opacity via a `loading: { opacity: 0.5, ... }` overlay using ECharts `showLoading()` with a custom loading type (`'default'` with `maskColor: 'rgba(0,0,0,0.02)'`). User still sees the last state while the new one loads — no flicker.
- **Error**: render a `PanelErrorState` from `@netz/ui` inside the chart frame. Do not throw.

---

## Part D — Chart token extension for terminal aesthetic

The workbench is denser than Discovery. Proposed CSS variable additions in `app.css`:

```css
:root {
  /* existing */
  --chart-primary: ...;
  --chart-benchmark: ...;
  --chart-grid: ...;
  --chart-axis-label: ...;
  --chart-tooltip-bg: ...;
  --chart-tooltip-border: ...;
  --chart-font: "Urbanist", system-ui, sans-serif;
  --chart-positive: ...;
  --chart-negative: ...;
  --chart-regime-stress: ...;
  --chart-regime-normal: ...;

  /* new: workbench variant */
  --chart-workbench-font-size: 10px;
  --chart-workbench-axis-label-size: 9px;
  --chart-workbench-axis-width: 0;           /* hairline axes */
  --chart-workbench-grid-opacity: 0.35;
  --chart-workbench-tooltip-max-width: 180px;
  --chart-workbench-tooltip-padding: 4px 6px;
  --chart-workbench-border-radius: 2px;       /* flatter than default 4px */
  --chart-workbench-symbol-size: 4;           /* smaller markers */
  --chart-workbench-line-width: 1.25;         /* thinner lines */
}
```

### D.1 `chartTokens()` variant parameter

Extend the existing reader (`charts/chart-tokens.ts`) to accept an optional variant:

```ts
export function chartTokens(variant: 'default' | 'workbench' = 'default') {
  const base = {
    primary: cssVar('--chart-primary'),
    benchmark: cssVar('--chart-benchmark'),
    // ... existing fields
  };
  if (variant === 'default') return base;
  return {
    ...base,
    fontSize: cssVar('--chart-workbench-font-size', '10px'),
    axisLabelSize: cssVar('--chart-workbench-axis-label-size', '9px'),
    tooltipMaxWidth: cssVar('--chart-workbench-tooltip-max-width', '180px'),
    tooltipPadding: cssVar('--chart-workbench-tooltip-padding', '4px 6px'),
    symbolSize: Number(cssVar('--chart-workbench-symbol-size', '4')),
    lineWidth: Number(cssVar('--chart-workbench-line-width', '1.25')),
    gridOpacity: Number(cssVar('--chart-workbench-grid-opacity', '0.35')),
  };
}

export type ChartTokens = ReturnType<typeof chartTokens>;
```

The return type is a union; callers that pass `'workbench'` get the extended shape. Existing Discovery callers pass nothing and remain unchanged — zero breakage.

Option generators in `charts/option-builders/` (new folder) should accept `tokens: ChartTokens` and branch on `'fontSize' in tokens ? dense : default` — no chart component should read CSS vars directly.

### D.2 Option impact of `'workbench'` variant

For every workbench chart:

```ts
const dense = 'fontSize' in tokens;
return {
  textStyle: { fontFamily: tokens.fontFamily, fontSize: dense ? 10 : 12 },
  grid: dense
    ? { top: 16, right: 8, bottom: 20, left: 36, containLabel: false }
    : { top: 28, right: 24, bottom: 48, left: 56, containLabel: false },
  xAxis: { axisLabel: { fontSize: dense ? 9 : 11 }, splitLine: { show: !dense } },
  yAxis: { axisLabel: { fontSize: dense ? 9 : 11 } },
  tooltip: { extraCssText: dense ? `max-width:${tokens.tooltipMaxWidth};padding:${tokens.tooltipPadding}` : '' },
  // ...
};
```

---

## Part E — Tooltip discipline for workbench

Workbench tooltips must be tiny, data-dense, and render fast. HTML table rendering in ECharts tooltips is the #1 cause of sluggish tooltip latency — avoid it.

### E.1 Rules

1. Max width 180px — overflow is cut with `text-overflow: ellipsis`
2. Max 4 lines of content
3. Every numeric value passes through `formatCurrency` / `formatPercent` / `formatNumber` from `@netz/ui` — inline `.toFixed`/`Intl.*` is ESLint-blocked
4. No `<table>` — use flex rows with `justify-content: space-between`
5. `transitionDuration: 0` — tooltips must snap, not fade
6. `confine: true` — tooltips clamp inside chart box

### E.2 Helper: `workbenchTooltipFormatter`

Extends the Discovery `navTooltipFormatter` with:
- Tighter padding (4px 6px instead of 8px 10px)
- No date header row when `xAxis.type !== 'time'`
- `font-size: 10px`, `line-height: 1.25`
- Max 4 series; overflow collapsed into `"+N more"` line
- Accepts a `ChartTokens` with the workbench variant

Signature sketch:

```ts
export function workbenchTooltipFormatter(
  tokens: ChartTokens,
  opts: { maxRows?: number; valueFormatter?: (v: number) => string } = {},
) {
  const maxRows = opts.maxRows ?? 4;
  const fmt = opts.valueFormatter ?? ((v) => formatPercent(v, 2));
  return (params: EChartsTooltipParam[] | EChartsTooltipParam): string => { /* ... */ };
}
```

Lives in `charts/tooltips.ts` alongside `navTooltipFormatter`.

---

## Part F — Chart components list with file paths

All paths absolute, all wealth-specific charts under `frontends/wealth/src/lib/components/charts/portfolio/`. Tokens, formatters, and option builders are shared via `charts/` root. `@netz/ui` stays the home of truly neutral primitives only.

### F.1 Existing — reuse unchanged

| Component | Path | Reused by |
|---|---|---|
| `NavHeroChart` | `frontends/wealth/src/lib/components/charts/discovery/NavHeroChart.svelte` | Analytics (model portfolio + constituent) |
| `RollingRiskChart` | `frontends/wealth/src/lib/components/charts/discovery/RollingRiskChart.svelte` | Analytics |
| `DrawdownUnderwaterChart` | `frontends/wealth/src/lib/components/charts/discovery/DrawdownUnderwaterChart.svelte` | Analytics |
| `ReturnDistributionChart` | `frontends/wealth/src/lib/components/charts/discovery/ReturnDistributionChart.svelte` | Analytics |
| `MonthlyReturnsHeatmap` | `frontends/wealth/src/lib/components/charts/discovery/MonthlyReturnsHeatmap.svelte` | Analytics |
| `RiskMetricsBulletChart` | `frontends/wealth/src/lib/components/charts/discovery/RiskMetricsBulletChart.svelte` | Analytics |

### F.2 New — shared infrastructure

| Component / module | Path | Purpose |
|---|---|---|
| `chartTokens(variant)` extension | `frontends/wealth/src/lib/components/charts/chart-tokens.ts` | Add workbench variant |
| `workbenchTooltipFormatter` | `frontends/wealth/src/lib/components/charts/tooltips.ts` | Dense tooltip helper |
| `option-builders/efficientFrontier.ts` | `frontends/wealth/src/lib/components/charts/option-builders/efficientFrontier.ts` | Option factory, no Svelte |
| `option-builders/radar.ts` | `frontends/wealth/src/lib/components/charts/option-builders/radar.ts` | Ex-ante radar factory |
| `option-builders/treemapAnimated.ts` | `frontends/wealth/src/lib/components/charts/option-builders/treemapAnimated.ts` | Smooth-update treemap |
| `option-builders/workbenchCore.ts` | `frontends/wealth/src/lib/components/charts/option-builders/workbenchCore.ts` | Centerpiece tool-state → option |
| `ChartInstancePool.ts` | `frontends/wealth/src/lib/components/charts/ChartInstancePool.ts` | Pooled ECharts instances (sparklines) |

### F.3 New — Builder phase charts

| Component | Path | Chart type | Data contract |
|---|---|---|---|
| `EfficientFrontierChart` | `frontends/wealth/src/lib/components/charts/portfolio/EfficientFrontierChart.svelte` | scatter + line | `{ frontier: {vol:number; ret:number}[]; current: {vol; ret}; preview?: {vol; ret}; peerMedian?: {vol; ret} }` |
| `ExAnteRadarChart` | `frontends/wealth/src/lib/components/charts/portfolio/ExAnteRadarChart.svelte` | radar | `{ axes: {name; max; invert?:boolean}[]; current: number[]; preview?: number[]; peer?: number[] }` |
| `ConstraintHeatmapChart` | `frontends/wealth/src/lib/components/charts/portfolio/ConstraintHeatmapChart.svelte` | heatmap | `{ constraints: {name; current; preview?; limit; slack}[] }` |
| `AllocationTreemapChart` | `frontends/wealth/src/lib/components/charts/portfolio/AllocationTreemapChart.svelte` | treemap | `{ tree: TreemapNode[]; mode: 'current' \| 'preview' \| 'both' }` |
| `StressScenarioBarChart` | `frontends/wealth/src/lib/components/charts/portfolio/StressScenarioBarChart.svelte` | grouped bar | `{ scenarios: {name: 'GFC'\|'COVID'\|'Taper'\|'RateShock'; current: number; preview?: number; holdings?: {fundId; loss}[] }[] }` |

### F.4 New — Analytics phase charts (portfolio-specific)

| Component | Path | Chart type | Data contract |
|---|---|---|---|
| `RiskAttributionBarChart` | `frontends/wealth/src/lib/components/charts/portfolio/RiskAttributionBarChart.svelte` | stacked horizontal bar | `{ rows: {fundId; name; systematic; idiosyncratic}[]; topN: number }` |
| `ConstituentCorrelationHeatmap` | `frontends/wealth/src/lib/components/charts/portfolio/ConstituentCorrelationHeatmap.svelte` | heatmap | `{ order: string[]; matrix: number[][] }` (matrix pre-sorted by server) |
| `FactorExposureBarChart` | `frontends/wealth/src/lib/components/charts/portfolio/FactorExposureBarChart.svelte` | horizontal bar | `{ factors: {name; loading}[] }` |
| `BrinsonWaterfallChart` | `frontends/wealth/src/lib/components/charts/portfolio/BrinsonWaterfallChart.svelte` | bar waterfall | `{ steps: {label; value; type: 'total'\|'delta'}[] }` |

### F.5 New — Live Workbench charts

| Component | Path | Chart type | Data contract |
|---|---|---|---|
| `WorkbenchCoreChart` | `frontends/wealth/src/lib/components/charts/portfolio/WorkbenchCoreChart.svelte` | multi-series line/area | `{ tool: WorkbenchTool; datasets: Record<WorkbenchTool, SeriesBundle>; events: EventMarker[]; focus?: HoldingFocus }` |
| `AllocationDivergenceChart` | `frontends/wealth/src/lib/components/charts/portfolio/AllocationDivergenceChart.svelte` | grouped bar | `{ buckets: {name; strategic; tactical; effective; trackingError}[] }` |
| `SparklineSVG` | `frontends/wealth/src/lib/components/charts/portfolio/SparklineSVG.svelte` | SVG path (NOT ECharts) | `{ values: Float64Array; up: boolean }` |
| `AlertTimelineChart` | `frontends/wealth/src/lib/components/charts/portfolio/AlertTimelineChart.svelte` | scatter + markArea | `{ alerts: {ts; severity:'info'\|'warning'\|'critical'; label; fundId?}[] }` |
| `RebalanceImpactTreemap` | `frontends/wealth/src/lib/components/charts/portfolio/RebalanceImpactTreemap.svelte` | dual treemap | `{ before: TreemapNode[]; after: TreemapNode[] }` |

All data contracts are TypeScript interfaces the backend specialist owns — this doc claims only the field names, not the Pydantic shape.

---

## Part G — Performance budget

### G.1 Targets

| Scenario | Budget |
|---|---|
| Slider drag (Builder) | 60fps sustained; each preview response rerenders 3 charts within the same rAF |
| Live price tick (Workbench) | <16ms chart-update wall clock per flush; 30 sparklines + core chart + allocation bar |
| Initial workbench cold start | <800ms TTI (after data ready) |
| Tool switch on centerpiece | <100ms option diff + paint |
| Analytics page cold start | <1200ms TTI |

### G.2 ECharts tree-shaking plan

Use `echarts/core` + explicit imports. The `echarts-setup.ts` needs updating (current `@investintell/ui/charts/echarts-setup.ts` imports the whole `echarts` bundle — audit required).

Required chart modules:
```
LineChart, BarChart, ScatterChart, HeatmapChart, TreemapChart,
RadarChart, CustomChart, GraphChart (for network graphs from Discovery reuse)
```

Required component modules:
```
GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
VisualMapComponent, MarkLineComponent, MarkAreaComponent, MarkPointComponent,
GraphicComponent, DatasetComponent, TransformComponent
```

Renderers:
```
CanvasRenderer  // canvas is faster for dense data; SVGRenderer only for print
```

Not imported: `PieChart`, `FunnelChart`, `GaugeChart`, `BoxplotChart`, `CandlestickChart`, `ParallelChart`, `SankeyChart` (until capital flows ship), `ThemeRiverChart`, `MapChart`, `LinesChart`, `EffectScatterChart`, `PictorialBarChart`, `SunburstChart` (re-add if Discovery adds it; treemap is preferred).

Expected bundle savings vs current: ~40% of the ECharts slice. Measured via `pnpm build --report` after the change lands.

### G.3 `dataset` + `encode` vs per-series arrays

For 30 sparklines: **neither pattern scales if you instantiate 30 ECharts**. The answer is to not use ECharts for sparklines at all (SVG path, Part F.5).

For the centerpiece: use the `dataset` component with a single typed source and per-series `encode: { x: 0, y: 1 }` / `{ x: 0, y: 2 }`. The `dataset` pattern lets `setOption` diff only the `dataset.source` array when ticks arrive — series definitions stay stable. This is measurably faster than rebuilding per-series `data[]` arrays in our internal profiling on similar-density charts (references: ECharts docs "dataset" section — optimize rendering of large data).

For the allocation bar / radar / treemap (Builder phase): per-series arrays are fine — update cadence is slow and the data shape changes per render.

### G.4 Typed arrays

Live data series should be `Float64Array`/`Float32Array`, not JS arrays. ECharts supports typed arrays natively on `series.data` and avoids a copy during the parsing phase. Backend SSE payloads should stream as typed-array-compatible shapes (server specialist owns the wire format; frontend does `new Float64Array(buffer)` on arrival).

### G.5 ChartInstancePool

If the SVG sparkline approach proves insufficient (e.g., users demand tooltips on sparklines), fall back to a pool of 8 pre-warmed ECharts instances round-robin'd across visible table rows. Off-screen rows share pool slots. This is the last-resort pattern — do not build it eagerly.

---

## Part H — Gaps / open decisions

These are items this chart layer cannot decide alone:

1. **Quant specialist input needed**:
   - Exact shape of the preview endpoint response (Builder Part C). This doc assumes `{ frontier, current, preview, constraints, treeDelta }` in one payload but the quant service design owns it.
   - Factor axis list and inversion rules for the ex-ante radar. This doc assumes backend already inverts "bad-when-high" metrics.
   - Correlation matrix ordering: this doc requires the server to deliver pre-clustered indices. If the quant service cannot, we need a client-side clustering library (rejected — violates smart-backend principle).
   - Stress test per-holding loss breakdown — does the engine currently emit per-holding attribution for each of the 4 scenarios, or only portfolio-level loss? If only portfolio-level, Part A.5 and Part F.3 `StressScenarioBarChart` must drop the `holdings` field.

2. **DB / ingestion specialist input needed**:
   - Real-time price source. Yahoo Finance delayed quotes are 15 min — not true intraday. Need Andrei decision: is 15-min delay acceptable (call it "near-real-time"), or does this need an intraday provider (IEX Cloud, Polygon, Alpaca) which requires provider selection and budget? This doc assumes 5s SSE cadence regardless of underlying freshness.
   - Where do intraday ticks land in the DB? A new `intraday_nav` hypertable or Redis ring buffer? If Redis, the worker bridging Yahoo → Redis → SSE is owned elsewhere; this layer just consumes.
   - Alert timeline data source — is the existing `strategy_drift_alerts` table sufficient or does it need a union with `breach_events` + `rebalance_events`?

3. **Andrei input needed**:
   - Priority order across phases: Builder preview > Analytics > Workbench? Or Workbench first as the "wow" demo?
   - Sparkline approach: SVG path (fast, no tooltip) or ECharts pool (slower, with tooltip)?
   - Is Sharpe isoquant overlay on the efficient frontier desired for the MVP or deferred?
   - Stress scenario set: stay with 4 engine scenarios (GFC, COVID, Taper, Rate Shock) or add a custom "what if rates +100bps" scenario slider that would require its own mini-chart?
   - Density target: exactly how dense is "Bloomberg-dense"? 10px font is aggressive; 11px is safer. Need a visual calibration session before locking tokens.

4. **Decisions deferred for post-MVP**:
   - Theme-aware re-read on dark-mode toggle for the workbench: current Discovery pattern uses `MutationObserver` on `data-theme` attribute. Fine for v1 but will re-run all `$derived` option builders on toggle. If it becomes a perf issue, move to `matchMedia('(prefers-color-scheme: dark)')` listener + token cache.
   - Accessibility: ECharts `aria` component enabled via `aria: { enabled: true, decal: { show: false } }` — out of scope for this doc but must be enforced at component template level by the component specialist.
   - Print / PDF rendering: the centerpiece chart must support a print variant that disables animations and uses `SVGRenderer`. Flag only — implementation deferred.

---

## Appendix — Anti-patterns explicitly forbidden

Reinforcing memories and CLAUDE.md invariants:

1. **No Chart.js, Recharts, D3, Highcharts, Plotly** — ECharts via `svelte-echarts` only. Sparkline SVG path is the only allowed non-ECharts chart primitive, and only because it is a glyph.
2. **No `localStorage` persistence** of chart state — in-memory + SSE + URL state only.
3. **No `.toFixed()` / `.toLocaleString()` / `Intl.*`** inline — use `@netz/ui` formatters everywhere. ESLint-enforced.
4. **No hex literals** in chart components — everything through `chartTokens()` or CSS vars.
5. **No hardcoded font families** — Urbanist comes via `--chart-font`.
6. **No provider-section names visible to users** — "Yahoo Finance" etc. must never leak into chart labels, legends, or tooltips. Show the data, not the source.
7. **No pie/donut charts** for allocation > 4 slices — treemap only.
8. **No dual y-axes** on the workbench core chart except for the rolling-correlation-vs-benchmark tool, where it is justified (price vs correlation are different scales). Must be explicitly labeled.
9. **No client-side quant computation** — no CVaR, Sharpe, correlation, or attribution math in Svelte. Backend computes, frontend displays.
10. **No `notMerge: true`** on the workbench core chart — kills animation state and zoom position.
11. **No per-row ECharts instances** for sparklines without a pool.
12. **No module-level `echarts.init`** — always inside `onMount` or `$effect` so it runs client-side.

---

## Appendix — Option sketch: WorkbenchCoreChart state machine

Illustrative only — component specialist owns final shape.

```ts
type WorkbenchTool =
  | 'nav'
  | 'drawdown'
  | 'rollingSharpe'
  | 'rollingVol'
  | 'rollingCorrelation'
  | 'rollingTrackingError'
  | 'regimeOverlay'
  | 'intraday';

interface SeriesBundle {
  primary: { id: string; name: string; data: [string, number][] };
  overlays: { id: string; name: string; data: [string, number][] }[];
  yAxisName: string;
  yAxisFormatter: (v: number) => string;
}

function buildWorkbenchOption(
  tool: WorkbenchTool,
  bundle: SeriesBundle,
  events: EventMarker[],
  tokens: ChartTokens,
) {
  const dense = 'fontSize' in tokens;
  return {
    textStyle: { fontFamily: tokens.fontFamily, fontSize: dense ? 10 : 12 },
    grid: { top: 16, right: 12, bottom: 28, left: 42, containLabel: false },
    tooltip: {
      trigger: 'axis',
      confine: true,
      transitionDuration: 0,
      backgroundColor: tokens.tooltipBg,
      borderColor: tokens.tooltipBorder,
      borderWidth: 1,
      padding: [4, 6],
      extraCssText: `max-width:180px;border-radius:2px`,
      formatter: workbenchTooltipFormatter(tokens, {
        valueFormatter: bundle.yAxisFormatter,
      }),
    },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: tokens.grid } },
      axisLabel: { fontSize: 9, color: tokens.axisLabel },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: bundle.yAxisName,
      nameTextStyle: { fontSize: 9, color: tokens.axisLabel },
      axisLabel: {
        fontSize: 9,
        color: tokens.axisLabel,
        formatter: bundle.yAxisFormatter,
      },
      splitLine: { lineStyle: { color: tokens.grid, opacity: 0.35 } },
    },
    dataZoom: [
      { type: 'inside', filterMode: 'weakFilter' },
      { type: 'slider', height: 14, bottom: 2, filterMode: 'weakFilter', borderColor: 'transparent' },
    ],
    series: [
      {
        id: bundle.primary.id,
        name: bundle.primary.name,
        type: 'line',
        data: bundle.primary.data,
        smooth: tool !== 'intraday',
        symbol: 'none',
        sampling: 'lttb',
        progressive: 500,
        progressiveThreshold: 3000,
        lineStyle: { width: 1.25, color: tokens.primary },
        animation: tool !== 'intraday',
        animationDurationUpdate: tool === 'intraday' ? 0 : 250,
        markLine: {
          silent: true,
          symbol: 'none',
          data: events.map((e) => ({
            xAxis: e.ts,
            lineStyle: { color: e.color, type: 'dashed', width: 1 },
            label: { show: false },
          })),
        },
      },
      ...bundle.overlays.map((o) => ({
        id: o.id,
        name: o.name,
        type: 'line' as const,
        data: o.data,
        symbol: 'none' as const,
        sampling: 'lttb' as const,
        lineStyle: { width: 1, color: tokens.benchmark, type: 'dashed' as const },
      })),
    ],
  };
}
```

Svelte 5 component wraps this via `$derived`:

```svelte
<script lang="ts">
  import ECharts from 'svelte-echarts';
  import { chartTokens } from '../chart-tokens';
  import { buildWorkbenchOption } from '../option-builders/workbenchCore';
  import { workbench } from '$lib/state/workbench.svelte';

  let tokens = $state(chartTokens('workbench'));
  let option = $derived(
    buildWorkbenchOption(workbench.tool, workbench.bundle, workbench.events, tokens),
  );

  $effect(() => {
    const obs = new MutationObserver(() => (tokens = chartTokens('workbench')));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  });
</script>

<ECharts
  {option}
  initOptions={{ renderer: 'canvas' }}
  updateOptions={{ notMerge: false, lazyUpdate: true, replaceMerge: ['series', 'markLine'] }}
  style="width:100%;height:100%"
/>
```

End of design document.
