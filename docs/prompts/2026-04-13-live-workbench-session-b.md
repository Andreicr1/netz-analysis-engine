# Phase 5 Live Workbench — Session B: Rebalance FocusMode + Trade Execution

## Context

Live Workbench Session A (PR #134) + layout fix (PR #135) delivered a 3-column
trading terminal with Watchlist, Chart (lightweight-charts + Tiingo WS), Holdings
Table, Portfolio Summary, News Feed, Macro Regime Panel, and Trade Log.

The PortfolioSummary currently has a "REBALANCE" button that shows a stub alert.
This session makes it functional: RebalanceFocusMode with trade proposals, impact
analysis, and trade execution.

**Backend infrastructure (ALL VERIFIED — exists and is functional):**
- `POST /model-portfolios/{id}/rebalance/preview` → `SuggestedTrade[]` + turnover + CVaR
- `POST /model-portfolios/{id}/execute-trades` → `TradeTicket[]` + optimistic lock
- `GET /model-portfolios/{id}/actual-holdings` → current holdings state
- `GET /model-portfolios/{id}/trade-tickets` → paginated trade history
- `TradeTicket` model (append-only log, org-scoped, RLS)
- `PortfolioActualHoldings` model (mutable JSONB, optimistic lock via holdings_version)

## Sanitization

| Internal term | Terminal label |
|---|---|
| CVaR 95 | Tail Loss (95% confidence) |
| cvar_warning | Risk limit approaching |
| estimated_turnover_pct | Turnover |
| delta_weight | Weight Change |
| fill_status: "simulated" | Simulated |

## MANDATORY: Read these files FIRST

### Backend (verify schemas/signatures)
1. `backend/app/domains/wealth/routes/model_portfolios.py` — search for "rebalance/preview", "execute-trades", "actual-holdings", "trade-tickets". Read the request/response schemas.
2. `backend/app/domains/wealth/schemas/shadow_oms.py` — SuggestedTrade, ExecuteTradesRequest, ExecuteTradesResponse, TradeTicketResponse, RebalancePreviewResponse, ActualHoldingsResponse schemas
3. `backend/app/domains/wealth/models/shadow_oms.py` — TradeTicket, PortfolioActualHoldings models

### Frontend (extend these)
4. `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte` — current page (wire rebalance button)
5. `frontends/wealth/src/lib/components/terminal/live/PortfolioSummary.svelte` — has REBALANCE button stub
6. `frontends/wealth/src/lib/components/terminal/live/TradeLog.svelte` — will refresh after trade execution
7. `frontends/wealth/src/lib/components/terminal/live/HoldingsTable.svelte` — will update with actual weights after execution

### Primitives (reuse patterns)
8. `frontends/wealth/src/lib/components/terminal/focus-mode/FocusMode.svelte` — generic FocusMode primitive (if it exists). If not, read the Builder's ConsequenceDialog pattern for modal overlay.
9. `frontends/wealth/src/lib/components/terminal/builder/ConsequenceDialog.svelte` — reference for typed confirmation + focus trap pattern
10. `packages/investintell-ui/src/lib/tokens/terminal.css` — terminal tokens

## ARCHITECTURE RULES

- Svelte 5 runes only. All formatters from `@investintell/ui`. Zero hex values.
- Terminal tokens exclusively. Monospace, hairline borders, zero radius.
- No localStorage. No new npm packages.
- FocusMode for rebalance (full-screen overlay, NOT drawer, NOT inline expansion).
- URL state: `?rebalance=open` added when FocusMode is open, removed on close.
- Idempotent: the "Submit Proposal" button must disable on click and prevent double-submit.
- Optimistic lock: `execute-trades` requires `expected_version` matching `holdings_version`.

## DELIVERABLES (4 items)

### 1. RebalanceFocusMode: `frontends/wealth/src/lib/components/terminal/live/RebalanceFocusMode.svelte`

Full-screen overlay (95vw x 95vh, dark scrim, focus trap, ESC closes).
Uses URL state `?rebalance=open` for reload safety.

**Layout inside FocusMode (2-column, 50/50):**

```
┌──── [ REBALANCE ] // PORTFOLIO NAME // 2026-04-13 ─── [ ESC · CLOSE ] ────┐
│                                                                              │
│  ┌──── PROPOSED TRADES ──────────────┐  ┌──── IMPACT ANALYSIS ──────────┐  │
│  │ FUND       ACTION  CURRENT TARGET │  │                               │  │
│  │ ──────────────────────────────────  │  │  Turnover        12.4%       │  │
│  │ VGSH       BUY     14.8%   15.0%  │  │  Tail Loss (95%) 8.2%        │  │
│  │ VCIT       SELL    26.2%   25.0%  │  │  Risk Warning    No           │  │
│  │ VTIP       BUY      9.1%   10.0%  │  │  Trades          5            │  │
│  │ BND        HOLD    20.0%   20.0%  │  │                               │  │
│  │ CASH       SELL     9.9%    5.0%  │  │  ─── TRADE VALUES ───        │  │
│  │ ──────────────────────────────────  │  │  Total BUY       $1.24M     │  │
│  │ 5 trades (3 BUY, 2 SELL, 0 HOLD)  │  │  Total SELL       $892K     │  │
│  │                                    │  │  Net Flow         $348K      │  │
│  └────────────────────────────────────┘  └───────────────────────────────┘  │
│                                                                              │
│  ┌──── CONFIRMATION ───────────────────────────────────────────────────┐    │
│  │  This will generate trade orders for the active portfolio.          │    │
│  │  Execution is simulated — no real broker orders will be placed.     │    │
│  │                                                                     │    │
│  │  [ CANCEL ]                                 [ SUBMIT PROPOSAL ]     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Data flow:**
1. On open: call `POST /model-portfolios/{id}/rebalance/preview` with current holdings
2. Display `SuggestedTrade[]` in the left table (sorted by |delta_weight| desc)
3. Display `RebalancePreviewResponse` metrics in the right panel (turnover, CVaR, warning)
4. PM reviews and clicks "Submit Proposal"
5. Before submit: show ConsequenceDialog-style confirmation (no typed ACTIVATE needed —
   simpler than portfolio activation. Just a "Are you sure?" with Cancel/Confirm.)
6. On confirm: call `POST /model-portfolios/{id}/execute-trades` with the trade tickets
7. On success: close FocusMode, refresh TradeLog + HoldingsTable, show success toast
8. On error (409 version conflict): show "Portfolio was modified by another user. Refresh and retry."

**Proposed Trades table columns:**
| Fund | Ticker | Action | Current | Target | Delta | Trade Value |
- Action: BUY badge (green bg), SELL badge (red bg), HOLD badge (muted bg)
- Delta: `formatPercent`, color-coded
- Trade Value: `formatCurrency`, estimated from AUM * delta_weight

**Impact Analysis panel:**
- Turnover: `formatPercent` — amber if > 10%, red if > 20%
- Tail Loss: `formatPercent` — with "Risk limit approaching" warning if `cvar_warning` is true
- Trade count: number
- Total BUY/SELL/Net: `formatCurrency`

**Keyboard:** ESC closes. Tab trap inside modal. Enter on "Submit Proposal" if focused.

**Loading state:** While `rebalance/preview` is fetching, show a terminal-style loading
indicator (pulsing "COMPUTING REBALANCE..." text, not a spinner).

### 2. Wire REBALANCE button in PortfolioSummary

In `PortfolioSummary.svelte`, replace the stub alert with actual navigation:

```typescript
function handleRebalance() {
    // Add ?rebalance=open to URL
    const params = new URLSearchParams(page.url.searchParams);
    params.set("rebalance", "open");
    goto(`/portfolio/live?${params.toString()}`, { replaceState: true });
}
```

In `+page.svelte`, conditionally render RebalanceFocusMode based on URL:

```typescript
const showRebalance = $derived(page.url.searchParams.get("rebalance") === "open");

function handleRebalanceClose() {
    const params = new URLSearchParams(page.url.searchParams);
    params.delete("rebalance");
    goto(`/portfolio/live?${params.toString()}`, { replaceState: true });
}
```

### 3. Post-execution refresh

After `execute-trades` succeeds:
1. **TradeLog** must refresh — re-fetch `GET /trade-tickets` to show new entries
2. **HoldingsTable** must update — re-fetch `GET /actual-holdings` to reflect new weights
3. **PortfolioSummary** drift status may change (fewer breaches after rebalance)

Implement this via a callback chain: RebalanceFocusMode `onsuccess` → parent page
re-fetches holdings + trade tickets. Use `$effect` dependencies or explicit `refetch()` methods.

### 4. Trade execution confirmation

Before calling `execute-trades`, show a simple confirmation overlay (NOT the full
ConsequenceDialog with typed ACTIVATE — this is less consequential than activation):

```
┌────────────────────────────────────────┐
│  Execute 5 trades?                     │
│                                        │
│  3 BUY orders, 2 SELL orders           │
│  Estimated turnover: 12.4%             │
│  Execution: Simulated                  │
│                                        │
│  [ Cancel ]          [ Execute ]       │
└────────────────────────────────────────┘
```

Simple modal, ESC closes, Enter confirms. Amber "Execute" button.
After execution, show result status (success count, any failures).

## FILE STRUCTURE

```
frontends/wealth/src/
  routes/(terminal)/portfolio/live/
    +page.svelte                          ← MODIFY: wire RebalanceFocusMode + URL state
  lib/components/terminal/live/
    RebalanceFocusMode.svelte             ← NEW: full-screen rebalance overlay
    TradeConfirmation.svelte              ← NEW: simple execution confirmation
    PortfolioSummary.svelte               ← MODIFY: wire REBALANCE button to URL
```

## GATE CRITERIA

1. REBALANCE button in PortfolioSummary opens RebalanceFocusMode
2. URL shows `?rebalance=open` when FocusMode is active (reload-safe)
3. RebalanceFocusMode calls `POST /rebalance/preview` and displays trade proposals
4. Trade table shows BUY/SELL/HOLD badges with correct color coding
5. Impact panel shows turnover, tail loss, risk warning
6. "Submit Proposal" opens TradeConfirmation dialog
7. Confirming executes `POST /execute-trades` with correct payload
8. After execution: TradeLog refreshes, HoldingsTable updates, FocusMode closes
9. 409 version conflict shows meaningful error message
10. ESC closes FocusMode, URL cleaned
11. Zero hex colors, zero `.toFixed()`, all terminal tokens
12. `svelte-check` — zero errors
13. `pnpm build` — clean

## What NOT to do

- Do NOT modify NewsFeed, MacroRegimePanel, Watchlist, ChartToolbar, or chart components
- Do NOT create real broker integration — all trades are `fill_status="simulated"`
- Do NOT require typed "ACTIVATE" confirmation — simple Cancel/Execute is sufficient
- Do NOT install new packages
- Do NOT use hex colors
- Do NOT hardcode trade data — wire to real backend endpoints

## COMMIT

```
feat(live): Session B — rebalance FocusMode + trade execution flow

Full-screen RebalanceFocusMode with trade proposals from POST /rebalance/preview,
impact analysis (turnover, tail loss, risk warning), and trade execution via
POST /execute-trades with optimistic lock. URL state ?rebalance=open for reload
safety. Post-execution refresh of TradeLog + HoldingsTable.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Push to origin/feat/live-workbench-session-b.
