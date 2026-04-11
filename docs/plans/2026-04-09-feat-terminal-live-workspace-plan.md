---
title: "feat: Terminal-Grade Live Workspace"
type: feat
status: active
date: 2026-04-09
origin: docs/brainstorms/2026-04-09-terminal-live-workspace-brainstorm.md
---

# Terminal-Grade Live Workspace ("Brutalismo Financeiro")

## Enhancement Summary

**Deepened on:** 2026-04-09
**Sections enhanced:** 6 phases + architecture + security + performance
**Research agents used:** architecture-strategist, security-sentinel, performance-oracle, best-practices-researcher (lightweight-charts v5), framework-docs-researcher (FastAPI WS), svelte5-frontend-consistency, data-integrity-guardian

### Key Improvements from Deepening

1. **Upgrade to lightweight-charts v5** (not v4) — native multi-pane for volume, 16% smaller bundle (~35KB), better tree-shaking
2. **Split chart `$effect` into two paths** — `series.setData()` for historical loads, `series.update()` for live ticks (O(1) vs O(n))
3. **Fix optimistic lock pattern** — `UPDATE ... WHERE holdings_version = :expected` with rowcount check on `portfolio_actual_holdings` (not `model_portfolios`)
4. **Add `disposed` flag pattern** for async `onMount` cleanup (prevents lightweight-charts memory leak on fast unmount)
5. **Declare `chart`/`series` as `$state`** (not plain `let`) so `$effect` tracks them after async dynamic import
6. **Per-org WS connection limit** — prevent single tenant from exhausting 64-client cap
7. **Terminal route RBAC guard** — add `+layout.server.ts` under `(terminal)/` blocking INVESTOR role
8. **Ticker subscription validation** — regex + per-connection cap (200 tickers max)
9. **Confirmation dialog as separate component** (`TradeConfirmationDialog.svelte`), not snippet
10. **SQL injection fix** (pre-existing) in `market_data.py` dashboard queries — parameterize f-string interpolation

### New Security Findings (Pre-Existing, Not Plan-Introduced)

- **CRITICAL:** SQL injection via f-string in `market_data.py` lines 238-282 — must fix before terminal ships
- **HIGH:** JWT in WS query param appears in logs — add log redaction, consider WS ticket exchange pattern

### Performance Optimizations Discovered

- Remove legacy `market:prices` global Redis channel (dual-publish wastes 2x PUBLISH commands)
- Add subscription reconciliation in `TiingoStreamBridge` to shed stale tickers (no per-ticker unsubscribe)
- Raise `BroadcasterConfig.max_connections` from 64 to 128 (dual-store pattern doubles per-user connections)

---

## Overview

Transform the `/portfolio/live` route from a web-app-styled 3-tool-tabbed monitor into a Bloomberg/FactSet-grade execution terminal with extreme information density, real-time Tiingo WebSocket streaming, TradingView lightweight-charts, and a 4-zone zero-scroll layout. This is the execution heart of Phase 4 (Circulatory System) in the wealth investment lifecycle.

**Critical discovery during research:** The backend already has a **complete Tiingo WebSocket infrastructure** — `ConnectionManager` with `RateLimitedBroadcaster`, `TiingoStreamBridge` (IEX), JWT-authenticated WS endpoint at `/market-data/live/ws`, REST provider for news/EOD/intraday, and a production frontend WS client in `market-data.svelte.ts`. The scope of this plan is primarily **frontend architecture + wiring** with targeted backend additions.

## Problem Statement

The current Live route suffers from three critical deficiencies:

1. **Low density** — 3 tools hidden behind tabs (overview/drift/execution). PM must switch tabs to see drift AND orders AND chart. Bloomberg shows everything simultaneously.
2. **Mock data** — `LivePricePoller` generates synthetic random-walk ticks via `setInterval`. No real market data. The existing Tiingo WebSocket infrastructure (`market-data.svelte.ts`) is inaccessible because the `(terminal)` layout bypasses `(app)` where the store is declared.
3. **Web-app aesthetics** — Rounded corners, generous padding, Urbanist body font for numbers. An execution surface demands monospace tabular-nums, zero-radius, and p-1 density.

## Proposed Solution

A 6-phase refactor (A-F) that: replaces the 3-pane WorkbenchLayout with a 4-zone CSS Grid; swaps ECharts for lightweight-charts; wires the terminal to the existing Tiingo WebSocket proxy; eliminates the sidebar and tool ribbon; adds execution safeguards (idempotency, confirmation, role guard); and polishes for print/responsive/accessibility.

## Technical Approach

### Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ HEADER 44px: [Portfolio ▾] TICKER 142.38 ▲+0.23% | KPIs | ⚠3 │ ✕  │
├──────────────────────────────────────────┬───────────────────────────┤
│ CHART (grid-area: chart, 1fr)           │ OMS (grid-area: oms)     │
│ lightweight-charts Baseline/Candlestick │ Trade tickets + Approve  │
│ Time controls: [1D][1W][1M][3M]        │ 340px fixed              │
│ Volume histogram sub-pane              │ Broker slots (dormant)   │
├──────────────────────────────────────────┴───────────────────────────┤
│ BLOTTER (grid-area: blotter, 35vh)                                  │
│ [POSITIONS] [TRADE LOG] — merged drift + allocations                │
└──────────────────────────────────────────────────────────────────────┘
```

```css
.terminal-grid {
  display: grid;
  grid-template: 44px 1fr 35vh / 1fr 340px;
  grid-template-areas:
    "header  header"
    "chart   oms"
    "blotter blotter";
  height: 100%;
  overflow: hidden;
  background: var(--tg-bg, #05080f);
}
```

### Key Architectural Decisions (from brainstorm)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Charting engine | lightweight-charts (TradingView) | 45KB WebGL, native candlestick/baseline, magnetic crosshair. Rule 9.1 updated to permit in `(terminal)` |
| D2 | Data provider | Tiingo API (already integrated) | 85k+ tickers, WebSocket real-time, bid/ask/volume |
| D3 | Scope | Phase (a) portfolio monitor → Phase (b) generalist terminal | Solid base first |
| D4 | Real-time arch | Backend WS proxy (already exists) | API key secure, ~50ms latency |
| D5 | Asset classes | All from day one | Proxy is asset-class agnostic |
| D6 | Execution | Simulated, pre-wired for broker | Dormant slots for venue/fill |
| D7 | Layout | 4-zone CSS Grid, zero scroll | All panels visible simultaneously |
| D8 | Design | Brutalismo financeiro | #05080f, monospace nums, p-1/p-2, zero radius |
| D9 | Components | 5 eliminated, 3 refactored | See component inventory below |

(see brainstorm: docs/brainstorms/2026-04-09-terminal-live-workspace-brainstorm.md)

### WebSocket Client Strategy (resolves SpecFlow Q1)

The `(terminal)` layout bypasses `(app)` where the `MarketDataStore` is declared. Solution: **instantiate a terminal-specific `MarketDataStore` in `(terminal)/+layout.svelte`** using the same `getToken()` from root Clerk context.

```
Root +layout.svelte (Clerk auth, fonts, theme tokens)
├── (app)/+layout.svelte → MarketDataStore instance (dashboard, screener, builder)
└── (terminal)/+layout.svelte → NEW MarketDataStore instance (terminal-only)
    └── portfolio/live/+page.svelte → consumes via getContext()
```

This keeps stores independent — the terminal subscribes only to portfolio tickers, the dashboard subscribes to watchlist tickers. No cross-contamination. Connection count is bounded by `ConnectionManager`'s 64-client hard cap.

### Chart Data Source (resolves SpecFlow Q6)

The chart displays **a user-selectable instrument from the blotter**. PM clicks a row in the positions table → chart switches to that instrument's price feed.

- Default: highest-weight instrument in the portfolio (auto-selected on load)
- Historical data: `GET /market-data/historical/{ticker}` (existing endpoint) with `?resampleFreq=` for intraday
- Live data: WS ticks for the selected ticker (already subscribed as part of portfolio set)
- Portfolio-level composite NAV display is Phase (b) scope

### Implementation Phases

---

#### Phase 1: Pre-Flight Migration + Backend Hardening

**Goal:** Add missing DB columns, execution safeguards, and trade history endpoint before touching frontend.

**Files:**

| File | Action |
|------|--------|
| `backend/app/core/db/migrations/versions/0108_terminal_oms_hardening.py` | **Create.** On `trade_tickets`: add `execution_venue VARCHAR(50) NULL`, `fill_status VARCHAR(20) NOT NULL DEFAULT 'simulated'` with CHECK constraint `IN ('simulated', 'pending', 'filled', 'partial', 'rejected')`. On `portfolio_actual_holdings` (NOT `model_portfolios`): add `holdings_version INTEGER NOT NULL DEFAULT 1`. Tiebreaker index: ensure `ix_trade_tickets_portfolio_executed` covers `(portfolio_id, executed_at DESC, id DESC)` for stable pagination. |
| `backend/app/domains/wealth/routes/model_portfolios.py` | **Modify.** (1) Add `@idempotent` decorator with key `f"execute_trades:{portfolio_id}:{zlib.crc32(canonical_payload_hash)}"`, lock ID `900_103`, TTL 60s. (2) Add role guard: `require_role(actor, [Role.ADMIN, Role.INVESTMENT_TEAM])`. (3) Add `SELECT ... FOR UPDATE` on `PortfolioActualHoldings` row. (4) Add optimistic lock: `UPDATE ... WHERE holdings_version = :expected` with rowcount check — return 409 on mismatch. (5) Add `write_audit_event()` with before/after JSONB snapshots. |
| `backend/app/domains/wealth/routes/model_portfolios.py` | **Add endpoint.** `GET /model-portfolios/{id}/trade-tickets?page=1&per_page=50` — paginated trade history, sorted by `executed_at DESC`. Response includes `execution_venue`, `fill_status`. |
| `backend/app/domains/wealth/schemas/model_portfolio.py` | **Modify.** Add `TradeTicketRead` schema with all columns including new ones. Add `ExecuteTradesRequest` with `expected_version: int` field. |

**Tests:**
- `test_execute_trades_idempotent` — same request twice returns same result
- `test_execute_trades_role_guard` — INVESTOR role gets 403
- `test_execute_trades_optimistic_lock` — stale version gets 409
- `test_trade_tickets_list` — pagination, date filtering

**Success criteria:**
- `make check` passes
- Execute-trades has triple-layer dedup (Redis + SingleFlight + advisory lock)
- Role guard blocks INVESTOR
- 409 returned on concurrent execution with stale version

---

#### Phase 2: Terminal Grid Shell (Frontend Phase A)

**Goal:** Replace `WorkbenchLayout` with bespoke CSS Grid. Eliminate sidebar and tool ribbon. All 4 zones visible simultaneously.

**Files:**

| File | Action |
|------|--------|
| `frontends/wealth/src/routes/(terminal)/+layout.svelte` | **Modify.** Instantiate `MarketDataStore` via `createMarketDataStore()` and `setContext()`. Import `getToken` from root layout data. |
| `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte` | **Simplify.** Remove `activeTool`/`onToolChange` props and `?tool=` URL param. Only `?portfolio=<id>` remains. |
| `frontends/wealth/src/lib/components/portfolio/live/LiveWorkbenchShell.svelte` | **Rewrite.** Replace `WorkbenchLayout` import with inline CSS Grid (4 zones). Remove tool-conditional rendering. All panels always visible. Keep holdings fetch logic, error boundaries, poller lifecycle (as fallback). Add `selectedInstrument` state for chart ticker selection. |
| `frontends/wealth/src/lib/components/portfolio/live/workbench-state.ts` | **Simplify.** Remove `WorkbenchTool` union, `WORKBENCH_TOOLS`, `WorkbenchToolMeta`, `resolveWorkbenchTool`. Keep only portfolio URL param helper. |
| `frontends/wealth/src/lib/components/portfolio/live/WorkbenchToolRibbon.svelte` | **Delete.** |
| `frontends/wealth/src/lib/components/portfolio/live/LivePortfolioSidebar.svelte` | **Delete** (replaced by `PortfolioDropdown` in Phase 4). |
| `frontends/wealth/src/lib/components/portfolio/live/LivePortfolioKpiStrip.svelte` | **Delete** (absorbed into header in Phase 4). |

**Terminal CSS tokens** (local to `(terminal)` scope):
```css
:root {
  --tg-bg: #05080f;
  --tg-panel: #0c1018;
  --tg-border: rgba(255, 255, 255, 0.08);
  --tg-text: #e0e6ed;
  --tg-muted: #5a6a7a;
  --tg-mono: 'SF Mono', 'Fira Code', 'Fira Mono', 'Roboto Mono', 'Courier New', monospace;
}
```

**Svelte 5 patterns:**
- Grid area visibility: `const showOms = $derived(selected !== null)`
- Chart height: auto-sized by grid cell (no manual viewport calc, remove `viewportHeight` state and resize listener)
- Poller lifecycle: `$effect` runs whenever `selected !== null` (no tool check)
- Selected instrument: `let selectedInstrument = $state<string | null>(null)` — set by blotter row click, consumed by chart

**Success criteria:**
- 4-zone grid renders at `h-screen` with zero scroll
- All panels visible simultaneously (no ribbon)
- Portfolio dropdown placeholder in header zone (wired in Phase 4)
- Empty states render correctly in each zone
- `make check-all` passes (no broken imports from deleted components)

---

#### Phase 3: lightweight-charts + Real-Time Data (Frontend Phase B)

**Goal:** Replace `WorkbenchCoreChart` (ECharts) with lightweight-charts Baseline series. Wire to real Tiingo WebSocket data via `MarketDataStore`.

**Dependencies:** Phase 2 (grid shell), Phase 1 (not strictly required but recommended)

**Files:**

| File | Action |
|------|--------|
| `frontends/wealth/package.json` | **Modify.** Add `"lightweight-charts": "^5.0.0"` dependency. |
| `frontends/wealth/src/lib/components/portfolio/live/charts/TerminalPriceChart.svelte` | **Create.** lightweight-charts Baseline chart with dynamic import (SSR safe). |
| `frontends/wealth/src/lib/components/portfolio/live/charts/WorkbenchCoreChart.svelte` | **Delete.** |
| `frontends/wealth/src/lib/components/portfolio/live/LiveWorkbenchShell.svelte` | **Modify.** Wire `TerminalPriceChart` to `MarketDataStore` ticks for the selected instrument. Wire historical data fetch on instrument/range change. |

**TerminalPriceChart component API:**

```typescript
interface Props {
  ticker: string | null;
  ticks: readonly PriceTick[];       // from MarketDataStore
  historicalBars: readonly OhlcvBar[]; // from REST fetch
  range: TimeRange;                   // '1D' | '1W' | '1M' | '3M' | 'ALL'
  ariaLabel?: string;
}
```

**lightweight-charts integration (Svelte 5 lifecycle):**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  // Dynamic import — prevents SSR crash
  type LWC = typeof import("lightweight-charts");

  let { ticker, ticks, historicalBars, range, ariaLabel = "Live price chart" }: Props = $props();
  let containerEl: HTMLDivElement | undefined = $state();
  let chart: ReturnType<LWC["createChart"]> | null = null;
  let series: ReturnType<ReturnType<LWC["createChart"]>["addBaselineSeries"]> | null = null;

  onMount(async () => {
    const lwc = await import("lightweight-charts");
    if (!containerEl) return;

    chart = lwc.createChart(containerEl, {
      autoSize: true,
      layout: { background: { type: lwc.ColorType.Solid, color: "transparent" }, textColor: "#85a0bd", fontSize: 10 },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(64,66,73,0.4)", style: lwc.LineStyle.Dashed } },
      crosshair: { mode: lwc.CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: true },
      handleScroll: false,
      handleScale: false,
    });

    series = chart.addBaselineSeries({ /* ... brand accent colors from CSS vars */ });

    // Theme toggle observer (same MutationObserver pattern as current chart)
    const themeObs = new MutationObserver(() => { /* re-read accent, applyOptions */ });
    themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    return () => { themeObs.disconnect(); chart?.remove(); chart = null; series = null; };
  });

  // Data update — merge historical + live ticks
  $effect(() => {
    if (!series) return;
    const data = [...historicalToBaselineData(historicalBars), ...ticksToBaselineData(ticks)];
    if (data.length === 0) return;
    series.setData(data);
    chart?.timeScale().fitContent();
  });
</script>
```

**Historical data stitching:**
- Range `1D`: IEX intraday via `GET /market-data/historical/{ticker}?resampleFreq=5Min&startDate=today`
- Range `1W`/`1M`: IEX intraday via `GET /market-data/historical/{ticker}?resampleFreq=1Hour&startDate=...`
- Range `3M`/`ALL`: EOD daily via `GET /market-data/historical/{ticker}?frequency=daily&startDate=...`
- Live WS ticks appended to the right edge of historical data

**Time range controls:** Pill buttons inside the chart panel header. `let range = $state<TimeRange>('1D')`. On change, re-fetch historical and call `series.setData()`.

**Success criteria:**
- lightweight-charts renders in the chart grid zone
- Baseline series shows historical data from Tiingo REST
- Live ticks from WebSocket append in real-time
- Magnetic crosshair works
- No SSR crash (dynamic import verified)
- Chart resizes with container (autoSize)
- Theme toggle updates chart colors

---

#### Phase 4: Terminal Header + Portfolio Dropdown (Frontend Phase C)

**Goal:** Build the ticker strip header with portfolio dropdown, inline KPIs, and live price display.

**Dependencies:** Phase 2 (grid shell)

**Files:**

| File | Action |
|------|--------|
| `frontends/wealth/src/lib/components/portfolio/live/TerminalTickerStrip.svelte` | **Create.** 44px header with all elements. |
| `frontends/wealth/src/lib/components/portfolio/live/PortfolioDropdown.svelte` | **Create.** Popover listbox replacing the sidebar. |

**TerminalTickerStrip layout:**
```
[Portfolio ▾] │ AAPL  142.3847  ▲ +0.23%  │ Bid 142.34  Ask 142.36  │ Ret 8.2%  Vol 12.4%  │ ⚠ 3  │ [Exit →]
```

**Props:**
```typescript
interface Props {
  portfolios: ModelPortfolioSummary[];
  selected: ModelPortfolioSummary | null;
  selectedInstrument: string | null;
  latestTick: PriceTick | null;        // from MarketDataStore for selected instrument
  optimizationMetrics: OptimizationResult | null;
  driftCount: number;
  alertCount: number;
  onSelect: (portfolio: ModelPortfolioSummary) => void;
  onExit: () => void;
}
```

**KPIs (inline, absorbed from LivePortfolioKpiStrip):**
- Expected Return → "Ret X.X%" (from `optimization.expected_return`)
- Volatility → "Vol X.X%" (from `optimization.portfolio_volatility`)
- Drift badge → "⚠ N" (count of instruments with |drift| > tolerance)
- All via `formatPercent()` from `@investintell/ui`

**Price display:**
- Last price: 28px monospace, `tabular-nums`
- Change: green `▲ +0.23%` / red `▼ -0.15%` via `--ii-success`/`--ii-danger`
- Bid/Ask: from `PriceTick.bid_price`/`PriceTick.ask_price` (show "---" when unavailable, e.g. mutual funds)

**PortfolioDropdown:**
- Popover with listbox (`role="listbox"`)
- Max-height 400px, internal scroll
- Keyboard navigable (Arrow keys + Enter + Escape)
- Shows: portfolio name, profile, inception date, state chip (live/paused)
- Only `live` and `paused` portfolios shown (not draft/archived)

**Success criteria:**
- Header renders at 44px fixed height
- Portfolio dropdown selects and updates URL
- Price updates in real-time from WS
- Bid/Ask shows for equities/ETFs, "---" for mutual funds
- KPIs display from optimization metrics
- Drift badge shows correct count
- Keyboard navigation works on dropdown

---

#### Phase 5: OMS Panel + Blotter (Frontend Phases D+E)

**Goal:** Adapt OMS for terminal density with execution safeguards. Build merged blotter with positions/trade-log toggle.

**Dependencies:** Phase 2 (grid shell), Phase 1 (trade-tickets endpoint, idempotency)

**Files:**

| File | Action |
|------|--------|
| `frontends/wealth/src/lib/components/portfolio/live/TerminalOmsPanel.svelte` | **Create.** Refactored from `RebalanceSuggestionPanel` with terminal density. Adds confirmation dialog. Pre-wires broker slots (dormant). |
| `frontends/wealth/src/lib/components/portfolio/live/TerminalBlotter.svelte` | **Create.** Merged positions + trade log table with toggle. |
| `frontends/wealth/src/lib/components/portfolio/live/RebalanceSuggestionPanel.svelte` | **Delete** (replaced by TerminalOmsPanel). |
| `frontends/wealth/src/lib/components/portfolio/live/LiveAllocationsTable.svelte` | **Delete** (absorbed into TerminalBlotter). |
| `frontends/wealth/src/lib/components/portfolio/live/WeightVectorTable.svelte` | **Keep** (still used by `/portfolio/advanced`). Remove from live route imports. |

**TerminalOmsPanel (340px right column):**

```
┌─ OMS (12 tickets) ──────────┐
│ Turnover: 2.34%              │
│ ─────────────────────────── │
│ ▲ BUY  +1.12%  Vanguard... │
│ ▼ SELL -0.77%  PIMCO Inc... │
│ ▲ BUY  +0.45%  BlackRock... │
│ (scroll for more)            │
│ ─────────────────────────── │
│ Venue: [Simulated ▾]  (dim) │
│ ─────────────────────────── │
│ [Approve & Execute]  [Print] │
└──────────────────────────────┘
```

- Font: 11px body, 9px labels
- Ticket cards: zero radius, p-1
- BUY/SELL chips: 8px font, `p-[1px_4px]`
- **Confirmation dialog** (resolves SpecFlow EX-1): On click "Approve & Execute" → modal appears:
  ```
  ┌─ Confirm Execution ────────────┐
  │ You are about to execute:      │
  │ • 8 BUY orders                 │
  │ • 4 SELL orders                │
  │ • Est. turnover: 2.34%        │
  │                                │
  │ Portfolio: Core Equity Balanced │
  │                                │
  │ [Cancel]         [Confirm →]   │
  └────────────────────────────────┘
  ```
- Sends `expected_version` in payload (from current `holdings_version`)
- Handles 409: "Portfolio was modified by another team member. Refresh to see latest state." + Refresh button
- Handles 403: "Insufficient permissions to execute trades."
- **Broker slots (dormant):** `Venue: [Simulated]` dropdown, disabled, `opacity-40`. Renders but is non-interactive until broker adapter exists.

**TerminalBlotter (bottom zone, 35vh):**

Positions view (default):
```
INSTRUMENT          │ BLOCK        │ TARGET │ ACTUAL │ DRIFT  │ P&L    │ SCORE
Vanguard Total Stk  │ Core Equity  │ 25.00% │ 26.12% │ +1.12% │ +0.34% │  78.2
PIMCO Income Fund   │ Fixed Income │ 15.00% │ 14.23% │ -0.77% │  ---   │  82.1
────────────────────┼──────────────┼────────┼────────┼────────┼────────┼──────
TOTAL               │              │100.00% │100.43% │ +0.43% │        │
```

Trade Log view:
```
TIME     │ ACTION │ INSTRUMENT          │ DELTA   │ STATUS    │ VENUE
14:32:07 │ BUY    │ Vanguard Total Stk  │ +1.12%  │ Simulated │ ---
14:32:07 │ SELL   │ PIMCO Income Fund   │ -0.77%  │ Simulated │ ---
```

- Row height: 24px, sticky header, sticky footer (totals)
- `$derived.by` for merged row data (target + actual + live price)
- Sorted by `|drift| DESC` (largest deviations first)
- Row click → sets `selectedInstrument` → chart switches to that ticker
- Selected row has `bg-white/5` highlight
- Drift coloring: green (within tolerance), yellow (>2pp), red (>3pp)
- P&L: "---" until per-instrument live prices are wired
- MF instruments: show "EOD" badge next to instrument name
- Toggle: `[POSITIONS]` `[TRADE LOG]` pill buttons in blotter header
- Trade Log data: `GET /model-portfolios/{id}/trade-tickets` (new endpoint from Phase 1)

**Success criteria:**
- OMS renders at 340px with terminal density
- Confirmation dialog appears before execution
- 409/403 errors handled gracefully
- Blotter shows merged positions with drift coloring
- Trade Log tab shows execution history
- Row click selects instrument for chart
- Broker venue dropdown renders but is disabled

---

#### Phase 6: Polish — Print, Responsive, Accessibility, Edge Cases

**Goal:** Restore print mode, add responsive collapse, audit accessibility, handle all edge cases.

**Dependencies:** All above phases

**Files:**

| File | Action |
|------|--------|
| `LiveWorkbenchShell.svelte` | **Modify.** Add `@media print` rules for new grid areas. Add `@media (max-width: *)` responsive rules. |
| `TerminalTickerStrip.svelte` | **Modify.** Add `aria-live="polite"` on price region. |
| `TerminalBlotter.svelte` | **Modify.** Audit table semantics (th scope, sr-only labels). |
| `TerminalPriceChart.svelte` | **Modify.** Add stale data badge ("DELAYED" if last tick > 5 min). |

**Print mode:**
- `@media print`: hide `[data-area="header"]`, `[data-area="chart"]`, `[data-area="blotter"]`
- Show only `[data-area="oms"]` with white background, black text
- Keep institutional print header from existing OMS panel
- If Trade Log view is active, print the trade log table instead

**Responsive collapse:**
- `@media (max-width: 1400px)`: OMS slides to bottom, chart takes full width
  ```css
  grid-template: 44px 1fr 280px 35vh / 1fr;
  grid-template-areas: "header" "chart" "oms" "blotter";
  ```
- `@media (max-width: 960px)`: OMS becomes slide-out drawer, blotter reduces columns
- `@media (max-width: 768px)`: Show "Terminal requires desktop (1024px+)" message

**Accessibility:**
- Grid areas: `aria-label` attributes on each zone
- OMS: `role="complementary"`
- Price: `aria-live="polite"` + `aria-atomic="true"` (throttled announcements)
- Blotter: `<thead>`, `<th scope="col">`, `<th scope="row">` for instrument names
- Drift: never color-only — `+`/`-` prefix text always present
- Focus: `Escape` from any panel → focus to dropdown
- `prefers-reduced-motion`: disable chart animations (already `animation: false` on lightweight-charts)

**Edge cases:**

| Case | Behavior |
|------|----------|
| Empty portfolio (0 instruments) | EmptyState in chart + blotter: "No positions configured. Return to Builder." CTA button. |
| No live prices (WS disconnected) | Header price: "---" in muted color. Chart: flat line at last known price + "OFFLINE" badge. |
| Stale data (last tick > 5 min) | Red "DELAYED" badge next to price in header. |
| Simulated holdings (`source: "target_fallback"`) | Yellow "SIMULATED" badge in blotter header. |
| Holdings error | Red banner above blotter: "Failed to load holdings. [Retry]" |
| JWT expiry during session | WS closes 1008 → `MarketDataStore` calls `getToken()` on reconnect → Clerk auto-refreshes session token → reconnects. If Clerk session is fully expired → redirect to login. |
| Deep link to non-existent portfolio | No match in dropdown → auto-select first portfolio, toast "Portfolio not found". |
| Tab switch and return | WS heartbeat timeout → auto-reconnect on visibility change. Chart shows gap then backfills from REST on range change. |
| Concurrent execution (409) | Modal: "Another team member modified this portfolio. [Refresh]" |
| MF-only portfolio (no WS stream) | All instruments show "EOD" badge. Chart shows daily bars only. Header shows "EOD pricing" note. |
| Crypto in portfolio | Covered by IEX WS for US-listed crypto ETFs (BITO, etc). Direct crypto tokens not in IEX — show "EOD" badge. |

**Success criteria:**
- Print produces clean A4 trade sheet
- Responsive layout works at 1400px, 960px breakpoints
- All ARIA attributes present
- All edge cases render graceful fallback states
- `svelte-autofixer` clean on all new components
- Browser-validated in Chrome, Firefox, Safari (desktop)

## System-Wide Impact

### Interaction Graph

1. PM clicks "Approve & Execute" → `TerminalOmsPanel` → confirmation dialog → `POST /model-portfolios/{id}/execute-trades`
2. Backend validates: JWT → RLS → role guard → idempotency check (Redis + SingleFlight + advisory lock) → optimistic lock (`expected_version`) → insert `trade_tickets` → update `portfolio_actual_holdings` → increment `holdings_version` → audit event
3. Response returns → frontend re-fetches `GET /model-portfolios/{id}/actual-holdings` → drift recalculates → blotter updates → drift badge in header updates
4. Trade tickets visible in Trade Log tab via `GET /model-portfolios/{id}/trade-tickets`

### Error & Failure Propagation

| Layer | Error | Handling |
|-------|-------|----------|
| Tiingo WS upstream | Connection drop | `TiingoStreamBridge` exponential backoff (already implemented) |
| Backend WS proxy | Client slow consumer | `RateLimitedBroadcaster` drops oldest, evicts after 3 threshold violations |
| Frontend WS | Disconnect | `MarketDataStore` exponential backoff, 5 max retries, health preflight |
| Frontend WS | Auth 1008 | `getToken()` refresh on reconnect. Full session expiry → login redirect |
| Execute trades | 409 conflict | Show modal with refresh button |
| Execute trades | 403 forbidden | Show toast "Insufficient permissions" |
| Execute trades | Network error | Show retry button in OMS footer |
| Historical REST | Timeout | Show "Chart data unavailable" placeholder |

### State Lifecycle Risks

- **Stale drift after execution:** Holdings re-fetch after execute ensures drift recalculates. If re-fetch fails, show "Holdings may be outdated" warning.
- **WS ticker accumulation on portfolio switch:** Frontend MUST call `unsubscribe(oldTickers)` before `subscribe(newTickers)`. Implemented via `$effect` cleanup.
- **Chart data leak on portfolio switch:** `chart.remove()` + recreate on ticker change. Or `series.setData([])` + fresh data load.
- **Optimistic lock gap:** Between PM reading drift and clicking execute, holdings may change. `expected_version` prevents silent over-correction.

### API Surface Parity

| Interface | Needs Update |
|-----------|-------------|
| `POST /execute-trades` | Add idempotency, role guard, optimistic lock |
| `GET /trade-tickets` (new) | New endpoint |
| `WS /market-data/live/ws` | No change — already supports terminal use case |
| `GET /market-data/historical/{ticker}` | No change — already supports all time ranges |
| `GET /model-portfolios` | No change — already returns all needed data |
| `GET /model-portfolios/{id}/actual-holdings` | No change |

### Integration Test Scenarios

1. **E2E: Portfolio selection → WS subscribe → tick arrival → chart update → header price update**
   - Select portfolio with 5 instruments → verify WS subscribes to 5 tickers → send mock tick → verify chart and header update
2. **E2E: Execute trades → drift zeroes → blotter updates**
   - View drift → click execute → confirm → verify holdings re-fetch → verify drift columns zero
3. **E2E: Concurrent execution → 409 → recovery**
   - Two tabs, same portfolio → execute in tab A → immediately execute in tab B → tab B gets 409 → verify recovery flow
4. **E2E: WS disconnect → reconnect → chart continuity**
   - Streaming ticks → kill WS → verify reconnect → verify chart resumes without gap
5. **E2E: Portfolio switch → unsubscribe → resubscribe**
   - Portfolio A streaming → switch to B → verify A tickers unsubscribed → B tickers subscribed → chart resets

## Acceptance Criteria

### Functional Requirements

- [ ] 4-zone grid layout renders at h-screen with zero global scroll
- [ ] All panels visible simultaneously (no tool ribbon/tab switching)
- [ ] lightweight-charts renders Baseline series with real Tiingo data
- [ ] Magnetic crosshair on chart
- [ ] Time range controls (1D/1W/1M/3M) fetch correct historical data
- [ ] Portfolio dropdown replaces sidebar, keyboard navigable
- [ ] Header shows real-time price, change%, bid/ask from Tiingo WS
- [ ] Blotter shows positions with Target/Actual/Drift columns
- [ ] Row click in blotter selects instrument for chart
- [ ] Trade Log tab shows execution history from new endpoint
- [ ] OMS shows trade tickets with terminal density
- [ ] Confirmation dialog before trade execution
- [ ] Idempotent execute-trades with optimistic locking
- [ ] Role guard on execution (ADMIN + INVESTMENT_TEAM only)
- [ ] 409 handled gracefully for concurrent execution

### Non-Functional Requirements

- [ ] Zero SSR crash (lightweight-charts dynamic import)
- [ ] Chart autoSize responds to container resize
- [ ] WS reconnects automatically after disconnect (exponential backoff)
- [ ] JWT refresh works for 8+ hour terminal sessions
- [ ] Print produces clean A4 trade sheet
- [ ] Responsive collapse at 1400px and 960px
- [ ] All numbers via `@investintell/ui` formatters (no `.toFixed()`)
- [ ] Monospace `tabular-nums` for all numeric data
- [ ] ARIA labels on all zones, `aria-live` on prices
- [ ] No `localStorage` anywhere

### Quality Gates

- [ ] `make check` passes (backend lint + typecheck + tests)
- [ ] `make check-all` passes (frontend lint + typecheck)
- [ ] `svelte-autofixer` clean on all new components
- [ ] Browser-validated in Chrome, Firefox, Safari
- [ ] All edge cases (empty portfolio, WS disconnect, stale data, MF-only) manually tested

## Dependencies & Prerequisites

| Dependency | Status | Required By |
|-----------|--------|-------------|
| Tiingo WebSocket infrastructure | **Already exists** (`ws/manager.py`, `ws/tiingo_bridge.py`) | Phase 3 |
| Tiingo REST provider | **Already exists** (`providers/tiingo_provider.py`) | Phase 3 |
| Frontend WS client | **Already exists** (`market-data.svelte.ts`) | Phase 3 |
| `TIINGO_API_KEY` env var | **Already configured** (`settings.py` line 77) | Phase 3 |
| `@idempotent` decorator | **Already exists** (`core/runtime/`) | Phase 1 |
| `RateLimitedBroadcaster` | **Already exists** (`core/runtime/broadcaster.py`) | Phase 3 |
| `lightweight-charts` npm package | **Not installed** | Phase 3 |
| Migration 0108 (OMS hardening) | **Not created** | Phase 1 |
| Trade tickets GET endpoint | **Not created** | Phase 5 |

## Risk Analysis & Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| lightweight-charts SSR crash | High (certain if not handled) | Blocks page load | Dynamic `import()` in `onMount` — proven pattern |
| WS connection exhaustion (64 cap) | Low (< 50 concurrent users) | Some users can't connect | Monitor via `ws_manager.connection_count`, alert at 80% |
| Tiingo IEX doesn't cover MFs/crypto | Known | No live prices for some instruments | "EOD" badge, daily bars from `nav_timeseries` |
| Accidental trade execution | Medium | Financial/compliance risk | Confirmation dialog + idempotency + optimistic lock |
| Chart ticker accumulation on switch | Medium | Bandwidth waste, visual corruption | `$effect` cleanup: unsubscribe old, subscribe new |
| JWT expiry kills terminal | High (certain after session timeout) | PM loses all state | `getToken()` refresh on reconnect, Clerk auto-refreshes |
| 409 race on concurrent execution | Low | Confusing UX | Clear error modal with refresh button |

## Component Inventory

### Created

| Component | Zone | Lines (est.) |
|-----------|------|-------------|
| `TerminalPriceChart.svelte` | Chart | ~180 |
| `TerminalTickerStrip.svelte` | Header | ~150 |
| `PortfolioDropdown.svelte` | Header | ~120 |
| `TerminalOmsPanel.svelte` | Right | ~400 |
| `TerminalBlotter.svelte` | Bottom | ~300 |

### Deleted

| Component | Reason |
|-----------|--------|
| `WorkbenchToolRibbon.svelte` | No tool switching in terminal |
| `LivePortfolioSidebar.svelte` | Replaced by PortfolioDropdown |
| `LivePortfolioKpiStrip.svelte` | Absorbed into header inline |
| `LiveAllocationsTable.svelte` | Absorbed into TerminalBlotter |
| `WorkbenchCoreChart.svelte` | Replaced by TerminalPriceChart |

### Refactored

| Component | Change |
|-----------|--------|
| `LiveWorkbenchShell.svelte` | WorkbenchLayout → CSS Grid, tool routing → all-visible |
| `RebalanceSuggestionPanel.svelte` | Logic extracted into TerminalOmsPanel, file deleted |
| `workbench-state.ts` | Remove tool union, keep portfolio URL helper |

### Unchanged

| Component | Note |
|-----------|------|
| `WeightVectorTable.svelte` | Still used by `/portfolio/advanced`, removed from live imports |
| `LivePricePoller` | Kept as fallback mock, replaced by real WS in production |

## Execution Order & Parallelization

```
Phase 1 (Backend Hardening)  ←── no dependencies, start immediately
    │
    ├──→ Phase 2 (Grid Shell)  ←── no backend dependency
    │        │
    │        ├──→ Phase 3 (Chart + WS)  ←── needs grid zones + lightweight-charts install
    │        │
    │        ├──→ Phase 4 (Header + Dropdown)  ←── needs grid header zone
    │        │
    │        └──→ Phase 5 (OMS + Blotter)  ←── needs grid zones + Phase 1 endpoints
    │
    └──→ Phase 6 (Polish)  ←── needs all above
```

**Recommended sequence:** Phase 1 → Phase 2 → Phase 3 + Phase 4 + Phase 5 (parallel) → Phase 6

Phase 1 is backend-only (migration + endpoint hardening). Phase 2 is the critical frontend foundation. Phases 3/4/5 are independent frontend work that can run in parallel after Phase 2.

## ERD — New/Modified Tables

```mermaid
erDiagram
    trade_tickets {
        uuid id PK
        uuid portfolio_id FK
        uuid organization_id
        uuid instrument_id FK
        varchar action "BUY | SELL"
        numeric delta_weight
        timestamptz executed_at
        uuid executed_by FK
        varchar execution_venue "NULL (dormant broker slot)"
        varchar fill_status "simulated | pending | filled | partial | rejected"
        int holdings_version "version at time of execution"
    }

    portfolio_actual_holdings {
        uuid portfolio_id PK_FK
        uuid organization_id
        int holdings_version "incremented on each execute-trades"
        jsonb holdings
        timestamptz last_rebalanced_at
    }

    trade_tickets }o--|| model_portfolios : "portfolio_id"
```

## Documentation Plan

| Document | Update Required |
|----------|----------------|
| `CLAUDE.md` — Worker table | Add note that `live_price_poll` worker (lock 900_100) is superseded by Tiingo WS bridge for terminal route |
| `CLAUDE.md` — Critical Rules | Add: "Terminal route uses lightweight-charts (not ECharts)" |
| `docs/reference/wealth-charting-tech-debt.md` | Rule 9.1 already updated (2026-04-09) |
| `docs/reference/market-data-provider-reference.md` | Add terminal WebSocket consumption pattern |

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-04-09-terminal-live-workspace-brainstorm.md](docs/brainstorms/2026-04-09-terminal-live-workspace-brainstorm.md) — Key decisions carried forward: D1 (lightweight-charts), D4 (WS proxy), D7 (4-zone grid), D6 (simulated execution pre-wired for broker)

### Internal References

- WebSocket manager: `backend/app/core/ws/manager.py`
- Tiingo bridge: `backend/app/core/ws/tiingo_bridge.py`
- WS auth: `backend/app/core/ws/auth.py`
- Market data routes: `backend/app/domains/wealth/routes/market_data.py`
- Tiingo REST provider: `backend/app/services/providers/tiingo_provider.py`
- Frontend WS client: `frontends/wealth/src/lib/stores/market-data.svelte.ts`
- Stability guardrails: `docs/reference/stability-guardrails.md`
- Charting tech debt: `docs/reference/wealth-charting-tech-debt.md`
- Market data reference: `docs/reference/market-data-provider-reference.md`
- Svelte performance: `docs/reference/svelte-performance-reactivity-reference.md` (section 10)

### SpecFlow Gaps Addressed

All 15 gaps from SpecFlow analysis addressed in this plan:
- WS-1 (terminal store access) → Phase 2, WS Client Strategy section
- WS-2 (ticker accumulation) → Phase 3, `$effect` cleanup
- WS-3 (token refresh) → Phase 6, edge cases
- DM-1 (trade history endpoint) → Phase 1
- DM-2 (execution_venue/fill_status) → Phase 1 migration
- DM-3 (idempotency) → Phase 1
- DM-4 (optimistic locking) → Phase 1
- CH-1 (chart data source) → Chart Data Source section
- CH-2 (chart cleanup on switch) → Phase 3
- TL-1 (4-zone vs tabs) → Phase 2 (4-zone, ribbon deleted)
- TL-2 (sidebar elimination) → Phase 4 (PortfolioDropdown)
- EX-1 (confirmation dialog) → Phase 5
- EX-2 (stale drift) → Phase 1 (optimistic lock)
- EX-3 (role guard) → Phase 1
- PR-1 (print in trade log view) → Phase 6

---

## Deepened Research Insights

### lightweight-charts: Use v5, Not v4

Research discovered that **lightweight-charts v5** is the current stable version (released late 2024). The plan should target `"lightweight-charts": "^5.0.0"` instead of `^4.2.0`.

**v5 advantages over v4:**
- **Native multi-pane** via `chart.addPane({ height: 80 })` — volume histogram gets its own pane instead of overlay hack
- **16% smaller bundle** (~35KB gzipped vs ~45KB)
- **Better tree-shaking** — series types are named imports: `import { BaselineSeries, CandlestickSeries, HistogramSeries } from 'lightweight-charts'`
- **ES2020 only** (no CommonJS) — aligns with SvelteKit's Vite ESM pipeline
- **v5 API change:** `chart.addSeries(BaselineSeries, options)` replaces `chart.addBaselineSeries(options)`

**Critical implementation pattern — split `$effect` into two paths:**

```typescript
// HISTORICAL: runs on ticker/range change (infrequent)
$effect(() => {
  if (!series) return;
  series.setData(historicalToBaselineData(historicalBars)); // O(n), acceptable on range change
  chart?.timeScale().fitContent();
});

// LIVE: runs on tick buffer flush (4x/sec) — O(1)
$effect(() => {
  if (!series || ticks.length === 0) return;
  const latest = ticks[ticks.length - 1];
  series.update({ time: Math.floor(latest.ts / 1000) as UTCTimestamp, value: latest.price });
  // NO fitContent() here — preserves user's scroll/zoom position
});
```

**Never call `series.setData()` on every tick.** Official TradingView docs explicitly warn against this.

### Svelte 5 Lifecycle: Async onMount + Canvas

Two blockers discovered by the Svelte 5 agent:

**1. `chart` and `series` must be `$state`, not plain `let`:**

The `$effect` that calls `series.update()` runs during component initialization, before `onMount` completes the async `import("lightweight-charts")`. If `series` is a plain `let`, Svelte 5 does not track it — the effect runs once with `series === null`, returns early, and never re-triggers when `series` is assigned inside `onMount`.

```typescript
// WRONG: $effect won't re-trigger when series is assigned
let series = null;

// CORRECT: $effect tracks $state and re-runs when assigned
let series = $state<ISeriesApi<'Baseline'> | null>(null);
```

**2. Use `disposed` flag for async cleanup safety:**

```typescript
onMount(() => {
  let disposed = false;
  (async () => {
    const lwc = await import("lightweight-charts");
    if (disposed || !containerEl) return; // Guard: component may have unmounted during await
    chart = lwc.createChart(containerEl, { ... });
    series = chart.addSeries(lwc.BaselineSeries, { ... });
  })();
  return () => {
    disposed = true;
    try { chart?.remove(); } catch {} // Container may already be gone
    chart = null;
    series = null;
  };
});
```

### Security Hardening (Pre-Phase 1)

The security sentinel found 2 CRITICAL issues that should be fixed **before or alongside Phase 1**:

**1. SQL injection in `market_data.py` (lines 238-282):**
```python
# CURRENT (vulnerable):
placeholders = ", ".join(f"'{iid}'" for iid in instrument_ids)
query = text(f"... WHERE instrument_id::text IN ({placeholders}) ...")

# FIX (parameterized):
query = text("... WHERE instrument_id = ANY(:ids)")
result = await db.execute(query, {"ids": instrument_ids})
```

**2. Per-org WebSocket connection limit (add to ConnectionManager):**
- Track `_org_counts: dict[uuid.UUID, int]` in `ConnectionManager`
- Enforce ceiling of 16 connections per org in `accept()`
- Return WS close code 1013 ("Try Again Later") when exceeded

**3. Terminal route RBAC (add to Phase 2):**
- Create `(terminal)/+layout.server.ts` that checks actor role
- Redirect non-INVESTMENT_TEAM/ADMIN users to `/portfolio`

**4. Ticker subscription validation (add to WS endpoint):**
- Validate format: `re.match(r'^[A-Z0-9.\-]{1,12}$', ticker)`
- Cap per-connection: 200 tickers max
- Cap per-subscribe message: 50 tickers max

### Performance Optimizations

Three backend optimizations discovered by the performance oracle:

**1. Remove legacy `market:prices` global channel:**
Every tick is dual-published to `market:prices:{TICKER}` AND `market:prices`. The legacy `redis_subscriber` consumes the global channel but routes to an empty subscriber set. Remove `pipe.publish("market:prices", payload)` from `publish_price_ticks_batch()` and kill the `redis_subscriber` task. Saves 2x Redis PUBLISH commands per tick.

**2. Subscription reconciliation in TiingoStreamBridge:**
Tiingo IEX WS has no per-ticker unsubscribe. After portfolio switches, stale tickers accumulate. Add a periodic check (every 60s): if stale tickers exceed 50% of active demand, close and reconnect WS with current demand set only.

**3. Raise `BroadcasterConfig.max_connections` to 128:**
With two MarketDataStore instances (dashboard + terminal), each user consumes 2 WS connections. At the current 64-client cap, 32 concurrent users hits the ceiling. Raise to 128 for the terminal use case.

### Data Integrity Refinements

From the data-integrity-guardian review:

- **`holdings_version` goes on `portfolio_actual_holdings`**, not `model_portfolios` — keeps the version check and data mutation on the same row, eliminating TOCTOU race window
- **`fill_status` is `NOT NULL DEFAULT 'simulated'`** (not nullable) — every ticket must have a known status
- **VARCHAR + CHECK constraint** (not PostgreSQL ENUM) — aligns with codebase convention, allows transactional migration for new values
- **No unique constraint on `(portfolio_id, instrument_id, executed_at)`** — would reject legitimate multi-leg trades in same batch
- **Pagination tiebreaker:** `ORDER BY executed_at DESC, id DESC` for stable ordering within same-timestamp batches
- **`SELECT ... FOR UPDATE` on holdings row** is essential even with optimistic locking — serializes concurrent requests before they waste INSERT work on trade tickets that will be rolled back
- **Consider Decimal for weight arithmetic** — current float addition in JSONB is lossy; optimistic locking makes drift more visible over many trades

### Confirmation Dialog Architecture

The Svelte 5 agent recommends a **separate component** (`TradeConfirmationDialog.svelte`), not a snippet:

- Needs own `$state` for open/close, loading during POST, error handling for 409/403
- Precedent: existing `TransitionConfirmDialog.svelte` is standalone
- Use shadcn-svelte `Dialog` from `@investintell/ui` or native `<dialog>` with `showModal()`
- Props: `open: boolean`, `tickets: TradeTicket[]`, `turnover: number`, `portfolioName: string`, `onConfirm`, `onCancel`

### Print Mode for Canvas Charts

lightweight-charts renders to `<canvas>`, which does not print natively in all browsers:

```typescript
// Swap canvas for static image on print
window.addEventListener('beforeprint', () => {
  const canvas = chart.takeScreenshot();
  const img = document.createElement('img');
  img.src = canvas.toDataURL('image/png');
  img.style.width = '100%';
  container.style.display = 'none';
  container.parentElement?.appendChild(img);
});
window.addEventListener('afterprint', () => {
  img.remove();
  container.style.display = '';
});
```

### WebSocket Token Refresh for Long Sessions

Terminal sessions can run 8+ hours. Clerk JWTs expire in 5-60 minutes. The existing `MarketDataStore` calls `getToken()` on reconnect, which triggers Clerk's `getSession()` auto-refresh. This works IF the Clerk session itself has not expired.

For additional safety, consider adding an in-band `refresh_token` WS message type:
- Frontend sends `{"action": "refresh_token", "token": "<fresh-jwt>"}` proactively (30s before expiry)
- Backend validates new JWT, updates actor on connection, responds `{"type": "token_refreshed"}`
- Avoids the 1008 close → reconnect cycle entirely
