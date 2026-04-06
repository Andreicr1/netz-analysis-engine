# Portfolio Construction — Architecture Audit v3

> **Date:** 2026-04-05
> **Branch:** `refactor/factsheet-executive-snapshot`
> **Scope:** Full-stack audit of the Portfolio Construction module (frontend Svelte 5 + backend FastAPI + quant engines)
> **Prior art:** `rebalance-drift-systems-audit.md` (same date, drift/rebalance focus)

---

## Table of Contents

- [A. File Inventory](#a-file-inventory)
- [B. State Architecture (Svelte 5 Runes)](#b-state-architecture-svelte-5-runes)
- [C. Drag-and-Drop Mechanics](#c-drag-and-drop-mechanics)
- [D. Allocation Mechanics & Weight Normalization](#d-allocation-mechanics--weight-normalization)
- [E. Backend Integration Map](#e-backend-integration-map)
- [F. Gaps & Recommendations](#f-gaps--recommendations)

---

## A. File Inventory

### A.1 Frontend — Svelte 5 Components

| File | Lines | Role |
|------|------:|------|
| `frontends/wealth/src/routes/(app)/portfolio/models/create/+page.svelte` | 1 633 | **5-step creation wizard** — profile → fund selection → macro inputs → construction → activation |
| `frontends/wealth/src/routes/(app)/portfolio/models/[portfolioId]/+page.svelte` | 20 747 | **Model Portfolio Workbench** — detail view with drift, rebalance preview, backtest, stress, fund editor, reports |
| `frontends/wealth/src/routes/(app)/portfolio/builder/+page.svelte` | 29 | Legacy redirect to `AllocationView` |
| `frontends/wealth/src/lib/components/AllocationView.svelte` | 1 045 | Strategic/tactical/effective tabs, CVaR simulation, governed save |
| `frontends/wealth/src/lib/components/portfolio/PortfolioOverview.svelte` | 310 | **Drop zones** — HTML5 DnD targets per allocation block |
| `frontends/wealth/src/lib/components/portfolio/UniversePanel.svelte` | 228 | **Drag source** — filterable approved-fund cards |
| `frontends/wealth/src/lib/components/model-portfolio/FundSelectionEditor.svelte` | 491 | Inline fund editor (checkbox list + change summary + re-construct trigger) |
| `frontends/wealth/src/lib/components/model-portfolio/ConstructionAdvisor.svelte` | 754 | CVaR coverage gap analysis, ranked candidates, minimum viable set |
| `frontends/wealth/src/lib/components/model-portfolio/DriftGauge.svelte` | 119 | Visual drift indicator |
| `frontends/wealth/src/lib/components/model-portfolio/RebalancePreview.svelte` | 165 | Trade list + turnover display |
| `frontends/wealth/src/lib/components/model-portfolio/StrategyDriftAlerts.svelte` | 101 | Strategy anomaly alerts |
| `frontends/wealth/src/lib/components/model-portfolio/ICViewsPanel.svelte` | 795 | Investment Committee views management |
| `frontends/wealth/src/lib/components/model-portfolio/JobProgressTracker.svelte` | 227 | SSE job progress bars |
| `frontends/wealth/src/lib/components/model-portfolio/GeneratedReportsPanel.svelte` | 277 | Report history & generation UI |
| `frontends/wealth/src/lib/components/model-portfolio/ReportVault.svelte` | 283 | Report storage & search |
| `frontends/wealth/src/lib/components/model-portfolio/ScoreBreakdownPopover.svelte` | 222 | Fund score metric details |
| `frontends/wealth/src/lib/components/allocation/AllocationTable.svelte` | 264 | Hierarchical L1/L2 allocation table |

**Total frontend components:** 17 files, ~27 500 lines

### A.2 Frontend — State Management (Runes Stores)

| File | Lines | Scope |
|------|------:|-------|
| `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` | 361 | **Global singleton** — active portfolio, universe, DnD add, construct, stress, rebalance actions, macro shock mapping |
| `frontends/wealth/src/lib/stores/portfolio-workspace.svelte.ts` | 272 | **Per-instance factory** — live drift polling (30s), rebalance preview, strategy alerts, monitoring alerts |
| `frontends/wealth/src/lib/stores/portfolio-reports.svelte.ts` | 241 | **Per-instance factory** — report history, SSE job tracking with AbortController cleanup |
| `frontends/wealth/src/lib/stores/portfolio-analytics.svelte.ts` | 199 | Risk metrics aggregation |
| `frontends/wealth/src/lib/stores/risk-store.svelte.ts` | 541 | CVaR, volatility, regime computations |
| `frontends/wealth/src/lib/stores/market-data.svelte.ts` | 361 | Market data caching layer |

### A.3 Frontend — Types

| File | Role |
|------|------|
| `frontends/wealth/src/lib/types/model-portfolio.ts` | Full domain types: `ModelPortfolio`, `SelectionSchema`, `InstrumentWeight`, `BacktestResult`, `StressResult`, `ParametricStressRequest/Result`, `RebalancePreviewRequest/Response`, `ConstructionAdvice` |
| `frontends/wealth/src/lib/types/universe.ts` | Universe asset types for screener/DnD |

### A.4 Backend — Routes

| File | Prefix | Endpoints |
|------|--------|----------:|
| `backend/app/domains/wealth/routes/model_portfolios.py` | `/model-portfolios` | 14 |
| `backend/app/domains/wealth/routes/rebalancing.py` | `/rebalancing` | 1 |
| `backend/app/domains/wealth/routes/monitoring.py` | `/monitoring` | 1 |
| `backend/app/domains/wealth/routes/strategy_drift.py` | `/analytics/strategy-drift` | 5 |
| `backend/app/domains/wealth/routes/allocation.py` | `/allocation` | ~5 |

### A.5 Backend — Schemas (Pydantic)

| File | Key Schemas |
|------|-------------|
| `backend/app/domains/wealth/schemas/portfolio.py` | `PortfolioSummary`, `PortfolioSnapshotRead`, `RebalanceEventRead`, `PositionDetail`, `PerformancePoint`, `BlockDriftRead`, `DriftReportRead`, `LiveDriftResponse`, `AlertRead`, `AlertBatchRead` |
| `backend/app/domains/wealth/schemas/allocation.py` | `StrategicAllocationRead/Update`, `TacticalPositionRead/Update`, `EffectiveAllocationRead`, `AllocationProposal`, `SimulationResult`, `MacroAllocationProposalRead` |
| `backend/app/domains/wealth/schemas/model_portfolio.py` | `ModelPortfolioCreate/Read/Update`, `StressTestRequest/Response`, `RebalancePreviewRequest/Response`, `ConstructionAdviceRead`, `OverlapResultRead` |

### A.6 Backend — Vertical Engines

| Package | Key Files | Purpose |
|---------|-----------|---------|
| `vertical_engines/wealth/model_portfolio/` | `service.py`, `models.py` | Portfolio CRUD, construction orchestration |
| `vertical_engines/wealth/rebalancing/` | `preview_service.py`, `weight_proposer.py`, `impact_analyzer.py`, `service.py` | Stateless delta engine, proportional redistribution, impact analysis |
| `vertical_engines/wealth/monitoring/` | `drift_monitor.py`, `strategy_drift_scanner.py`, `alert_engine.py`, `overlap_scanner.py` | Drift detection, Z-score anomalies, DD/rebalance alerts, overlap |

### A.7 Backend — Quant Engine

| Service | File | Key Functions |
|---------|------|---------------|
| Drift | `quant_engine/drift_service.py` | `compute_block_drifts()`, `compute_dtw_drift()`, `resolve_drift_thresholds()` |
| Optimizer | `quant_engine/optimizer_service.py` | `optimize_fund_portfolio()` (CLARABEL 4-phase cascade), `optimize_portfolio_pareto()` (NSGA-II) |
| Rebalance | `quant_engine/rebalance_service.py` | `determine_cascade_action()`, `validate_status_transition()` |
| Scoring | `quant_engine/scoring_service.py` | `compute_fund_score()` (6-component weighted composite) |
| Allocation | `quant_engine/allocation_proposal_service.py` | Black-Litterman regime tilts |

### A.8 Backend — Workers

| Worker | Lock ID | Frequency | Role |
|--------|---------|-----------|------|
| `drift_check` | 42 | Daily | Block-level drift → auto-create `RebalanceEvent` |
| `portfolio_eval` | 900_008 | Daily | CVaR + regime → `PortfolioSnapshot` + breach alerts |
| `portfolio_nav_synthesizer` | 900_030 | Daily | Weighted NAV from `nav_timeseries` → `model_portfolio_nav` |

### A.9 Backend — Tests (New)

| File | Coverage |
|------|----------|
| `backend/tests/test_drift_rebalance_endpoints.py` | 327 lines — schema unit tests + endpoint integration (drift 401/404/200, live drift 401/404/200/400, monitoring alerts 401/200) |
| `backend/tests/test_portfolio_analytics.py` | Analytics endpoint tests |

---

## B. State Architecture (Svelte 5 Runes)

### B.1 Two-Store Pattern

The Portfolio Construction UI uses a **two-store pattern** to separate concerns:

```
┌──────────────────────────────────────────────────────────────────┐
│  GLOBAL SINGLETON (portfolio-workspace.svelte.ts in /state/)     │
│                                                                  │
│  class PortfolioWorkspaceState {                                 │
│    portfolio = $state<ModelPortfolio | null>(null)               │
│    universe  = $state<UniverseFund[]>([])                        │
│    fundsByBlock = $derived.by(() => groupBy(schema.funds))       │
│    loading   = $state(false)                                     │
│  }                                                               │
│                                                                  │
│  Methods:                                                        │
│    addFundToBlock(fund, blockId) → equal-weight recalc           │
│    construct(portfolioId) → POST /construct                      │
│    stress(portfolioId, request) → POST /stress-test              │
│    rebalance(portfolioId, request) → POST /rebalance/preview     │
│    setMacroShocks(equity%, rates_bps, credit_bps) → per-block    │
│                                                                  │
│  export const workspace = new PortfolioWorkspaceState()          │
└──────────────────────┬───────────────────────────────────────────┘
                       │ used by create wizard + DnD + advisor
                       │
┌──────────────────────▼───────────────────────────────────────────┐
│  PER-INSTANCE FACTORY (portfolio-workspace.svelte.ts in /stores/)│
│                                                                  │
│  createPortfolioWorkspace(config) → PortfolioWorkspaceStore      │
│                                                                  │
│  State (all $state):                                             │
│    drift: LiveDriftResult | null                                 │
│    driftLoading, driftError                                      │
│    rebalancePreview: RebalancePreviewResult | null               │
│    rebalanceLoading, rebalanceError                              │
│    strategyAlerts: StrategyDriftAlert[]                          │
│    monitoringAlerts: MonitoringAlert[]                            │
│                                                                  │
│  Lifecycle:                                                      │
│    startPolling() → setInterval(fetchDrift, 30s) + initial fetch │
│    destroy() → clearInterval                                     │
│                                                                  │
│  Used in: [portfolioId]/+page.svelte via onMount/onDestroy       │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  PER-INSTANCE FACTORY (portfolio-reports.svelte.ts)              │
│                                                                  │
│  createPortfolioReportsStore(config) → ReportsStore              │
│                                                                  │
│  State:                                                          │
│    reports: ReportHistoryItem[]                                  │
│    jobs: Map<string, JobProgress>                                │
│    abortControllers: Map<string, AbortController>                │
│                                                                  │
│  SSE: fetch() + ReadableStream (not EventSource — auth headers)  │
│  Events: progress → update %, done → mark complete, error → fail │
└──────────────────────────────────────────────────────────────────┘
```

### B.2 Reactivity Chain — Adding a Fund via DnD

```
User drags fund from UniversePanel
  │
  ▼
UniversePanel.handleDragStart(e, fund)
  → e.dataTransfer.setData("text/plain", fund.instrument_id)
  │
  ▼
PortfolioOverview.handleDrop(e, blockId)
  → instrumentId = e.dataTransfer.getData("text/plain")
  → validate: fund exists in universe, not already in block
  │
  ▼
workspace.addFundToBlock(fund, blockId)                    ← MUTATION
  → schema.funds.push({instrument_id, block_id, weight: 0, ...})
  → blockFunds = schema.funds.filter(f => f.block_id === blockId)
  → equalWeight = Math.round((1 / blockFunds.length) * 10000) / 10000
  → for (f of blockFunds) f.weight = equalWeight            ← EQUAL-WEIGHT
  → portfolio = {...portfolio}                               ← TRIGGERS $derived
  │
  ├──▶ fundsByBlock = $derived.by(...)                      ← RECOMPUTES
  │      → Map<blockId, InstrumentWeight[]> rebuilt
  │
  ├──▶ Template re-renders block cards
  │      → Weight column: {formatPercent(fund.weight)}
  │      → Total weight strip updates
  │
  └──▶ Allocated fund card in UniversePanel dims (opacity: 0.5)
```

### B.3 Reactivity Chain — Optimizer Reconstruction

```
User clicks "Re-construct" (Builder Step 4 or Detail page)
  │
  ▼
workspace.construct(portfolioId)
  → POST /model-portfolios/{id}/construct
  → Backend: CLARABEL 4-phase cascade (10-30s)
    Phase 1: max risk-adjusted return
    Phase 1.5: robust SOCP (ellipsoidal uncertainty)
    Phase 2: variance-capped
    Phase 3: min-variance
    Fallback: heuristic
  │
  ▼
Response: ModelPortfolioRead with updated fund_selection_schema
  → schema.funds[].weight = optimizer weights (sum ≈ 1.0)
  → schema.optimization = {expected_return, volatility, sharpe, cvar_95, solver, status}
  │
  ▼
workspace.portfolio = response                              ← MUTATION
  → All $derived recompute
  → UI updates: pie chart, weight bars, risk metrics panel
```

### B.4 Reactivity Chain — Drift Polling

```
onMount → ws = createPortfolioWorkspace({portfolioId, getToken})
  │
  ▼
ws.startPolling()
  → fetchDrift() (immediate)
  → setInterval(fetchDrift, 30_000)                         ← 30s POLL
  │
  ▼ (every 30s)
GET /model-portfolios/{id}/drift/live
  → Backend: reads fund_selection_schema + live NAV prices
  → Computes current_weight per block from market values
  → Calls compute_block_drifts(current, target)
  │
  ▼
drift = $state<LiveDriftResult>(response)                   ← MUTATION
  → DriftGauge.svelte re-renders (color-coded bars)
  → rebalance_recommended flag → "Rebalance Needed" badge
  │
  ▼
onDestroy → ws.destroy()
  → clearInterval(driftTimer)
```

---

## C. Drag-and-Drop Mechanics

### C.1 Technology

**HTML5 Native DataTransfer API** — no external library (no `svelte-dnd-action`).

### C.2 Implementation Assessment

| Aspect | Implementation | Rating |
|--------|----------------|--------|
| **Drag source** | `UniversePanel.svelte`: `ondragstart` sets `effectAllowed = "copy"`, payload = `instrument_id` in `text/plain` | Solid |
| **Drop target** | `PortfolioOverview.svelte`: per-block `ondragover/enter/leave/drop` with state machine (`idle → accept → idle` or `idle → reject → idle`) | Solid |
| **Visual feedback** | Accept: dashed green border + glow. Reject: dashed red border (600ms flash). Allocated: dimmed opacity 0.5. | Good UX |
| **Validation** | Drop handler validates: fund exists in universe, block_id matches, fund not already allocated to this block | Sufficient |
| **Accessibility** | No keyboard DnD alternative. No `aria-grabbed`, `aria-dropeffect`. | Gap |
| **Mobile/touch** | HTML5 DnD has poor mobile support. No touch fallback. | Gap (low priority for institutional desktop app) |
| **Multi-item drag** | Not supported. Single fund per drag operation. | Acceptable |
| **Cross-block reorder** | Not supported. Funds stay in their dropped block. | By design |

### C.3 Drop Zone State Machine

```
          ondragenter
idle ──────────────────▶ accept (green dashed border)
  ▲                          │
  │     ondragleave          │ ondrop
  │     (if exiting zone)    │
  └──────────────────────────┘
                             │
                             ▼ (if validation fails)
                        reject (red dashed border, 600ms)
                             │
                             └──▶ idle (setTimeout)
```

---

## D. Allocation Mechanics & Weight Normalization

### D.1 Where Weights Are Validated

| Layer | Location | What It Does | Sum=1.0? |
|-------|----------|-------------|----------|
| **Frontend DnD** | `portfolio-workspace.svelte.ts` (global) `addFundToBlock()` | Equal-weight within block: `1/n` per fund, 4-decimal precision | Per-block only |
| **Frontend Allocation** | `AllocationView.svelte` | Strategic/tactical editing with simulation preview | Via POST /simulate |
| **Pydantic schema** | `StrategicAllocationUpdate.validate_weights_sum()` | `sum(target_weight) ∈ [0.99, 1.01]` | Yes (±1%) |
| **Pydantic schema** | `StrategicAllocationItem.validate_weight_bounds()` | `min ≤ target ≤ max`, `min ≤ max` | N/A |
| **Optimizer output** | `optimizer_service.py` `_extract_weights()` | `w_arr /= total` post-solve normalization | Yes (exact) |
| **Rebalance preview** | `preview_service.py` | Cash = residual `max(1.0 - fund_sum, 0.0)` | Implicit |
| **Rebalance apply** | `model_portfolios.py` `_apply_weights_to_selection()` | Proportional redistribution within blocks | Preserved |
| **Cash sweep** | `preview_service.py` `_apply_cash_sweep()` | `sum(trade_value) == 0` (neutrality within $0.01) | Trade-neutral |

### D.2 Dual Validation Assessment

**Strategic allocation weights:** Validated in both frontend (simulation preview) and backend (Pydantic ±1% tolerance). **Double-validated.**

**Fund-level weights (fund_selection_schema):** The optimizer normalizes to exactly 1.0 on output. But `fund_selection_schema` is JSONB — there is **no Pydantic validator on the JSONB content itself** when the schema is persisted. The frontend `addFundToBlock()` sets equal weights per block but does NOT enforce that the sum across all blocks equals 1.0.

**Gap:** After DnD additions (before re-construction), the sum of all fund weights may not equal 1.0 if blocks have unequal strategic allocations. This is acceptable because the state is a "draft" and the optimizer will normalize on construction. But the UI should show a warning if weights diverge significantly.

---

## E. Backend Integration Map

### E.1 Complete Endpoint Inventory (Frontend ↔ Backend)

| Frontend Action | Method | Endpoint | Request | Response |
|----------------|--------|----------|---------|----------|
| Create portfolio | POST | `/model-portfolios` | `ModelPortfolioCreate` | `ModelPortfolioRead` |
| List portfolios | GET | `/model-portfolios` | — | `list[ModelPortfolioRead]` |
| Get portfolio detail | GET | `/model-portfolios/{id}` | — | `ModelPortfolioRead` |
| Update metadata | PATCH | `/model-portfolios/{id}` | `ModelPortfolioUpdate` | `ModelPortfolioRead` |
| Run optimizer | POST | `/model-portfolios/{id}/construct` | — | `ModelPortfolioRead` |
| Activate | POST | `/model-portfolios/{id}/activate` | — | `ModelPortfolioRead` |
| Backtest | POST | `/model-portfolios/{id}/backtest` | — | `dict` |
| Historical stress | POST | `/model-portfolios/{id}/stress` | — | `dict` |
| Parametric stress | POST | `/model-portfolios/{id}/stress-test` | `StressTestRequest` | `StressTestResponse` |
| Holdings overlap | GET | `/model-portfolios/{id}/overlap` | query: `limit_pct` | `OverlapResultRead` |
| Construction advice | POST | `/model-portfolios/{id}/construction-advice` | — | `ConstructionAdviceRead` |
| Block drift (snapshot) | GET | `/model-portfolios/{id}/drift` | — | `DriftReportRead` |
| Live drift (NAV) | GET | `/model-portfolios/{id}/drift/live` | — | `LiveDriftResponse` |
| Rebalance preview | POST | `/model-portfolios/{id}/rebalance/preview` | `RebalancePreviewRequest` | `RebalancePreviewResponse` |
| Apply rebalance | POST | `/rebalancing/proposals/{id}/apply` | — | `PortfolioSnapshotRead` |
| Simulate allocation | POST | `/allocation/{profile}/simulate` | allocation payload | `SimulationResult` |
| Save allocation | POST | `/allocation/{profile}/save` | `StrategicAllocationUpdate` | — |
| Strategy drift alerts | GET | `/analytics/strategy-drift/alerts` | query: severity, limit | `list[StrategyDriftRead]` |
| Strategy drift scan | POST | `/analytics/strategy-drift/scan` | — | `StrategyDriftScanRead` |
| Monitoring alerts | GET | `/monitoring/alerts` | — | `AlertBatchRead` |
| Load approved universe | GET | `/universe` | — | fund list |
| Report history | GET | `/model-portfolios/{id}/reports` | — | report list |
| Generate report | POST | `/model-portfolios/{id}/reports/generate` | — | `{job_id}` |
| Stream progress (SSE) | GET | `/model-portfolios/{id}/reports/stream/{jobId}` | — | SSE events |
| Download fact sheet | GET | `/fact-sheets/{path}/download` | — | PDF binary |

### E.2 Drift → Rebalance Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│  DAILY WORKERS (Background)                                      │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  portfolio_nav_synthesizer (lock 900_030)                        │
│    → weighted NAV from nav_timeseries → model_portfolio_nav      │
│                                                                  │
│  portfolio_eval (lock 900_008)                                   │
│    → CVaR + regime detection → PortfolioSnapshot                 │
│    → breach alerts via Redis pub/sub                             │
│                                                                  │
│  drift_check (lock 42)                                           │
│    → For each profile:                                           │
│      1. Load latest PortfolioSnapshot.weights                    │
│      2. Load StrategicAllocation + TacticalPosition              │
│      3. compute_block_drifts(current, strategic + tactical)      │
│      4. If rebalance_recommended:                                │
│         → INSERT RebalanceEvent(status='pending',                │
│           event_type='drift_rebalance')                          │
│                                                                  │
│  risk_calc (lock 900_007)                                        │
│    → FundRiskMetrics (7 metrics + momentum + GARCH)              │
│                                                                  │
│  drift_check (lock 42) — strategy drift via aeon DTW             │
│    → StrategyDriftAlert (Z-score anomaly per instrument)         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                       │
                       ▼ Data in DB
┌──────────────────────────────────────────────────────────────────┐
│  USER-FACING ENDPOINTS (On-Demand)                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  GET /drift → reads latest PortfolioSnapshot                     │
│    → compute_block_drifts() → DriftReportRead                    │
│                                                                  │
│  GET /drift/live → reads fund_selection_schema + live NAV        │
│    → current_weight = (fund_weight * fund_nav) / total_aum       │
│    → compute_block_drifts() → LiveDriftResponse                  │
│                                                                  │
│  POST /rebalance/preview → stateless                             │
│    → target from fund_selection_schema                           │
│    → current from request body (external custodian positions)    │
│    → delta → BUY/SELL/HOLD trades + cash sweep                  │
│    → RebalancePreviewResponse                                    │
│                                                                  │
│  POST /proposals/{id}/apply → applies RebalanceEvent             │
│    → _apply_weights_to_selection() proportional redistrib        │
│    → new PortfolioSnapshot + ModelPortfolioNav breakpoint        │
│    → portfolio_nav_synthesizer reprocesses from breakpoint       │
│                                                                  │
│  GET /monitoring/alerts → scan_alerts()                          │
│    → DD expiry (>360d) + rebalance overdue (>90d)                │
│    → AlertBatchRead                                              │
│                                                                  │
│  GET /strategy-drift/alerts → DB read (is_current=True)          │
│  POST /strategy-drift/scan → full org scan (advisory lock)       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                       │
                       ▼ API responses
┌──────────────────────────────────────────────────────────────────┐
│  FRONTEND STORES (Svelte 5 Runes)                                │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  createPortfolioWorkspace()                                      │
│    drift = $state(null)     ← GET /drift/live (polled 30s)       │
│    rebalancePreview = $state(null) ← POST /rebalance/preview     │
│    strategyAlerts = $state([]) ← GET /strategy-drift/alerts      │
│    monitoringAlerts = $state([]) ← GET /monitoring/alerts        │
│                                                                  │
│  Components read $state → render:                                │
│    DriftGauge ← drift                                            │
│    RebalancePreview ← rebalancePreview                           │
│    StrategyDriftAlerts ← strategyAlerts                          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## F. Gaps & Recommendations

### F.1 Critical Gaps (Must Fix)

| # | Gap | Impact | Recommendation |
|---|-----|--------|----------------|
| **G1** | **`fund_selection_schema` JSONB has no Pydantic validator for fund weights** — weights inside the JSONB dict are not validated on create/update. Only the optimizer normalizes them. | A malformed API call could persist weights summing to 1.5 or 0.3. Drift and rebalance computations would produce nonsensical results. | Add a `@model_validator` on `ModelPortfolioCreate`/`ModelPortfolioUpdate` that validates `sum(funds[].weight) ∈ [0.98, 1.02]` when `fund_selection_schema` is provided. Allow wider tolerance for draft status. |
| **G2** | **No "weight budget" indicator in DnD UI** — after adding funds via drag-and-drop (equal-weight per block), the sum across all blocks may not equal 1.0. The UI does not warn the user. | User confusion: "I added 3 funds to equities and 2 to fixed income but my total is 83%". | Add a derived `totalWeight` in the global workspace that sums all `fund.weight` across blocks. Display a "Total: X%" badge that turns amber if < 98% or > 102%. |
| **G3** | **Rebalance preview does NOT validate CVaR** — `preview_service.py` is stateless and does not check whether suggested trades would violate the portfolio's CVaR limit. | User could execute a rebalance that pushes CVaR beyond the hard limit, requiring a second rebalance cycle to correct. | Add optional CVaR estimation to preview response (can be approximate using current optimizer weights + delta). At minimum, add a `cvar_warning: bool` flag. |

### F.2 Important Gaps (Should Fix)

| # | Gap | Impact | Recommendation |
|---|-----|--------|----------------|
| **G4** | **No keyboard-accessible DnD** — HTML5 DataTransfer has no keyboard equivalent. Power users (institutional analysts) may prefer keyboard workflows. | Accessibility gap. Low urgency for institutional desktop app but blocks WCAG AA compliance. | Add keyboard shortcuts: select fund with Enter → assign to block with number keys (1-5). Or use `FundSelectionEditor` (checkbox-based) as the primary flow, with DnD as enhancement. |
| **G5** | **Drift computation assumes weights sum to 1.0** — `compute_block_drifts()` in `drift_service.py` does not validate input weights. | If `PortfolioSnapshot.weights` has a rounding error (e.g., sums to 0.9997), drift magnitudes may be slightly off. | Add a normalization step at the top of `compute_block_drifts()` or at least an assertion. |
| **G6** | **`instrument_id` in `fund_selection_schema` has no referential integrity** — JSONB cannot enforce FK constraints. A deleted instrument remains in the schema. | Orphan instruments in portfolio after universe cleanup. Drift/overlap would fail silently or with cryptic errors. | Add a `validate_fund_selection()` function called before construct/activate that checks all `instrument_id` values exist in `instruments_org`. |
| **G7** | **No explicit "manual weight editing" UI** — users can only get optimizer-assigned weights or equal-weight from DnD. There is no slider or numeric input to manually set fund weights. | Power users who want to override optimizer suggestions (e.g., "I want exactly 12% in this fund") must edit via API. | Add per-fund weight sliders in `FundSelectionEditor.svelte` with a "normalize to 100%" button. Mark portfolio as `manual_override = true` to distinguish from optimizer output. |
| **G8** | **Data staleness in live drift** — `GET /drift/live` reads `nav_timeseries` which may be days old if the `instrument_ingestion` worker failed. No staleness indicator. | User sees "Live Drift" badge but data may be 3 days old. False sense of freshness. | Include `latest_nav_date` in `LiveDriftResponse`. Frontend shows "as of {date}" instead of "Live". Amber warning if > 1 business day old. |

### F.3 Low Priority / Nice to Have

| # | Gap | Impact | Recommendation |
|---|-----|--------|----------------|
| **G9** | **No undo for DnD** — once a fund is dropped into a block, the only way to remove it is through `FundSelectionEditor`. | Minor UX friction. | Add a "remove" button (X icon) on each fund card in the block. |
| **G10** | **Strategy drift alerts not filtered by portfolio** — `GET /analytics/strategy-drift/alerts` returns all org-wide alerts. The portfolio detail page shows alerts for funds not in this portfolio. | Noise in the drift alerts panel. | Add `instrument_ids` query filter to the endpoint. Frontend passes the portfolio's fund IDs. |
| **G11** | **No batch construction** — creating portfolios for all 3 profiles (conservative/moderate/growth) requires 3 sequential wizard completions. | Tedious for IC workflow where all profiles are typically built together. | Add "Create for all profiles" option in Step 1 that queues 3 parallel constructions. |
| **G12** | **Overlap scanner O(N^2)** — `compute_overlap()` explodes N-PORT holdings for all funds. | Can be slow for portfolios with 20+ funds, each with 500+ holdings. | Add pagination or top-K limit to the overlap endpoint. Already has `limit_pct` parameter; ensure it's used to prune early. |

### F.4 Architecture Observations (No Action Needed)

| Observation | Assessment |
|-------------|------------|
| **Two-store pattern** (global singleton + per-instance factory) | Well-architected. Prevents stale state leaks between portfolio detail pages. |
| **SSE via fetch() + ReadableStream** (not EventSource) | Correct for auth-header requirement. AbortController cleanup prevents memory leaks. |
| **HTML5 native DnD** (no library) | Appropriate for the use case. Lower bundle size, sufficient for block-level drop zones. |
| **Stateless rebalance preview** | Good design — no side effects, can be called repeatedly without risk. |
| **Cash as residual** (not explicit allocation) | Standard institutional practice. Cash = 1.0 - sum(fund_weights). |
| **CLARABEL 4-phase cascade** | Production-grade. Fallback chain ensures a solution is always returned. |
| **30s drift polling** | Reasonable for institutional use. Not real-time but sufficient for daily monitoring. |
| **Governed save flow** (ConsequenceDialog + rationale) | Matches institutional audit requirements. |

---

## Summary

The Portfolio Construction module is **~90% complete**. The frontend implements a sophisticated 5-step wizard with HTML5 DnD, real-time drift monitoring, SSE-powered report generation, and a clean two-store Svelte 5 runes architecture. The backend provides 21+ endpoints covering the full lifecycle from portfolio creation through optimization, stress testing, drift detection, and rebalancing.

**The 3 critical gaps are:** (1) no Pydantic validation on `fund_selection_schema` JSONB weights, (2) no total-weight budget indicator in the DnD UI, and (3) rebalance preview lacks CVaR awareness. All three are addressable with minimal code changes and do not require architectural refactoring.
