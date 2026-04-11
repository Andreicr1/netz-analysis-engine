---
date: 2026-04-09
topic: terminal-live-workspace
---

# Terminal-Grade Live Workspace ("Brutalismo Financeiro")

## What We're Building

A Bloomberg/FactSet-grade execution terminal at `(terminal)/portfolio/live` that replaces the current "web app" aesthetic with extreme information density, real-time data via Tiingo API, and TradingView lightweight-charts for financial charting. The terminal is the heart of Phase 4 (Circulatory System) of the wealth investment lifecycle -- where PMs monitor live portfolios, detect drift, and execute rebalancing.

## Why This Approach

The current Live route uses ECharts (analytics-grade) with web-app spacing and a 3-tool ribbon that hides information behind tabs. For an execution surface, this fails on two fronts: (1) density -- PMs need to see drift, positions, orders, AND the chart simultaneously, and (2) real-time fidelity -- Yahoo Finance batch polling at 60s cadence is insufficient for monitoring. Tiingo provides institutional-grade WebSocket streaming with bid/ask/volume across all asset classes.

## Key Decisions

### D1: Charting Engine
**lightweight-charts (TradingView)** for the terminal. Rule 9.1 updated to permit lightweight-charts + more advanced engines in `(terminal)` route group. ECharts/LayerChart remain for analytics routes (Builder, Screener, Dashboard). Rationale: 45KB WebGL, native candlestick/baseline, magnetic crosshair, purpose-built for real-time financial data.

### D2: Data Provider
**Tiingo API** replaces Yahoo Finance for the terminal. Coverage: 85k+ tickers (stocks, ETFs, mutual funds), 2100+ crypto, 140+ forex pairs. WebSocket real-time streaming (`wss://api.tiingo.com/iex`). REST for historical OHLCV with intraday granularity (1min-1hour). Auth: `Authorization: Token KEY` header. Env var: `TIINGO_API_KEY`.

### D3: Terminal Scope (Phased)
**Phase (a):** Portfolio execution monitor -- PM selects a constructed portfolio, monitors drift, executes rebalance. Tiingo provides real-time prices for portfolio instruments. **Phase (b) future:** Generalist market terminal -- any Tiingo ticker searchable independently, research station for individual assets. Phase (a) first as solid base, (b) as extension with new routes in `(terminal)/`.

### D4: Real-Time Architecture
**Backend WebSocket proxy.** The backend connects to Tiingo WebSocket and exposes `wss://api.investintell.com/terminal/feed` to the frontend. API key stays server-side (secure). Latency ~50ms. Frontend subscribes to tickers via the proxy. Pattern: FastAPI WebSocket endpoint → Tiingo WebSocket upstream → Redis pub/sub for fan-out → client WebSocket downstream.

### D5: Asset Class Scope
**All asset classes from day one.** The WebSocket proxy is asset-class agnostic -- it subscribes to whatever Tiingo accepts. Stocks, ETFs, mutual funds, crypto, forex all work. Formatters adapt: crypto gets 8 decimal places, forex gets pip notation, equities get standard 2-4 decimals. This future-proofs the Phase (b) expansion without rework.

### D6: Trade Execution Model
**Simulated now, pre-wired for real broker.** "Execute" updates portfolio weights in DB and zeros drift (current behavior). The `TerminalOmsPanel` architecture includes dormant slots for: (i) broker selection dropdown, (ii) order routing config, (iii) fill confirmation panel, (iv) partial fill tracking. These render as disabled/hidden until a broker adapter exists. Data model includes `execution_venue` and `fill_status` fields (nullable). Trade sheet print continues to work for manual execution via external broker.

### D7: Layout Architecture
**4-zone CSS Grid, zero scroll.** Sidebar eliminated (portfolio dropdown in header). Tool ribbon eliminated (all panels visible simultaneously, Bloomberg style).

```
grid-template: 44px 1fr 35vh / 1fr 340px;
areas: "header header" / "chart oms" / "blotter blotter"
```

### D8: Design Language
- Background: `#000000` / `#05080f`
- Borders: `border-white/10`, zero or 1px border-radius
- Numbers: system `font-mono` stack, `font-variant-numeric: tabular-nums`
- Padding: `p-1` / `p-2` maximum
- Font sizes: 11px body, 9px labels, 28-32px last price
- Colors: green up / red down via `--ii-success` / `--ii-danger` tokens

### D9: Components That Survive vs Die

**Eliminated:**
- `LivePortfolioSidebar.svelte` → dropdown in header
- `WorkbenchToolRibbon.svelte` → deleted (no tool switching)
- `LivePortfolioKpiStrip.svelte` → absorbed into header inline
- `LiveAllocationsTable.svelte` → absorbed into blotter
- `WorkbenchLayout` import → custom CSS Grid

**Refactored:**
- `RebalanceSuggestionPanel.svelte` → `TerminalOmsPanel.svelte` (same logic, terminal density, broker slots)
- `WorkbenchCoreChart.svelte` → `TerminalPriceChart.svelte` (lightweight-charts, Tiingo data)
- `WeightVectorTable.svelte` → merged into `TerminalBlotter.svelte`

**Unchanged:**
- `LivePricePoller` → kept as mock fallback, but real data comes via WebSocket proxy
- `+page.server.ts` → minimal changes (still loads portfolio list)

## Execution Phases

| Phase | Scope | Depends On |
|-------|-------|------------|
| **A** | CSS Grid shell, terminal tokens, eliminate sidebar/ribbon | Nothing |
| **B** | lightweight-charts component + Tiingo backend (WebSocket proxy, REST service) | Phase A for frontend, independent for backend |
| **C** | Terminal header (ticker strip, portfolio dropdown, inline KPIs) | Phase A |
| **D** | OMS panel (terminal density, broker slots pre-wired) | Phase A |
| **E** | Bottom blotter (positions/trade log toggle, merged drift+allocations) | Phase A |
| **F** | Polish (print, responsive, accessibility, edge cases) | All above |

Phases B/C/D/E are parallelizable after A. Backend work (Tiingo service, WebSocket proxy) can start in parallel with Phase A.

## Backend Work Required

| Component | File | Description |
|-----------|------|-------------|
| `TiingoService` | `backend/app/services/tiingo_client.py` | Async httpx client for REST endpoints (EOD, IEX, crypto, forex). Ticker search/autocomplete against cached `supported_tickers.zip`. |
| WebSocket proxy | `backend/app/domains/wealth/routes/terminal_ws.py` | FastAPI WebSocket endpoint. Upstream: Tiingo IEX/Crypto/FX WebSocket. Downstream: client WebSocket with ticker subscription. Redis pub/sub for multi-client fan-out. |
| `TIINGO_API_KEY` | `.env`, Railway secrets | New env var. |
| Ticker search endpoint | `GET /api/v1/terminal/search?q=&asset_type=` | Autocomplete against Tiingo ticker catalog. Returns ticker, name, exchange, asset type. |

## Open Questions

- **Tiingo tier:** Power ($10/mo) gives 5k req/hour. Sufficient for Phase (a) with <50 concurrent users. Need Commercial tier for Phase (b) at scale?
- **WebSocket reconnection:** Tiingo WebSocket drops connections periodically. Backend proxy needs exponential backoff + heartbeat monitoring. Pattern from existing SSE workers?
- **Historical depth for chart ranges:** 1W/1M/3M range buttons need historical data. Tiingo IEX gives max 2000 intraday points. For 3M daily, use EOD endpoint. Seamless stitching needed?
- **Crypto formatting:** 8 decimal places for BTC, 2 for stablecoins. Need asset-class-aware formatter or just use Tiingo's `priceCurrency` metadata?

## Next Steps

→ `/ce:plan` for implementation details (file-level changes, code patterns, test strategy)
