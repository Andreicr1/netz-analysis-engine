# Portfolio Construction Frontend Audit

> Audit date: 2026-03-31
> Reference: `docs/reference/portfolio-construction-complete-reference.md`
> Scope: Wealth frontend (`frontends/wealth/`) — all pages, components, types, and stores related to the 11-stage portfolio construction pipeline.

---

## Methodology

Each of the 11 pipeline stages documented in the reference was evaluated against the frontend implementation. For each stage, the audit checks:

1. **Visibility** — Is the stage's output visible to the user?
2. **Interactivity** — Can the user trigger, configure, or influence the stage?
3. **Feedback** — Does the user see loading states, errors, and success confirmations?
4. **Data completeness** — Are all fields from the backend schema rendered?
5. **Transitions** — Are navigation flows and state transitions correct?

---

## Stage-by-Stage Audit

### Stage 1 — Regime Detection

| Aspect | Status | Notes |
|--------|--------|-------|
| Regime badge on Dashboard | OK | `dashboard/+page.svelte:114` — shows current regime via `riskStore.regime` with SSR fallback |
| Regime badge on Portfolio Workbench | OK | `portfolios/[profile]/+page.svelte:304` — `StatusBadge` with live regime |
| Regime labels & colors | OK | `constants/regime.ts` — all 4 regimes mapped (RISK_ON, RISK_OFF, INFLATION, CRISIS) |
| Regional regime breakdown | **GAP** | Backend computes per-region regimes (US, Europe, Asia, EM) with GDP-weighted composition. Frontend only shows the final global regime. No regional detail is exposed. |
| Regime CVaR multiplier display | **GAP** | The effective CVaR multiplier (1.00 / 0.85 / 0.70 / 0.90) applied by the current regime is never shown. The user cannot see how regime detection tightened/loosened their CVaR constraint. |
| Regime history | PARTIAL | `risk-store.svelte.ts` fetches `/risk/regime/history` but no component renders it. The data is available in the store (`regimeHistory`) but no chart or timeline consumes it. |
| Regime confidence | **GAP** | `RegimeData` type includes `confidence: number | null` but no UI renders it. |

**Impact:** Users see which regime is active but lack understanding of *why* (regional breakdown) and *how much* it affects their portfolio (CVaR multiplier). Regime history is fetched but invisible.

---

### Stage 2 — Strategic Allocation

| Aspect | Status | Notes |
|--------|--------|-------|
| Allocation blocks display | OK | `portfolios/[profile]/+page.svelte` Strategic tab — table with block, target, min, max |
| Block taxonomy (16 blocks) | PARTIAL | `blockLabel()` in `model-portfolio.ts:114` only maps 9 of 16 blocks (missing `na_equity_growth`, `na_equity_value`, `dm_europe_equity`, `dm_asia_equity`, `em_equity`, `fi_us_tips`, `alt_commodities`). Unmapped blocks fall through to `blockId.replace(/_/g, " ")` which is readable but inconsistent with the reference. |
| Regime-tilted allocation | **GAP** | Backend's `compute_regime_tilted_weights()` adjusts neutral allocation based on regime. Frontend shows strategic weights but not the regime-tilted effective allocation with tilt explanations. The user cannot see tilt direction/magnitude per asset class. |
| Regional tilts (equity) | **GAP** | Backend applies regional macro score tilts to equity blocks. Frontend does not expose the regional scores or the resulting equity-specific adjustments. |
| Allocation editing | OK | `portfolios/[profile]/+page.svelte:371-431` — inline weight editor with total validation (must = 100%), bounds validation, delta display, ConsequenceDialog with rationale |
| Effective allocation view | OK | Effective tab shows strategic + tactical OW + effective + bounds per block |
| Tactical tab | OK | Shows current snapshot weights with bar visualization |

**Impact:** The user can manage strategic allocation but cannot see regime-driven tilts or regional adjustments. They lose insight into why effective allocation differs from their neutral strategic targets.

---

### Stage 3 — Universe Loading

| Aspect | Status | Notes |
|--------|--------|-------|
| Fund selection in wizard | OK | `create/+page.svelte` Step 2 — block sidebar + fund checkboxes from approved universe |
| Approval filter | OK | `approvedFunds = universe.filter(f => f.approval_decision === "approved")` |
| Geography pre-filter | OK | `BLOCK_GEOGRAPHY` mapping with toggle to show all |
| Block coverage indicator | OK | Counter shows `coveredBlocks / totalBlocks` |
| Fund scoring display (manager_score) | PARTIAL | Score is shown in fund tables as a number (`fund.score.toFixed(1)`) but the 6-component breakdown (return consistency, risk-adj return, drawdown, IR, momentum, fee efficiency) is not decomposed anywhere. Users see a composite number without understanding its drivers. |
| Missing block constraint rescaling | **GAP** | When the approved universe doesn't cover all strategic blocks, the backend rescales min/max proportionally. The wizard shows "{N} blocks skipped — the optimizer will redistribute weight proportionally" but does not show the rescaled constraint values. |

**Impact:** Users can select funds by block but cannot see score decomposition or understand how the optimizer handles partial universe coverage.

---

### Stage 4 — Statistical Inputs

| Aspect | Status | Notes |
|--------|--------|-------|
| Covariance method display | **GAP** | Backend uses Ledoit-Wolf shrinkage (default) or sample covariance. The method used is not shown in construction results. |
| Returns lookback window | **GAP** | The lookback window (120+ trading days, configurable) is not displayed. Users don't know how much history the optimizer used. |
| Black-Litterman indication | PARTIAL | IC Views Panel (`ICViewsPanel.svelte`) allows CRUD for BL views, and the empty state says "optimizer uses market equilibrium prior". However, after construction, there's no indication of whether BL was actually used vs. historical mean returns. |
| Fee adjustment flag | **GAP** | Backend can subtract expense ratios from expected returns (`fee_adjustment.enabled`). No indication in the UI of whether this was applied. |
| Data sufficiency warning | **GAP** | When < 120 aligned trading days are available, the backend falls back to heuristic. The construction result shows `solver` status but doesn't explain "insufficient aligned trading days between funds X, Y, Z". |
| Higher moments (skew/kurtosis) | **GAP** | Backend computes portfolio skewness/kurtosis for Cornish-Fisher CVaR. These are not shown anywhere. At extreme values (|skew| > 2.5 or |kurtosis| > 12), CF becomes unreliable — this condition is not surfaced. |

**Impact:** Users have zero visibility into the statistical inputs that drive the optimizer. They cannot assess data quality, estimation method, or parameter sensitivity.

---

### Stage 5 — CLARABEL Optimizer Cascade

| Aspect | Status | Notes |
|--------|--------|-------|
| "Construct Portfolio" button | OK | `[portfolioId]/+page.svelte:301` — enabled when no fund_selection_schema exists |
| "Re-construct" button | OK | Line 304 — enabled after first construction |
| Loading state | OK | `constructing` flag disables button and shows "Constructing..." |
| Error handling | OK | Catch block shows error message |
| Solver display | OK | `optimizationMeta.solver` shown in Construction Result header (e.g. "CLARABEL") |
| Status display | OK | `optimizationMeta.status` shown (e.g. "optimal", "optimal:cvar_constrained") |
| Cascade phase explanation | **GAP** | The status string (e.g. "optimal:min_variance_fallback") is shown raw. No human-readable explanation of what each phase means. The user sees "optimal:robust" without knowing it means "Phase 1.5 SOCP was needed because Phase 1 violated CVaR". |
| Phase progression indicator | **GAP** | No indication of which phases were attempted. E.g., "Phase 1 failed CVaR → Phase 2 succeeded" would help users understand optimizer behavior. |
| Turnover penalty display | **GAP** | Backend supports turnover cost (L1 penalty). No display of whether turnover penalty was applied or its magnitude. |
| Robust optimization flag | **GAP** | Backend supports robust SOCP (Phase 1.5) via `robust: true` config. No toggle or indicator in the UI. |

**Impact:** Users see that construction succeeded and which solver was used, but cannot understand the cascade decision path or why a particular phase was chosen.

---

### Stage 6 — Portfolio Composition

| Aspect | Status | Notes |
|--------|--------|-------|
| Fund table | OK | `[portfolioId]/+page.svelte:620-654` — instrument name, type badge, block, weight, score, weight bar |
| Block allocation aggregation | OK | Lines 570-589 — bar chart per block with weight % and fund count |
| Optimization metrics | OK | Lines 522-569 — expected return, volatility, Sharpe, CVaR 95%, CVaR limit, status |
| CVaR within limit indicator | OK | Red/green coloring + text "Within limit" / "Exceeds limit" |
| Factor exposures | OK | Lines 560-568 — factor chips if available (e.g. "VIX_inv: 45.0%") |
| Factor exposure labels | PARTIAL | Factors are displayed with raw labels (e.g. `VIX_inv`, `DGS10`, `factor_3`). No human-readable interpretation. |
| Day-0 snapshot creation | INVISIBLE | Backend creates PortfolioSnapshot after composition. No confirmation or display of snapshot creation in the UI. |
| Heuristic fallback indicator | PARTIAL | The wizard Step 4 checks for `heuristic_fallback` in solver to block advancement. However, in the workbench detail page, there's no distinct visual treatment for heuristic results vs. optimizer results. |
| Fund removal/weight override | **GAP** | Users cannot manually remove a fund from the composition or override individual weights before activation. The optimizer output is take-it-or-leave-it. |

**Impact:** Composition display is solid. Main gaps are in explainability (factor labels, heuristic indication) and user agency (no manual weight override).

---

### Stage 7 — Construction Advisor

| Aspect | Status | Notes |
|--------|--------|-------|
| Auto-trigger on CVaR failure | OK | `$effect` at line 81 auto-fetches advice when `!cvarWithinLimit` |
| Coverage progress bar | OK | `ConstructionAdvisor.svelte:238-248` — X% blocks covered |
| Block gap analysis | OK | Accordion per block with target/gap/priority display |
| Candidate table | OK | 7 columns: Fund, Vol 1Y, Corr, Overlap, Proj CVaR, Improvement, Add button |
| Single-fund add | OK | Import from catalog if needed + assign to block + toast notification |
| Batch add (MVS) | OK | Sticky footer with "Add All & Re-construct" + ConsequenceDialog |
| Alternative profile suggestion | OK | Lines 342-355 — shows if current CVaR would pass a different profile |
| No-solution message | OK | Lines 381-385 — suggests expanding catalog or adjusting profile |
| "Browse Catalog" link | OK | Line 271 — link to screener when no candidates for a block |
| Candidate scoring weights display | **GAP** | Backend uses configurable weights (vol 40%, corr 35%, overlap 15%, sharpe 10%). These weights are not shown. Users don't know how candidates are ranked. |
| MVS search method display | **GAP** | Backend returns `search_method` ("brute_force" or "greedy_swap") in `MinimumViableSet`. The type is defined but not rendered. |
| Projected CVaR is heuristic badge | OK | Line 232-234 — shows badge when projections are heuristic |

**Impact:** The advisor is well-implemented with complete UX flow. Minor gaps in transparency (ranking weights, search method).

---

### Stage 8 — Validation (Backtest + Stress)

| Aspect | Status | Notes |
|--------|--------|-------|
| "Run Backtest" button | OK | `[portfolioId]/+page.svelte:307` — triggers `POST /backtest` |
| Backtest metrics | OK | Mean Sharpe, Std Sharpe, Positive Folds displayed |
| Backtest folds table | OK | Per-fold: Sharpe, CVaR 95%, Max DD, Observations |
| "Stress Test" button | OK | Line 309 — triggers `POST /stress` |
| Historical stress scenarios | OK | Bar chart per scenario (GFC, COVID, Taper, Rate Shock) + Max DD + Recovery days |
| Parametric stress | OK | Lines 426-516 — preset selector + custom per-block shock inputs + results display |
| Parametric stress results | OK | NAV impact %, stressed CVaR, per-block impact bars, worst/best block |
| Scenario labels | PARTIAL | `scenarioLabel()` only maps 3 of 4 scenarios explicitly (`2008_gfc`, `2020_covid`, `2022_rate_hike`). Missing explicit label for `taper_2013` — falls through to generic `name.replace(/_/g, " ")`. |
| Backtest equity curve chart | **GAP** | Section title says "Backtest — Walk-Forward CV" but only shows metric cards and fold table. No equity curve visualization (cumulative return chart over time). The reference describes walk-forward with expanding window — a chart would be the natural visualization. |
| Backtest youngest fund start | **GAP** | `BacktestResult.youngest_fund_start` is typed but never rendered. This is useful context — tells users "backtest is limited to data since [date] because [fund] was launched then". |
| Stress recovery visualization | **GAP** | Recovery days are shown as text but no drawdown/recovery chart. For a committee presentation, a visual drawdown curve per scenario would be more impactful. |
| Validation sequencing guidance | **GAP** | No guidance on recommended validation order (backtest first → stress → review → activate). The buttons are presented as independent actions with no suggested workflow. |

**Impact:** Core validation functionality is present. The main UX gap is the absence of charts — backtest results are table-only, and stress results use simple bars. For an institutional IC presentation, charts would significantly improve comprehension.

---

### Stage 9 — Activation

| Aspect | Status | Notes |
|--------|--------|-------|
| "Activate" button | OK | `[portfolioId]/+page.svelte:315-319` — visible only for draft + fund_selection_schema + CVaR within limit |
| CVaR guard | OK | `canActivate` derived checks `cvarWithinLimit`. Button disabled with tooltip when CVaR exceeds limit. |
| HTTP 409 handling | OK | Error catch block shows activation error message |
| Status lifecycle display | PARTIAL | `StatusBadge` shows current status but there's no visual stepper/timeline showing `draft → constructed → validated → active`. |
| Activation in wizard (Step 5) | OK | `create/+page.svelte:734-797` — summary table + IC approval checkbox + naming + inception date |
| Wizard activation route | PARTIAL | Wizard uses `PATCH` to set `status: "approved"` (not `POST /activate`). This may bypass the CVaR guard that `POST /activate` enforces on the backend. |
| Deactivation flow | **GAP** | No way to deactivate an active portfolio. No "Deactivate" or "Archive" button exists. Once active, the portfolio has no off-switch in the UI. |
| Re-activation after re-construct | **GAP** | After re-constructing an active portfolio, the status transitions are unclear. Does it go back to draft? The UI doesn't show this path. |

**Impact:** Activation works for the happy path. The wizard may bypass the CVaR guard, and there's no deactivation flow.

---

### Stage 10 — Monitoring

| Aspect | Status | Notes |
|--------|--------|-------|
| Risk Store (SSE + poll) | OK | `risk-store.svelte.ts` — full SSE primary / poll fallback with monotonic version gate |
| CVaR per profile (live) | OK | Dashboard cards + Portfolio Workbench KPIs show live CVaR from store |
| CVaR utilization bar | OK | Dashboard — utilization bar with color coding (green < 80%, yellow 80-99%, red >= 100%) |
| Trigger status badge | OK | Portfolio Workbench shows breach/critical/rebalance_triggered with tooltip |
| Consecutive breach days | OK | Tooltip shows breach day count |
| Drift alerts (DTW) | OK | Dashboard alerts panel shows DTW alerts with instrument name + score |
| Behavior change alerts | OK | Dashboard shows anomaly alerts with severity |
| CVaR history chart | **GAP** | `cvarHistoryByProfile` is fetched and stored (`/risk/{p}/cvar/history`) but no chart renders it. This time-series data could show CVaR evolution over time — critical for IC monitoring. |
| Regime history chart | **GAP** | `regimeHistory` is fetched and stored (`/risk/regime/history`) but no chart renders it. A timeline of regime transitions would help the committee understand market context over time. |
| Portfolio NAV chart | **GAP** | Backend `portfolio_nav_synthesizer` worker computes daily synthetic NAV into `model_portfolio_nav` hypertable. No chart displays the portfolio NAV time series. The dashboard shows static NAV number but no curve. |
| Drift history for portfolio | PARTIAL | `DriftHistoryPanel.svelte` exists and renders per-instrument drift with scatter chart + table. However, it's only used in the screener context, not integrated into the Portfolio Workbench monitoring tab. |
| Connection quality indicator | **GAP** | `risk-store.svelte.ts` exposes `connectionQuality` ("live" / "degraded" / "offline") but no UI component displays it. Users don't know if they're seeing real-time or stale data. |
| Staleness indicator | PARTIAL | `StaleBanner.svelte` component exists but its integration in portfolio pages was not verified. The store sets `status = "stale"` when computed_at is old. |
| Macro indicators | **GAP** | `macroIndicators` is fetched from `/risk/macro` and stored but no component renders it in the monitoring context. |

**Impact:** The risk store is architecturally excellent (SSE + poll + monotonic versioning). However, most of its time-series data (CVaR history, regime history, macro indicators) is fetched but never rendered. The monitoring experience is real-time numbers without trend context.

---

## Cross-Cutting Gaps

### A. Type/Label Inconsistencies

| Issue | Location | Detail |
|-------|----------|--------|
| Block label map incomplete | `model-portfolio.ts:115-127` | Only 9 of 16 blocks mapped. Missing: `na_equity_growth`, `na_equity_value`, `dm_europe_equity`, `dm_asia_equity`, `em_equity`, `fi_us_tips`, `alt_commodities`. |
| Block label duplication | `create/+page.svelte:57-76` vs `model-portfolio.ts:115-127` | Two separate block label maps with different names for same blocks (e.g. wizard: "US Large Cap Equity" vs workbench: "NA Equity Large"). Should be consolidated. |
| Scenario label gap | `model-portfolio.ts:78-85` | `scenarioLabel()` handles 3 of 4+ scenarios. Missing `taper_2013` and `rate_shock_200bps`. |
| `InstrumentWeight.instrument_type` | `model-portfolio.ts:28` | Typed as `"fund" | "bond" | "equity" | null`. Backend sends `"mutual_fund"`, `"etf"`, `"bdc"`, `"money_market"`, etc. Type union is stale. |

### B. Missing Confirmation Dialogs

| Action | Has Dialog? | Risk |
|--------|-------------|------|
| Construct Portfolio | No | Low — non-destructive, can re-construct |
| Re-construct | No | Medium — overwrites current fund_selection_schema |
| Run Backtest | No | Low — additive |
| Run Stress Test | No | Low — additive |
| Activate | No | **High** — irreversible status transition. Should have a ConsequenceDialog with rationale, similar to rebalance. |
| Wizard "Activate & Deploy" | PARTIAL | Has IC approval checkbox but no ConsequenceDialog |

### C. Missing Progress Indicators

| Action | Loading State | Duration Display | Progress Bar |
|--------|-------------|-----------------|-------------|
| Construct | OK ("Constructing...") | No | No |
| Backtest | OK ("Running...") | No | No |
| Stress Test | OK ("Running...") | No | No |
| Advisor fetch | OK (spinner + text) | No | No |
| Batch add (MVS) | OK ("Adding...") | No | No |

For longer operations (construct can take 200ms+, backtest 500ms+), a progress bar or elapsed timer would improve UX. However, these operations are fast enough that spinners are acceptable.

### D. Navigation & Discovery Issues

| Issue | Detail |
|-------|--------|
| No link from Portfolio Workbench to Model Portfolio Workbench | `/portfolios/[profile]` and `/model-portfolios/[id]` are separate pages with complementary views. No cross-navigation. |
| No link from Dashboard to specific portfolio | Dashboard cards show CVaR/NAV per profile but clicking doesn't navigate to `portfolios/[profile]`. |
| No "last constructed" timestamp | After construction, there's no visible timestamp showing when the current fund_selection_schema was generated. |
| No construction history | Users cannot see previous construction results. Each construct overwrites the previous one with no audit trail in the UI. |

### E. IC Views Panel (Black-Litterman)

| Aspect | Status |
|--------|--------|
| View table (active views) | OK — instrument, peer, type, return, confidence bar, dates |
| Add view form | OK — type selector, instrument picker with search, peer picker, return %, confidence slider, date range, rationale |
| Delete view | OK — inline confirm (Remove? Yes/No) |
| Edit view | **GAP** — no edit. Must delete and re-create. |
| View impact preview | **GAP** — after adding a view, no preview of how it changes expected returns before re-constructing. |
| Views ↔ Construction link | **GAP** — no button to "Re-construct with updated views" directly from the IC Views panel. |

### F. Allocation Page (`/allocation`)

| Aspect | Status |
|--------|--------|
| `AllocationView.svelte` | OK — profile tabs, hierarchical table, edit mode with simulation, confirmation dialog |
| Relationship to Portfolio Construction | **GAP** — `/allocation` page and `/model-portfolios` page are independent. Changes in strategic allocation don't prompt re-construction of affected model portfolios. |

---

## Priority-Ranked Recommendations

### P0 — Critical (affects IC decision-making)

1. **CVaR history chart** — Render `cvarHistoryByProfile` as a line chart on the Portfolio Workbench. The data is already fetched. This is the #1 monitoring tool for IC members.

2. **Portfolio NAV chart** — Add a time-series chart using `model_portfolio_nav` data. The backend synthesizes daily NAV but no chart exists. Without it, users cannot see portfolio performance over time.

3. **Activation confirmation dialog** — Add ConsequenceDialog before `POST /activate`. This is an irreversible status transition that should require explicit rationale, matching the rebalance flow.

4. **Wizard CVaR guard bypass** — The creation wizard uses `PATCH` to set `status: "approved"` instead of `POST /activate`. This may bypass the backend CVaR guard. Should call the same activation endpoint.

### P1 — Important (improves comprehension)

5. **Regime CVaR multiplier display** — Show the effective multiplier (e.g. "RISK_OFF: CVaR tightened by 15%") next to the regime badge on Portfolio Workbench. One line of text adds significant context.

6. **Optimizer cascade explanation** — Map status strings to human-readable descriptions:
   - `optimal` → "Optimal solution found (max risk-adjusted return)"
   - `optimal:robust` → "Robust optimization applied — portfolio resilient to estimation error"
   - `optimal:cvar_constrained` → "Variance-capped — CVaR constraint was binding"
   - `optimal:min_variance_fallback` → "Minimum-variance fallback — all other phases exceeded CVaR"
   - `optimal:cvar_violated` → "Warning: CVaR limit exceeded in all optimization phases"

7. **Backtest equity curve chart** — Add a cumulative return chart to the backtest section. The fold table is informative but a chart is essential for IC presentations.

8. **Block label consolidation** — Create a single `BLOCK_LABELS` constant shared across all components. Currently duplicated in 2+ locations with inconsistent names.

9. **Score decomposition** — When clicking a fund in the composition table, show a breakdown of the 6 scoring components (return consistency 20%, risk-adj return 25%, etc.) with individual values.

### P2 — Nice-to-have (polish & transparency)

10. **Regime history timeline** — Render `regimeHistory` as a horizontal timeline or bar chart showing regime transitions over time.

11. **Regional regime breakdown** — Show per-region regime classification (US, Europe, Asia, EM) with GDP-weighted composition in a tooltip or expandable section.

12. **Connection quality indicator** — Display the SSE connection status ("Live" / "Degraded" / "Offline") somewhere in the layout header.

13. **IC View edit** — Allow editing existing views in-place instead of delete + re-create.

14. **Construction history** — Store and display previous construction results (date, solver, CVaR, status) so users can compare across iterations.

15. **Dashboard card navigation** — Make dashboard portfolio cards clickable → navigate to `/portfolios/[profile]`.

16. **Cross-link Portfolio ↔ Model Portfolio** — Add bidirectional links between `/portfolios/[profile]` and `/model-portfolios/[id]`.

17. **Youngest fund start date** — Render `backtest.youngest_fund_start` in the backtest section as context for data coverage.

18. **Stress drawdown chart** — Add drawdown visualization per stress scenario instead of simple bar + text.

19. **`InstrumentWeight.instrument_type` type fix** — Update the union type to match backend values (`mutual_fund`, `etf`, `bdc`, `money_market`, etc.).

20. **Deactivation flow** — Add ability to deactivate/archive active portfolios.

---

## Component Inventory (Related to Pipeline)

| Component | Stage(s) | Completeness |
|-----------|----------|-------------|
| `dashboard/+page.svelte` | 1, 10 | Regime + CVaR + alerts (no charts) |
| `model-portfolios/+page.svelte` | — | List page (OK) |
| `model-portfolios/create/+page.svelte` | 2, 3, 5, 6, 9 | 5-step wizard (good) |
| `model-portfolios/[portfolioId]/+page.svelte` | 5, 6, 7, 8, 9 | Main workbench (good, gaps in explainability) |
| `portfolios/+page.svelte` | 10 | Profile summary cards (OK) |
| `portfolios/[profile]/+page.svelte` | 2, 10 | 8-tab workbench (good) |
| `model-portfolio/ConstructionAdvisor.svelte` | 7 | Complete (minor gaps) |
| `model-portfolio/ICViewsPanel.svelte` | 4 (BL inputs) | CRUD OK, no edit, no impact preview |
| `PortfolioCard.svelte` | 10 | Display-only summary (OK) |
| `AllocationView.svelte` | 2 | Full allocation editor (OK) |
| `DriftHistoryPanel.svelte` | 10 | Per-instrument drift (not in portfolio context) |
| `risk-store.svelte.ts` | 1, 10 | Excellent architecture, data under-consumed |

---

## Summary

**Overall assessment:** The frontend covers the core happy path well — users can create portfolios, run the optimizer, review results, validate with backtest/stress, and activate. The Construction Advisor is particularly well-implemented with complete UX flow.

**Key theme:** The frontend is *action-complete* but *insight-incomplete*. All backend actions have buttons and API calls. But the rich data the backend computes (CVaR history, regime history, regime multipliers, optimizer cascade details, statistical inputs, factor labels, score decomposition, NAV time series) is either fetched-but-not-rendered or not fetched at all. For an institutional investment committee, *understanding why* is as important as *doing what*.

**Top 4 fixes for maximum impact:**
1. CVaR history line chart (data already in store)
2. Portfolio NAV time-series chart (data in hypertable)
3. Activation confirmation dialog (safety)
4. Optimizer status human-readable labels (1 function, zero API changes)
