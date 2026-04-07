# Wealth Charting — Technical Debt Register

**Last updated:** 2026-04-07
**Owner:** Wealth frontend
**Status:** Living document — append to it after each charting PR.

This document tracks deferred work, design constraints, and known limitations in the Wealth charting stack so that subsequent PRs and future contributors don't re-discover the same trade-offs.

---

## 0. Context

In April 2026 the wealth charting stack was audited end-to-end across four routes (`/dashboard`, `/portfolio`, `/portfolio/advanced`, `/market`). The audit found 18 charts with a mix of stylistic problems (pitch-deck gradients, hex hardcoding, inconsistent fonts), performance bugs (40k-point line series rendered without sampling, 2-second freezing animations), broken UX (decorative dual selectors, half-built features), and one chart violating the `svelte-echarts` mandate.

Three PRs followed:

| PR | Branch | Scope |
|---|---|---|
| **#95** | `feat/wealth-charts-foundational` | Quick-win hygiene across MacroChart, MainPortfolioChart, StressTestPanel, FactorAnalysisPanel, SeriesPicker, Macro page, Dashboard dual-selector. Geist→Urbanist global font. Deleted G4 single-bar chart-junk. |
| **#TBD** | `feat/wealth-advanced-market-chart-rewrite` | Tier A rewrite of AdvancedMarketChart from `lightweight-charts` to `svelte-echarts`. Line/Area/Candle switcher, bottom range chips, indicators (SMA/EMA/Bollinger), volume sub-pane, last-price callout, log/% toggles, live tick fold preserved. Tech debt doc (this file) added. |
| Future | TBD | Items registered below. |

The platform mandate is **`svelte-echarts` only**, no `Chart.js`, no `lightweight-charts`, no Highcharts. The Tier A PR removes the last violation of that mandate.

---

## 1. AdvancedMarketChart — Tier B (queued, recommended next)

**What's missing relative to the Barchart north-star screenshot.**

### B1. Compare overlay (multi-symbol)
Barchart's "Compare" button lets the user overlay 1-N additional symbols on the same chart, normalized to percent change from the visible range start. Required for relative-value analysis (single most-requested feature for analyst workflows).

- **Backend:** existing `/market-data/historical/{ticker}` already supports this — just call N times in parallel.
- **Frontend:** add `compareTickers: string[]` state, fetch in parallel via `Promise.all`, normalize each series to base-100 from `visibleStart`, render as additional line series with palette colors, dedicated legend.
- **Tooltip:** must show all symbol values at the hovered timestamp.
- **Effort:** ~200-300 LoC, half a day.

### B2. RSI / MACD sub-pane
Indicator sub-pane below the volume pane. Toggleable from the indicators menu. Layout: main grid 60%, RSI/MACD 20%, volume 20%.

- **Compute:** RSI = 100 - 100/(1 + RS) where RS = avgGain(14) / avgLoss(14). MACD = EMA12 - EMA26, signal = EMA9(MACD), histogram = MACD - signal.
- **ECharts:** add a third grid + xAxis + yAxis, add `rsi` line series (with overbought/oversold guideline at 70/30) OR `macd` histogram + lines.
- **Effort:** ~300 LoC, half a day. Requires `axisPointer.link` rework to keep three grids in sync.

### B3. f(x) — full transformations
Tier A only ships log scale and percent change. Barchart's f(x) menu also has:
- Year-over-year change
- Day-over-day change
- Smoothed (moving average overlay on price itself)
- Custom formula expressions

- **Effort:** YoY/DoD = trivial. Custom formulas = needs an expression parser, defer to Tier C alongside drawing tools.

### B4. Symbol search box (top-left)
Currently the chart receives `ticker` as a prop and the dashboard hardcodes the active ticker in its own state. Barchart has a search input directly in the chart header.

- **Backend:** symbol search endpoint exists in `/screener/catalog`, can be reused.
- **Frontend:** ~100 LoC for an autocomplete combobox in the chart header.
- **Effort:** afternoon.

### B5. Last-bar pulse animation on live tick
Currently the live tick fold updates the markPoint label. A subtle radial pulse on the last data point (like `effectScatter` ripple) would communicate "feed is hot" without being noisy.

- **Effort:** ~30 LoC. Add an `effectScatter` series at `[lastTime, lastClose]` with `rippleEffect` config.

---

## 2. AdvancedMarketChart — Tier C (large, dedicated PR)

### C1. Drawing tools sidebar
Trendline, fibonacci retracement, horizontal/vertical line, channel, rectangle, ellipse, text annotation, measurement tool, eraser. This is the most-requested-but-hardest item.

**Why it's expensive:**
- ECharts has **no native drawing tools**. The `graphic` component supports static shapes but not interactive drawing.
- Three implementation paths:
  1. **Custom HTML5 Canvas overlay** stacked on top of the ECharts canvas. Catch mouse events, render shapes in `requestAnimationFrame`. Persist to backend. Estimated 1500-2500 LoC for trendline/fib/horizontal/vertical, +500 LoC per additional tool.
  2. **Switch to `klinecharts`** (open-source TradingView clone, has drawing tools natively). Trade-off: replaces ECharts for THIS chart only, breaks consistency with the rest of the stack. Maintenance risk.
  3. **Use `lightweight-charts` again** — but it doesn't have drawing tools either. Barchart writes their own on top. Same problem.

**Recommendation:** Option 1 (custom canvas overlay) when this becomes a real ask. Estimate 2-3 dedicated days for the first 4 tools, persistence integration extra.

**Persistence:** drawings need to live in DB. New table `chart_annotations(id, organization_id, user_id, ticker, kind, payload_json, created_at)` with RLS. Endpoints `GET/POST/PATCH/DELETE /charts/annotations`.

### C2. Templates
Save/load chart layouts (chart type + indicators + range + drawings + compare set). Backend table + endpoints. Frontend popover.

- **Effort:** ~600 LoC + backend.

---

## 3. AdvancedMarketChart — Tier D (depends on backend)

| Feature | Requires |
|---|---|
| **Notes** (Barchart top-right) | `chart_notes` table, RLS, CRUD endpoints |
| **Alerts** (price/indicator threshold) | `price_alerts` table, evaluator worker, push notification stack |
| **Watch** (add to watchlist from chart) | reuse existing watchlist domain — just an integration |
| **My Charts** (saved layouts library) | reuse Templates infra (C2) |

None of these belong in a charting PR. Each is a backend project of its own.

---

## 4. Backend smart-compute opportunities

CLAUDE.md mandates "smart-backend / dumb-frontend". Tier A computes indicators client-side because it was the fastest path to delivery. Better long-term posture:

### 4a. Pre-compute SMA / EMA / Bollinger in `/market-data/historical/{ticker}`

Add optional query params: `?indicators=sma20,sma50,ema20,bbands20`. Backend computes them once per request (or caches in Redis with key `mkt:hist:{ticker}:{interval}:{indicators}`) and returns them as additional fields per bar:

```json
{
  "bars": [
    {
      "timestamp": "2026-01-01T00:00:00Z",
      "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1234,
      "sma20": 100.5, "sma50": 99.8, "ema20": 100.7,
      "bb_upper": 103.2, "bb_lower": 97.8
    }
  ]
}
```

- **Why:** Client-side compute is fine for 5k bars but doesn't scale to multi-symbol compare or to 10y daily history at intraday granularity (~250k bars). Server-side compute can be vectorized in numpy and cached.
- **Effort:** ~150 LoC backend, ~30 LoC frontend (drop the local compute helpers, read fields from response).

### 4b. Pre-compute RSI / MACD in the same response

Same pattern. Add `?indicators=rsi14,macd` and return per-bar values. Required if Tier B2 ships server-side.

### 4c. NBER recession bands endpoint

For MacroChart Tier B (see §5). New endpoint `GET /macro/recessions` returning `[{ start, end, label }]` from FRED `USREC` series. Already in `macro_data` hypertable, just needs a thin route + cache.

### 4d. Macro events endpoint

For MacroChart event annotations (FOMC dates, CPI release dates, recession starts). New endpoint `GET /macro/events?from=&to=&kinds=fomc,cpi,nfp,recession`. Source: scrape FRED release calendar + hardcoded recession dates. Cache aggressively.

### 4e. Server-side favorites for SeriesPicker

Currently SeriesPicker accepts a `favorites: Set<string>` prop and an `onToggleFavorite` callback. PR #95 added the "Favorites" pinned section but the storage backend is not implemented — the parent component must persist client-side.

- **Per CLAUDE.md** "Sem localStorage" rule, persistence has to be server-side.
- **Required:** new `user_macro_favorites` table or column on `users`, endpoints `GET/POST/DELETE /users/me/macro-favorites`.
- **Effort:** ~120 LoC backend, ~20 LoC frontend.

---

## 5. MacroChart — queued redesign work

PR #95 fixed the performance and animation bugs. Visual upgrade is still pending.

### 5a. NBER recession bands

`markArea` over the chart with light grey fill during recession periods. Data source: `4c` above.

### 5b. Regime markArea overlay

The MacroChart parent already passes `regime: { regional_regimes }` in its data — but the chart **ignores it**. The audit flagged this as dead-but-promising data. Render colored `markArea` zones based on regime: `RISK_OFF` orange, `CRISIS` red, `INFLATION` amber, `RISK_ON` blue.

### 5c. Transformations dropdown

Levels (default) / YoY % / MoM % / Diff / Index=100 / Log scale. Frontend can apply most of these to the data array; log requires `yAxis.type: 'log'`.

### 5d. Event annotations

`markLine` per FRED release date (CPI, NFP, FOMC, GDP). Data source: `4d` above. Tooltip on hover.

### 5e. Drop dead-code `subSeries` path

`MacroChart.svelte` still has `subSeries` filtering and a second grid path that no caller uses (no `subchart: true` flag is set anywhere). Either delete it or actually wire it for volume macro indicators (M2 supply, BoJ balance sheet). Delete is safer.

### 5f. SeriesPicker presets

"Recession Watch", "Inflation Tracker", "Yield Curve", "Global Stress" — one-click selection of 3-6 indicators. Pure client-side mapping. ~80 LoC.

### 5g. SeriesPicker virtualization

Currently 75 indicators hardcoded inline. Once the catalog passes ~150 entries, render time becomes noticeable. Use `@tanstack/svelte-virtual` (already a dependency in `frontends/wealth/package.json`).

### 5h. SeriesPicker fuzzy search

Substring-only search misses "CPI" if the entry is named "Consumer Price Index". Add Fuse.js (~10KB).

### 5i. Pull catalog out of the component

`SeriesPicker.svelte` has 117 lines of inline `CATALOG` array. Move to `frontends/wealth/src/lib/data/macro-catalog.ts` for testability and to enable backend-driven catalog later.

---

## 6. `/portfolio/advanced` (`analytics/entity/*`) — chart-type rebuilds

The audit found these panels structurally sound but using the wrong chart type for the data:

| Panel | Current | Should be |
|---|---|---|
| `MonteCarloPanel` | Single line + PDF curve computed in frontend | **Fan chart**: percentile bands (P5/P25/P50/P75/P95) shaded. PDF computation moves to backend. |
| `CaptureRatiosPanel` | Side-by-side bar | **Quadrant scatter**: up-capture × down-capture with diagonal `y=x` and Morningstar quadrant labels |
| `TailRiskPanel` | Single bar | **Grouped bar**: VaR/CVaR at multiple confidence levels (90/95/99) |
| `PeerGroupPanel` | Single bar | **Quartile bars / box**: P25-P50-P75 with peer group fundo highlight (Morningstar Direct style) |

Each is a 200-400 LoC dedicated PR. Compatible with smart-backend pattern — backend already returns the right data shape, just rendered wrong.

`ActiveSharePanel.svelte` is suspected orphan — not imported by any route. Delete after verification.

---

## 7. `/portfolio` root — Tier B chart-type swaps

Same pattern. PR #95 stripped the pitch-deck styling but kept the chart-type choice as-is. Recommended swaps:

| Panel | Current | Should be |
|---|---|---|
| `FactorAnalysisPanel` donut | 2-5 slice donut | **Stacked-100 horizontal bar** (institutional convention; donuts are amateur for ≤5 slices) |
| `MainPortfolioChart` | Single line with markLine for base | **Performance Cockpit**: line + benchmark dashed + drawdown area underlay + regime markArea + stats panel side. Requires backend endpoint that returns benchmark + drawdown in same shot. |
| `SectorAllocationChart` | (audit didn't reach it — not in the 18) | TBD |

---

## 8. Long-tail hygiene sweep (boring but real)

### 8a. Remaining `.toFixed` callsites in `lib/components/charts/*`

Audit found `.toFixed(` in 7 chart components that PR #95 didn't touch (they're not wired into the audited routes but they're orphan-or-future-use):

- `NavPerformanceChart.svelte`
- `BacktestEquityCurve.svelte`
- `FundScoringRadar.svelte`
- `DecileBoxplot.svelte`
- `CorrelationHeatmap.svelte`
- `SectorAllocationChart.svelte`
- `SectorAllocationTreemap.svelte`

ESLint formatter rule doesn't catch them because they're inside ECharts callbacks. Sweep them in a single PR.

### 8b. Long-tail Tailwind hex arbitrary values

PR #95 cleaned StressTestPanel + FactorAnalysisPanel. The dashboard `/dashboard/+page.svelte` and other portfolio panels still have a long tail of `text-[#85a0bd]`, `bg-[#141519]`, `border-[#404249]/30`, `text-[#fc1a1a]`, `text-[#11ec79]`. These violate the design-token rule. Pure mechanical sweep but tedious — ~2 hours.

### 8c. `regimeColors` and `statusColors` hex exports in `echarts-setup.ts`

```ts
export const regimeColors: Record<string, string> = {
  RISK_ON: "#3b82f6",
  // ...
};
export const statusColors = {
  ok: "#22c55e",
  // ...
};
```

These should resolve from CSS vars at call time. Currently they're frozen to a specific palette and won't follow theme changes. Fix: turn them into helper functions `getRegimeColor(name)` / `getStatusColor(name)` that read `getComputedStyle`.

### 8d. Component-local token resolution helpers are duplicated

Tier A's `AdvancedMarketChart` inlines a `readChartTokens()` helper that reads `--ii-success`, `--ii-danger`, `--ii-text-muted`, `--ii-brand-primary`, etc. So do `MainPortfolioChart`, `StressTestPanel`, `FactorAnalysisPanel` (after PR #95). Extract to `@investintell/ui/charts/use-chart-tokens.svelte.ts` as a shared rune.

---

## 9. Mandate / convention reminders

These aren't debt — they're **rules** future contributors must follow. Listed here to avoid relitigation:

1. **`svelte-echarts` only.** No `Chart.js`, no `lightweight-charts`, no Highcharts. Tier A PR removed the last violation.
2. **Tokens, not hex.** Inside ECharts options where CSS vars can't be used directly, resolve once via `getComputedStyle` + re-resolve via `MutationObserver` on `data-theme` attribute changes. Never inline hex literals in templates or scripts.
3. **No `localStorage`.** Persistence is server-side, every time. Tier B/C/D items that need persistence (drawings, templates, notes, favorites, alerts) all require backend endpoints — none of them are frontend-only.
4. **Smart-backend / dumb-frontend.** Indicator math, percentile bands, recession data, peer aggregates — all should land server-side. Tier A computes indicators client-side as a stop-gap; §4a is the proper fix.
5. **No CVaR/regime/DTW jargon in user-facing copy.** Per CLAUDE.md. Use AUM, performance, holdings, drawdown, volatility — terms a wealth client recognizes.
6. **Formatters from `@investintell/ui`.** Never `.toFixed()`, `.toLocaleString()`, or inline `Intl.NumberFormat`. The ESLint rule catches template usage but not callback bodies inside ECharts options — review those manually.
7. **Performance flags on long line series.** `sampling: 'lttb'`, `progressive: 2000`, `progressiveThreshold: 5000`, `large: true`, `largeThreshold: 2000`. Tier A applies them; future chart components must too.
8. **`animationDuration` ≤ 300ms.** Anything longer feels like a freeze on filter interactions. Default in `globalChartOptions` is 300; per-chart overrides are red flags.
9. **dataZoom slider position math.** Without subchart: `grid.bottom = 60`, `slider.bottom = 8`. With subchart: main grid uses upper 50%, subgrid `top: '55%' bottom: 60`, slider `bottom: 8`. Anything else creates dead canvas.
