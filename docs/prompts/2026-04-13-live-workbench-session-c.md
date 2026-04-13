# Phase 5 Live Workbench — Session C: Drift Monitor + Alerts Inbox

## Context

Live Workbench Sessions A (PR #134) + layout fix (#135) + Session B (#136) delivered:
3-column trading terminal, real-time charts, watchlist, holdings, news feed, macro regime,
trade execution via RebalanceFocusMode. Phase 5 is nearly complete.

This session adds the final two pieces: a proper DriftMonitorPanel inside the Live
Workbench and a global `/alerts` inbox route (TopNav ALERTS tab activation).

**Backend infrastructure to verify:**
- `drift_check` worker (lock 42) — writes to `strategy_drift_alerts` table
- `portfolio_alerts` model/table — may or may not have data
- Alert routes — check if `GET /alerts` or `/alerts/inbox` exists
- Drift routes — check if `GET /model-portfolios/{id}/drift` exists
- `alert_sweeper` worker (lock 900_102) — may not exist yet

## Sanitization

| Internal term | Terminal label |
|---|---|
| DTW drift / dtw_distance | Strategy Drift |
| drift_score | Drift Score |
| drift_type: style_drift | Style drift detected |
| drift_type: tracking_error | Tracking divergence |
| REGIME_RISK_ON / RISK_OFF | Expansion / Defensive |

## MANDATORY: Read these files FIRST

### Backend (verify what exists)
1. `backend/app/domains/wealth/routes/` — search ALL route files for "alert", "drift", "inbox"
2. `backend/app/domains/wealth/models/` — search for "Alert", "Drift", "portfolio_alerts"
3. `backend/app/domains/wealth/workers/drift_check.py` — understand what it writes
4. `backend/app/domains/wealth/routes/model_portfolios.py` — search for "drift", "alerts"
5. `backend/app/domains/wealth/schemas/` — search for alert/drift schemas

### Frontend
6. `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte` — current live page
7. `frontends/wealth/src/lib/components/terminal/live/PortfolioSummary.svelte` — drift status display
8. `frontends/wealth/src/lib/components/terminal/shell/TerminalTopNav.svelte` — ALERTS tab is PENDING
9. `frontends/wealth/src/lib/components/terminal/shell/AlertTicker.svelte` — if exists, understand the global ticker
10. `packages/investintell-ui/src/lib/tokens/terminal.css` — terminal tokens

## ARCHITECTURE RULES

- Svelte 5 runes only. All formatters from `@investintell/ui`. Zero hex values.
- Terminal tokens exclusively. Monospace, hairline borders, zero radius.
- No localStorage. No new npm packages.
- SSE via `fetch()` + `ReadableStream` (if alert streaming is implemented).
- `<svelte:boundary>` on async-dependent sections.

## DELIVERABLES (5 items)

### 1. DriftMonitorPanel: `frontends/wealth/src/lib/components/terminal/live/DriftMonitorPanel.svelte`

Replaces the simple "Drift Status: Aligned" in PortfolioSummary with a dedicated panel.
Add it to the Live Workbench layout — either as a tab in the bottom area, or as a
collapsible panel above the holdings table. Read the current +page.svelte layout to
decide the best placement.

**Content: per-fund drift table**

```
┌ DRIFT MONITOR ─────────────────────────────────────────┐
│ FUND           TARGET   ACTUAL   DRIFT     STATUS      │
│ ───────────────────────────────────────────────────────│
│ VGSH           15.0%    14.8%    -0.2%     ● Aligned  │
│ VCIT           25.0%    23.2%    -1.8%     ◐ Watch    │
│ VTIP           10.0%    12.4%    +2.4%     ○ Breach   │
│ BND            20.0%    19.7%    -0.3%     ● Aligned  │
│ ───────────────────────────────────────────────────────│
│ PORTFOLIO: WATCH  (1 Watch, 1 Breach)  [REBALANCE →]  │
└────────────────────────────────────────────────────────┘
```

**Three drift states:**
- **Aligned** (|drift| < 2pp): green dot, `--terminal-status-success`
- **Watch** (|drift| 2-3pp): amber half-dot, `--terminal-status-warn`
- **Breach** (|drift| >= 3pp): red ring, `--terminal-status-error`

These thresholds may come from the backend drift_check worker config. Check what
thresholds it uses and mirror them. If configurable server-side, fetch from config.
Otherwise use 2pp/3pp as sensible defaults.

**Data source:** Compute drift from `actual-holdings` vs `fund_selection_schema.funds`.
The actual holdings are already loaded in the Live Workbench page. This is a pure
frontend derivation — no new endpoint needed.

**Footer:** Aggregate portfolio status (pessimistic: worst fund determines portfolio
status) + "[REBALANCE]" link that triggers the RebalanceFocusMode.

**If the actual-holdings endpoint returns fallback data (source: "target_fallback"),
show "All weights aligned to target — no actual holdings imported yet" instead.**

### 2. AlertStreamPanel: `frontends/wealth/src/lib/components/terminal/live/AlertStreamPanel.svelte`

Portfolio-scoped alert list in the Live Workbench. Placement: either replace or sit
alongside the DriftMonitorPanel in the right column, or as a tab.

**First: check if a portfolio alerts endpoint exists.** Search backend routes for:
- `GET /model-portfolios/{id}/alerts`
- `GET /alerts?portfolio_id={id}`
- `GET /portfolio-alerts`

**If an endpoint exists:** Fetch alerts for the selected portfolio and display.

**If NO endpoint exists:** Create the component with proper structure but show
"No alerts" empty state. Do NOT create backend routes in this session — that's
infrastructure work for a separate sprint.

**Visual (each alert, ~44px):**
```
  ⚠ WARN  14:32
  Fund VCIT drifting from target allocation (-1.8%)
  [ Acknowledge ]
```
- Severity badge: INFO (cyan), WARN (amber), CRIT (red)
- Timestamp: monospace, `--terminal-fg-tertiary`
- Message: `--terminal-fg-secondary`, 11px
- "Acknowledge" button: hairline border, on click marks as read (if endpoint exists)
- Scrollable, newest first, max 15 items visible

### 3. Alerts Inbox route: `frontends/wealth/src/routes/(terminal)/alerts/+page.svelte`

New terminal route at `/alerts`. Activates the ALERTS tab in TopNav.

**If alerts backend endpoint exists:** Build a full inbox with:
- Filter bar: severity (ALL/INFO/WARN/CRIT), portfolio dropdown, status (open/acknowledged)
- Alert list: rows with severity badge, portfolio name, message, timestamp, actions
- Keyboard: J/K scroll, E acknowledge, Enter open detail
- Empty state: "No alerts"

**If NO alerts backend endpoint exists:** Build a placeholder page with:
- TopNav ALERTS tab activated (no PENDING badge)
- Page content: "Alerts inbox — coming soon. Portfolio-scoped alerts are visible in the Live Workbench."
- This still delivers value by activating the tab and reserving the route.

### 4. Activate ALERTS tab in TopNav

In `TerminalTopNav.svelte`:
- Change alerts entry from `status: "pending"` to `status: "active"`
- Add `HREF_ALERTS = resolve("/alerts")`
- Add rendering block for the alerts tab (same pattern as BUILDER activation)
- Update `isHrefActive()` and `activePathSegment()`

### 5. Wire DriftMonitorPanel into Live Workbench

In `+page.svelte`, add the DriftMonitorPanel. Best placement options (choose based
on what looks right with the current grid):

**Option A:** Add as a panel between the chart and the holdings area (full width of center column, 120px fixed height). This pushes the chart up slightly.

**Option B:** Add as a sub-tab in the bottom-right area (next to or replacing TradeLog when portfolio has active drift).

**Option C:** Integrate drift data directly into the HoldingsTable by adding a "Status" column with Aligned/Watch/Breach badges (most compact, least additional UI).

Read the current layout and choose the option that best fits the 3-column grid without
overcrowding. If uncertain, go with Option C (least disruptive — just adds a column
to HoldingsTable).

## FILE STRUCTURE

```
frontends/wealth/src/
  routes/(terminal)/
    alerts/
      +page.svelte                         ← NEW: global alerts inbox
    portfolio/live/
      +page.svelte                         ← MODIFY: wire DriftMonitorPanel
  lib/components/terminal/
    live/
      DriftMonitorPanel.svelte             ← NEW: per-fund drift table
      AlertStreamPanel.svelte              ← NEW: portfolio-scoped alerts
    shell/
      TerminalTopNav.svelte                ← MODIFY: activate ALERTS tab
```

## GATE CRITERIA

1. DriftMonitorPanel shows per-fund drift with Aligned/Watch/Breach status
2. Drift thresholds produce correct color coding (green < 2pp, amber 2-3pp, red >= 3pp)
3. Portfolio aggregate drift status reflects worst fund
4. AlertStreamPanel renders (with data if endpoint exists, empty state if not)
5. `/alerts` route renders inside TerminalShell
6. TopNav ALERTS tab is active (no PENDING badge), highlights when on /alerts
7. Zero hex colors, all terminal tokens
8. `svelte-check` — zero errors
9. `pnpm build` — clean

## COMMIT

```
feat(live): Session C — drift monitor + alerts inbox route

DriftMonitorPanel with per-fund Aligned/Watch/Breach tri-state.
AlertStreamPanel for portfolio-scoped alerts (graceful empty state
if backend endpoint missing). Global /alerts route with TopNav
ALERTS tab activated. Completes Phase 5 Live Workbench.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Push to origin/feat/live-workbench-session-c.
