# Portfolio Vertical — Enterprise UX & Navigation Flow (Design Document)

> **Scope of this document:** UX, navigation, information architecture, state machines, and flow gates for the Portfolio vertical of Netz Wealth OS. This is ONE of five specialist sections — it does not cover DB migrations, component internals, chart specs, or quant engine wiring. Those are owned by parallel specialists and will be merged later.
>
> **Quality bar:** Discovery FCL plan (`docs/superpowers/plans/2026-04-07-discovery-fcl-analysis-page.md`). Read it first. Every pattern here either reuses Discovery primitives or justifies a deliberate divergence.
>
> **Philosophy anchor:** Smart backend, polished frontend. The quant engine (CLARABEL cascade, Black-Litterman, Ledoit-Wolf, regime-conditioned CVaR, GARCH, robust SOCP) is extraordinarily intelligent. The user never sees those words. They see: *proposed weights*, *binding rule*, *market conditions*, *expected risk-adjusted return*, *turnover vs current*. Jargon translation is not optional — it is the product.

---

## 0. Context Snapshot (what exists today, 2026-04-08)

**Frontend (`frontends/wealth/src/routes/(app)/portfolio/`):**
- `/portfolio` — single FCL page, orchestrator (`+page.svelte`) with `FlexibleColumnLayout` from `@investintell/ui`. Left column toggles between Models / Universe / Policy sub-pills. Center = `BuilderColumn` (action bar + chart + allocation blocks with DnD). Right = `AnalyticsColumn` (placeholder, fund/portfolio/stress/compare tabs unfinished).
- `/portfolio/advanced` — legacy.
- `/portfolio/analytics` — legacy.
- `/portfolio/model` — legacy.
- Components: `BuilderColumn`, `BuilderTable`, `UniverseColumn`, `UniverseTable`, `UniversePanel`, `ModelListPanel`, `PolicyPanel`, `FactorAnalysisPanel`, `OverlapScannerPanel`, `PolicyPanel`, `RebalanceSimulationPanel`, `StressTestPanel`, `MainPortfolioChart`, `PortfolioOverview`.
- State store: `$lib/state/portfolio-workspace.svelte` (single source of truth, reset-on-entry rule).

**Backend (`backend/app/domains/wealth/routes/`):**
- `model_portfolios.py` — 21 endpoints (prefix `/model-portfolios`): create, list, get, patch, construct, stress, backtest, critic, policy, validate, promote, etc.
- `portfolios.py` — live portfolio surface (prefix `/portfolios`).
- `rebalancing.py` — rebalance proposals (prefix `/rebalancing`).
- `analytics.py`, `risk.py`, `monitoring.py`, `strategy_drift.py`, `attribution.py`, `correlation_regime.py`, `exposure.py`.
- Workers: `portfolio_nav_synthesizer` (lock 900_030), `portfolio_eval` (lock 900_008), `drift_check` (lock 42), `risk_calc` (lock 900_007), `global_risk_metrics` (lock 900_071).

**What works:** FCL scaffolding, universe table, DnD allocation blocks, construct endpoint call.

**Andrei's five complaints (anchored):**
1. Builder calibration is mock/real confused — sliders don't mutate state, stress scenarios are fake, "new portfolio" is placeholder.
2. Run Construct is opaque — no narrative, no binding constraints, no before/after metrics.
3. Allocation advisor invisible — no signal of what it does or whether it ran.
4. Approval → Live workflow non-existent — no states, no gates, no promotion.
5. Missing Live Workbench — no Bloomberg-style terminal for LIVE portfolios with alerts, strategic/tactical/effective views, live prices, charting.

---

## 1. Top-Level Navigation Map (locked)

The Portfolio vertical breaks into **three process phases**, each a standalone route with its own URL contract. This mirrors Andrei's mental model (Builder → Analytics → Live) and is orthogonal to Discovery.

### 1.1 URL contract

```
/portfolio                                → redirect to /portfolio/builder
/portfolio/builder                        → Phase 1: Construction workbench (FCL 3-col)
  ?models=list|draft|approved|archived    → left sub-pill state
  ?tab=models|universe|policy             → center-left tab
  ?draft={portfolio_id}                   → active draft being edited
  ?fund={external_id}                     → analytics drill-down (col3 open)
  ?view=fund|portfolio|stress|compare     → col3 content
  #construct-narrative                    → scroll to narrative output after run

/portfolio/builder/universe               → sub-pill: Approved Universe (governed list)
  ?status=pending|approved|rejected
  ?fund={external_id}

/portfolio/analytics                      → Phase 2: Analytical surface (mirrors Discovery Analysis)
  ?scope=models|universe|both             → dataset scope
  ?subject={portfolio_id|external_id}     → subject under analysis
  ?group=returns-risk|holdings|peer|stress
  ?window=1y|3y|5y|10y|max
  #dock                                   → bottom tab dock state (hash-encoded)

/portfolio/analytics/{subject_id}         → deep link to a specific subject
  # same query params as above

/portfolio/live                           → Phase 3: Live Workbench (terminal)
  ?portfolio={portfolio_id}               → active live portfolio
  ?panel=alerts|rebalance|calibration     → right-rail state
  ?chart=nav|drawdown|exposure|contrib    → center chart mode
  ?overlay=strategic|tactical|effective|all
```

**Rules:**
- No `localStorage`. All state is URL-driven + in-memory `portfolio-workspace.svelte` store + SSE. (memory: `feedback_echarts_no_localstorage.md`)
- Reset-on-entry rule from the current Builder spec is preserved: entering `/portfolio/builder` with no query params snaps to Estado B (2-col), col3 closed.
- `/portfolio/live` is a **separate page shell** from Builder/Analytics — it has its own layout cage overrides for terminal density (see §5).

### 1.2 TopNav integration

The global TopNav exposes the Portfolio vertical as a single entry (`Portfolio`) that, when active, reveals a **sub-nav ribbon** inside the content panel (under the TopNav bar, above the layout cage) with three phase pills:

```
[ Builder ]   [ Analytics ]   [ Live ]
  3 drafts      1 subject       2 active · 5 alerts
```

The badge on each pill is the count of meaningful context (drafts in progress, subjects being analyzed, live portfolios with open alerts). Badges are derived, never stored. This ribbon replaces the current `sub-pills` inside Builder's left column — sub-pills are now reserved for intra-phase navigation (Models/Universe/Policy *inside* Builder).

**Sub-nav ribbon is always present** when the user is anywhere under `/portfolio/*`. Clicking a pill does a client-side navigation that preserves the session (open drafts, open analyses) via the workspace store — the user never loses work switching phases.

---

## 2. Entry / Exit Points & Flow Gates

The full user journey from raw fund discovery to a live, monitored portfolio is a gated chain. Every gate is explicit in the UI (disabled state + tooltip reason) and in the state machine (§3).

### 2.1 Canonical flow

```
Discovery (external)
   ↓  [Open Analysis] navigates to /discovery/funds/{id}/analysis
Analytical review (DD Report, Fact Sheet, Quant Analysis)
   ↓  [Add to Universe] → POST instruments_org with approval_status=pending
Approved Universe (sub-pill in /portfolio/builder/universe)
   ↓  [Approve] (admin / senior analyst role) → approval_status=approved
Builder (/portfolio/builder) — approved funds only visible in universe panel
   ↓  DnD into allocation blocks + Run Construct
Constructed draft (state=constructed)
   ↓  [Validate Quant] → runs stress + critic + risk checks
Validated draft (state=validated)
   ↓  [Send for Approval] (4-eyes if policy requires)
Approved model portfolio (state=approved)
   ↓  [Go Live] → triggers portfolio_nav_synthesizer (lock 900_030)
Live portfolio (/portfolio/live) — receives alerts, rebalance suggestions
   ↓  [Pause] / [Rebalance] / [Archive]
```

### 2.2 Gate definitions

| Gate | Entry condition | Exit condition | UI affordance |
|------|-----------------|----------------|---------------|
| G1. Into Universe | Fund exists in `instruments_universe` | `InstrumentOrg` row created with `approval_status=pending` | Button "Add to Universe" on Discovery Analysis page + Fact Sheet |
| G2. Universe → Builder | `approval_status=approved` | Fund appears in Builder universe column | Universe sub-pill shows pending/approved/rejected tabs; Approve requires ADMIN or INVESTMENT_TEAM role |
| G3. Draft → Constructed | At least 1 allocation block with weights, policy attached | `construct` endpoint returns 200 with proposed weights | Big primary button "Run Construct" in BuilderColumn action bar, disabled with tooltip until blocks present |
| G4. Constructed → Validated | Construct succeeded | Stress passes + critic passes + no red risk flags | Button "Validate" opens validation panel (right rail); gate requires all 3 green checks |
| G5. Validated → Approved | Validated state | Approval recorded (self-approve if allowed, else 4-eyes second reviewer) | Button "Send for Approval"; creates approval request, shows "Awaiting second reviewer" badge |
| G6. Approved → Live | Approved state + no other live version of same portfolio_id | `portfolio_nav_synthesizer` activated | "Go Live" CTA in Analytics subject detail page, modal confirming prerequisites |
| G7. Live → Paused/Archived | Live state | Worker paused or stopped | Actions menu in Live Workbench toolbar |

**Gate visualization rule:** every transition button shows its prerequisites inline. A disabled "Validate" shows "Run Construct first". A disabled "Go Live" shows "2 prerequisites pending: critic review, stress scenario fail". Never a silent disabled button.

### 2.3 Entry points

- **From Discovery:** `[Add to Universe]` CTA on Discovery Analysis page (fund-level) routes to `/portfolio/builder/universe?fund={id}&status=pending` and opens the approval drawer.
- **From TopNav:** direct click on "Portfolio" pill → lands on `/portfolio/builder` (Estado B, fresh).
- **From Alerts (live):** clicking an alert notification (regime change, drift breach) routes to `/portfolio/live?portfolio={id}&panel=alerts&alert={alert_id}`.
- **From a Model listing:** clicking a draft opens `/portfolio/builder?draft={id}`; clicking a live portfolio opens `/portfolio/live?portfolio={id}`.

### 2.4 Exit points

- From Builder → Analytics: "Analyze this draft" button on draft header → `/portfolio/analytics?scope=models&subject={draft_id}`.
- From Analytics → Builder: "Edit draft" on subject header (only if state is `draft`/`constructed`).
- From Live → Analytics: "Analyze" in Live toolbar → `/portfolio/analytics?scope=models&subject={live_id}` (read-only mode for live portfolios).
- From Live → Rebalance → Builder: "Propose Rebalance" opens rebalance proposal; accepted proposal spawns a new draft in Builder (state=draft, parent_id=live_id).

---

## 3. State Machine (Approval → Live)

This is the contract every UI affordance must obey. Backend owns state transitions; frontend renders state + available actions.

### 3.1 States

```
draft           → user is composing allocations, no construct run yet
constructed    → optimizer ran successfully, proposed weights available
validated      → stress + critic + risk checks all passed
approved       → human approval recorded (self or 4-eyes)
live           → portfolio_nav_synthesizer is computing NAV daily
paused         → was live, worker paused (still visible in Live list)
archived       → terminal state, read-only
rejected       → terminal state, can be cloned to new draft
```

### 3.2 Transition table

| From | To | Trigger | Backend check | UI location |
|------|----|---------|-----|-------------|
| (none) | draft | POST /model-portfolios | ConfigService policy exists for org | Builder action bar "+ New Portfolio" |
| draft | constructed | POST /model-portfolios/{id}/construct | allocation blocks ≥ 1, universe funds ≥ 2, policy attached | BuilderColumn "Run Construct" |
| constructed | draft | Edit weights/blocks/policy | invalidates construct; banner "Construct stale — rerun" | Automatic on any mutation |
| constructed | validated | POST /model-portfolios/{id}/validate | stress_ok AND critic_ok AND risk_ok | Right rail "Validate" button |
| validated | approved | POST /model-portfolios/{id}/approve | role check, 4-eyes policy | Right rail "Send for Approval" |
| approved | live | POST /model-portfolios/{id}/promote | no sibling live, nav_ready (constituents have NAV) | Analytics detail "Go Live" modal |
| live | paused | POST /portfolios/{id}/pause | worker lock released | Live Workbench toolbar |
| live | live (rebalance) | POST /rebalancing/propose + accept | new weights applied, audit event | Live Workbench rebalance panel |
| paused | live | POST /portfolios/{id}/resume | — | Live Workbench toolbar |
| any | archived | POST /portfolios/{id}/archive | confirmation modal | Actions menu |
| constructed/validated | rejected | POST /model-portfolios/{id}/reject (4-eyes reviewer) | — | Approval drawer |

### 3.3 State visibility rules (the "where do I see this?" map)

- `/portfolio/builder` **Models panel** sub-tabs: `Drafts (draft+constructed+validated)` / `Approved (approved)` / `Live (live+paused)` / `Archive (archived+rejected)`.
- `/portfolio/analytics` **scope=models** subject selector shows all non-archived states with a state badge pill.
- `/portfolio/live` shows only `live` + `paused`.

### 3.4 Race conditions & idempotency

- **Construct single-flight:** clicking "Run Construct" twice → second click is swallowed; button shows streaming state. Backend already uses Redis single-flight lock + `@idempotent`.
- **Promote race:** if two users click "Go Live" simultaneously → `pg_advisory_xact_lock` on portfolio_id (crc32, not `hash()`). Losing client gets 409 with "Another user just promoted this — refresh".
- **Stale construct detection:** mutating a weight after construct stamps `construct_stale=true`. Validate button disabled with "Rerun Construct first".
- **Session expiry mid-Construct:** SSE construct stream receives 401 → store sets `sessionExpired=true`, shows modal "Session expired — your draft was saved (state=draft). Sign in to resume."

---

## 4. Phase 1 — Builder (`/portfolio/builder`)

### 4.1 Layout (FCL 3-column, same primitive as Discovery)

```
┌──────────── sub-nav ribbon (Builder · Analytics · Live) ─────────────┐
├─ Col 1 ──────────┬─ Col 2 ────────────────┬─ Col 3 ──────────────────┤
│ Left Navigator    │ Builder Workbench       │ Analytics Drawer          │
│ sub-pills:        │ Action Bar:             │ Tabs:                     │
│  Models           │  [+ New] [Policy▾]      │  Fund | Portfolio |       │
│  Universe         │  [Run Construct] [⚠]    │  Stress | Compare         │
│  Policy           │ ─────────────────────   │ ──────────────────────   │
│                    │ Main Chart (NAV sim +   │ Opens on:                 │
│ (ModelListPanel /  │  proposed vs current)   │  - row click in universe  │
│  UniversePanel /   │ ─────────────────────   │  - "View Chart" in builder│
│  PolicyPanel)      │ Allocation Blocks DnD   │                           │
│                    │ ─────────────────────   │ Read-only analytical      │
│                    │ Construct Narrative     │ deep-dive                 │
│                    │ (after Run)             │                           │
└──────────────────┴─────────────────────────┴────────────────────────┘
```

Applies layout cage pattern (`calc(100vh-88px)` + `padding:24px`). (memory: `feedback_layout_cage_pattern.md`)

### 4.2 Calibration workbench (fix for complaint #1)

Currently sliders are mocked. The fix is to split calibration into a **dedicated drawer** (not inline sliders) with ALL engine inputs grouped and each wired to the construct API payload.

**Calibration drawer** (opens from action bar "Policy ▾" → "Calibrate Construction"):

```
Objective                    [Max Risk-Adj Return ▾] (translation: Sharpe-oriented)
Construction Style           [Diversified ▾]
Risk Budget
  Maximum acceptable loss     ▓▓▓▓▓▓░░░░ 8%  (backend: CVaR 95%)
  Volatility ceiling          ▓▓▓▓░░░░░░ 12%
Concentration
  Max weight per fund         ▓▓▓▓▓░░░░░ 8%
  Max weight per strategy     ▓▓▓▓▓▓▓░░░ 25%
  Min holdings                ▓▓░░░░░░░░ 8
Turnover
  Max turnover vs current     ▓▓▓▓▓░░░░░ 15%
  Rebalance frequency         [Monthly ▾]
Views (Black-Litterman)
  [+ Add view] → form: asset, expected return, confidence
Stress scenarios (toggle which to run on construct)
  ☑ 2008 Credit crisis
  ☑ 2020 Pandemic drawdown
  ☑ 2013 Taper tantrum
  ☑ Rate shock +300bps
  ☐ Custom scenario
Advanced
  [Regime-conditioned covariance]          [ ON ]
  [Robust optimization (uncertainty sets)] [ ON ]
  [GARCH-adjusted volatility]              [ ON ]
```

**Translation discipline:** slider labels are plain English. Hover tooltip shows the backend name in small gray text for power users: *"Max loss (95% worst case) — backend: CVaR 95 multiplier applied per regime"*. Never "CVaR" in the label. (memory: `feedback_smart_backend_dumb_frontend.md`)

**Live preview:** while sliders move, a **live preview band** at the top of the drawer recomputes lightweight derived metrics (projected volatility, expected turnover based on current holdings) using a debounced (400ms) call to a lightweight endpoint `/model-portfolios/{id}/calibration-preview` — NOT the full construct. Full construct is still opt-in via "Run Construct".

**State sync:** calibration state lives in the workspace store as `workspace.calibration`. Every slider write updates store + syncs to backend draft via `PATCH /model-portfolios/{id}`. No hidden local state.

**The mock problem goes away** when sliders are wired to the real payload. If a knob isn't wired, it doesn't ship. No placeholder UI.

### 4.3 Run Construct narrative output (fix for complaint #2)

After `/construct` returns, the center column scrolls to a **Construct Narrative** section below the allocation blocks. The optimizer is opaque by default — this section is where Netz translates the cascade into a story.

**Information architecture:**

```
── Construct Narrative ───────────────────────────── 2026-04-08 14:32 UTC ──

SUMMARY
The portfolio was rebalanced toward a more defensive mix. Risk-adjusted return
is expected to improve from 0.94 to 1.12. Turnover required: 12%.

WHAT THE OPTIMIZER DID
  ✓ Phase 1 — Target the best risk-adjusted return                  solved
  ✓ Phase 1.5 — Stress-test the result against worst-case inputs    solved
  ✓ Phase 2 — Tighten volatility ceiling                             solved
  → Final result taken from Phase 2 (volatility-capped)

BINDING RULES (what was the active constraint)
  • Max weight per fund (8%) — hit on Fidelity Contrafund, iShares Core S&P
  • Max weight per strategy (25%) — hit on US Large Cap Equity
  The optimizer could not go further because these rules were the bottleneck.

MARKET CONDITIONS
  Current regime: Risk-Off
  A defensive multiplier was applied to worst-case loss estimates (-15%)

EXPECTED OUTCOMES (proposed vs current)
  Risk-adjusted return     0.94  →  1.12   ↑
  Expected volatility      14.2% → 12.8%   ↓
  Worst-case loss (95%)    -22%  → -18%    ↓
  Max drawdown (modeled)   -24%  → -19%    ↓
  Number of holdings       18    →  22     ↑
  Turnover vs current             12%

TOP 5 HOLDING CHANGES (with rationale)
  ▲ Vanguard Total Bond ETF      +3.2%   Defensive tilt, low correlation
  ▲ iShares Gold Trust           +2.1%   Regime-driven hedge allocation
  ▼ ARK Innovation ETF           -4.0%   Hit concentration + volatility caps
  ▼ Invesco QQQ                  -2.3%   Strategy cap (US Large Cap) binding
  ▲ Dodge & Cox International    +1.8%   Diversifies toward DM ex-US

WARNINGS (if any)
  ⚠ Phase 1 fell back to Phase 2 after robust check trimmed 2 candidates
  ⚠ 1 requested fund (XYZ) has <2y of price history — excluded from run

[  Accept Proposal  ]   [  Discard  ]   [  Run Again with Different Inputs  ]
```

**Key design rules:**
- **No solver names.** "CLARABEL", "SOCP", "Ledoit-Wolf", "robust uncertainty set" never appear. Phase descriptions are plain English.
- **Binding rules** are the most important section — institutional users read this FIRST. They want to know what prevented a better answer.
- **Accept Proposal** is the state transition → `constructed` → `draft` with new weights. Discard preserves the old draft.
- **Narrative is persisted** as an artifact (`model_portfolios.last_construct_narrative` JSONB) so Analytics can replay it.
- **All numbers use `@netz/ui` formatters** (`formatPercent`, `formatNumber` with signs). Never `.toFixed()`. (memory: `feedback_no_remove_endpoints.md` + CLAUDE.md formatter rule)

### 4.4 Allocation advisor visibility (fix for complaint #3)

The advisor is currently invisible. Make it **explicit and labeled** as a first-class subject.

- Action bar gets a new chip: `Advisor: ON [Balanced tilt ▾]` with states `OFF | Balanced | Aggressive | Defensive`.
- When ON, the advisor runs a lightweight suggestion call before each Construct and injects BL views into the payload. The Construct Narrative gets a new section: `ADVISOR INPUT — Views applied from Balanced tilt: US Equities +1.5%, EM Debt +0.8% (confidence: medium)`.
- If advisor is OFF, the narrative section is omitted — no ghost signals.
- Tooltip on the chip: "The advisor translates market conditions into expected return adjustments and feeds them as views into the optimizer."

No black box. If it contributed, it's credited in the narrative.

### 4.5 Universe sub-pill (Andrei's rule: universe lives in portfolio)

Per memory note `feedback_universe_lives_in_portfolio.md`, Approved Universe is a sub-pill of `/portfolio/builder`, never a standalone route. This document locks that in.

- URL: `/portfolio/builder/universe` (shallow route, same layout shell).
- Left column becomes the **universe filter rail** (FilterRail primitive from Discovery).
- Center column becomes the **universe table** (EnterpriseTable primitive, reused from Discovery).
- Right column is the **fund drill-down** (same AnalyticsColumn as Builder, read-only).
- Header shows tabs `Pending | Approved | Rejected` with counts.
- Drag from approved universe table DIRECTLY into allocation blocks on Builder works via a shared workspace state — when the user switches back to `/portfolio/builder` the drag target is still there.

---

## 5. Phase 2 — Analytics (`/portfolio/analytics`)

### 5.1 Positioning

Analytics is the **deterministic vs subjective reasoning surface**. Builder is where you construct; Analytics is where you interrogate. Same pattern as Discovery Analysis — FilterRail left + ChartCard grid center + BottomTabDock at bottom.

Andrei's rule: Analytics covers **both model portfolios AND approved funds**, side by side. Use scope switcher at the top.

### 5.2 Layout

```
┌─ sub-nav ribbon ──────────────────────────────────────────────────┐
├─ Scope ──────────────────────────────────────────────────────────┤
│ [Scope: Model Portfolios ▾]  [Subject: Balanced v3 ▾]            │
│  Groups:  Returns & Risk | Holdings | Peer | Stress              │
│  Window:  [1y|3y|5y|10y|max]     Benchmark: [ACWI ▾]             │
├─ FilterRail (260) ─┬─ Chart Grid (3×2) ─────────────────────────┤
│  (advanced filters)│  ChartCard ChartCard ChartCard              │
│                    │  ChartCard ChartCard ChartCard              │
│                    │                                              │
├────────────────────┴────────────────────────────────────────────┤
│  BottomTabDock: [Balanced v3 · Returns] [Conservative · Holdings]│
└─────────────────────────────────────────────────────────────────┘
```

Reuses Discovery primitives 1:1: `FilterRail`, `EnterpriseTable`, `ChartCard`, `AnalysisGrid`, `BottomTabDock`.

### 5.3 Scope switcher

Three scopes:

- **Model Portfolios** (default) — subject dropdown shows all non-archived portfolios grouped by state.
- **Approved Universe** — subject dropdown shows approved funds only (Bloomberg-style: drill into a single fund).
- **Compare Both** — dual-subject mode, overlays a model portfolio against a benchmark fund or another portfolio.

### 5.4 Analysis groups

- **Returns & Risk** — NAV line + drawdown hero, rolling Sharpe, rolling volatility, return distribution, regime scatter, contribution-to-risk (reusing Discovery components).
- **Holdings** — sunburst (sector/geo), top 20, overlap vs another portfolio, concentration metrics.
- **Peer** — peer ladder, expense percentile, information ratio vs peer median.
- **Stress** — parametric scenarios (GFC, COVID, Taper, Rate Shock) as narrative cards with charts. **This is where complaint #1 stress test fix lives** — scenarios pulled directly from `stress_service.py` parametric results, never mocked. Each scenario card shows:
  ```
  2008 Credit Crisis                                              -21.3%
  In a scenario similar to late 2008, this portfolio would have
  lost approximately 21% over 6 months. The worst-hit positions
  would have been Financials (-34%) and High Yield Credit (-28%).
  [ See drawdown path ▾ ]
  ```

### 5.5 Go Live entry point

On the Analytics subject header (Model Portfolios scope), state-aware primary action:

- `state=draft` → "Edit in Builder"
- `state=constructed` → "Validate" (calls /validate)
- `state=validated` → "Send for Approval"
- `state=approved` → **"Go Live"** (opens promotion modal with prerequisite checklist)
- `state=live` → "Open Live Workbench"

This is the single exit to Live.

---

## 6. Phase 3 — Live Workbench (`/portfolio/live`) — The Terminal

This is the missing page. Terminal aesthetic: full-width, tighter borders, less rounded, info-dense. NOT the FCL pattern — a different shell.

### 6.1 Shell divergence from Discovery

Live Workbench is the **only** page in Wealth that intentionally diverges from the FCL layout cage. Rationale: alert density, multi-chart workbench, live prices require maximum screen real estate.

Overrides:
- Layout cage retained (`calc(100vh-88px)`) but `padding:16px` instead of `24px`.
- Card border radius: 6px instead of 12px.
- Card gap: 8px instead of 16px.
- Typography scale: drop one step (body 13px instead of 14px).
- Data tables: tighter row height (28px instead of 36px).
- No hover shadows — flat terminal look.
- Monospace numerals (`font-variant-numeric: tabular-nums`) — already in tokens.

These are **new tokens** in `@netz/ui` (`--terminal-*` semantic tokens), not overrides — so they're admin-configurable. (memory: `feedback_tokens_vs_components.md`)

### 6.2 Layout regions

```
┌─ sub-nav ribbon ───────────────────────────────────────────────┐
├── Portfolio Toolbar ──────────────────────────────────────────┤
│  [Balanced v3 ▾]  LIVE · NAV 1.0847 (+0.23% today)            │
│  Actions: [Rebalance] [Pause] [Analyze] [···]                 │
├─ Col 1 (280) ─┬─ Col 2 (flex) ────────┬─ Col 3 (320) ────────┤
│ Portfolio     │ Chart Workbench        │ Right Rail            │
│ Selector      │                        │ (tabs at top)         │
│ (live list)   │ Tabs: NAV/Drawdown/    │  Alerts               │
│               │  Exposure/Contribution │  Rebalance            │
│ ───────────   │                        │  Calibration          │
│ Alerts Feed   │ [Overlay: S/T/E/All]  │                       │
│ (always-on,   │                        │                       │
│  SSE stream)  │ ──────────────────── │ ──────────────────── │
│               │ Strategic / Tactical / │ (context-sensitive    │
│               │ Effective tables       │  panels)              │
└───────────────┴────────────────────────┴───────────────────────┘
```

**Col 1 — Portfolio Selector + Alerts Feed:**
- Top half: live portfolios list (compact table, 28px rows, columns: Name, NAV, ΔDay, State, Alerts count).
- Bottom half: persistent alerts feed, scrolled reverse-chrono, grouped by severity. Always visible — this is mission critical.

**Col 2 — Chart Workbench + Allocation Tables:**
- Top 60%: chart canvas with tabs (NAV, Drawdown, Exposure, Contribution-to-risk). Chart supports multi-overlay: strategic target vs tactical tilt vs effective current. Multi-select legend. Range slider. Crosshair with tooltip showing values at cursor. Right-click → "Compare constituent" opens constituent chart overlay.
- Bottom 40%: **three stacked tables** (collapsible):
  - **Strategic allocation** (the approved target weights)
  - **Tactical allocation** (advisor/PM override, if any)
  - **Effective allocation** (current market-value weights, drift vs strategic)
  Rows highlight drift in red/amber/green per policy band.

**Col 3 — Right Rail (tabs):**
- **Alerts tab** — detail of selected alert (or most recent), with explanation + recommended action + one-click routes ("Open Rebalance Proposal", "Dismiss", "Snooze 24h").
- **Rebalance tab** — if a rebalance proposal exists, shows suggested trades, impact analysis, turnover, cost estimate. CTA "Open in Builder" creates a new draft.
- **Calibration tab** — read-only peek at the active policy (risk budget, concentration, objectives). "Edit in Builder" routes back.

### 6.3 Always-visible vs collapsible

| Region | Behavior |
|--------|----------|
| Portfolio toolbar | Always visible |
| Portfolio selector (col1 top) | Always visible |
| Alerts feed (col1 bottom) | Always visible |
| Chart workbench (col2 top) | Always visible |
| Allocation tables (col2 bottom) | Collapsible individually (strategic/tactical/effective each toggle) |
| Right rail | Collapsible (icon-only fallback to max chart width) |

### 6.4 Live price integration

- Live prices come from a dedicated SSE channel: `GET /portfolios/{id}/live-stream` (fetch + ReadableStream, not EventSource — auth headers). Backend worker publishes to Redis on tick; SSE bridge fans out.
- Price updates use a **client-side tick buffer** (`createTickBuffer<T>` from stability guardrails — CLAUDE.md §3). Never spread into `$state` per tick. Flush at 4Hz to avoid jank.
- Fallback: if SSE drops, fall back to polling `/portfolios/{id}/snapshot` every 30s. Indicator in toolbar: `● LIVE` vs `● DELAYED 30s`.

---

## 7. Alerts Feed Architecture

### 7.1 Alert sources (backend workers, already exist)

- `drift_check` (lock 42) → `strategy_drift_alerts` table
- `portfolio_eval` (lock 900_008) → breach status, regime cascade
- `monitoring` domain → limit breach, fee drag anomalies
- Regime change events from `regime_fit` worker

### 7.2 Unified alert contract

All alerts converge into a single Redis pub/sub channel per org (`alerts:{org_id}`) and surface via a single SSE endpoint `GET /alerts/stream?scope=portfolio&portfolio_id={id?}` (org-wide or filtered to one portfolio).

Alert shape (to be formalized by DB specialist — this is the UX contract):

```
{
  id, portfolio_id, severity: "info"|"warn"|"critical",
  kind: "drift"|"limit_breach"|"regime_change"|"rebalance_suggested"|"fee_anomaly",
  title: "Strategy drift: Balanced v3",
  body:  "Effective weights drifted 4.2% from strategic target (threshold: 3%).",
  next_action: { label: "Review rebalance", href: "/portfolio/live?portfolio=...&panel=rebalance" },
  created_at, acknowledged_at, snoozed_until
}
```

### 7.3 Presentation tiers

- **Persistent feed (Live Workbench col1 bottom):** accumulates everything, scoped to selected portfolio.
- **Toast on event (any page under /portfolio/*):** top-right slide-in on `critical` only, auto-dismiss 8s, click routes to next_action.
- **Badge counts:** sub-nav ribbon pill "Live · 2 active · 5 alerts" = unacknowledged alerts across live portfolios.
- **Global bell** in TopNav: cross-vertical, shows totals.

### 7.4 Rules

- No `localStorage` for read state. Acknowledgement is a backend write (`POST /alerts/{id}/acknowledge`).
- Snooze is also server-side — stale on refresh is unacceptable.
- Session expiry on SSE → automatic reconnect with exponential backoff; banner "Reconnecting to alerts stream..." if > 5s.
- 409 on acknowledge (already ack'd by another user) → silently refresh from server, no error toast.

---

## 8. Multi-Portfolio Navigation

When a user manages 5+ live portfolios, switching must be friction-free.

### 8.1 Primary mechanism: Portfolio Selector (col1 top in Live Workbench)

- Compact table, always visible in Live Workbench, scoped to `state=live OR state=paused`.
- Columns: Name, NAV, ΔDay, Drift %, Alerts.
- Click = switch active portfolio (updates `?portfolio=` URL, right rail, chart, tables).
- Search box at top for 20+ portfolios.

### 8.2 Secondary mechanism: BottomTabDock (reused from Discovery)

Live Workbench also gets a **BottomTabDock** showing recently analyzed/opened portfolios. Clicking a dock tab switches without losing state. Tab format: `[Portfolio name] · [Chart mode]`. This is optional for Live but mandatory for Analytics (where multi-subject comparison is the main job).

### 8.3 Mental model lock-in

- **Live Workbench** = persistent selector in col1 (single active portfolio, detailed).
- **Analytics** = BottomTabDock (parallel sessions across subjects).
- **Builder** = single draft in the center column (switching drafts = URL change).

Three different patterns because three different jobs. Don't collapse them into one.

---

## 9. Discovery Parallel — Reuse vs Divergence

### 9.1 Reuse 1:1

| Primitive | Usage in Portfolio | Source |
|-----------|-------------------|--------|
| `FlexibleColumnLayout` | Builder, Analytics | `@netz/ui` (promoted from Discovery Phase 2) |
| `EnterpriseTable` | Universe, Models list, Allocation tables | `@netz/ui` |
| `FilterRail` | Analytics, Universe sub-pill | `@netz/ui` |
| `ChartCard` | Analytics grid | `@netz/ui` |
| `AnalysisGrid` | Analytics chart layout | `@netz/ui` |
| `BottomTabDock` | Analytics (mandatory), Live (optional) | `@netz/ui` |
| `PanelErrorState` | Every fallible panel | `@netz/ui` |

### 9.2 Deliberate divergence

- **Live Workbench shell**: new `TerminalShell` primitive in `@netz/ui`. Shares tokens but has its own density overrides. Not a one-off — this will be reused by future credit/wealth live dashboards.
- **Calibration Drawer**: new `CalibrationDrawer` primitive. Right-side drawer with grouped sliders and live preview. Builder-specific for v1.
- **Construct Narrative Block**: new composite component — list of sections, state-aware. Goes in Builder center column + replayed in Analytics.
- **Strategic/Tactical/Effective tables**: new `AllocationComparisonTable` — three-way diff table with drift highlighting. Specific to Live.

### 9.3 Pattern discipline

Any new Portfolio primitive that is not trivially specific MUST go into `@netz/ui`. Do not duplicate.

---

## 10. Formatting, Language & Jargon Translation Table

Every backend field passing through Portfolio UI runs through this sanitization. This table is normative.

| Backend field / concept | UI label | Formatter |
|-------------------------|----------|-----------|
| `cvar_95` | "Worst-case loss estimate (95%)" | `formatPercent` |
| `sharpe_ratio` | "Risk-adjusted return" | `formatNumber` (2dp) |
| `max_drawdown` | "Worst loss period" | `formatPercent` |
| `volatility_garch` | "Expected volatility" | `formatPercent` |
| `turnover` | "Turnover vs current" | `formatPercent` |
| `regime=RISK_OFF` | "Market conditions: Defensive" | text |
| `regime=CRISIS` | "Market conditions: Stress" | text |
| `regime=NORMAL` | "Market conditions: Balanced" | text |
| `regime=BULL` | "Market conditions: Expansion" | text |
| `CLARABEL Phase 1` | "Target the best risk-adjusted return" | text |
| `CLARABEL Phase 1.5` | "Stress-test against worst-case inputs" | text |
| `CLARABEL Phase 2` | "Tighten volatility ceiling" | text |
| `CLARABEL Phase 3` | "Minimize overall risk" | text |
| `robust SOCP` | "Stress-tested against uncertainty" | text |
| `Ledoit-Wolf shrinkage` | (not surfaced) | — |
| `Black-Litterman views` | "Views applied" | text |
| `factor loading` | "Style exposure" | `formatNumber` |
| `information ratio` | "Active return per unit of active risk" | `formatNumber` |
| `binding constraint` | "Binding rule" | text |
| `CLARABEL infeasible → Phase 2 fallback` | "Optimizer tightened the rules and retried" | text |
| `strategy_drift_alerts.severity=high` | "Drift alert: action needed" | text |
| `fee_drag_bps` | "Fee drag" | `formatPercent` from bps/100 |

All currency/number/date output uses `@netz/ui` formatters. No `.toFixed()`, no inline `Intl.*`. Enforced by `frontends/eslint.config.js`. (CLAUDE.md formatter rule)

---

## 11. Risks, Open Decisions & Andrei Input Needed

### 11.1 Risks

- **Live Workbench scope creep.** Terminal design is the biggest new surface. Risk of feature sprawl (sector heatmap? options overlays? corporate actions?). MUST lock scope to v1 = NAV/Drawdown/Exposure/Contribution chart modes + strategic/tactical/effective tables + alerts/rebalance/calibration tabs. Everything else is v1.1.
- **SSE backpressure.** 5+ live portfolios × tick buffer × alerts stream × user on slow network. Needs throughput budget. Plan: cap client subscriptions at 1 live price stream (active portfolio only) + 1 org-wide alerts stream. Other portfolios poll snapshot every 60s.
- **Construct narrative artifact growth.** `last_construct_narrative` JSONB could balloon. Cap at last 10 construct runs per portfolio, archive older to R2.
- **State machine drift.** Frontend and backend can disagree on what transitions are legal. Mitigation: backend is authoritative. Frontend receives `allowed_actions: [...]` array on every portfolio GET and renders only those buttons. No hardcoded "if state === 'validated'" in UI.
- **@tanstack/svelte-table breakage** (memory: `project_frontend_platform.md`). EnterpriseTable is the native Svelte 5 fix. Portfolio must use EnterpriseTable, not revive tanstack.
- **Approval workflow ambiguity.** 4-eyes policy is per-org config but not surfaced in admin UI yet. v1: read `ConfigService.get("wealth", "approval_policy", org_id)`, show "Self-approval permitted" vs "Second reviewer required" in the Send-for-Approval button tooltip. Admin UI for this is out of scope.

### 11.2 Open decisions needing Andrei

1. **Analytics scope=Compare Both mode** — is it v1 or v1.1? It's the most complex (dual subject diff). I recommend v1.1.
2. **Live Workbench portfolio selector UX** — table (as spec'd) or sidebar list? Recommendation: table wins at 3+ portfolios, list at ≤3. Confirm.
3. **Rebalance proposal acceptance** — does accepting a rebalance mutate the LIVE portfolio in place (new weights, state stays `live`), or does it spawn a NEW draft that must re-traverse validation→approval→Go Live? Institutional norm is the latter (audit trail), and I recommend it. Confirm.
4. **4-eyes approval UI for small orgs** — if an org has only 1 user, do we hard-block `validated → approved` or allow self-approval with a warning banner? Recommendation: allow self-approval when ConfigService flag is set, audit-log it as self-approved.
5. **Construct Narrative language — PT vs EN.** Fact Sheets have PT/EN i18n; Narrative currently spec'd EN only. Is PT a v1 requirement?
6. **Universe sub-pill approval actions** — should "Approve" in bulk be allowed? Recommend yes (select N rows → Approve), with a confirmation modal.
7. **Live → Rebalance entry** — should the rebalance workspace be a drawer inside Live, or a full route `/portfolio/rebalance/{id}`? Recommendation: drawer for proposal review + "Open in Builder" for deep edits. Confirm.
8. **Regime label translation** — "Defensive / Balanced / Growth / Stress" is my proposal. Andrei's preference?
9. **`/portfolio/advanced`, `/portfolio/model`, `/portfolio/analytics` legacy routes** — delete, redirect, or keep? Recommend: redirect `/portfolio/analytics` → `/portfolio/analytics` (new surface, same URL works), delete `/portfolio/advanced` and `/portfolio/model`.
10. **Live Workbench density tokens** — should `TerminalShell` tokens be admin-configurable (per-org density preference) or hardcoded? Recommend hardcoded for v1, promote to tokens in v1.1.

---

## 12. Locked Decisions (this document → implementation plan)

Before implementation starts, the following are locked (subject to Andrei sign-off on §11.2):

- L1. Three-phase URL contract: `/portfolio/builder`, `/portfolio/analytics`, `/portfolio/live`. Sub-nav ribbon under TopNav.
- L2. Universe is a sub-pill of Builder (`/portfolio/builder/universe`), never a standalone route.
- L3. State machine: `draft → constructed → validated → approved → live → paused/archived`. Backend-authoritative, frontend renders `allowed_actions`.
- L4. Run Construct produces a narrative artifact with SUMMARY / PHASES / BINDING RULES / MARKET CONDITIONS / EXPECTED OUTCOMES / TOP CHANGES / WARNINGS sections. Stored as JSONB, replayable in Analytics.
- L5. Calibration is a dedicated drawer, every slider is wired, no mocks ship. Live preview uses a debounced lightweight endpoint, not full construct.
- L6. Allocation Advisor is explicit and credited in the narrative. OFF by default.
- L7. Live Workbench diverges from FCL — new `TerminalShell` primitive with density overrides as tokens.
- L8. Live Workbench col1 = portfolio selector + persistent alerts feed. col2 = chart workbench + strategic/tactical/effective tables. col3 = right rail (alerts/rebalance/calibration tabs).
- L9. Alerts via single SSE endpoint per org. Three presentation tiers: persistent feed, critical toasts, badge counts.
- L10. Live prices via fetch+ReadableStream with tick buffer. Fallback to 30s polling. `LIVE` / `DELAYED` indicator in toolbar.
- L11. Analytics reuses Discovery primitives 1:1. Builder reuses FCL + EnterpriseTable. Live diverges.
- L12. Jargon translation table in §10 is normative. New backend fields require an entry before UI shipping.
- L13. No `localStorage`. All state in URL + in-memory store + SSE.
- L14. All numbers/dates/currency use `@netz/ui` formatters. Enforced by ESLint.
- L15. `@tanstack/svelte-table` is forbidden. EnterpriseTable is the canonical table.

---

## 13. Phase Sequencing (for the merged plan)

This section is a recommended sequence for the eventual merged implementation plan — the other four specialists will flesh out each phase. I am only staking out the UX skeleton.

1. **Phase A — Sub-nav ribbon + routing skeleton** (UX only, no backend). Ship the three URL shells with placeholder content so nav is testable.
2. **Phase B — Builder calibration drawer + wired sliders** (depends on quant specialist wiring `/calibration-preview` endpoint and DB specialist extending ModelPortfolio schema).
3. **Phase C — Construct Narrative artifact** (backend persists narrative, frontend renders block). Includes Allocation Advisor credit section.
4. **Phase D — State machine UI** (allowed_actions contract, state badges, approval drawer). Depends on backend exposing state transition endpoints and gate checks.
5. **Phase E — Analytics surface migration** (reuse Discovery primitives, add scope switcher, migrate legacy /portfolio/analytics).
6. **Phase F — Universe sub-pill** (URL + EnterpriseTable + approval actions).
7. **Phase G — Live Workbench shell** (TerminalShell primitive, portfolio toolbar, portfolio selector).
8. **Phase H — Alerts feed + SSE** (persistent feed, toasts, badges).
9. **Phase I — Live price streaming + tick buffer**.
10. **Phase J — Strategic/Tactical/Effective tables**.
11. **Phase K — Rebalance proposal drawer + spawn-draft flow**.
12. **Phase L — Go Live promotion modal + worker activation**.
13. **Phase M — Multi-portfolio navigation polish (BottomTabDock in Analytics, selector UX in Live)**.

Phases A–F unlock Builder + Analytics fluency (complaints #1–#4). Phases G–L deliver Live (complaint #5). Phase-order respects Andrei's "product-facing first" rule (memory: `feedback_phase_ordering.md`).

---

## 14. Validation Checklist (per phase)

Every phase must pass before being marked done:

- [ ] `svelte-autofixer` clean on every new/changed component
- [ ] Browser-validated against real backend (memory: `feedback_visual_validation.md`)
- [ ] No `.toFixed()`, `.toLocaleString()`, `Intl.*` in UI code — only `@netz/ui` formatters
- [ ] No jargon leak (run against §10 table)
- [ ] No `localStorage` calls in wealth code
- [ ] No `EventSource` — fetch+ReadableStream only
- [ ] Layout cage intact (`calc(100vh-88px)` + padding)
- [ ] Sub-nav ribbon visible and badges accurate
- [ ] State machine matches backend `allowed_actions` response
- [ ] Race conditions tested: double-click construct, concurrent promote, session expiry mid-construct, SSE drop
- [ ] 409 UX tested (concurrent approve, concurrent rebalance accept)
- [ ] `svelte-echarts` used (no Chart.js)
- [ ] EnterpriseTable used (no `@tanstack/svelte-table`)
- [ ] Feedback loop with Andrei before locking phase

---

## 15. Out of Scope (for this document)

Not my lane — other specialists will cover:

- DB schema changes (new columns, new tables, migrations) — DB specialist
- Quant engine payload/contract changes (calibration fields, narrative JSONB shape, stress scenario catalogue) — quant specialist
- Svelte component internals (TerminalShell, CalibrationDrawer, ConstructNarrative, AllocationComparisonTable implementation) — components specialist
- Chart spec details (which chart for NAV vs Drawdown, tick format, zoom behavior) — charts specialist
- Backend routes (new endpoints for `/calibration-preview`, `/allowed-actions`, `/live-stream`, `/alerts/stream`) — DB/quant specialists jointly

This document owns: navigation, URL contract, state machine, flow gates, page layouts, region behavior, jargon translation, validation checklist.

---

*End of Portfolio Vertical UX & Navigation Flow design document.*
