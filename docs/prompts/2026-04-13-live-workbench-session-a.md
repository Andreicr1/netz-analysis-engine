# Phase 5 Live Workbench — Session A: Terminal Rebuild + Real-Time Chart + Watchlist

## Context

Phase 5 of 10-phase Terminal Unification. Phase 4 Builder COMPLETE (PRs #131-#133).
The Live Workbench exists at `(terminal)/portfolio/live/` but was built BEFORE the
terminal design system matured. It has 4,141 lines of hardcoded hex colors, mock data
(`Math.random()`), Urbanist font, and a layout that doesn't match the terminal aesthetic.

**Critical discovery:** The real-time infrastructure is MORE COMPLETE than expected:
- `tiingo_bridge.py` (429L) — Tiingo IEX WebSocket streaming, 50ms buffer, Redis pub
- `market_data.py` — Backend WebSocket endpoint with subscribe/unsubscribe protocol
- `market-data.svelte.ts` (492L) — Frontend MarketDataStore with tick buffer (250ms)
- `TerminalPriceChart.svelte` (398L) — lightweight-charts v5 with dual series
- Shadow OMS models (TradeTicket, PortfolioActualHoldings) with routes

**The gap is NOT infrastructure — it's wiring + UI rebuild.**

## Design Vision

The Live Workbench is a REAL trading terminal, not a simplified monitoring dashboard.
The chart (lightweight-charts) is the HERO — center stage, receiving real-time data
via Tiingo WebSocket. Portfolio holdings appear as a live watchlist. Any ticker
available in Tiingo can be searched and compared on the chart.

**Reference layout (adapted from investment dashboard reference):**

```
┌───────────────────────────────────────────────────────────────┐
│ TERMINAL TOPNAV (32px) — already exists via TerminalShell     │
├─────────────┬─────────────────────────────────────────────────┤
│ WATCHLIST    │  CHART TOOLBAR (32px)                           │
│ (240px,     │  [TICKER INPUT] [1D][1W][1M][3M][1Y] [Compare] │
│  left,      ├─────────────────────────────────────────────────┤
│  scrollable │                                                 │
│  portfolio  │  CHART (lightweight-charts, hero, flex)          │
│  holdings   │  Real-time Tiingo WS, crosshair, tooltip,       │
│  as live    │  volume bars, percentage mode                    │
│  tickers    │                                                 │
│  with       │                                                 │
│  prices,    │                                                 │
│  change%,   │                                                 │
│  spark)     │                                                 │
│             ├──────────────────────┬──────────────────────────┤
│             │ PORTFOLIO SUMMARY    │ HOLDINGS TABLE            │
│             │ (240px, AUM, return, │ (flex, positions,         │
│             │  status badge,       │  weight, actual vs target,│
│             │  drift status)       │  P&L, last price)         │
│             │                      │                           │
├─────────────┴──────────────────────┴──────────────────────────┤
│ STATUS BAR (24px) — already exists via TerminalShell           │
└───────────────────────────────────────────────────────────────┘
```

## Branch

`feat/builder-session-2` — No, use: `feat/live-workbench-session-a`
Create a new branch from main.

## Sanitization — Mandatory Label Mapping

| Internal term | Terminal label |
|---|---|
| DTW drift / dtw_distance | Strategy Drift |
| CVaR 95 | Tail Loss (95% confidence) |
| fill_status: "simulated" | Simulated |
| REGIME_RISK_ON / RISK_OFF / CRISIS | Expansion / Defensive / Stress |
| scoring composite | Quality Score |

## MANDATORY: Read these files FIRST before writing ANY code

### Existing Live Workbench (understand what to rebuild)
1. `frontends/wealth/src/lib/components/portfolio/live/LiveWorkbenchShell.svelte` — 641L, current 3-col layout, mock data, hex colors. Understand the structure, then rebuild from scratch.
2. `frontends/wealth/src/lib/components/portfolio/live/TerminalTickerStrip.svelte` — 395L, current header. Will NOT be reused — too different.
3. `frontends/wealth/src/lib/components/portfolio/live/TerminalBlotter.svelte` — 318L, position table. Logic salvageable, UI needs rebuild.
4. `frontends/wealth/src/lib/components/portfolio/live/charts/TerminalPriceChart.svelte` — 398L, lightweight-charts. THIS IS SALVAGEABLE — needs wiring to MarketDataStore.

### Real-time infrastructure (wire these, don't rebuild)
5. `frontends/wealth/src/lib/stores/market-data.svelte.ts` — 492L. MarketDataStore with tick buffer (250ms), WebSocket connection to `/api/v1/market-data/live/ws`. Key API: `start()`, `stop()`, `subscribe(tickers)`, `unsubscribe(tickers)`, `priceMap` (reactive Map), `holdings` (derived, live-fused), `status` (WsStatus).
6. `frontends/wealth/src/lib/components/portfolio/live/workbench-state.ts` — context key for terminal-scoped MarketDataStore
7. `frontends/wealth/src/routes/(terminal)/+layout.svelte` — terminal layout, creates MarketDataStore and sets context via `TERMINAL_MARKET_DATA_KEY`

### Backend endpoints
8. `backend/app/domains/wealth/routes/market_data.py` — WebSocket endpoint at `/api/v1/market-data/live/ws?token=<jwt>`. Protocol: `{"action":"subscribe","tickers":["SPY"]}` → `{"type":"price","data":{PriceTick}}`. Also has REST: `GET /market-data/quote/{ticker}` for single-shot price lookup.
9. `backend/app/domains/wealth/routes/model_portfolios.py` — search for `actual-holdings`, `trade-tickets`, `rebalance/preview`, `execute-trades`, `activate`

### Design reference
10. `packages/investintell-ui/src/lib/tokens/terminal.css` — all terminal tokens
11. `docs/plans/2026-04-13-phase-4-builder-design.md` — reference for terminal aesthetic (already implemented in Builder)
12. `frontends/wealth/src/lib/components/terminal/builder/+page.svelte` — reference for how Builder uses terminal tokens, layout patterns

## ARCHITECTURE RULES (non-negotiable)

- Svelte 5 runes only: `$state`, `$derived`, `$effect`, `$props`.
- All formatting via `@investintell/ui` formatters. Never `.toFixed()` or inline Intl.
- CSS uses terminal tokens from `terminal.css` exclusively. ZERO hex values.
- No localStorage. No EventSource.
- `<svelte:boundary>` on async-dependent sections.
- Monospace font, 1px borders, zero radius.
- lightweight-charts for the hero chart (NOT svelte-echarts — this is a trading chart, not a dashboard chart).
- WebSocket via MarketDataStore (already built) — do NOT create a new WS connection.

## DELIVERABLES (6 items)

### 1. New route page: `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte`

**COMPLETE REWRITE** of the existing +page.svelte. The current page imports
LiveWorkbenchShell and passes portfolios. The new page IS the shell — no separate
LiveWorkbenchShell component.

**Layout structure (CSS Grid):**
```css
.live-shell {
    display: grid;
    grid-template-columns: 240px 1fr;
    grid-template-rows: auto 1fr auto;
    height: calc(100vh - 88px);
    gap: 1px;
    background: var(--terminal-bg-void);
    font-family: var(--terminal-font-mono);
}
```

Grid areas:
- Left column (240px): Watchlist (full height)
- Right top: Chart toolbar (32px) + Chart (flex)
- Right bottom: Portfolio summary (240px fixed) + Holdings table (flex)

**Portfolio selection:** Reuse PortfolioDropdown pattern from Builder. On portfolio
change, update watchlist tickers and chart default series.

**MarketDataStore integration:** Read from context (`TERMINAL_MARKET_DATA_KEY`).
The (terminal)/+layout.svelte already creates and provides it. On portfolio selection:
1. Get portfolio's fund tickers
2. Call `marketStore.subscribe(tickers)` 
3. Watchlist reads from `marketStore.priceMap`

### 2. Watchlist component: `frontends/wealth/src/lib/components/terminal/live/Watchlist.svelte`

Create new directory `frontends/wealth/src/lib/components/terminal/live/`.

**Props:**
```typescript
interface WatchlistItem {
    ticker: string;
    name: string;
    instrument_id: string;
    price: number;
    change: number;
    change_pct: number;
    weight: number; // portfolio weight
}

interface Props {
    items: WatchlistItem[];
    selectedTicker: string | null;
    onSelect: (ticker: string) => void;
}
```

**Visual (each row, 36px):**
```
 SPY          │ ▲ +0.42%
 S&P 500 ETF  │ $523.18
```
- Ticker: `--terminal-fg-primary`, bold, 11px
- Name: `--terminal-fg-tertiary`, 10px, truncated with ellipsis
- Price: `--terminal-fg-primary`, tabular-nums, right-aligned
- Change%: green (`--terminal-status-success`) if positive, red (`--terminal-status-error`) if negative
- Selected row: `--terminal-bg-panel-raised` background + left 2px amber border
- On click: fires `onSelect(ticker)` — chart switches to this instrument

**Portfolio weight badge:** Small `12.5%` text in muted below the name, showing the
instrument's allocation weight in the model portfolio.

**Header (28px):** "WATCHLIST" label + portfolio name (truncated).

**Footer:** Ticker search input (28px) — type to search any ticker. On Enter, calls
`GET /market-data/quote/{ticker}` to validate, then subscribes via MarketDataStore
and adds to the watchlist temporarily. This allows the PM to look up ANY Tiingo-available
instrument, not just portfolio holdings.

**Scrollable:** `overflow-y: auto` on the items container.

### 3. Chart area: Wire TerminalPriceChart to MarketDataStore

**DO NOT REWRITE TerminalPriceChart.svelte** — it's 398 lines of working lightweight-charts
code with proper SSR handling, percentage mode, dual series, and timeframe selection.

**What to change:**
- Move it from `portfolio/live/charts/` to `terminal/live/charts/` (or keep and import)
- Wire its `historicalBars` prop to real data from `GET /market-data/quote/{ticker}` (historical bars)
- Wire its `lastTick` prop to `marketStore.priceMap.get(selectedTicker)`
- Wire its `portfolioNavBars` prop to model portfolio NAV from `model_portfolio_nav` table
  (via `GET /model-portfolios/{id}/nav-history` endpoint from Session 3)

**Chart toolbar (32px, above chart):**
```
[ TICKER ▾ ] // INSTRUMENT NAME // PRICE // CHG% // │ [1D] [1W] [1M] [3M] [1Y] │ [Compare ▾] │ [Indicators]
```
- Ticker dropdown or display showing the currently selected instrument
- Timeframe buttons (already exist in TerminalPriceChart — expose them in the toolbar)
- Compare button: opens a dropdown to add a second series (any ticker from Tiingo)
- Indicators button: stub for Session B (future)

**Comparison mode:** When the PM clicks "Compare" and types a ticker (e.g., "SPY"),
add a second line series to the chart in a different color. Both series use percentage
mode so they're normalized. The TerminalPriceChart already supports dual series
(baseline + line). Extend to support N comparison series if needed, or use the existing
NAV overlay slot.

**Real-time updates:** Set up an `$effect` that watches `marketStore.priceMap` and
updates the chart's `lastTick` whenever the selected ticker gets a new price:
```typescript
$effect(() => {
    const tick = marketStore.priceMap.get(selectedTicker);
    if (tick) {
        lastTick = { time: tick.timestamp, price: tick.price };
    }
});
```

### 4. Portfolio Summary panel

Small panel (240px wide, bottom-left of the right column) showing aggregate portfolio stats.

```
┌ PORTFOLIO ──────────────────────────┐
│                                     │
│  STATUS          ● LIVE             │
│  AUM             $125.4M            │
│  RETURN (1Y)     +8.2%              │
│  DRIFT STATUS    Aligned            │
│  INSTRUMENTS     34                 │
│  LAST REBALANCE  2026-04-10         │
│                                     │
│  [ REBALANCE ]                      │
└─────────────────────────────────────┘
```

- Status badge: green dot + "LIVE" for active, amber dot + "PAUSED" for paused
- AUM: `formatCurrency` from @investintell/ui
- Return: green/red, `formatPercent`
- Drift Status: "Aligned" (green) / "Watch" (amber) / "Breach" (red) — derived from
  holdings drift data (Session B will add DriftMonitorPanel, for now show aggregate)
- REBALANCE button: amber outline, opens RebalanceFocusMode (stub for Session B, shows
  "Coming in Session B" alert for now)

Data source: workspace portfolio state + `GET /model-portfolios/{id}` response fields.

### 5. Holdings Table

Bottom-right panel showing the portfolio's actual positions.

**Columns:**
| Fund | Ticker | Weight | Target | Drift | Price | Change |
|---|---|---|---|---|---|---|

- Fund: name, truncated, `--terminal-fg-primary`
- Ticker: `--terminal-fg-tertiary`, 10px
- Weight: actual weight (from actual-holdings or target as fallback), `formatPercent`
- Target: target weight from construction, `formatPercent`, muted
- Drift: `actual - target`, color-coded (green if aligned, amber if watch, red if breach)
- Price: live from `marketStore.priceMap`, `formatCurrency`
- Change: change_pct, green/red, `formatPercent`

**Click row:** Selects ticker in the watchlist and switches chart to that instrument.

**Sticky header.** Scrollable body. Terminal table styling (monospace, hairline borders,
no radius, `--terminal-text-10` for data, `--terminal-text-10` uppercase for headers).

**Data source:** 
- Weights: from portfolio's `fund_selection_schema.funds` (or `GET /{id}/actual-holdings`)
- Prices: live from `marketStore.priceMap`
- If actual-holdings endpoint returns data, use it. Otherwise fallback to target weights.

### 6. Update +page.server.ts

Update `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.server.ts` to also
load the selected portfolio's holdings for SSR seeding:

```typescript
export const load: PageServerLoad = async ({ parent, url }) => {
    const { token } = await parent();
    if (!token) return { portfolios: [], selectedPortfolioData: null };

    const api = createServerApiClient(token);
    const portfolios = await api.get<ModelPortfolio[]>("/model-portfolios").catch(() => []);
    
    // Pre-load selected portfolio data if ID in query params
    const selectedId = url.searchParams.get("portfolio");
    let selectedPortfolioData = null;
    if (selectedId) {
        selectedPortfolioData = await api.get(`/model-portfolios/${selectedId}`).catch(() => null);
    }
    
    return { portfolios, selectedPortfolioData };
};
```

## FILE STRUCTURE (new + modified)

```
frontends/wealth/src/
  routes/(terminal)/portfolio/live/
    +page.server.ts                    ← MODIFY: add selected portfolio pre-load
    +page.svelte                       ← REWRITE: new 2-zone grid layout
  lib/components/terminal/live/
    Watchlist.svelte                   ← NEW: live ticker watchlist (left panel)
    ChartToolbar.svelte               ← NEW: ticker display + timeframe + compare
    PortfolioSummary.svelte           ← NEW: aggregate stats panel
    HoldingsTable.svelte              ← NEW: positions table with live prices
```

**Do NOT delete** the existing `portfolio/live/` components — they'll be removed in Phase 9
when (app)/ routes are frozen. For now, the new `terminal/live/` components coexist.

## GATE CRITERIA

1. `/portfolio/live` renders inside TerminalShell with new layout (watchlist left, chart center, tables bottom)
2. Watchlist shows portfolio holdings with live prices from MarketDataStore WebSocket
3. Chart displays real historical data for selected ticker (lightweight-charts)
4. Chart receives real-time tick updates from MarketDataStore (price updates on chart)
5. Ticker search in watchlist footer can look up any Tiingo-available instrument
6. Chart comparison: PM can add a second ticker as overlay series
7. Holdings table shows positions with live prices, weight vs target, drift coloring
8. Portfolio summary shows AUM, status badge, return, drift aggregate
9. Click watchlist item → chart switches to that instrument
10. Click holdings row → chart switches + watchlist highlights
11. Zero hex color values — all terminal.css tokens
12. Zero `.toFixed()` / inline Intl — all @investintell/ui formatters
13. `cd frontends/wealth && pnpm exec svelte-check` — zero errors
14. `cd frontends/wealth && pnpm build` — clean
15. No TypeScript `any` types

## IMPORTANT WARNINGS

- Do NOT rewrite TerminalPriceChart.svelte (398L) — wire it to real data, don't rebuild
- Do NOT rewrite market-data.svelte.ts (492L) — consume from context, don't modify
- Do NOT create a new WebSocket connection — use MarketDataStore from (terminal)/+layout.svelte context
- Do NOT delete existing `portfolio/live/` components (LiveWorkbenchShell etc.) — they stay for now
- Do NOT install new npm packages — lightweight-charts v5 is already installed
- Do NOT use svelte-echarts for the main trading chart — lightweight-charts is the correct library for real-time price data
- Do NOT add mock/random data — wire to real endpoints or show empty state
- Do NOT use hex colors — all from terminal.css tokens
- The MarketDataStore is already created in `(terminal)/+layout.svelte` and provided via `TERMINAL_MARKET_DATA_KEY` context — just read it

## Post-Session Checklist

After commit and push, verify in browser at http://localhost:5173/portfolio/live:

1. Watchlist renders with portfolio holdings and live prices updating
2. Chart shows real historical data for selected instrument
3. Price ticks appear on chart in real-time (verify WS connection in Network tab)
4. Click watchlist item → chart switches
5. Type ticker in search → chart shows that instrument
6. Compare button → add second series
7. Holdings table shows positions with live prices
8. Portfolio summary shows AUM + status
9. No console errors
10. Terminal aesthetic: monospace, zero radius, hairline borders, amber/cyan accents

If the Tiingo WebSocket is not available (no API key configured), the chart should
still render historical data from the REST endpoint and the watchlist should show
"Offline" status badges. Graceful degradation, never crash.

## COMMIT

When all gate criteria pass, commit with:
```
feat(live): Session A — terminal workbench rebuild with real-time Tiingo charts

3-zone layout: watchlist (240px, live prices) + hero chart (lightweight-charts,
Tiingo WS real-time) + holdings table (positions with drift). Portfolio summary
panel with AUM/status/drift aggregate. Ticker search for any Tiingo instrument.
Chart comparison mode. Wired to MarketDataStore WebSocket (existing infra).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Push to origin/feat/live-workbench-session-a.
