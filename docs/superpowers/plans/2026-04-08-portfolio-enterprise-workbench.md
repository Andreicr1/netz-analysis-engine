# Portfolio Enterprise Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is the unified synthesis of five specialist drafts: UX flow, DB schema, components, charts, quant layer. Each phase cites the originating drafts.

**Goal:** Rebuild the Portfolio vertical of Netz Wealth OS into an institutional-grade three-phase workbench: **Builder → Analytics → Live Management**. Today the surface is a single FCL page with a PolicyPanel whose sliders are a literal no-op (`portfolio-workspace.svelte.ts:684-688`), a calibration drawer that exposes 2 of 63 engine inputs, a Run Construct that returns 8 numeric fields with zero narrative, a StressTestPanel that cannot reach the 4 canonical engine scenarios, a "New Portfolio" button with no `onclick`, an allocation Advisor that exists at `construction_advisor.py:789` but is invisible from Builder, no state machine, no approval gate, and no live workbench. This plan closes every one of those gaps by (1) returning the optimizer trace + advisor + stress + validation + narrative in a single `/construct` response, (2) persisting all 63 calibration inputs in a typed `portfolio_calibration` table, (3) persisting every run in `portfolio_construction_runs` with binding constraints and phase trace, (4) introducing a backend-authoritative state machine (`draft → constructed → validated → approved → live → paused → archived`) with `allowed_actions` on every portfolio GET, (5) rebuilding the Builder around a new `CalibrationPanel` (Preview/Apply), `ConstructionNarrative`, and `StressScenarioPanel`, (6) reusing every Discovery primitive (FCL, EnterpriseTable, FilterRail, ChartCard, AnalysisGrid, BottomTabDock, PanelErrorState) for a parity Analytics surface, and finally (7) shipping a Bloomberg-terminal `/portfolio/live` workbench with `WorkbenchLayout`, `WorkbenchCoreChart` (single instance, option rebuild via `replaceMerge: ['series']`), SSE live price ticks buffered via `createTickBuffer`, and a unified alerts feed backed by a new `portfolio_alerts` table and `live_price_poll` worker (lock 900_100). Builder + Analytics ship before Live so product-facing value lands first (per `feedback_phase_ordering`).

**Architecture:** Three distinct surfaces — each with its own layout primitive — unified by a single backend state machine and a single calibration persistence layer.

1. **`/portfolio/builder`** — FCL 3-column (reuses Discovery's `FlexibleColumnLayout`). Col1 = Models/Universe/Policy sub-pills. Col2 = BuilderCanvas (action bar + allocation blocks DnD + chart strip + `ConstructionNarrative` after Run). Col3 = `BuilderRightStack` (Calibration | Narrative | Preview tabs). Approved Universe is a sub-pill of Builder, never a standalone route (per `feedback_universe_lives_in_portfolio`).
2. **`/portfolio/analytics`** — Standalone analytical surface mirroring Discovery Analysis. FilterRail (260px) + AnalysisGrid (3×2 ChartCards) + BottomTabDock. Scope switcher toggles `model_portfolios | approved_universe | compare_both`. Groups: **Returns & Risk | Holdings | Peer | Stress**. Reuses Discovery's `NavHeroChart`, `RollingRiskChart`, `DrawdownUnderwaterChart`, `ReturnDistributionChart`, `MonthlyReturnsHeatmap`, `RiskMetricsBulletChart` verbatim; adds portfolio-specific `BrinsonWaterfallChart`, `FactorExposureBarChart`, `ConstituentCorrelationHeatmap`, `RiskAttributionBarChart`.
3. **`/portfolio/live`** — Bloomberg-terminal workbench. NOT FCL — diverges via a new `WorkbenchLayout` primitive in `@netz/ui` (12-col CSS Grid, 4px gap, 22px row height, 10px axis font, hairline borders, `data-density="workbench"` token set). Central `WorkbenchCoreChart` (single ECharts instance, tool state machine: `nav | drawdown | rollingSharpe | rollingVol | rollingCorrelation | rollingTrackingError | regimeOverlay | intraday`, option rebuild via `setOption(..., { notMerge: false, lazyUpdate: true, replaceMerge: ['series','markLine'] })`), `WeightVectorTable` with SVG sparkline glyphs and `createTickBuffer<PriceTick>`, `AlertsFeedPanel` on persistent SSE, strategic/tactical/effective comparison, rebalance suggestion panel.

**Layout primitives (named once, reused everywhere):**

- **`FlexibleColumnLayout`** — `@netz/ui`, promoted from Discovery Phase 2.2. Builder + Analytics.
- **`EnterpriseTable`** — `@netz/ui`, extracted from `UniverseTable.svelte` in Discovery Phase 2.3. Universe, Models list, Analytics subject table, Live portfolio selector, strategic/tactical/effective allocation tables.
- **`FilterRail`** — `@netz/ui`. Analytics, Universe sub-pill.
- **`ChartCard` + `AnalysisGrid`** — `@netz/ui`. Analytics 3×2 grid.
- **`BottomTabDock`** — `@netz/ui`. Analytics (mandatory persistent cross-subject sessions), Live (optional portfolio switcher).
- **`PanelErrorState`** — `@netz/ui/runtime`. Every `<svelte:boundary>` failed snippet.
- **`WorkbenchLayout`** — `@netz/ui` (NEW). `/portfolio/live` only. The sole intentional divergence from FCL — carries its own `--workbench-*` tokens (admin-overridable via ConfigService per §Phase 8).
- **`CalibrationPanel` + `ConstructionNarrative` + `AllocationComparisonTable` + `NewPortfolioDialog`** — wealth-specific, under `frontends/wealth/src/lib/components/portfolio/`.

**Tech Stack:** SvelteKit 2 + Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`, `$bindable`) + `@netz/ui` + svelte-echarts (LineChart/BarChart/ScatterChart/HeatmapChart/TreemapChart/RadarChart/CustomChart/GraphChart) + FastAPI + PostgreSQL 16 + TimescaleDB + Redis (SSE pub/sub + single-flight locks + Upstash) + pgvector. Backend uses `asyncpg` + `SQLAlchemy 2.0 AsyncSession` + Alembic (current head `0096_discovery_fcl_keyset_indexes`). Frontend SSE via `fetch() + ReadableStream` (never `EventSource` — Clerk JWT headers needed). Zero `localStorage`, zero `.toFixed()`, zero inline `Intl.*` — enforced by `frontends/eslint.config.js`. All formatters from `@netz/ui`.

**Decisions locked (Andrei, 2026-04-08):**

- **DL1. Three-phase URL contract.** `/portfolio/builder`, `/portfolio/analytics`, `/portfolio/live`. Sub-nav ribbon beneath TopNav, always visible under `/portfolio/*`, with derived badges (drafts in progress · subjects under analysis · live portfolios with open alerts). Replaces legacy routes `/portfolio/advanced`, `/portfolio/model`, `/portfolio/analytics` (redirect only; do not delete handlers until visual validation passes). Per UX draft §1.
- **DL2. Universe is a Builder sub-pill.** `/portfolio/builder/universe` (shallow, same layout shell). DnD from Approved Universe table directly into allocation blocks via the workspace store — never a standalone route. Per UX draft §4.5 + memory `feedback_universe_lives_in_portfolio`.
- **DL3. Backend-authoritative state machine.** `draft → constructed → validated → approved → live → paused → archived` (+ `rejected`). Frontend consumes `allowed_actions: string[]` from every portfolio GET and only renders buttons whose actions appear in that array. Zero `if state === "validated"` conditionals in Svelte. Per UX draft §3 + DB draft §2.
- **DL4. Narrative is a first-class persisted artifact.** Every `/construct` writes one row to `portfolio_construction_runs` with `optimizer_trace`, `binding_constraints`, `regime_context`, `ex_ante_metrics`, `ex_ante_vs_previous`, `factor_exposure`, `stress_results[]`, `advisor`, `validation.checks[]`, `narrative{technical,client_safe}`, `rationale_per_weight`. Analytics can replay any run. Cap 10 most recent per portfolio; older `failed` runs pruned after 90 days by `alert_sweeper` worker extension. Per UX draft §4.3 + DB draft §3 + quant draft §B.
- **DL5. Calibration surface is the Builder column 3 spine.** All 63 engine inputs reachable via a `CalibrationPanel` with Basic/Advanced/Expert tiers (5/10/48). Explicit "Preview" + "Apply" gating — never reactive recompute on slider input (rejected for the same reason Andrei's current PolicyPanel feels broken: every drag → 10-30s spinner). Basic default view (`mandate`, `cvar_limit`, `max_single_fund_weight`, `turnover_cap`, `stress_scenarios_active`, `advisor_enabled`). Advanced adds regime override + BL + GARCH + turnover lambda. Expert covers the remaining 47 inputs. Per quant draft §A + components draft Part C.
- **DL6. Advisor is folded into `/construct` response.** `construction_advisor.py` (789 lines, already wired) runs inside `_run_construction_async` after optimizer, before validation. Result embedded as `response.advisor`. Standalone `POST /model-portfolios/{id}/construction-advice` endpoint kept for what-if re-runs with different scoring weights. Advisor credit section appears in `ConstructionNarrative` when `advisor_enabled=true`. Per quant draft §C + UX draft §4.4.
- **DL7. Four canonical stress scenarios visible from Builder and Analytics.** `gfc_2008 | covid_2020 | taper_2013 | rate_shock_200bps` + `custom`. Backend catalog endpoint `GET /portfolio/stress-test/scenarios` enumerates them. UI drops the 3-input custom-only form. `StressScenarioPanel` presents a matrix of all 4 scenarios by default; Custom is a secondary tab. Per quant draft §D + components draft F.2 Stage 3.
- **DL8. Narrative templater is deterministic Jinja2, NEVER LLM.** Pure templater with `jinja2.SandboxedEnvironment` (per CLAUDE.md: prompts are Netz IP, never in client responses, always sandboxed). Reproducible for audit. Sub-second. Consumes the structured construct payload and produces `narrative.headline`, `narrative.key_points[]`, `narrative.constraint_story`, `narrative.holding_changes[]`, `narrative.client_safe`. Per quant draft §J.1.
- **DL9. `WorkbenchCoreChart` is a single ECharts instance with option-rebuild state machine.** Never `notMerge: true` (destroys animation and zoom). Never per-tool `v-if` remounts (40ms cold init churn). Tool switch = `$derived` option rebuild + `setOption(next, { notMerge: false, lazyUpdate: true, replaceMerge: ['series','markLine','markArea'] })`. `dataZoom` must use `filterMode: 'weakFilter'` so brush survives tool switches. Per charts draft A.3 item 10.
- **DL10. Live-price sparklines are SVG paths, NOT ECharts.** The only place in the workbench where ECharts is not mandatory — justified because a no-axes no-tooltip sparkline is a glyph, not a chart. 30+ ECharts instances per row would tank the workbench. `SparklineSVG.svelte` consumes `Float64Array` (typed, zero copy). Per charts draft A.3 item 12 + G.4.
- **DL11. Live prices via dedicated `live_price_poll` worker (lock 900_100, integer literal, NOT `hash()`).** Poll Yahoo batch quote (250 symbols/call) every 60s for instruments held by any `live|paused` portfolio. Write Redis `live:px:v1` hash with TTL 180s. Emit `price_staleness` alert if > 30% instruments stale > 10min. On-demand fallback for newly-added holdings wrapped in `ExternalProviderGate` interactive (30s); batch loop wrapped in `ExternalProviderGate` bulk (5min). No new hypertable for intraday history in v1 — ephemeral by design. Per DB draft §8 + quant draft §G.3.
- **DL12. Alerts via a single unified table `portfolio_alerts` (plain table, partial index, NOT a hypertable).** Replaces fire-and-forget `_publish_alert` in `portfolio_eval.py:138-166`. `portfolio_eval`, `drift_check`, `regime_fit`, `live_price_poll`, `alert_sweeper` all write rows. SSE bridge `/alerts/stream?portfolio_id=...` reads Redis pubsub + falls back to DB on reconnect. Three presentation tiers: persistent feed (Live col1 bottom), critical toast (any `/portfolio/*` page), badge count (sub-nav ribbon pill). Per DB draft §7 + UX draft §7.
- **DL13. Strategic/Tactical/Effective weights live in a `portfolio_weight_snapshots` hypertable (7-day chunks, `segmentby portfolio_id`, compression after 14 days, no drop retention).** Three nullable columns per row — one row per `(org, portfolio, instrument, as_of)`. `portfolio_nav_synthesizer` (lock 900_030) writes the effective column daily. Strategic/tactical written by separate flows (IC view acceptance, manual overlay). Legacy `strategic_allocation` / `tactical_positions` / `portfolio_snapshots` tables kept alive for the 3-profile CVaR monitor — dual coexistence for 1-2 quarters. Per DB draft §6.
- **DL14. Jargon translation table is normative.** Every backend field surfaced to Portfolio UI must have a `@netz/ui` formatter AND a plain-English label AND appear in the translation table in Phase 10 Task 10.1. New backend fields require a translation entry before UI shipping. "CLARABEL", "SOCP", "Ledoit-Wolf", "robust uncertainty set", "Markov filtered" never appear in user-facing copy. Per UX draft §10 + memory `feedback_smart_backend_dumb_frontend`.
- **DL15. No `localStorage` / `sessionStorage` anywhere in wealth code.** All state lives in URL query/hash + in-memory `portfolio-workspace.svelte` store + SSE + cookies (theme only). `BottomTabDock` persists in URL hash (`#tabs=<base64>`), never storage. `CalibrationDraft` persists via `PUT /model-portfolios/{id}/calibration` on Apply — never local. Per memory `feedback_echarts_no_localstorage` + Discovery Phase 8 precedent.
- **DL16. Formatter discipline is absolute.** All number/date/currency formatting via `@netz/ui` formatters (`formatNumber`, `formatCurrency`, `formatPercent`, `formatBps`, `formatDate`, `formatDateTime`, `formatShortDate`). Zero `.toFixed()`, zero `.toLocaleString()`, zero inline `Intl.NumberFormat` / `Intl.DateTimeFormat`. Enforced by `frontends/eslint.config.js`. Phase 10 Task 10.2 sweeps the 5 known violations in `RebalanceSimulationPanel.svelte:259,265,290`, `BuilderTable.svelte:233`, `portfolio/analytics/+page.svelte:60-61`. Per CLAUDE.md + components draft F.1.
- **DL17. `@tanstack/svelte-table` is forbidden.** Broken on Svelte 5 across all three frontends (`project_frontend_platform`). `EnterpriseTable` is the canonical table primitive. `CatalogTable` v1/v2 already eliminated in Discovery Phase 2.4. Per memory `project_frontend_platform`.
- **DL18. Stability guardrails P1-P6 apply to every new worker, route, and component.** Bounded (120s construct timeout), Batched (`execute_many` for weight snapshot upserts), Isolated (RLS subselect on every new tenant-scoped table), Lifecycle (state machine is literal), Idempotent (`@idempotent` decorator on construct/activate/acknowledge routes + `UNIQUE(construction_run_id, scenario)` on stress results), Fault-Tolerant (`ExternalProviderGate` + circuit breakers on Yahoo). Per CLAUDE.md §Stability Guardrails + DB draft §12.
- **DL19. Advisory locks are integer literals or `zlib.crc32` on deterministic byte strings — never Python `hash()`.** Reserved lock IDs for this plan: `900_100` (`live_price_poll`), `900_101` (`construction_run_executor`), `900_102` (`alert_sweeper`). Existing `portfolio_eval` (900_008), `drift_check` (42), `regime_fit` (TBD — confirm in Phase 0), `portfolio_nav_synthesizer` (900_030), `risk_calc` (900_007), `global_risk_metrics` (900_071) untouched. Per CLAUDE.md §Stability Guardrails + DB draft §11.2.
- **DL20. Migration range 0097-0104 reserved for this plan.** Zero overlap with Discovery (0093-0096). Current head at branch base is `0096_discovery_fcl_keyset_indexes`. Phase 0 updates CLAUDE.md. Per DB draft §0 + §10.

---

## Open Decisions for Andrei (BLOCKING — must resolve before `/ce:work`)

`/ce:work` cannot start until Andrei locks each of the following. Each decision is grouped by theme, given an ID, and attributed to the originating draft(s). Where drafts converge on a recommendation, it is stated.

### Theme 1 — Calibration surface shape

- **OD-1. Calibration tier default.** Basic by default with an "Advanced" expand toggle, or Advanced by default with a "Show Expert" toggle? *Drafts: quant §J.1.1, components Part H#2.* **Recommendation:** Basic by default — 80% of Portfolio users are PMs not quants.
- **OD-2. Slider vs numeric input vs paired.** Paired slider + bound numeric input (slider drives number, number drives slider, ↑↓ keyboard nudge by step) — acceptable visual density? *Drafts: components Part H#9.* **Recommendation:** Paired.
- **OD-3. PT vs EN narrative language.** Fact Sheets have PT/EN i18n. Is PT a v1 requirement for Construction Narrative? *Drafts: UX §11.2.5.* **Recommendation:** EN only for v1; PT in v1.1 alongside the client-safe translation layer.
- **OD-4. Scoring weights at construction time.** Should per-run scoring weight overrides be exposed in calibration? *Drafts: quant §J.1.5.* **Recommendation:** NO — scoring is a fund-level cache; per-run tweaks break caching and create incoherent IC discussions. Keep in admin ConfigService only.

### Theme 2 — Construction + validation gate

- **OD-5. Activation gate strictness.** `block`-severity validation failures: HARD block (cannot activate, period) or SOFT block (IC chair can override with rationale + audit log)? *Drafts: quant §J.1.3.* **Recommendation:** Soft with audit log — institutional reality is IC may override on documented judgment.
- **OD-6. 4-eyes approval for single-user orgs.** Hard-block `validated → approved` or allow self-approval with audit flag when `ConfigService.get("wealth","approval_policy",org_id).allow_self_approval=true`? *Drafts: UX §11.2.4.* **Recommendation:** Allow self-approval flagged as `self_approved=true` in the audit row.
- **OD-7. Bulk approve in Universe sub-pill.** Allow select-N-rows → Approve with confirmation modal, or single-row only? *Drafts: UX §11.2.6.* **Recommendation:** Yes, with confirmation modal.

### Theme 3 — Stress test UX

- **OD-8. Stress panel shape.** Single panel with scenario select dropdown (preset/custom) OR two tabs: `ScenarioMatrix` (runs all 4 presets, comparison grid) + `CustomShock` (existing form)? *Drafts: components Part H#3, UX §5.4.* **Recommendation:** Two tabs — institutional users want the comparison view.
- **OD-9. Stress scenario catalog authoring.** Ship user-authored custom scenarios (would need `portfolio_stress_scenarios` catalog table) or defer and only support the 4 presets + inline custom body? *Drafts: DB §13.6.* **Recommendation:** Defer catalog; accept inline custom per run as `scenario_kind='user_defined'`.

### Theme 4 — Live Workbench

- **OD-10. Route name.** `/portfolio/live` (matches three-phase mental model) vs `/workbench` (decouples, matches Bloomberg mental model)? *Drafts: components Part H#4, UX §1.1.* **Recommendation:** `/portfolio/live` — preserves the three-phase ribbon navigation and keeps the vertical scoped.
- **OD-11. Workbench density tokens admin-configurable?** `--workbench-*` tokens hardcoded in `@netz/ui`, or exposed via `ConfigService.get("wealth","workbench_density",org_id)` so some orgs can dial back? *Drafts: components Part H#7, charts D.1, UX §6.1.* **Recommendation:** Admin-overridable via ConfigService (tokens are admin config per `feedback_tokens_vs_components`) but ship with a single default density.
- **OD-12. Portfolio selector UX.** Table (as spec'd in Live col1 top) or sidebar list? *Drafts: UX §11.2.2.* **Recommendation:** Table wins at 3+ portfolios (the only scale worth designing for).
- **OD-13. Multi-portfolio navigation in Live.** Primary = col1 selector. Secondary = `BottomTabDock`. Keep both? *Drafts: UX §8.* **Recommendation:** Keep both — selector is persistent one-active-portfolio detail; BottomTabDock is parallel sessions for comparison. Two different jobs.
- **OD-14. Real-time price provider.** Yahoo Finance batch quote is delayed 15min. Accept (label "near-real-time") or integrate a paid provider (IEX Cloud / Polygon / Alpaca) which changes rate-limit math and budget? *Drafts: DB §13.4, charts Part H#2.* **Recommendation:** Yahoo v1 with "Delayed 15min" label in toolbar; upgrade in v1.1.
- **OD-15. Intraday history persistence.** Ship ephemeral Redis-only (no `nav_intraday` hypertable) or persist 1-min chunks in a new hypertable? *Drafts: DB §13.5, quant §G.3.* **Recommendation:** Ephemeral v1. Add `nav_intraday` hypertable (1min chunks, segmentby `instrument_id`, compression after 7 days) as migration 0105 if workbench demand grows.

### Theme 5 — Rebalance workflow

- **OD-16. Rebalance mutation semantics.** Accepting a rebalance proposal mutates the LIVE portfolio in place (new weights, state stays `live`) OR spawns a NEW draft that must re-traverse `validated → approved → Go Live`? *Drafts: UX §11.2.3.* **Recommendation:** Spawn new draft (institutional norm — preserves audit trail). `state_metadata.parent_live_id = <live_id>` for traceability.
- **OD-17. Rebalance entry point.** Drawer inside Live Workbench right rail vs full route `/portfolio/rebalance/{id}`? *Drafts: UX §11.2.7.* **Recommendation:** Drawer for proposal review + "Open in Builder" CTA for deep edits.

### Theme 6 — Legacy cleanup and backward-compat

- **OD-18. Legacy route deletion.** Redirect `/portfolio/advanced` → `/portfolio/analytics` (same URL works after rebuild)? Delete `/portfolio/model` + `/portfolio/advanced` handlers after visual validation in Phase 10? *Drafts: UX §11.2.9, components Part H#5.* **Recommendation:** Redirect + soft-delete (keep files in git history, remove from routing tree in Phase 10).
- **OD-19. `ModelPortfolio.status` legacy column.** The plan adds a new `state` column on `model_portfolios` and keeps legacy `status` for backward compat. Drop `status` in a cleanup migration inside this sprint or defer? *Drafts: DB §13.2.* **Recommendation:** Defer to a 01xx cleanup migration post-Phase-10.
- **OD-20. `strategic_allocation` / `tactical_positions` / profile-keyed `portfolio_snapshots` dual coexistence.** Keep them alive alongside the new `portfolio_weight_snapshots` hypertable for 1-2 quarters while the 3-profile CVaR monitor migrates off? *Drafts: DB §13.1.* **Recommendation:** Dual coexistence for one full sprint cycle. Hard cutover is out of scope for this plan.
- **OD-21. `PortfolioOverview.svelte` rename vs absorb.** It is the Holdings tree on the Model page, misnamed. Rename to `ModelHoldingsTree.svelte` OR absorb into new `WeightVectorTable` for both Model and Live? *Drafts: components Part H#6.* **Recommendation:** Rename for clarity; `WeightVectorTable` is Live-specific with live-price columns that the Model page does not need.

### Theme 7 — Narrative + regime semantics

- **OD-22. Regime label translation.** Proposed mapping: `NORMAL → "Balanced"`, `RISK_ON → "Expansion"`, `RISK_OFF → "Defensive"`, `CRISIS → "Stress"`, `INFLATION → "Inflation"`. Andrei's preference? *Drafts: UX §11.2.8, quant §F.1 client_safe.* **Recommendation:** Lock the above and add to Phase 10 Task 10.1 translation table.
- **OD-23. Alert dedup strategy.** App-level `payload->>'dedupe_key'` check OR materialized `dedupe_key text` column with partial `UNIQUE(portfolio_id, alert_type, dedupe_key) WHERE dismissed_at IS NULL`? *Drafts: DB §13.7.* **Recommendation:** Materialized column — one more column is cheap, stronger guarantee, better query plan.
- **OD-24. Portfolio-scoped drift alert fanout.** `strategy_drift_alerts` is instrument-keyed. Backfill migration 0103 fans out to all portfolios holding the instrument (N rows per drift event). Acceptable or join-at-query-time? *Drafts: DB §13.8.* **Recommendation:** Fanout (the partial index `ix_portfolio_alerts_open` on `(portfolio_id, created_at DESC) WHERE open` depends on portfolio_id equality, joining would regress it).

### Theme 8 — Scope + phasing

- **OD-25. Analytics `Compare Both` mode (dual-subject diff) — v1 or v1.1?** *Drafts: UX §11.2.1.* **Recommendation:** v1.1 — most complex scope item, highest risk of drift.
- **OD-26. Mock data policy during backend enrichment transit.** Empty states ("Backend payload incomplete — missing fields X, Y, Z") strict, OR partial rendering with whatever exists? *Drafts: components Part H#10.* **Recommendation:** Strict — aligns with `feedback_smart_backend_dumb_frontend`. No MOCK data ships under any circumstance.
- **OD-27. Sharpe isoquant overlay on Efficient Frontier.** MVP or defer? *Drafts: charts A.1#1, Part H#3 bullet 3.* **Recommendation:** Defer to v1.1.
- **OD-28. Phase ordering confirmation.** Builder + Analytics first (Phases 1-6), Live second (Phases 7-9)? Or Live first as the "wow" demo? *Drafts: charts Part H#3 bullet 1, UX §13, memory `feedback_phase_ordering`.* **Recommendation:** Builder + Analytics first — product-facing value lands sooner, complaint #1-#4 resolved before complaint #5.

---

## Revision Log

- **2026-04-08** — Initial unified plan stitched from 5 specialist drafts (UX flow, DB schema, components, charts, quant layer). Consolidates 40+ draft open questions into 28 blocking decisions for Andrei, locks 20 decisions, defines 10 implementation phases, allocates migrations 0097-0104 and worker lock IDs 900_100-900_102.

---

## Phase 0 — Diagnostics + alignment

Before any migration or code: confirm the real state of the branch + prod. Prevents the same-shaped wasted motion Discovery caught with its `nav_monthly_returns_agg` diagnostic in Phase 0.

### Task 0.1: Audit portfolio MOCK/REAL state against components draft Part A

**Files:**
- Report: `docs/superpowers/diagnostics/2026-04-08-portfolio-state.md`

- [ ] **Step 1: Verify PolicyPanel no-op**

Grep for the literal lines in components draft A.2:

```bash
rg -n "updatePolicy" frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts
rg -n "handleCvarChange|updatePolicy" frontends/wealth/src/lib/components/portfolio/PolicyPanel.svelte
```

Expected: `portfolio-workspace.svelte.ts:684-688` body contains `this.portfolio = { ...this.portfolio };` with no fetch or mutation — confirming the no-op. If the lines have drifted, update the diagnostic file with the new line numbers before Phase 4 Task 4.2 consumes them.

- [ ] **Step 2: Verify "New Portfolio" button stub**

```bash
rg -n "New Portfolio" frontends/wealth/src/routes/\(app\)/portfolio/+page.svelte
```

Expected: lines 115-118 contain `<button type="button" class="bld-pill bld-pill--new">` with no `onclick` attribute. Confirms components draft A.2 claim.

- [ ] **Step 3: Verify StressTestPanel sends only `custom`**

```bash
rg -n "scenario_name" frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts
rg -n "runStressTest" frontends/wealth/src/lib/components/portfolio/StressTestPanel.svelte
```

Expected: `workspace.runStressTest` at `portfolio-workspace.svelte.ts:844` always dispatches `scenario_name: "custom"`. Confirms components draft A.2.

- [ ] **Step 4: Verify `construction_advisor.py` exists at 789 lines and is wired to `/construction-advice`**

```bash
wc -l backend/vertical_engines/wealth/model_portfolio/construction_advisor.py
rg -n "construction-advice" backend/app/domains/wealth/routes/model_portfolios.py
```

Expected: advisor file exists, route mounted at approx line 563. Confirms quant draft §C.1.

- [ ] **Step 5: Verify `stress_scenarios.PRESET_SCENARIOS` contents**

```bash
rg -n "PRESET_SCENARIOS" backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py
```

Expected: dict with keys `gfc_2008`, `covid_2020`, `taper_2013`, `rate_shock_200bps`. Confirms quant draft §D.1.

- [ ] **Step 6: Verify `/construct` response shape against quant draft §B.1**

Read `backend/app/domains/wealth/routes/model_portfolios.py` around line 1553-1562 and confirm the response embeds `result["optimization"]` with the 8 numeric fields (`expected_return`, `portfolio_volatility`, `sharpe_ratio`, `solver`, `status`, `cvar_95`, `cvar_limit`, `cvar_within_limit`) and no narrative.

- [ ] **Step 7: Count formatter violations**

```bash
rg -n "\.toFixed\(" frontends/wealth/src/lib/components/portfolio frontends/wealth/src/lib/components/model-portfolio frontends/wealth/src/routes/\(app\)/portfolio
rg -n "toLocaleString\(" frontends/wealth/src/lib/components/portfolio
rg -n "Intl\." frontends/wealth/src/lib/components/portfolio
```

Expected baseline (to be eliminated in Phase 10 Task 10.2):
- `RebalanceSimulationPanel.svelte:259,265,290`
- `BuilderTable.svelte:233`
- `portfolio/analytics/+page.svelte:60-61`

Update the diagnostic file if additional violations surface.

- [ ] **Step 8: Write diagnostic report**

Create `docs/superpowers/diagnostics/2026-04-08-portfolio-state.md` documenting each of the 7 verifications with the exact line numbers found. Classify each as `CONFIRMED`, `DRIFTED (new line numbers)`, or `RESOLVED (no longer present)`. Phase 4 consumes this report verbatim.

- [ ] **Step 9: Commit**

```bash
git add docs/superpowers/diagnostics/2026-04-08-portfolio-state.md
git commit -m "docs: portfolio MOCK/REAL state diagnostic pre-rebuild"
```

### Task 0.2: Confirm migration head and worker lock inventory

**Files:**
- Modify: `CLAUDE.md` (line mentioning `0095_mv_unified_funds_share_class`)
- Report: `docs/superpowers/diagnostics/2026-04-08-migration-head-and-locks.md`

- [ ] **Step 1: Confirm actual head**

```bash
ls backend/app/core/db/migrations/versions/ | sort | tail -5
```

Expected: `0096_discovery_fcl_keyset_indexes.py`. If a higher number exists (Discovery phases landed faster), update the reserved range in Phase 1-7 accordingly but preserve the same 8-migration count.

- [ ] **Step 2: Sync CLAUDE.md**

Edit the line `Current migration head: \`0095_mv_unified_funds_share_class\`` to `Current migration head: \`0096_discovery_fcl_keyset_indexes\``.

- [ ] **Step 3: Confirm lock IDs 900_100 / 900_101 / 900_102 are unused**

```bash
rg -n "900_100|900_101|900_102|pg_try_advisory_lock\(900" backend/app/domains/wealth/workers backend/app/domains/credit
```

Expected: zero matches. Confirms DB draft §11.2.

- [ ] **Step 4: Confirm `regime_fit.py` worker lock ID**

Open `backend/app/domains/wealth/workers/regime_fit.py` (the file is uncommitted per `git status` at plan start — read it as-is). Grep for `pg_try_advisory_lock`. Document the exact lock ID. Quant draft §F.2 lists it as 900_026 but needs confirmation since the file is uncommitted.

- [ ] **Step 5: Write diagnostic report**

Document the actual migration head, the 3 reserved lock IDs (900_100-900_102), and the confirmed `regime_fit` lock ID. Phase 7 Task 7.4 (`regime_fit` alert emission) consumes this.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/superpowers/diagnostics/2026-04-08-migration-head-and-locks.md
git commit -m "docs: confirm migration head 0096 + portfolio worker lock reservations"
```

### Task 0.3: Confirm Discovery FCL primitives landed in `@netz/ui`

**Files:**
- Report: `docs/superpowers/diagnostics/2026-04-08-netz-ui-primitives.md`

- [ ] **Step 1: Verify primitive exports**

```bash
rg -n "FlexibleColumnLayout|EnterpriseTable|FilterRail|ChartCard|AnalysisGrid|BottomTabDock|PanelErrorState" packages/ui/src/lib/index.ts
```

Expected: all 7 names exported. If Discovery Phase 2.2/2.3/5.2/5.3/8.1 have not yet merged, note which primitives are still wealth-local and adjust this plan's Phase 4 / Phase 6 / Phase 8 accordingly — but do NOT fork. Wait for Discovery to land or promote the primitive in a coordinated PR.

- [ ] **Step 2: Verify `WorkbenchLayout` does NOT yet exist**

```bash
ls packages/ui/src/lib/layouts/ 2>/dev/null | rg -i workbench
```

Expected: no output. Phase 8 Task 8.1 creates it.

- [ ] **Step 3: Write diagnostic report**

Document which primitives are ready to import and which (if any) are still wealth-local. Flag any gaps to Andrei before Phase 4 starts.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/diagnostics/2026-04-08-netz-ui-primitives.md
git commit -m "docs: confirm @netz/ui primitives availability for portfolio rebuild"
```

### Task 0.4: Read uncommitted `regime_fit.py` changes

**Files:**
- Report: appended to `docs/superpowers/diagnostics/2026-04-08-migration-head-and-locks.md`

- [ ] **Step 1: Diff uncommitted work**

```bash
git diff backend/app/domains/wealth/workers/regime_fit.py
```

- [ ] **Step 2: Decide disposition**

Three options:
1. **Commit as-is** on a separate branch and merge before Phase 7 starts.
2. **Stash** and re-apply after Phase 7 lands (risk: merge conflicts on `portfolio_alerts` write path).
3. **Integrate into Phase 7 Task 7.4** — extend `regime_fit.py` there to also write `portfolio_alerts` rows on regime transition, folding the uncommitted work into the same commit.

**Recommendation:** Option 3 — cleanest audit trail and avoids dangling uncommitted work across a long sprint.

- [ ] **Step 3: Append decision to diagnostic**

Document which option was chosen and update Phase 7 Task 7.4 step references if Option 3 is selected.

- [ ] **Step 4: Commit documentation only (do not commit `regime_fit.py` yet)**

```bash
git add docs/superpowers/diagnostics/2026-04-08-migration-head-and-locks.md
git commit -m "docs: note uncommitted regime_fit.py changes for Phase 7 integration"
```

### Phase 0 gate

- [ ] All 4 diagnostic reports exist and are committed
- [ ] CLAUDE.md migration head line updated
- [ ] Reserved lock IDs confirmed free
- [ ] Phase 1 is safe to start

---
