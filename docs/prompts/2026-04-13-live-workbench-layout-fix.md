# Live Workbench — Layout Refinement: 3-Column + Vertical Rebalance

## Context

Session A (PR #134) delivered the Live Workbench rebuild with Watchlist + Chart + Holdings.
The result works functionally but the layout has proportion problems:

1. **Chart is too wide** — occupies full width minus 240px watchlist, looks stretched
2. **Portfolio/Holdings area is too short** — squeezed at the bottom with excessive horizontal space
3. **No contextual information panels** — the PM needs News Feed and Macro Regime data visible while monitoring

## Design Direction (from product owner)

Add a **3rd column on the right (280px)** with two stacked panels:
- **News Feed** (top, ~55% height) — market news from Tiingo News API
- **Macro Regime** (bottom, ~45% height) — key indicators (VIX, CPI, DXY, etc.) from `macro_data` table

Increase the **vertical space for the portfolio area** (bottom) so the chart becomes
more square (less horizontally stretched, more balanced aspect ratio).

Add a **Trade Log** panel to the right of the Holdings table (bottom area) to make
the holdings table more compact horizontally.

## Target Layout

```
┌──────────┬───────────────────────────┬──────────────┐
│WATCHLIST  │ CHART TOOLBAR (32px)      │ NEWS FEED    │
│(220px)   ├───────────────────────────┤ (280px)      │
│          │                           │ Tiingo news  │
│ Portfolio │ CHART (lightweight-charts) │ headlines    │
│ holdings  │ (aspect ratio ~16:10,    │ with tags    │
│ as live   │  NOT ultra-wide)         │              │
│ tickers   │                           │──────────────│
│          │                           │ MACRO REGIME │
│          │                           │ VIX: 18.2    │
│          │                           │ CPI: 3.1%    │
│          │                           │ DXY: 104.2   │
│          │                           │ 10Y: 4.25%   │
│          │                           │ SPREAD: 142  │
│          ├───────────────┬───────────┤              │
│          │ PORTFOLIO     │ TRADE LOG │              │
│          │ SUMMARY +     │ (recent   │              │
│          │ HOLDINGS      │  orders,  │              │
│          │ TABLE         │  BUY/SELL │              │
│          │ (~45% height) │  status)  │              │
│          │               │           │              │
└──────────┴───────────────┴───────────┴──────────────┘
```

## Branch

`feat/live-workbench-layout-fix` (already created from main)

## MANDATORY: Read these files FIRST

1. `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte` — current 2-column layout (710 lines). This is what you're modifying.
2. `frontends/wealth/src/lib/components/terminal/live/Watchlist.svelte` — left panel (328L)
3. `frontends/wealth/src/lib/components/terminal/live/ChartToolbar.svelte` — toolbar (363L)
4. `frontends/wealth/src/lib/components/terminal/live/PortfolioSummary.svelte` — summary panel (253L)
5. `frontends/wealth/src/lib/components/terminal/live/HoldingsTable.svelte` — positions table (260L)
6. `backend/app/domains/wealth/routes/market_data.py` — check if Tiingo news endpoint exists (search for "news")
7. `backend/app/domains/wealth/routes/model_portfolios.py` — search for "trade-tickets" endpoint
8. `packages/investintell-ui/src/lib/tokens/terminal.css` — terminal design tokens

## ARCHITECTURE RULES

- Svelte 5 runes only. All formatters from `@investintell/ui`. Zero hex values.
- Terminal tokens exclusively. Monospace, hairline borders, zero radius.
- No localStorage. No new npm packages.

## DELIVERABLES (4 items)

### 1. Layout grid change in +page.svelte

Change the CSS grid from 2-column to 3-column:

```css
.live-shell {
    display: grid;
    grid-template-columns: 220px 1fr 280px;
    grid-template-rows: 32px 1fr 45%;
    height: calc(100vh - 88px);
    gap: 1px;
    background: var(--terminal-bg-void);
    font-family: var(--terminal-font-mono);
}
```

Grid areas:
- **Row 1 (32px):** Watchlist header | Chart toolbar | News Feed header
- **Row 2 (1fr, ~55%):** Watchlist body | Chart | News Feed + Macro Regime stacked
- **Row 3 (45%):** Watchlist continues | Portfolio Summary + Holdings Table | Trade Log

Key change: **Row 3 is now 45% of the viewport height** (was `auto` or minimal).
This compresses the chart vertically, making it more square, and gives the portfolio
area proper breathing room.

The right column spans rows 1-3 as a single stacked panel internally divided into
News Feed (top) and Macro Regime (bottom).

Adjust the watchlist width from 240px to 220px (slightly more compact).

The bottom center area splits horizontally: Portfolio Summary (200px fixed left) +
Holdings Table (1fr center) + Trade Log (240px fixed right).

### 2. News Feed: `frontends/wealth/src/lib/components/terminal/live/NewsFeed.svelte`

**Data source:** Check if `GET /market-data/news` or similar Tiingo news endpoint exists.
If yes, fetch from it. If not, create a simple component that fetches from
`GET /api/v1/market-data/news?tickers={portfolio_tickers}&limit=20` — check the backend
route file for the exact path.

If NO news endpoint exists at all, create the component with an empty state
"News feed — coming soon" and do NOT create a backend route in this prompt. The layout
must still render correctly with the empty state.

**Visual (each news item, ~48px):**
```
  14:32  MACRO
  Fed signals rate cut timeline shift amid
  persistent inflation concerns
```
- Time: `--terminal-fg-tertiary`, monospace, 10px
- Tag: colored pill (MACRO=cyan, FUND=green, MARKET=amber, ALERT=red), 9px, uppercase
- Headline: `--terminal-fg-secondary`, 11px, max 2 lines, overflow ellipsis
- On hover: `--terminal-bg-panel-raised`
- Header: "NEWS FEED" (28px, sticky)
- Scrollable body, `overflow-y: auto`

If the news endpoint exists and returns data, show real headlines. If not, show the
empty state — NEVER show mock/random data.

### 3. Macro Regime Panel: `frontends/wealth/src/lib/components/terminal/live/MacroRegimePanel.svelte`

**Data source:** `GET /macro-data/latest` or check the backend for a macro snapshot
endpoint. The `macro_data` hypertable contains FRED series. Check if there's a route
that returns latest values. Also check `mv_macro_latest` materialized view.

If a macro endpoint exists, fetch from it. If not, fetch directly from
`GET /api/v1/macro/snapshot` or similar. Search the backend routes for "macro" or
"indicators".

**Display: key-value grid of regime-relevant indicators:**
```
┌ MACRO REGIME ──────────────────┐
│ VIX            18.2   ▲ +1.3  │
│ CPI (YoY)     3.1%   ▼ -0.1  │
│ DXY            104.2  ▲ +0.4  │
│ 10Y YIELD     4.25%   ─  0.0  │
│ IG SPREAD     142bp   ▲ +3    │
│ HY SPREAD     385bp   ▲ +8    │
│ FED FUNDS     5.25%   ─  0.0  │
│ UNEMPLOYMENT  3.7%    ▼ -0.1  │
└────────────────────────────────┘
```

- Indicator name: `--terminal-fg-tertiary`, 10px, uppercase
- Value: `--terminal-fg-primary`, 11px, bold, tabular-nums
- Change: green (▲ positive for VIX/spreads = warning, for returns = good),
  red (▼ for VIX drop = calming), muted (─ for unchanged). Use semantic meaning
  per indicator, not universal green=up.
- Header: "MACRO REGIME" (28px, sticky)
- All values from `@investintell/ui` formatters

If no macro endpoint returns these values, show the component structure with "—" dashes
as placeholder values. Do NOT hardcode fake numbers.

### 4. Trade Log: `frontends/wealth/src/lib/components/terminal/live/TradeLog.svelte`

**Data source:** `GET /model-portfolios/{id}/trade-tickets?page_size=20` — this endpoint
EXISTS (verified in audit). Returns `TradeTicketPage` with items.

**Display:**
```
┌ TRADE LOG ─────────────────────┐
│ VGSH   BUY   +2.0%   14:32   │
│ VCIT   SELL  -1.5%   14:31   │
│ VTIP   BUY   +0.8%   14:30   │
│ BND    SELL  -3.2%   14:28   │
│                                │
│ (scrollable, newest first)     │
└────────────────────────────────┘
```

- Ticker: `--terminal-fg-primary`, 11px, bold
- Action badge: BUY = `--terminal-status-success` bg, SELL = `--terminal-status-error` bg,
  both with `--terminal-bg-void` text, 9px uppercase pill
- Delta weight: `formatPercent`, green if BUY, red if SELL
- Time: `--terminal-fg-tertiary`, 10px, monospace
- Header: "TRADE LOG" (28px, sticky) + count badge
- Empty state: "No trades executed"
- Scrollable body

## FILE STRUCTURE

```
frontends/wealth/src/
  routes/(terminal)/portfolio/live/
    +page.svelte                       ← MODIFY: 3-col grid, wire new components
  lib/components/terminal/live/
    NewsFeed.svelte                    ← NEW
    MacroRegimePanel.svelte            ← NEW
    TradeLog.svelte                    ← NEW
```

Existing components (Watchlist, ChartToolbar, PortfolioSummary, HoldingsTable) are
NOT modified — only their grid placement changes in +page.svelte.

## GATE CRITERIA

1. Layout is 3 columns: Watchlist (220px) | Center (chart + portfolio) | Right (280px, news + macro)
2. Chart has a more balanced aspect ratio (not ultra-wide stretched)
3. Portfolio/Holdings area occupies ~45% of viewport height
4. News Feed panel renders in right column (real data or graceful empty state)
5. Macro Regime panel renders below news feed (real data or "—" placeholders)
6. Trade Log panel renders to the right of Holdings table
7. All panels have terminal styling (mono, hairline, zero radius, tokens only)
8. No hex colors, no .toFixed(), no new packages
9. `svelte-check` — zero errors
10. `pnpm build` — clean

## COMMIT

```
fix(live): 3-column layout + news feed + macro regime + trade log

Rebalance proportions: chart more square (not ultra-wide), portfolio area
taller (45vh). Right column: News Feed (Tiingo headlines) + Macro Regime
indicators (VIX, CPI, DXY, etc.). Trade Log panel next to Holdings table.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Push to origin/feat/live-workbench-layout-fix.
