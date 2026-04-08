# Portfolio Enterprise Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is the unified synthesis of five specialist drafts: UX flow, DB schema, components, charts, quant layer. Each phase cites the originating drafts.

**Goal:** Rebuild the Portfolio vertical of Netz Wealth OS into an institutional-grade three-phase workbench: **Builder → Analytics → Live Management**. Today the surface is a single FCL page with a PolicyPanel whose sliders are a literal no-op (`portfolio-workspace.svelte.ts:684-688`), a calibration drawer that exposes 2 of 63 engine inputs, a Run Construct that returns 8 numeric fields with zero narrative, a StressTestPanel that cannot reach the 4 canonical engine scenarios, a "New Portfolio" button with no `onclick`, an allocation Advisor that exists at `construction_advisor.py:789` but is invisible from Builder, no state machine, no approval gate, and no live workbench. This plan closes every one of those gaps by (1) returning the optimizer trace + advisor + stress + validation + narrative in a single `/construct` response, (2) persisting all 63 calibration inputs in a typed `portfolio_calibration` table, (3) persisting every run in `portfolio_construction_runs` with binding constraints and phase trace, (4) introducing a backend-authoritative state machine (`draft → constructed → validated → approved → live → paused → archived`) with `allowed_actions` on every portfolio GET, (5) rebuilding the Builder around a new `CalibrationPanel` (Preview/Apply), `ConstructionNarrative`, and `StressScenarioPanel`, (6) reusing every Discovery primitive (FCL, EnterpriseTable, FilterRail, ChartCard, AnalysisGrid, BottomTabDock, PanelErrorState) for a parity Analytics surface, and finally (7) shipping a Bloomberg-terminal `/portfolio/live` workbench with `WorkbenchLayout`, `WorkbenchCoreChart` (single instance, option rebuild via `replaceMerge: ['series']`), SSE live price ticks buffered via `createTickBuffer`, and a unified alerts feed backed by a new `portfolio_alerts` table and `live_price_poll` worker (lock 900_100). Builder + Analytics ship before Live so product-facing value lands first (per `feedback_phase_ordering`).

**Architecture:** Three distinct surfaces — each with its own layout primitive — unified by a single backend state machine and a single calibration persistence layer.

1. **`/portfolio/builder`** — FCL 3-column (reuses Discovery's `FlexibleColumnLayout`). Col1 = Models/Universe/Policy sub-pills. Col2 = BuilderCanvas (action bar + allocation blocks DnD + chart strip + `ConstructionNarrative` after Run). Col3 = `BuilderRightStack` (Calibration | Narrative | Preview tabs). Approved Universe is a sub-pill of Builder, never a standalone route (per `feedback_universe_lives_in_portfolio`).
2. **`/portfolio/analytics`** — Standalone analytical surface mirroring Discovery Analysis. FilterRail (260px) + AnalysisGrid (3×2 ChartCards) + BottomTabDock. Scope switcher toggles `model_portfolios | approved_universe | compare_both`. Groups: **Returns & Risk | Holdings | Peer | Stress**. Reuses Discovery's `NavHeroChart`, `RollingRiskChart`, `DrawdownUnderwaterChart`, `ReturnDistributionChart`, `MonthlyReturnsHeatmap`, `RiskMetricsBulletChart` verbatim; adds portfolio-specific `BrinsonWaterfallChart`, `FactorExposureBarChart`, `ConstituentCorrelationHeatmap`, `RiskAttributionBarChart`.
3. **`/portfolio/live`** — Bloomberg-terminal workbench. NOT FCL — diverges via a new `WorkbenchLayout` primitive in `@investintell/ui` (12-col CSS Grid, 4px gap, 22px row height, 10px axis font, hairline borders, `data-density="workbench"` token set). Central `WorkbenchCoreChart` (single ECharts instance, tool state machine: `nav | drawdown | rollingSharpe | rollingVol | rollingCorrelation | rollingTrackingError | regimeOverlay | intraday`, option rebuild via `setOption(..., { notMerge: false, lazyUpdate: true, replaceMerge: ['series','markLine'] })`), `WeightVectorTable` with SVG sparkline glyphs and `createTickBuffer<PriceTick>`, `AlertsFeedPanel` on persistent SSE, strategic/tactical/effective comparison, rebalance suggestion panel.

**Layout primitives (named once, reused everywhere):**

- **`FlexibleColumnLayout`** — `@investintell/ui`, promoted from Discovery Phase 2.2. Builder + Analytics.
- **`EnterpriseTable`** — `@investintell/ui`, extracted from `UniverseTable.svelte` in Discovery Phase 2.3. Universe, Models list, Analytics subject table, Live portfolio selector, strategic/tactical/effective allocation tables.
- **`FilterRail`** — `@investintell/ui`. Analytics, Universe sub-pill.
- **`ChartCard` + `AnalysisGrid`** — `@investintell/ui`. Analytics 3×2 grid.
- **`BottomTabDock`** — `@investintell/ui`. Analytics (mandatory persistent cross-subject sessions), Live (optional portfolio switcher).
- **`PanelErrorState`** — `@investintell/ui/runtime`. Every `<svelte:boundary>` failed snippet.
- **`WorkbenchLayout`** — `@investintell/ui` (NEW). `/portfolio/live` only. The sole intentional divergence from FCL — carries its own `--workbench-*` tokens (admin-overridable via ConfigService per §Phase 8).
- **`CalibrationPanel` + `ConstructionNarrative` + `AllocationComparisonTable` + `NewPortfolioDialog`** — wealth-specific, under `frontends/wealth/src/lib/components/portfolio/`.

**Tech Stack:** SvelteKit 2 + Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`, `$bindable`) + `@investintell/ui` + svelte-echarts (LineChart/BarChart/ScatterChart/HeatmapChart/TreemapChart/RadarChart/CustomChart/GraphChart) + FastAPI + PostgreSQL 16 + TimescaleDB + Redis (SSE pub/sub + single-flight locks + Upstash) + pgvector. Backend uses `asyncpg` + `SQLAlchemy 2.0 AsyncSession` + Alembic (current head `0097_curated_institutions_seed` — Phase 0 Task 0.2 confirmed; portfolio reserved range shifted to 0098-0105). Frontend SSE via `fetch() + ReadableStream` (never `EventSource` — Clerk JWT headers needed). Zero `localStorage`, zero `.toFixed()`, zero inline `Intl.*` — enforced by `frontends/eslint.config.js`. All formatters from `@investintell/ui`.

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
- **DL14. Jargon translation table is normative.** Every backend field surfaced to Portfolio UI must have a `@investintell/ui` formatter AND a plain-English label AND appear in the translation table in Phase 10 Task 10.1. New backend fields require a translation entry before UI shipping. "CLARABEL", "SOCP", "Ledoit-Wolf", "robust uncertainty set", "Markov filtered" never appear in user-facing copy. Per UX draft §10 + memory `feedback_smart_backend_dumb_frontend`.
- **DL15. No `localStorage` / `sessionStorage` anywhere in wealth code.** All state lives in URL query/hash + in-memory `portfolio-workspace.svelte` store + SSE + cookies (theme only). `BottomTabDock` persists in URL hash (`#tabs=<base64>`), never storage. `CalibrationDraft` persists via `PUT /model-portfolios/{id}/calibration` on Apply — never local. Per memory `feedback_echarts_no_localstorage` + Discovery Phase 8 precedent.
- **DL16. Formatter discipline is absolute.** All number/date/currency formatting via `@investintell/ui` formatters (`formatNumber`, `formatCurrency`, `formatPercent`, `formatBps`, `formatDate`, `formatDateTime`, `formatShortDate`). Zero `.toFixed()`, zero `.toLocaleString()`, zero inline `Intl.NumberFormat` / `Intl.DateTimeFormat`. Enforced by `frontends/eslint.config.js`. Phase 10 Task 10.2 sweeps the 5 known violations in `RebalanceSimulationPanel.svelte:259,265,290`, `BuilderTable.svelte:233`, `portfolio/analytics/+page.svelte:60-61`. Per CLAUDE.md + components draft F.1.
- **DL17. `@tanstack/svelte-table` is forbidden.** Broken on Svelte 5 across all three frontends (`project_frontend_platform`). `EnterpriseTable` is the canonical table primitive. `CatalogTable` v1/v2 already eliminated in Discovery Phase 2.4. Per memory `project_frontend_platform`.
- **DL18. Stability guardrails P1-P6 apply to every new worker, route, and component.** Bounded (120s construct timeout), Batched (`execute_many` for weight snapshot upserts), Isolated (RLS subselect on every new tenant-scoped table), Lifecycle (state machine is literal), Idempotent (`@idempotent` decorator on construct/activate/acknowledge routes + `UNIQUE(construction_run_id, scenario)` on stress results), Fault-Tolerant (`ExternalProviderGate` + circuit breakers on Yahoo). Per CLAUDE.md §Stability Guardrails + DB draft §12.
- **DL19. Advisory locks are integer literals or `zlib.crc32` on deterministic byte strings — never Python `hash()`.** Reserved lock IDs for this plan: `900_100` (`live_price_poll`), `900_101` (`construction_run_executor`), `900_102` (`alert_sweeper`). Existing `portfolio_eval` (900_008), `drift_check` (42), `regime_fit` (**no lock currently — Phase 0 Task 0.2 confirmed; Phase 7 Task 7.3 must add `900_026` when extending it to write `portfolio_alerts`**), `portfolio_nav_synthesizer` (900_030), `risk_calc` (900_007), `global_risk_metrics` (900_071) untouched. Per CLAUDE.md §Stability Guardrails + DB draft §11.2.
- **DL20. Migration range 0098-0105 reserved for this plan.** Originally drafted as 0097-0104 against the assumed head `0096_discovery_fcl_keyset_indexes`. Phase 0 Task 0.2 discovered that commit `365cd470 feat(db): curated_institutions table + seed` landed `0097_curated_institutions_seed` between drafting and execution, making it the new real head. Range shifted by +1 with zero collision (curated_institutions is a Discovery seed table, unrelated to portfolio scope). CLAUDE.md updated 2026-04-08. Per DB draft §0 + §10.

---

## Open Decisions for Andrei — RESOLVED 2026-04-08

> **STATUS — ALL 28 LOCKED.** Andrei reviewed all 28 open decisions on 2026-04-08 and accepted every recommendation verbatim. The list below is preserved as historical context for future revisions; treat each "Recommendation" line as the binding contract. New amendments must be added to the Revision Log. Each decision is grouped by theme, given an ID, and attributed to the originating draft(s).

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
- **OD-11. Workbench density tokens admin-configurable?** `--workbench-*` tokens hardcoded in `@investintell/ui`, or exposed via `ConfigService.get("wealth","workbench_density",org_id)` so some orgs can dial back? *Drafts: components Part H#7, charts D.1, UX §6.1.* **Recommendation:** Admin-overridable via ConfigService (tokens are admin config per `feedback_tokens_vs_components`) but ship with a single default density.
- **OD-12. Portfolio selector UX.** Table (as spec'd in Live col1 top) or sidebar list? *Drafts: UX §11.2.2.* **Recommendation:** Table wins at 3+ portfolios (the only scale worth designing for).
- **OD-13. Multi-portfolio navigation in Live.** Primary = col1 selector. Secondary = `BottomTabDock`. Keep both? *Drafts: UX §8.* **Recommendation:** Keep both — selector is persistent one-active-portfolio detail; BottomTabDock is parallel sessions for comparison. Two different jobs.
- **OD-14. Real-time price provider.** Yahoo Finance batch quote is delayed 15min. Accept (label "near-real-time") or integrate a paid provider (IEX Cloud / Polygon / Alpaca) which changes rate-limit math and budget? *Drafts: DB §13.4, charts Part H#2.* **Recommendation:** Yahoo v1 with "Delayed 15min" label in toolbar; upgrade in v1.1.
- **OD-15. Intraday history persistence.** Ship ephemeral Redis-only (no `nav_intraday` hypertable) or persist 1-min chunks in a new hypertable? *Drafts: DB §13.5, quant §G.3.* **Recommendation:** Ephemeral v1. Add `nav_intraday` hypertable (1min chunks, segmentby `instrument_id`, compression after 7 days) as migration 0106 (post-Phase-10 cleanup migration) if workbench demand grows.

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
- **OD-24. Portfolio-scoped drift alert fanout.** `strategy_drift_alerts` is instrument-keyed. Backfill migration 0104 fans out to all portfolios holding the instrument (N rows per drift event). Acceptable or join-at-query-time? *Drafts: DB §13.8.* **Recommendation:** Fanout (the partial index `ix_portfolio_alerts_open` on `(portfolio_id, created_at DESC) WHERE open` depends on portfolio_id equality, joining would regress it).

### Theme 8 — Scope + phasing

- **OD-25. Analytics `Compare Both` mode (dual-subject diff) — v1 or v1.1?** *Drafts: UX §11.2.1.* **Recommendation:** v1.1 — most complex scope item, highest risk of drift.
- **OD-26. Mock data policy during backend enrichment transit.** Empty states ("Backend payload incomplete — missing fields X, Y, Z") strict, OR partial rendering with whatever exists? *Drafts: components Part H#10.* **Recommendation:** Strict — aligns with `feedback_smart_backend_dumb_frontend`. No MOCK data ships under any circumstance.
- **OD-27. Sharpe isoquant overlay on Efficient Frontier.** MVP or defer? *Drafts: charts A.1#1, Part H#3 bullet 3.* **Recommendation:** Defer to v1.1.
- **OD-28. Phase ordering confirmation.** Builder + Analytics first (Phases 1-6), Live second (Phases 7-9)? Or Live first as the "wow" demo? *Drafts: charts Part H#3 bullet 1, UX §13, memory `feedback_phase_ordering`.* **Recommendation:** Builder + Analytics first — product-facing value lands sooner, complaint #1-#4 resolved before complaint #5.

---

## Revision Log

- **2026-04-08 (initial)** — Unified plan stitched from 5 specialist drafts (UX flow, DB schema, components, charts, quant layer). Consolidates 40+ draft open questions into 28 blocking decisions for Andrei, locks 20 decisions, defines 10 implementation phases, originally allocated migrations 0097-0104 against assumed head `0096_discovery_fcl_keyset_indexes` and worker lock IDs 900_100-900_102.
- **2026-04-08 (OD lock)** — Andrei locked all 28 open decisions by accepting every "Recommendation" line verbatim. Plan moves from BLOCKING to EXECUTABLE. Phase 0 begins immediately. Note for future amendments: changing any locked recommendation requires a new revision-log entry with the OD ID and the rationale.

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

### Task 0.2: Confirm migration head and worker lock inventory — EXECUTED 2026-04-08

**Files:**
- Modify: `CLAUDE.md` (line mentioning the current migration head)
- Report: `docs/superpowers/diagnostics/2026-04-08-migration-head-and-locks.md`

**Outcome (recorded for future amendments):**

1. **Real head is `0097_curated_institutions_seed`**, not `0096_discovery_fcl_keyset_indexes`. Commit `365cd470 feat(db): curated_institutions table + seed (Ivy endowments, family offices, sovereign)` landed `0097_curated_institutions_seed.py` between draft authoring and Phase 0 execution. The migration creates a `curated_institutions` table for Discovery seed data — fully unrelated to portfolio scope, zero column or constraint collision. Portfolio reserved range shifted +1 to **0098-0105** in DL20.
2. **CLAUDE.md updated:** `0095_mv_unified_funds_share_class` → `0097_curated_institutions_seed`.
3. **Lock IDs 900_100 / 900_101 / 900_102 confirmed unused** across `backend/app/domains/wealth/workers` and `backend/app/domains/credit`. Zero matches.
4. **`regime_fit.py` has NO advisory lock today.** The file at HEAD (committed in `9c29a140 fix(regime_fit): add strict=False to zip() calls (B905)`) contains zero `pg_try_advisory_lock` / `advisory_xact_lock` references. The quant draft §F.2's "900_026" was speculative. Phase 7 Task 7.3 must ADD the lock when extending the worker to write `portfolio_alerts` rows on regime transitions — proposed canonical ID `900_026` (still available, no collision).
5. Task 0.4 (uncommitted `regime_fit.py` integration) is **RESOLVED — file already committed in `9c29a140`**. No action needed in Phase 7 beyond the lock addition above.

### Task 0.3: Confirm Discovery FCL primitives landed in `@investintell/ui`

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
git commit -m "docs: confirm @investintell/ui primitives availability for portfolio rebuild"
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

## Phase 1 — DB foundation: state machine + construction runs (migrations 0098-0099)

**Goal:** Land the backend-authoritative state machine and the `portfolio_construction_runs` table so every later phase has something real to write into. No frontend work, no worker changes — pure schema.
**Drafts:** portfolio-enterprise-db.md §2 (state machine), §2.3 (transitions audit), §3 (construction_runs), §9 (indexes), §10 (migration sequence), §12 (guardrails).
**Locks consumed:** DL3 (state machine), DL4 (narrative persisted), DL18 (guardrails), DL19 (advisory lock discipline), DL20 (migration range).
**Migrations:** 0098, 0099.
**New worker locks:** none.
**Depends on:** Phase 0 gate.

### Task 1.1: Migration 0098 — `model_portfolios` state columns + `portfolio_state_transitions`

**Files:**
- Create: `backend/app/core/db/migrations/versions/0098_model_portfolio_lifecycle_state.py`
- Modify: `backend/app/core/db/models.py` (`ModelPortfolio`, add `PortfolioStateTransition`)
- Test: `backend/tests/db/test_migration_0098_lifecycle_state.py`
**Reference:** portfolio-enterprise-db.md §2.1, §2.2, §2.3, §10.

- [ ] **Step 1: Write failing test for columns + CHECK + RLS**
  Assert `model_portfolios.state`, `state_metadata`, `state_changed_at`, `state_changed_by` exist. Assert `CHECK` constraint enumerates exactly `draft|constructed|validated|approved|live|paused|archived|rejected`. Assert `portfolio_state_transitions` exists with RLS policy using `(SELECT current_setting('app.current_organization_id'))` subselect (per CLAUDE.md). Test fails before migration.

- [ ] **Step 2: Write migration upgrade**
  Add 4 columns to `model_portfolios` with `state` DEFAULT `'draft'`, `CHECK` constraint, `USING CASE` backfill from legacy `status` column (`active`→`live`, `draft`→`draft`, else `archived`). Create `portfolio_state_transitions` table with PK `id uuid`, FK `portfolio_id`, `from_state`, `to_state`, `actor_id text NOT NULL`, `reason text`, `metadata jsonb NOT NULL DEFAULT '{}'`, `created_at timestamptz NOT NULL DEFAULT now()`, `organization_id uuid NOT NULL`. Enable RLS. Add index `ix_pst_portfolio_created (portfolio_id, created_at DESC)`.
  → See portfolio-enterprise-db.md §2.3 for the full column list and §9 for index specs.

- [ ] **Step 3: Write migration downgrade**
  `DROP TABLE portfolio_state_transitions`, then `ALTER TABLE model_portfolios DROP COLUMN` x4. No `IF EXISTS` (per DB draft §10: fail loudly).

- [ ] **Step 4: Add SQLAlchemy models**
  Add `PortfolioStateTransition` model in `backend/app/core/db/models.py` with `lazy="raise"` on all relationships. Add new columns to `ModelPortfolio` (keep legacy `status` per DL — OD-19 defers drop). Set `expire_on_commit=False` guarantee inherits from base.

- [ ] **Step 5: Run migration + test**
  ```bash
  make migrate && pytest backend/tests/db/test_migration_0098_lifecycle_state.py -v
  ```

- [ ] **Step 6: Commit**
  ```bash
  git add backend/app/core/db/migrations/versions/0098_model_portfolio_lifecycle_state.py backend/app/core/db/models.py backend/tests/db/test_migration_0098_lifecycle_state.py
  git commit -m "feat(db): migration 0098 — portfolio lifecycle state machine + transition audit"
  ```

### Task 1.2: State machine service module

**Files:**
- Create: `backend/vertical_engines/wealth/model_portfolio/state_machine.py`
- Create: `backend/tests/wealth/model_portfolio/test_state_machine.py`
**Reference:** portfolio-enterprise-ux-flow.md §3.2 (transition table), §3.4 (idempotency).

- [ ] **Step 1: Encode transition table**
  Define `TRANSITIONS: dict[str, set[str]]` mirroring UX draft §3.2 — `draft → {constructed, archived}`, `constructed → {validated, rejected, draft}`, `validated → {approved, draft}`, `approved → {live, draft}`, `live → {paused, archived}`, `paused → {live, archived}`, `archived → {}`, `rejected → {draft, archived}`.

- [ ] **Step 2: Write `compute_allowed_actions(state, validation, four_eyes) -> list[str]`**
  Pure function returning the action strings (`"construct" | "validate" | "approve" | "activate" | "pause" | "resume" | "archive" | "reject" | "rebuild_draft"`) that map to UI buttons. Consult DL3 — frontend only renders buttons whose action string is in this list.

- [ ] **Step 3: Write `transition(db, portfolio_id, to_state, actor_id, reason, metadata)` async function**
  Inside a transaction: row-lock `model_portfolios` with `FOR UPDATE`, validate source → target in `TRANSITIONS`, UPDATE `state`, `state_changed_at`, `state_changed_by`, append `state_metadata` JSONB merge, INSERT `portfolio_state_transitions` row. Raise `InvalidStateTransition` on violation.

- [ ] **Step 4: Unit tests — every valid and invalid edge**
  Test `draft → archived` valid, `draft → live` invalid (expect raise), `live → draft` invalid, `archived → anywhere` invalid. Test `compute_allowed_actions` for each state with/without validation pass and self-approval flag.

- [ ] **Step 5: Commit**
  ```bash
  git add backend/vertical_engines/wealth/model_portfolio/state_machine.py backend/tests/wealth/model_portfolio/test_state_machine.py
  git commit -m "feat(wealth): portfolio state machine with compute_allowed_actions"
  ```

### Task 1.3: Migration 0099 — `portfolio_construction_runs`

**Files:**
- Create: `backend/app/core/db/migrations/versions/0099_portfolio_construction_runs.py`
- Modify: `backend/app/core/db/models.py` (add `PortfolioConstructionRun`)
- Test: `backend/tests/db/test_migration_0099_construction_runs.py`
**Reference:** portfolio-enterprise-db.md §3, §9, §10, §12.

- [ ] **Step 1: Write failing test**
  Assert table exists with columns per DB draft §3. Assert `CHECK (status IN ('running','succeeded','failed','superseded'))`. Assert RLS enabled with subselect policy. Assert indexes `ix_pcr_portfolio_requested_at (portfolio_id, requested_at DESC)` and `ix_pcr_status_requested_at (status, requested_at DESC) WHERE status IN ('running','failed')`.

- [ ] **Step 2: Write upgrade migration**
  One INSERT wins: create table with `id uuid PK`, `portfolio_id uuid NOT NULL`, `organization_id uuid NOT NULL`, `requested_by text NOT NULL`, `status text NOT NULL`, `calibration_id uuid NULL` (FK added in 0104), `calibration_snapshot jsonb NOT NULL`, `optimizer_trace jsonb NOT NULL`, `binding_constraints jsonb NOT NULL`, `regime_context jsonb NOT NULL`, `ex_ante_metrics jsonb NOT NULL`, `ex_ante_vs_previous jsonb`, `factor_exposure jsonb`, `advisor jsonb`, `validation jsonb NOT NULL`, `narrative jsonb NOT NULL`, `rationale_per_weight jsonb NOT NULL`, `weights_proposed jsonb NOT NULL`, `wall_clock_ms integer NOT NULL`, `requested_at timestamptz NOT NULL DEFAULT now()`, `completed_at timestamptz`.
  → See portfolio-enterprise-db.md §3 for the full column list and descriptions. **Note:** the FK on `calibration_id` is added in migration 0105 (originally 0104), after `portfolio_calibration` lands in 0100.

- [ ] **Step 3: Enable RLS subselect policy**
  `CREATE POLICY portfolio_construction_runs_rls ON portfolio_construction_runs USING (organization_id = (SELECT current_setting('app.current_organization_id'))::uuid)`. Subselect pattern is mandatory per CLAUDE.md.

- [ ] **Step 4: Run + test + commit**
  ```bash
  make migrate && pytest backend/tests/db/test_migration_0099_construction_runs.py -v
  git add backend/app/core/db/migrations/versions/0099_portfolio_construction_runs.py backend/app/core/db/models.py backend/tests/db/test_migration_0099_construction_runs.py
  git commit -m "feat(db): migration 0099 — portfolio_construction_runs persisted narrative"
  ```

### Task 1.4: `allowed_actions` on every portfolio GET

**Files:**
- Modify: `backend/app/domains/wealth/schemas/model_portfolio.py` (`ModelPortfolioRead`)
- Modify: `backend/app/domains/wealth/routes/model_portfolios.py` (list + detail handlers)
- Test: `backend/tests/wealth/routes/test_model_portfolios_allowed_actions.py`
**Reference:** portfolio-enterprise-ux-flow.md §3.3, portfolio-enterprise-db.md §2.

- [ ] **Step 1: Extend `ModelPortfolioRead` Pydantic schema**
  Add `state: Literal[...]`, `state_metadata: dict`, `state_changed_at: datetime`, `allowed_actions: list[str]` fields. Route returns via `model_validate()` — no inline dict serialization (CLAUDE.md rule).

- [ ] **Step 2: Populate `allowed_actions` in detail handler**
  Call `state_machine.compute_allowed_actions(portfolio.state, latest_run_validation, four_eyes_policy)`. Four-eyes policy from `ConfigService.get("wealth","approval_policy",org_id)` per OD-6.

- [ ] **Step 3: Test state→actions mapping**
  Assert a `draft` portfolio returns `["construct","archive"]`; a `validated` portfolio with `passed=true` returns `["approve","rebuild_draft"]`; an `archived` portfolio returns `[]`.

- [ ] **Step 4: Commit**
  ```bash
  git add backend/app/domains/wealth/schemas/model_portfolio.py backend/app/domains/wealth/routes/model_portfolios.py backend/tests/wealth/routes/test_model_portfolios_allowed_actions.py
  git commit -m "feat(wealth): allowed_actions on model portfolio responses"
  ```

### Phase 1 gate

- [ ] 0098 and 0099 migrated locally; `make migrate` clean
- [ ] `portfolio_state_transitions` and `portfolio_construction_runs` queryable via `psql` with RLS context set
- [ ] `state_machine.compute_allowed_actions` unit test covers all 8 states
- [ ] Every portfolio GET response has `allowed_actions` populated
- [ ] Phase 2 is safe to start

---

## Phase 2 — DB foundation: calibration + stress + weight snapshots + alerts + live price (migrations 0100-0105)

**Goal:** Finish the schema. Land calibration, stress, weight snapshots, alerts, backfill fanout, and the calibration→construction FK. Register the three new worker locks in the codebase index.
**Drafts:** portfolio-enterprise-db.md §4 (calibration), §5 (stress_results), §6 (weight_snapshots), §7 (alerts), §8 (live price layer), §10 (sequence), §11.2 (new workers), §12 (guardrails).
**Locks consumed:** DL5 (calibration spine), DL7 (stress scenarios), DL11 (live price worker), DL12 (unified alerts), DL13 (weight snapshots hypertable), DL18, DL19, DL20.
**Migrations:** 0100, 0101, 0102, 0103, 0104, 0105.
**New worker locks:** 900_100 (`live_price_poll`), 900_101 (`construction_run_executor`), 900_102 (`alert_sweeper`) — reserved, workers created in Phases 3/7/9.
**Depends on:** Phase 1 gate.

### Task 2.1: Migration 0100 — `portfolio_calibration`

**Files:**
- Create: `backend/app/core/db/migrations/versions/0100_portfolio_calibration.py`
- Modify: `backend/app/core/db/models.py` (add `PortfolioCalibration`)
- Test: `backend/tests/db/test_migration_0100_calibration.py`
**Reference:** portfolio-enterprise-db.md §4, portfolio-enterprise-quant.md §A (all 63 inputs).

- [ ] **Step 1: Failing test asserts all 63 fields persisted**
  Test loads a calibration row per-tier and asserts every field from the quant draft §A.1-A.16 enumeration round-trips through JSON.

- [ ] **Step 2: Table definition**
  Typed columns for the Basic tier (5 inputs — `mandate`, `cvar_limit`, `max_single_fund_weight`, `turnover_cap`, `stress_scenarios_active`) and Advanced tier (10 inputs — `regime_override`, `bl_enabled`, `bl_view_confidence_default`, `garch_enabled`, `turnover_lambda`, `stress_severity_multiplier`, `advisor_enabled`, `cvar_level`, `lambda_risk_aversion`, `shrinkage_intensity_override`). Expert tier (48 inputs) lives in `expert_overrides jsonb NOT NULL DEFAULT '{}'`. Plus `id uuid PK`, `portfolio_id uuid NOT NULL UNIQUE` (one active calibration per portfolio), `organization_id uuid NOT NULL`, `schema_version int NOT NULL DEFAULT 1`, `created_at`, `updated_at`, `updated_by text`.
  → See portfolio-enterprise-db.md §4 for the exact column types and defaults.

- [ ] **Step 3: RLS subselect + unique index + updated_at trigger**
  ```sql
  CREATE UNIQUE INDEX ix_portfolio_calibration_portfolio ON portfolio_calibration(portfolio_id);
  ```
  Trigger calls a shared `set_updated_at()` function (create if missing).

- [ ] **Step 4: Commit**
  ```bash
  git add backend/app/core/db/migrations/versions/0100_portfolio_calibration.py backend/app/core/db/models.py backend/tests/db/test_migration_0100_calibration.py
  git commit -m "feat(db): migration 0100 — portfolio_calibration with 63-input surface"
  ```

### Task 2.2: Migration 0101 — `portfolio_stress_results`

**Files:**
- Create: `backend/app/core/db/migrations/versions/0101_portfolio_stress_results.py`
- Modify: `backend/app/core/db/models.py` (add `PortfolioStressResult`)
- Test: `backend/tests/db/test_migration_0101_stress_results.py`
**Reference:** portfolio-enterprise-db.md §5, portfolio-enterprise-quant.md §D.1 (preset scenarios).

- [ ] **Step 1: Table + UNIQUE idempotency key (DL18)**
  `id uuid PK`, `construction_run_id uuid NOT NULL` FK → `portfolio_construction_runs(id) ON DELETE CASCADE`, `scenario text NOT NULL`, `scenario_kind text NOT NULL CHECK (IN ('preset','user_defined'))`, `nav_impact_pct numeric`, `cvar_impact_pct numeric`, `per_block_impact jsonb`, `per_instrument_impact jsonb`, `computed_at timestamptz NOT NULL DEFAULT now()`, `organization_id uuid NOT NULL`. Add `UNIQUE(construction_run_id, scenario)` for idempotency (DL18 P5).

- [ ] **Step 2: Index + RLS**
  ```sql
  CREATE INDEX ix_psr_run_scenario ON portfolio_stress_results(construction_run_id, scenario);
  ```

- [ ] **Step 3: Commit**
  ```bash
  git add backend/app/core/db/migrations/versions/0101_portfolio_stress_results.py backend/app/core/db/models.py backend/tests/db/test_migration_0101_stress_results.py
  git commit -m "feat(db): migration 0101 — portfolio_stress_results with run idempotency"
  ```

### Task 2.3: Migration 0102 — `portfolio_weight_snapshots` hypertable

**Files:**
- Create: `backend/app/core/db/migrations/versions/0102_portfolio_weight_snapshots_hypertable.py`
- Modify: `backend/app/core/db/models.py` (add `PortfolioWeightSnapshot`)
- Test: `backend/tests/db/test_migration_0102_weight_snapshots.py`
**Reference:** portfolio-enterprise-db.md §6, §12 (compression policy).

- [ ] **Step 1: Plain table first**
  Columns: `organization_id uuid NOT NULL`, `portfolio_id uuid NOT NULL`, `instrument_id uuid NOT NULL`, `as_of date NOT NULL`, `weight_strategic numeric`, `weight_tactical numeric`, `weight_effective numeric`, `notes text`. PK `(organization_id, portfolio_id, instrument_id, as_of)`.

- [ ] **Step 2: Hypertable conversion + compression**
  `create_hypertable` on `as_of` column with 7-day chunk interval. `ALTER TABLE SET (timescaledb.compress, compress_segmentby = 'portfolio_id')`. `add_compression_policy` at 14 days.
  → See portfolio-enterprise-db.md §6 for the exact DDL.

- [ ] **Step 3: RLS policy on chunks**
  Per DB draft §6 — enable RLS on the root table AND on all future chunks (`ALTER TABLE ... SET ROW LEVEL SECURITY`). Test writes one row per `(portfolio, instrument, as_of)` under two org contexts and asserts zero cross-tenant visibility.

- [ ] **Step 4: Commit**
  ```bash
  git add backend/app/core/db/migrations/versions/0102_portfolio_weight_snapshots_hypertable.py backend/app/core/db/models.py backend/tests/db/test_migration_0102_weight_snapshots.py
  git commit -m "feat(db): migration 0102 — portfolio_weight_snapshots 7d hypertable"
  ```

### Task 2.4: Migration 0103 — `portfolio_alerts`

**Files:**
- Create: `backend/app/core/db/migrations/versions/0103_portfolio_alerts.py`
- Modify: `backend/app/core/db/models.py` (add `PortfolioAlert`)
- Test: `backend/tests/db/test_migration_0103_portfolio_alerts.py`
**Reference:** portfolio-enterprise-db.md §7, portfolio-enterprise-ux-flow.md §7.2 (alert contract).

**BLOCKED ON: OD-23** (dedupe_key materialized column vs app-level). Default to materialized column per recommendation.

- [ ] **Step 1: Table definition**
  `id uuid PK`, `portfolio_id uuid NOT NULL`, `organization_id uuid NOT NULL`, `alert_type text NOT NULL CHECK (alert_type IN ('cvar_breach','drift','regime_change','price_staleness','weight_drift','rebalance_suggested','validation_block','custom'))`, `severity text NOT NULL CHECK (severity IN ('info','warning','critical'))`, `source_worker text NOT NULL`, `source_lock_id integer`, `dedupe_key text NOT NULL`, `payload jsonb NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`, `acknowledged_at timestamptz`, `acknowledged_by text`, `dismissed_at timestamptz`, `dismissed_by text`, `auto_dismiss_at timestamptz`.

- [ ] **Step 2: Partial open index (the hot path)**
  `ix_portfolio_alerts_open` on `(portfolio_id, created_at DESC) WHERE dismissed_at IS NULL` and `ix_portfolio_alerts_dedupe` UNIQUE on `(portfolio_id, alert_type, dedupe_key) WHERE dismissed_at IS NULL`. → portfolio-enterprise-db.md §9.

- [ ] **Step 3: RLS subselect policy**

- [ ] **Step 4: Commit**
  ```bash
  git add backend/app/core/db/migrations/versions/0103_portfolio_alerts.py backend/app/core/db/models.py backend/tests/db/test_migration_0103_portfolio_alerts.py
  git commit -m "feat(db): migration 0103 — unified portfolio_alerts feed with dedupe"
  ```

### Task 2.5: Migration 0104 — `strategy_drift_alerts` fanout backfill

**Files:**
- Create: `backend/app/core/db/migrations/versions/0104_portfolio_alerts_backfill.py`
- Test: `backend/tests/db/test_migration_0104_backfill.py`
**Reference:** portfolio-enterprise-db.md §7, §10, §13.8.

**BLOCKED ON: OD-24** (fanout vs join-at-query-time). Default to fanout per recommendation.

- [ ] **Step 1: Idempotent backfill**
  Upgrade body: `INSERT INTO portfolio_alerts` from `SELECT` joining `strategy_drift_alerts` to `portfolio_holdings` (or equivalent), keyed on `(portfolio_id, 'drift', md5(strategy_drift_alerts.id::text || portfolio_id::text))`. Guard with `ON CONFLICT (portfolio_id, alert_type, dedupe_key) WHERE dismissed_at IS NULL DO NOTHING` (compatible with the partial unique index from 0103).

- [ ] **Step 2: Downgrade — targeted DELETE**
  `DELETE FROM portfolio_alerts WHERE source_worker = 'drift_check_backfill'`.

- [ ] **Step 3: Commit**
  ```bash
  git add backend/app/core/db/migrations/versions/0104_portfolio_alerts_backfill.py backend/tests/db/test_migration_0104_backfill.py
  git commit -m "feat(db): migration 0104 — portfolio_alerts backfill from strategy_drift_alerts"
  ```

### Task 2.6: Migration 0105 — calibration FK on construction_runs

**Files:**
- Create: `backend/app/core/db/migrations/versions/0105_portfolio_calibration_fk_on_construction_runs.py`
**Reference:** portfolio-enterprise-db.md §10 (split rationale).

- [ ] **Step 1: ADD FOREIGN KEY**
  `ALTER TABLE portfolio_construction_runs ADD CONSTRAINT fk_pcr_calibration_id FOREIGN KEY (calibration_id) REFERENCES portfolio_calibration(id) ON DELETE SET NULL`. Downgrade drops the constraint.

- [ ] **Step 2: Commit**
  ```bash
  git add backend/app/core/db/migrations/versions/0105_portfolio_calibration_fk_on_construction_runs.py
  git commit -m "feat(db): migration 0105 — FK portfolio_construction_runs.calibration_id"
  ```

### Task 2.7: Update CLAUDE.md worker table + migration head

**Files:**
- Modify: `CLAUDE.md`
**Reference:** portfolio-enterprise-db.md §11.2, CLAUDE.md §Data Ingestion Workers.

- [ ] **Step 1: Bump migration head**
  Edit `Current migration head: \`0097_curated_institutions_seed\`` → `\`0105_portfolio_calibration_fk_on_construction_runs\``.

- [ ] **Step 2: Append 3 worker rows to the Data Ingestion Workers table**
  Rows for `live_price_poll` (900_100 | org | Redis hash | Yahoo batch quote | 60s), `construction_run_executor` (900_101 | org | `portfolio_construction_runs` | Computed | On-demand), `alert_sweeper` (900_102 | org | `portfolio_alerts` | Computed | Hourly).

- [ ] **Step 3: Commit**
  ```bash
  git add CLAUDE.md
  git commit -m "docs: CLAUDE.md migration head 0105 + 3 new portfolio worker locks"
  ```

### Phase 2 gate

- [ ] Migrations 0100-0105 apply cleanly in order
- [ ] Downgrade path verified on each migration individually (`alembic downgrade -1` round-trip)
- [ ] Compression policy visible via `SELECT * FROM timescaledb_information.compression_settings WHERE hypertable_name = 'portfolio_weight_snapshots'`
- [ ] Cross-tenant isolation test passes on all 6 new tables
- [ ] CLAUDE.md worker table reflects 900_100-900_102
- [ ] Phase 3 is safe to start

---

## Phase 3 — Backend `/construct` payload enrichment + Construction Advisor fold-in + Narrative templater + validation_gate.py

**Goal:** The `/construct` endpoint returns the full `ConstructionRunResponse` (per quant §B.2) with embedded advisor, deterministic Jinja2 narrative, and a 15-check validation gate. Persist every run to `portfolio_construction_runs` via `construction_run_executor` worker (900_101).
**Drafts:** portfolio-enterprise-quant.md §B.2 (full payload schema), §B.3 (new computations), §B.5 (translation layer), §C.2 (advisor fold-in), §D.3 (stress contract), §E.2 (15 validation checks), §E.3 (implementation location), §F.1 (regime payload), §J.1 (templater).
**Locks consumed:** DL4, DL5, DL6, DL7, DL8, DL18, DL19.
**Migrations:** none.
**New worker locks:** 900_101 (`construction_run_executor`) first use.
**Depends on:** Phase 2 gate.

### Task 3.1: `validation_gate.py` with 15 checks

**Files:**
- Create: `backend/vertical_engines/wealth/model_portfolio/validation_gate.py`
- Create: `backend/tests/wealth/model_portfolio/test_validation_gate.py`
**Reference:** portfolio-enterprise-quant.md §E.2 (15-check table), §E.3, §E.4.

- [ ] **Step 1: Define `ValidationCheck` dataclass**
  Frozen dataclass: `id: str`, `label: str`, `severity: Literal["block","warn"]`, `passed: bool`, `value: float | int | None`, `threshold: float | int | None`, `explanation: str`. Pure data — no ORM, safe to cross thread boundary (CLAUDE.md ORM thread-safety rule).

- [ ] **Step 2: Implement each of the 15 checks as a pure sync function**
  Each function takes `(run_payload: dict, db_context: ValidationDbContext)` and returns `ValidationCheck`. The 15 checks are weights-sum-to-one, no-stale-nav, cvar-within-effective-limit, turnover-within-cap, min-diversification-count, max-single-fund-weight, all-block-min-weights-satisfied, all-block-max-weights-satisfied, no-banned-instruments, all-instruments-approved, stress-within-tolerance, no-unrealistic-expected-return, bl-views-consistent-with-prior, garch-convergence-rate, factor-model-r-squared.
  → See portfolio-enterprise-quant.md §E.2 for thresholds and sources per check.

- [ ] **Step 3: `validate_construction(run_payload, db_context) -> ValidationResult`**
  Runs all 15 checks, aggregates into `{"passed": not any(block failures), "checks": [...], "warnings": [...]}`. Fail-fast NOT permitted — always run all 15 so UI can show complete health.

- [ ] **Step 4: Tests cover each check's pass/fail edge**
  15 pass cases, 15 fail cases, plus one synthetic run payload that fails 3 blocks and 2 warns to verify aggregation semantics.

- [ ] **Step 5: Commit**
  ```bash
  git add backend/vertical_engines/wealth/model_portfolio/validation_gate.py backend/tests/wealth/model_portfolio/test_validation_gate.py
  git commit -m "feat(wealth): validation_gate.py with 15 construction checks"
  ```

### Task 3.2: Deterministic Jinja2 narrative templater

**Files:**
- Create: `backend/vertical_engines/wealth/model_portfolio/narrative_templater.py`
- Create: `backend/vertical_engines/wealth/model_portfolio/prompts/construction_narrative.jinja2`
- Create: `backend/vertical_engines/wealth/model_portfolio/prompts/construction_narrative_client_safe.jinja2`
- Create: `backend/tests/wealth/model_portfolio/test_narrative_templater.py`
**Reference:** portfolio-enterprise-quant.md §J.1 (templater), portfolio-enterprise-components.md §D.1 (backend contract), CLAUDE.md §Critical Rules (prompts are Netz IP + SandboxedEnvironment).

- [ ] **Step 1: SandboxedEnvironment setup**
  Per DL8 + CLAUDE.md: `jinja2.SandboxedEnvironment(autoescape=True, undefined=StrictUndefined)`. Never a plain `Environment`. Templates under `prompts/` are Netz IP — never surfaced in client responses as strings.

- [ ] **Step 2: Template structure**
  Templates emit a JSON-shaped dict (via `| tojson`): `headline` (1 sentence, <= 120 chars), `key_points[]` (max 5 bullets), `constraint_story` (regime + binding constraints), `holding_changes[]` (top 10 moves), `client_safe` (separate template strips numbers per §B.5 translation layer).

- [ ] **Step 3: `render_narrative(run_payload: dict) -> dict` pure function**
  Takes the structured construct payload, returns the narrative dict. Sub-second. No LLM call. Deterministic (same input → same output).

- [ ] **Step 4: Golden test — stable output**
  Load a fixture payload, render, snapshot-compare the narrative dict. Any drift breaks the test.

- [ ] **Step 5: Commit**
  ```bash
  git add backend/vertical_engines/wealth/model_portfolio/narrative_templater.py backend/vertical_engines/wealth/model_portfolio/prompts/construction_narrative.jinja2 backend/vertical_engines/wealth/model_portfolio/prompts/construction_narrative_client_safe.jinja2 backend/tests/wealth/model_portfolio/test_narrative_templater.py
  git commit -m "feat(wealth): deterministic Jinja2 construction narrative templater"
  ```

### Task 3.3: Fold `construction_advisor.py` into `_run_construction_async`

**Files:**
- Modify: `backend/app/domains/wealth/routes/model_portfolios.py` (`_run_construction_async`)
- Modify: `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py` (keep signature, add optional `db_session` injection)
- Test: `backend/tests/wealth/routes/test_construct_advisor_fold_in.py`
**Reference:** portfolio-enterprise-quant.md §C.2 (fold-in), §C.3 (when NOT to auto-run).

- [ ] **Step 1: Sequence inside `_run_construction_async`**
  Order: calibration load → optimizer cascade → stress scenarios (4 presets by default) → factor exposure (PCA) → advisor (only if `calibration.advisor_enabled`) → validation_gate → narrative templater → persist to `portfolio_construction_runs`.

- [ ] **Step 2: Advisor skip conditions (§C.3)**
  Skip advisor when `calibration.advisor_enabled=false`, when optimizer phase 1 failed (nothing to advise on), or when universe has fewer than `min_diversification_count` eligible instruments.

- [ ] **Step 3: Standalone `POST /model-portfolios/{id}/construction-advice` kept alive**
  For what-if re-runs with different scoring weights. Does NOT write a construction_run row — it's read-only advice.

- [ ] **Step 4: Commit**
  ```bash
  git add backend/app/domains/wealth/routes/model_portfolios.py backend/vertical_engines/wealth/model_portfolio/construction_advisor.py backend/tests/wealth/routes/test_construct_advisor_fold_in.py
  git commit -m "feat(wealth): fold construction_advisor into /construct response"
  ```

### Task 3.4: `construction_run_executor` worker (lock 900_101)

**Files:**
- Create: `backend/app/domains/wealth/workers/construction_run_executor.py`
- Create: `backend/tests/wealth/workers/test_construction_run_executor.py`
**Reference:** portfolio-enterprise-db.md §11.2, portfolio-enterprise-quant.md §B.4 (caching), CLAUDE.md §Stability Guardrails.

- [ ] **Step 1: Integer-literal advisory lock**
  `async with pg_try_advisory_xact_lock(db, 900_101):` wraps the whole construct pipeline. Never `hash()`, never `zlib.crc32` on runtime string (DL19).

- [ ] **Step 2: Job-or-Stream pattern (DL18 P2)**
  Route `POST /model-portfolios/{id}/construct` returns 202 + `/jobs/{id}/stream` SSE URL. Per charter §3 (expected p95 > 500ms → Job-or-Stream). Worker writes run status transitions (`running → succeeded|failed`) to Redis pubsub; SSE bridges.

- [ ] **Step 3: Bounded timeout (DL18 P1)**
  Hard 120s timeout on the construct job. On timeout: mark run `failed`, store partial trace, emit `construction_timeout` alert into `portfolio_alerts`.

- [ ] **Step 4: Idempotency (DL18 P5)**
  `@idempotent` decorator on the route + Redis single-flight lock keyed on `(portfolio_id, calibration_hash)`. Same calibration inside 60s returns the cached run.

- [ ] **Step 5: Cache-key contract**
  Per quant §B.4: `sha256(calibration_snapshot || universe_fingerprint || as_of_date)`. Redis key `construct:v1:{portfolio_id}:{hash}`, TTL 1h. If cache hit → return cached `run_id` without re-running optimizer.

- [ ] **Step 6: Commit**
  ```bash
  git add backend/app/domains/wealth/workers/construction_run_executor.py backend/tests/wealth/workers/test_construction_run_executor.py
  git commit -m "feat(wealth): construction_run_executor worker (lock 900_101) with 120s bound"
  ```

### Task 3.5: `GET /portfolio/stress-test/scenarios` catalog endpoint

**Files:**
- Modify: `backend/app/domains/wealth/routes/model_portfolios.py`
- Create: `backend/app/domains/wealth/schemas/stress.py` (`StressScenarioCatalog`)
- Test: `backend/tests/wealth/routes/test_stress_scenarios_catalog.py`
**Reference:** portfolio-enterprise-quant.md §D.1, §D.2.

- [ ] **Step 1: Schema**
  `StressScenarioCatalog` enumerates the 4 presets (`gfc_2008`, `covid_2020`, `taper_2013`, `rate_shock_200bps`) with display name, description, shock components, and a `user_defined` slot for per-run inline customs (OD-9 deferred catalog).

- [ ] **Step 2: Endpoint**
  `@router.get("/portfolio/stress-test/scenarios", response_model=StressScenarioCatalogResponse)` — returns `PRESET_SCENARIOS` from `stress_scenarios.py` via `model_validate()`. No org filter (catalog is global).

- [ ] **Step 3: Commit**
  ```bash
  git add backend/app/domains/wealth/routes/model_portfolios.py backend/app/domains/wealth/schemas/stress.py backend/tests/wealth/routes/test_stress_scenarios_catalog.py
  git commit -m "feat(wealth): GET /portfolio/stress-test/scenarios catalog endpoint"
  ```

### Task 3.6: `GET /portfolio/regime/current` endpoint

**Files:**
- Modify: `backend/app/domains/wealth/routes/model_portfolios.py` (or a new `regime.py` router)
- Create: `backend/app/domains/wealth/schemas/regime.py`
- Test: `backend/tests/wealth/routes/test_regime_current.py`
**Reference:** portfolio-enterprise-quant.md §F.1, §F.3 (frontend banner contract).

- [ ] **Step 1: Schema mirrors quant §F.1**
  `as_of`, `regime`, `regime_source`, `p_low_vol`, `p_high_vol`, `regime_since`, `days_in_current_regime`, `vix_latest`, `vix_percentile_1y`, `dominant_signals`, `cvar_multiplier_applied`, `client_safe_label` (OD-22 recommendation: NORMAL→"Balanced", RISK_ON→"Expansion", RISK_OFF→"Defensive", CRISIS→"Stress", INFLATION→"Inflation").

- [ ] **Step 2: Reads from `quant_engine/regime_service.py`**
  Pure read — no worker trigger. Cached 60s in Redis.

- [ ] **Step 3: Commit**
  ```bash
  git add backend/app/domains/wealth/routes/model_portfolios.py backend/app/domains/wealth/schemas/regime.py backend/tests/wealth/routes/test_regime_current.py
  git commit -m "feat(wealth): GET /portfolio/regime/current with client_safe_label"
  ```

### Task 3.7: End-to-end `/construct` smoke test

**Files:**
- Create: `backend/tests/wealth/e2e/test_construct_end_to_end.py`
**Reference:** portfolio-enterprise-quant.md §B.2 (full payload).

- [ ] **Step 1: Happy path**
  Seed a `draft` portfolio with calibration. POST `/construct`. Assert 202 + SSE URL. Poll SSE until `status=succeeded`. GET the run. Assert every top-level key from quant §B.2 is present and non-null (or explicitly nullable per schema): `run_id`, `calibration_snapshot`, `regime_context`, `universe_summary`, `statistical_inputs`, `optimizer_trace`, `binding_constraints`, `ex_ante_metrics`, `ex_ante_vs_previous`, `factor_exposure`, `stress_results[]`, `advisor`, `validation`, `narrative`, `rationale_per_weight`.

- [ ] **Step 2: Validation block path**
  Seed a calibration that forces `max_single_fund_weight=0.5` then pass universe with one instrument — optimizer will concentrate, validation gate should flag `max_single_fund_weight` block. Assert `validation.passed=false` and portfolio state stays `draft`.

- [ ] **Step 3: Advisor disabled path**
  Seed `advisor_enabled=false`. Assert `response.advisor is None` and narrative has no advisor section.

- [ ] **Step 4: Commit**
  ```bash
  git add backend/tests/wealth/e2e/test_construct_end_to_end.py
  git commit -m "test(wealth): /construct end-to-end happy + block + no-advisor paths"
  ```

### Phase 3 gate

- [ ] `/construct` returns the full enriched payload per quant §B.2
- [ ] `validation_gate.py` runs all 15 checks and aggregates passed/warnings correctly
- [ ] Narrative templater is deterministic (golden test green)
- [ ] Advisor surfaces inside the construct response when enabled
- [ ] `construction_run_executor` worker honors the 900_101 lock + 120s bound
- [ ] `GET /portfolio/stress-test/scenarios` and `GET /portfolio/regime/current` reachable
- [ ] Every run writes a row to `portfolio_construction_runs`
- [ ] Phase 4 is safe to start

---

## Phase 4 — Builder UI: CalibrationPanel + ConstructionNarrative + StressScenarioPanel + Run Construct flow

**Goal:** Ship the Builder column 3 right stack (Calibration | Narrative | Preview tabs), the BuilderCanvas Run Construct flow, and the new Stress matrix panel. This is the phase that closes Andrei's complaints #1-#4.
**Drafts:** portfolio-enterprise-components.md Part C (CalibrationPanel), Part D (ConstructionNarrative), §B.1 (Builder layout), §F.2 (MOCK elimination), portfolio-enterprise-charts.md A.1 (Builder charts), Part C (calibration reactive preview), portfolio-enterprise-ux-flow.md §4.2, §4.3, §4.4, §5.4, portfolio-enterprise-quant.md §A (calibration inputs).
**Locks consumed:** DL5 (calibration spine), DL6 (advisor fold-in), DL7 (4 stress scenarios), DL14 (jargon translation), DL15 (no localStorage), DL16 (formatters), DL17 (no tanstack), DL18.
**Migrations:** none.
**New worker locks:** none.
**Depends on:** Phase 3 gate + Phase 0 Task 0.3 (@investintell/ui primitives confirmed).

### Task 4.1: `CalibrationPanel.svelte` — Basic tier first

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/CalibrationPanel.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/CalibrationSliderField.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/CalibrationNumberField.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/CalibrationSelectField.svelte`
**Reference:** portfolio-enterprise-components.md Part C.1-C.5, portfolio-enterprise-quant.md §A.7 (CVaR), §A.5 (Turnover), §A.6 (Position constraints), §A.13 (Stress).

**BLOCKED ON: OD-1** (Basic default) + **OD-2** (paired slider+number). Defaults per recommendations.

- [ ] **Step 1: Props + state model**
  Props via `$props()`: `portfolioId: string`, `initial: CalibrationState`, `onApply: (draft) => Promise<void>`. Local `$state`: `tier: 'basic'|'advanced'|'expert'`, `draft: CalibrationState` (cloned from `initial`). Derived: `dirty = !deepEqual(draft, initial)`. Per portfolio-enterprise-components.md §C.3.

- [ ] **Step 2: Basic tier — 5 fields**
  `mandate` (select: conservative/moderate/aggressive), `cvar_limit` (paired slider+number, -0.15 to -0.02, step 0.005), `max_single_fund_weight` (paired slider+number, 0.05-0.30, step 0.01), `turnover_cap` (paired slider+number, 0.05-1.0, step 0.05), `stress_scenarios_active` (4-checkbox group). All labels from Phase 10 translation table (use placeholder labels that Task 10.1 will overwrite).

- [ ] **Step 3: Preview + Apply button row (DL5)**
  Preview triggers an in-flight optimizer call via debounced fetch (see portfolio-enterprise-charts.md C.2 for 1500ms debounce strategy). Apply persists via `PUT /model-portfolios/{id}/calibration`. NEVER reactive on slider drag (DL5 explicit — that's complaint #1's root cause).

- [ ] **Step 4: Zero localStorage (DL15)**
  `draft` is in-memory in the component; Apply persists to backend. On route change, unsaved draft is lost — that's the contract.

- [ ] **Step 5: svelte-autofixer sweep**
  Run `npx @sveltejs/mcp svelte-autofixer` on the new files per CLAUDE.md §Svelte MCP.

- [ ] **Step 6: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/Calibration*.svelte
  git commit -m "feat(wealth): CalibrationPanel Basic tier with Preview/Apply gating"
  ```

### Task 4.2: `CalibrationPanel.svelte` — Advanced + Expert tiers

**Files:**
- Modify: `frontends/wealth/src/lib/components/portfolio/CalibrationPanel.svelte`
**Reference:** portfolio-enterprise-components.md §C.1, portfolio-enterprise-quant.md §A.8 (regime), §A.9 (BL), §A.11 (GARCH), §A.14 (factor), §A.16 (advisor).

- [ ] **Step 1: Advanced tier (10 fields)**
  Regime override (select: `auto | NORMAL | RISK_ON | RISK_OFF | CRISIS | INFLATION`), `bl_enabled` (toggle), `bl_view_confidence_default` (0-1), `garch_enabled` (toggle), `turnover_lambda` (0.1-10), `stress_severity_multiplier` (0.5-2.0), `advisor_enabled` (toggle), `cvar_level` (0.90/0.95/0.99 segmented), `lambda_risk_aversion` (0.5-5), `shrinkage_intensity_override` (0-1, with "auto" null).

- [ ] **Step 2: Expert tier (48 fields collapsed in sections)**
  Accordion sections: Optimizer, Position Constraints, CVaR internals, Regime Markov params, BL internals, Ledoit-Wolf, GARCH, Factor Model, Advisor. Each field with tooltip pulled from the quant draft §A.1-A.16 definitions.

- [ ] **Step 3: Expert overrides persist in `expert_overrides jsonb`**
  (per portfolio_calibration schema from Phase 2.1). Typed fields go in their typed column; expert knobs go in the jsonb blob.

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/CalibrationPanel.svelte
  git commit -m "feat(wealth): CalibrationPanel Advanced + Expert tiers (63 inputs)"
  ```

### Task 4.3: `ConstructionNarrative.svelte`

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/ConstructionNarrative.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/NarrativeHeadline.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/NarrativeMetricsStrip.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/HoldingChangesList.svelte`
**Reference:** portfolio-enterprise-components.md §D.2, §D.3 (2-col narrative + sticky metrics), §D.4 (empty states), portfolio-enterprise-quant.md §B.2 (payload).

- [ ] **Step 1: RouteData<T> load contract**
  Per CLAUDE.md §Stability Guardrails charter §3: detail pages use `RouteData<T>` + `<svelte:boundary>` + `PanelErrorState`. Never `throw error()`.

- [ ] **Step 2: 2-col layout**
  Left: narrative prose (`headline`, `key_points[]`, `constraint_story`, `holding_changes[]`) from the run's `narrative` JSON. Right: sticky `NarrativeMetricsStrip` showing `ex_ante_metrics` (expected return, vol, CVaR, Sharpe) with `ex_ante_vs_previous` deltas via `@investintell/ui` `formatPercent` / `formatBps`.

- [ ] **Step 3: Advisor section (only if `advisor_enabled`)**
  Tiered exposure recommendation table (per quant §A.16 "Tiered exposure recommendation") with credit for any blocks where the advisor suggestion matches the optimizer weights.

- [ ] **Step 4: Empty states (§D.4)**
  "No run yet — press Run Construct to generate narrative" (draft state), "Run in progress — tracking SSE" (running), "Last run failed: <reason>" (failed) with "See trace" expand.

- [ ] **Step 5: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/ConstructionNarrative.svelte frontends/wealth/src/lib/components/portfolio/Narrative*.svelte frontends/wealth/src/lib/components/portfolio/HoldingChangesList.svelte
  git commit -m "feat(wealth): ConstructionNarrative with 2-col + sticky metrics"
  ```

### Task 4.4: `StressScenarioPanel.svelte` — 2 tabs (Matrix + Custom)

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/StressScenarioPanel.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/StressScenarioMatrixTab.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/StressCustomShockTab.svelte`
**Reference:** portfolio-enterprise-components.md §F.2 Stage 3, portfolio-enterprise-ux-flow.md §5.4, portfolio-enterprise-quant.md §D.3.

**BLOCKED ON: OD-8** (two tabs vs single dropdown). Default to two tabs per recommendation.

- [ ] **Step 1: Matrix tab**
  4 preset scenarios in a grid: row per scenario, columns: name, NAV impact, CVaR impact, Pass/Warn chip, "Details" expand. Sparkline column uses `SparklineSVG.svelte` (Phase 9) from per-instrument impact — or plain text in Phase 4 and upgrade in Phase 9.

- [ ] **Step 2: Custom tab**
  Keep the existing 3-input custom-only form (equity shock, rate shock, credit spread shock) but submit via new contract `POST /portfolio/{id}/stress-test` with `scenario_kind='user_defined'`.

- [ ] **Step 3: Replace `workspace.runStressTest` no-op**
  Per Phase 0 Task 0.1 Step 3 diagnostic — the current call always dispatches `scenario_name: "custom"`. Wire the Matrix tab to send the chosen preset name.

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/Stress*.svelte
  git commit -m "feat(wealth): StressScenarioPanel with Matrix + Custom tabs"
  ```

### Task 4.5: Wire Run Construct into `BuilderCanvas`

**Files:**
- Modify: `frontends/wealth/src/lib/components/portfolio/BuilderCanvas.svelte`
- Modify: `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` (`runConstruct`)
- Create: `frontends/wealth/src/lib/components/portfolio/BuilderRightStack.svelte`
**Reference:** portfolio-enterprise-components.md §B.1, portfolio-enterprise-ux-flow.md §4.3.

- [ ] **Step 1: `BuilderRightStack` — 3 tabs**
  Calibration | Narrative | Preview. Svelte 5 runes for active tab state. Calibration tab renders `CalibrationPanel`. Narrative tab renders `ConstructionNarrative`. Preview tab renders a minimal metrics strip from the in-flight preview call.

- [ ] **Step 2: `runConstruct` via Job-or-Stream**
  Replace the current direct POST with `fetch('/api/model-portfolios/{id}/construct', { method: 'POST' })` → 202 → read SSE URL from response → open `fetch()+ReadableStream` SSE (DL15 — never EventSource). Stream `status` transitions and update workspace store.

- [ ] **Step 3: On `succeeded`, auto-switch `BuilderRightStack` to Narrative tab**
  UX nicety — the user asked "build me something", the answer should be front-and-center.

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/BuilderCanvas.svelte frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts frontends/wealth/src/lib/components/portfolio/BuilderRightStack.svelte
  git commit -m "feat(wealth): wire Run Construct SSE flow into BuilderCanvas"
  ```

### Phase 4 gate

- [ ] CalibrationPanel renders 5 Basic + 10 Advanced + 48 Expert inputs
- [ ] Preview debounced at 1500ms, Apply persists to backend
- [ ] Run Construct returns narrative into ConstructionNarrative panel
- [ ] Stress Matrix tab shows 4 preset scenarios with NAV/CVaR impacts
- [ ] Zero `localStorage`, zero `.toFixed()`, zero inline `Intl.*` in new files (eslint green)
- [ ] Phase 5 is safe to start

---

## Phase 5 — Builder UI: state machine bindings (allowed_actions), Universe sub-pill, NewPortfolioDialog, legacy PolicyPanel removal

**Goal:** Close the remaining Builder complaints — the dead "New Portfolio" button, the legacy PolicyPanel no-op, and the Universe-as-standalone-route anti-pattern. Bind every Builder button to `allowed_actions` from the backend.
**Drafts:** portfolio-enterprise-ux-flow.md §3.3 (visibility rules), §4.5 (universe sub-pill), portfolio-enterprise-components.md §A.2 (verification of Andrei's claims), §B.1 (builder layout), §F.2 (MOCK elimination Stage 1-2), portfolio-enterprise-ux-flow.md §11.2.
**Locks consumed:** DL1 (URL contract), DL2 (universe sub-pill), DL3 (state machine), DL15, DL16, DL17.
**Migrations:** none.
**New worker locks:** none.
**Depends on:** Phase 4 gate.

### Task 5.1: `NewPortfolioDialog.svelte` (kills the dead button)

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/NewPortfolioDialog.svelte`
- Modify: `frontends/wealth/src/routes/(app)/portfolio/+page.svelte` (the line 115-118 button)
- Modify: `backend/app/domains/wealth/routes/model_portfolios.py` (`POST /model-portfolios`)
- Test: `frontends/wealth/tests/new-portfolio-dialog.spec.ts`
**Reference:** portfolio-enterprise-components.md §A.2 claim 2, portfolio-enterprise-ux-flow.md §4.1, Phase 0 Task 0.1 Step 2.

- [ ] **Step 1: Dialog form fields**
  `name` (required), `mandate` (conservative/moderate/aggressive select), `copy_from` (optional — select an existing portfolio to seed calibration + strategic blocks), `description` (optional). Submit posts to `POST /model-portfolios` and routes to `/portfolio/builder/{new_id}` on success.

- [ ] **Step 2: Backend route creates in `draft` state**
  New portfolio row starts with `state='draft'`, initializes a paired `portfolio_calibration` row with Basic defaults from `ConfigService.get("wealth","default_calibration",org_id)`, and returns the full schema including `allowed_actions=["construct","archive"]`.

- [ ] **Step 3: Wire button onclick**
  Replace the dead button at `portfolio/+page.svelte:115-118` with `<button onclick={() => dialogOpen = true}>`. Open dialog, on success route to Builder.

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/NewPortfolioDialog.svelte frontends/wealth/src/routes/\(app\)/portfolio/+page.svelte backend/app/domains/wealth/routes/model_portfolios.py frontends/wealth/tests/new-portfolio-dialog.spec.ts
  git commit -m "feat(wealth): NewPortfolioDialog kills the dead +Portfolio button"
  ```

### Task 5.2: Bind Builder action buttons to `allowed_actions`

**Files:**
- Modify: `frontends/wealth/src/lib/components/portfolio/BuilderCanvas.svelte`
- Modify: `frontends/wealth/src/lib/components/portfolio/BuilderActionBar.svelte` (new or existing)
- Create: `frontends/wealth/src/lib/components/portfolio/PortfolioStateChip.svelte`
**Reference:** portfolio-enterprise-ux-flow.md §3.3 (visibility rules), §3.2 (transitions), portfolio-enterprise-components.md §B.1.

- [ ] **Step 1: Action → button mapping**
  One mapping object keyed by action string, valued by `{ label, variant, icon, endpoint }`. Example: `construct → { label: "Run Construct", variant: "primary", endpoint: "POST /construct" }`, `validate → { label: "Validate", variant: "secondary" }`, `approve → { label: "Approve", variant: "success", confirm: true }`, `activate → { label: "Go Live", variant: "primary", confirm: true }`.

- [ ] **Step 2: Render rule**
  `{#each portfolio.allowed_actions as action}<ActionButton {...ACTION_MAP[action]} />{/each}`. No `if state === ...` conditionals anywhere (DL3 explicit).

- [ ] **Step 3: `PortfolioStateChip` — visible at all times**
  Shows current state with client-safe label (`draft → "Draft"`, `constructed → "Built"`, `validated → "Validated"`, `approved → "Approved"`, `live → "Live"`, `paused → "Paused"`, `archived → "Archived"`, `rejected → "Rejected"`). Hover shows `state_metadata.latest_transition_reason`.

- [ ] **Step 4: Confirmation modals for `approve` and `activate`**
  Reuse `@investintell/ui` `ConfirmDialog`. Approve requires a `reason` text; Activate requires re-confirming the effective CVaR limit and the active stress suite.

- [ ] **Step 5: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/Builder*.svelte frontends/wealth/src/lib/components/portfolio/PortfolioStateChip.svelte
  git commit -m "feat(wealth): bind Builder action buttons to allowed_actions"
  ```

### Task 5.3: Universe sub-pill — shallow route under `/portfolio/builder`

**Files:**
- Create: `frontends/wealth/src/routes/(app)/portfolio/builder/universe/+page.svelte`
- Create: `frontends/wealth/src/routes/(app)/portfolio/builder/universe/+page.server.ts`
- Modify: `frontends/wealth/src/lib/components/portfolio/BuilderSubNav.svelte`
- Modify: `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` (`attachInstrumentToBlock`)
**Reference:** portfolio-enterprise-ux-flow.md §4.5, memory `feedback_universe_lives_in_portfolio`, portfolio-enterprise-components.md §B.1.

**BLOCKED ON: OD-7** (bulk approve yes/no). Default to yes with modal per recommendation.

- [ ] **Step 1: Route file at `/portfolio/builder/universe`**
  Same FCL shell as `/portfolio/builder` — Col1 remains Models/Policy/Universe sub-pills, Col2 becomes `UniverseTable` (Approved + Watchlist + Rejected filter rail), Col3 becomes a filter panel that reuses `FilterRail`.

- [ ] **Step 2: DnD into allocation blocks**
  Reuse `svelte-dnd-action` (already in repo via PipelineKanban). Drag a row from UniverseTable, drop on a block tile in a visible builder canvas (when navigated back), store invokes `attachInstrumentToBlock(block_id, instrument_id)`.

- [ ] **Step 3: Bulk approve modal**
  Select N rows → "Approve selected" button → confirmation modal ("Approve 23 instruments for use in portfolios?") → bulk POST to `/instruments/org/bulk-approve`.

- [ ] **Step 4: Remove `/universe` as a top-nav route**
  Redirect old top-nav universe route to `/portfolio/builder/universe` for 90 days, then delete in Phase 10.

- [ ] **Step 5: Commit**
  ```bash
  git add frontends/wealth/src/routes/\(app\)/portfolio/builder/universe/ frontends/wealth/src/lib/components/portfolio/BuilderSubNav.svelte frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts
  git commit -m "feat(wealth): Approved Universe as Builder sub-pill with DnD into blocks"
  ```

### Task 5.4: Delete legacy `PolicyPanel.svelte` no-op

**Files:**
- Delete: `frontends/wealth/src/lib/components/portfolio/PolicyPanel.svelte`
- Modify: `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` (remove `updatePolicy` no-op at lines 684-688 per Phase 0 diagnostic)
- Modify: any remaining consumers of `PolicyPanel`
**Reference:** portfolio-enterprise-components.md §A.2 claim 1, Phase 0 Task 0.1 Step 1.

- [ ] **Step 1: Confirm no external consumers**
  ```bash
  rg -n "PolicyPanel" frontends/wealth/src
  ```
  Expected: only the page file still imports it. If other call sites exist, stop and update this task with their locations.

- [ ] **Step 2: Delete + remove import**
  Delete the file, delete the import, delete the `updatePolicy` store method. CalibrationPanel is its replacement (DL5) — all 5 policy fields are now inside CalibrationPanel's Basic tier.

- [ ] **Step 3: Commit**
  ```bash
  git rm frontends/wealth/src/lib/components/portfolio/PolicyPanel.svelte
  git add frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts
  git commit -m "refactor(wealth): delete PolicyPanel no-op (replaced by CalibrationPanel)"
  ```

### Task 5.5: Sub-nav ribbon under TopNav

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/PortfolioSubNav.svelte`
- Modify: `frontends/wealth/src/routes/(app)/portfolio/+layout.svelte`
**Reference:** portfolio-enterprise-ux-flow.md §1.1, §1.2, DL1.

- [ ] **Step 1: Three pills**
  `Builder | Analytics | Live` with derived badges from `portfolio-workspace` store: `drafts_in_progress`, `subjects_under_analysis`, `live_portfolios_with_open_alerts`.

- [ ] **Step 2: Always visible under `/portfolio/*`**
  Mount in the portfolio layout. Sticky below TopNav.

- [ ] **Step 3: Hide on `/portfolio/live` full-terminal mode?**
  No — OD-13 locks both selector + BottomTabDock in Live. Sub-nav stays visible (DL1).

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/PortfolioSubNav.svelte frontends/wealth/src/routes/\(app\)/portfolio/+layout.svelte
  git commit -m "feat(wealth): /portfolio/* sub-nav ribbon with badge counts"
  ```

### Phase 5 gate

- [ ] "+Portfolio" button opens NewPortfolioDialog → creates draft → routes to Builder
- [ ] Every Builder action button comes from `allowed_actions` (zero if-state conditionals)
- [ ] Approved Universe reachable only via `/portfolio/builder/universe` sub-pill
- [ ] `PolicyPanel.svelte` deleted, no references remain
- [ ] Sub-nav ribbon visible under every `/portfolio/*` route with badge counts
- [ ] Phase 6 is safe to start

---

## Phase 6 — Analytics surface: scope switcher, AnalysisGrid, portfolio-specific chart components, Compare Both deferred to v1.1

**Goal:** Ship `/portfolio/analytics` with the Discovery Analysis primitives, a scope switcher (`model_portfolios | approved_universe`), and 4 portfolio-specific chart components. Defer `compare_both` to v1.1 per OD-25.
**Drafts:** portfolio-enterprise-ux-flow.md §5 (Analytics phase), §5.2 (layout), §5.3 (scope switcher), §5.4 (analysis groups), portfolio-enterprise-components.md §B.2 (reuse Discovery), portfolio-enterprise-charts.md §A.2 (Analytics charts), §F.4 (new chart components).
**Locks consumed:** DL1, DL14 (jargon), DL15, DL16, DL17, DL18.
**Migrations:** none.
**New worker locks:** none.
**Depends on:** Phase 5 gate + Discovery Phase 5-8 primitives landed in `@investintell/ui`.

### Task 6.1: `/portfolio/analytics` route + shell

**Files:**
- Create: `frontends/wealth/src/routes/(app)/portfolio/analytics/+page.svelte`
- Create: `frontends/wealth/src/routes/(app)/portfolio/analytics/+page.server.ts`
- Create: `frontends/wealth/src/lib/components/portfolio/PortfolioAnalyticsShell.svelte`
**Reference:** portfolio-enterprise-ux-flow.md §5.2, portfolio-enterprise-components.md §B.2.

- [ ] **Step 1: FCL shell, matching Discovery Analysis**
  Col1 = 260px `FilterRail`, Col2 = `AnalysisGrid` (3×2 ChartCards), Col3 = optional detail pane. BottomTabDock mounted at bottom for cross-subject sessions.

- [ ] **Step 2: Scope switcher at top of FilterRail**
  Segmented control: `Model Portfolios | Approved Universe | Compare Both (v1.1)`. The third option is present but disabled with a "v1.1" badge per OD-25.

- [ ] **Step 3: Scope drives subject list**
  `Model Portfolios` shows `model_portfolios` rows; `Approved Universe` shows `instruments_org WHERE approval_status='approved'`. Selecting a subject populates the 3×2 grid.

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/routes/\(app\)/portfolio/analytics/ frontends/wealth/src/lib/components/portfolio/PortfolioAnalyticsShell.svelte
  git commit -m "feat(wealth): /portfolio/analytics shell with scope switcher"
  ```

### Task 6.2: Reuse Discovery charts verbatim for Returns/Risk/Holdings/Peer groups

**Files:**
- Modify: `frontends/wealth/src/routes/(app)/portfolio/analytics/+page.svelte`
**Reference:** portfolio-enterprise-charts.md §F.1 (existing charts to reuse), portfolio-enterprise-ux-flow.md §5.4.

- [ ] **Step 1: Returns & Risk group (3 charts)**
  `NavHeroChart` + `RollingRiskChart` + `DrawdownUnderwaterChart` — reuse from Discovery without modification.

- [ ] **Step 2: Holdings group (2 charts)**
  Treemap of current weights (new portfolio-specific `HoldingsTreemapChart`, Task 6.3) + `ReturnDistributionChart` (reuse).

- [ ] **Step 3: Peer group (2 charts)**
  `MonthlyReturnsHeatmap` + `RiskMetricsBulletChart` (both reuse from Discovery).

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/routes/\(app\)/portfolio/analytics/+page.svelte
  git commit -m "feat(wealth): Analytics groups reuse Discovery chart primitives"
  ```

### Task 6.3: Portfolio-specific charts (4 new components)

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/charts/BrinsonWaterfallChart.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/charts/FactorExposureBarChart.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/charts/ConstituentCorrelationHeatmap.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/charts/RiskAttributionBarChart.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/charts/HoldingsTreemapChart.svelte`
**Reference:** portfolio-enterprise-charts.md §F.4 (new Analytics phase charts), §A.2 (Analytics spec), portfolio-enterprise-charts.md §D (chartTokens).

- [ ] **Step 1: BrinsonWaterfallChart — bar + marker**
  Consumes `{allocation_effect, selection_effect, interaction_effect, total}` from `GET /portfolio/{id}/attribution`. Uses `chartTokens()` default variant. Formatter: `formatBps`.

- [ ] **Step 2: FactorExposureBarChart — horizontal bars**
  Consumes `factor_exposure` from construction_run payload (per quant §B.2). X axis = factor loading (-1 to 1), Y axis = factor name. Reference line at 0.

- [ ] **Step 3: ConstituentCorrelationHeatmap — Marchenko-Pastur denoised**
  Reuses `vertical_engines/wealth/correlation/` backend output. Heatmap N×N, diverging colour scale from `chartTokens`.

- [ ] **Step 4: RiskAttributionBarChart — stacked bar per holding**
  One bar per instrument, stacks decompose total risk contribution into systematic (factor) + idiosyncratic.

- [ ] **Step 5: HoldingsTreemapChart**
  Reuses `TreemapChart` from svelte-echarts. Rectangle per holding sized by effective weight, coloured by sector or by block_id.

- [ ] **Step 6: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/charts/
  git commit -m "feat(wealth): 5 portfolio-specific Analytics chart components"
  ```

### Task 6.4: Stress group inside Analytics

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/charts/StressImpactMatrixChart.svelte`
- Modify: `frontends/wealth/src/routes/(app)/portfolio/analytics/+page.svelte`
**Reference:** portfolio-enterprise-ux-flow.md §5.4, portfolio-enterprise-charts.md §A.2.

- [ ] **Step 1: Stress group (4th group on a secondary tab if 4 groups overflow)**
  Matrix chart: rows = scenarios, columns = metrics (NAV impact, CVaR impact, VaR impact, max drawdown). Reads from `portfolio_stress_results` joined on latest succeeded run.

- [ ] **Step 2: Drill-down to per-instrument impact**
  Click scenario cell → right-pane detail showing per-instrument impact. Reuses `EnterpriseTable`.

- [ ] **Step 3: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/charts/StressImpactMatrixChart.svelte frontends/wealth/src/routes/\(app\)/portfolio/analytics/+page.svelte
  git commit -m "feat(wealth): Analytics Stress group with per-instrument drill-down"
  ```

### Task 6.5: BottomTabDock wiring for cross-subject sessions

**Files:**
- Modify: `frontends/wealth/src/routes/(app)/portfolio/analytics/+page.svelte`
**Reference:** portfolio-enterprise-ux-flow.md §8.2, DL15 (no localStorage — URL hash only).

- [ ] **Step 1: Mount BottomTabDock from `@investintell/ui`**
  Per Discovery Phase 8 precedent. Persist state in URL hash (`#tabs=<base64>`), never storage.

- [ ] **Step 2: Tab = `{subject_id, scope, group_focus}`**
  Opening a new subject creates a new tab; clicking an existing tab restores its state.

- [ ] **Step 3: Commit**
  ```bash
  git add frontends/wealth/src/routes/\(app\)/portfolio/analytics/+page.svelte
  git commit -m "feat(wealth): BottomTabDock for Analytics cross-subject sessions"
  ```

### Phase 6 gate

- [ ] `/portfolio/analytics` renders with scope switcher + FilterRail + 3×2 grid + BottomTabDock
- [ ] 4 chart groups (Returns & Risk, Holdings, Peer, Stress) reachable
- [ ] 5 new portfolio-specific charts render against real backend data
- [ ] `Compare Both` option visible but disabled with v1.1 badge
- [ ] Phase 7 is safe to start

---

## Phase 7 — Alerts unification: portfolio_alerts writes from portfolio_eval, drift_check, regime_fit + SSE bridge + AlertsFeedPanel + critical toast + sub-nav badge

**Goal:** Every worker that previously emitted fire-and-forget alerts now writes to `portfolio_alerts` (the unified feed from Phase 2). SSE bridge delivers them to three presentation tiers. Fold in the uncommitted `regime_fit.py` work per Phase 0 Task 0.4.
**Drafts:** portfolio-enterprise-db.md §11.1, portfolio-enterprise-ux-flow.md §7 (Alerts Feed Architecture), §7.3 (presentation tiers), §7.4 (rules), portfolio-enterprise-components.md §E.2 (AlertsFeedPanel).
**Locks consumed:** DL12 (unified alerts), DL18 (guardrails).
**Migrations:** none (0103 landed in Phase 2).
**New worker locks:** 900_102 (`alert_sweeper`) first use.
**Depends on:** Phase 2 gate (table exists), Phase 6 gate (Analytics needs alert counts for badges).

### Task 7.1: `portfolio_eval` writes to `portfolio_alerts`

**Files:**
- Modify: `backend/app/domains/wealth/workers/portfolio_eval.py` (lines 138-166 `_publish_alert`)
- Modify: `backend/app/domains/wealth/services/alerts_service.py` (new or existing)
- Test: `backend/tests/wealth/workers/test_portfolio_eval_alerts.py`
**Reference:** portfolio-enterprise-db.md §11.1, portfolio-enterprise-ux-flow.md §7.1.

- [ ] **Step 1: `AlertsService.write_alert(db, portfolio_id, alert_type, severity, source_worker, dedupe_key, payload)`**
  One method all writers share. Inserts row into `portfolio_alerts` with `ON CONFLICT DO NOTHING` on the dedupe partial unique index. After insert, `Redis PUBLISH portfolio:alerts:{portfolio_id}` for SSE bridging.

- [ ] **Step 2: Replace `_publish_alert` body**
  Current body publishes to Redis directly with no DB write. New body calls `AlertsService.write_alert(...)` with `alert_type='cvar_breach'` or `'weight_drift'`, severity mapped from the existing breach severity enum, `dedupe_key=f"{portfolio_id}:{alert_type}:{as_of_date}"`.

- [ ] **Step 3: Test dedupe**
  Two consecutive eval runs on the same day for the same breach → one row, one publish.

- [ ] **Step 4: Commit**
  ```bash
  git add backend/app/domains/wealth/workers/portfolio_eval.py backend/app/domains/wealth/services/alerts_service.py backend/tests/wealth/workers/test_portfolio_eval_alerts.py
  git commit -m "feat(wealth): portfolio_eval writes breaches to portfolio_alerts"
  ```

### Task 7.2: `drift_check` fanout to `portfolio_alerts`

**Files:**
- Modify: `backend/app/domains/wealth/workers/drift_check.py`
- Test: `backend/tests/wealth/workers/test_drift_check_alert_fanout.py`
**Reference:** portfolio-enterprise-db.md §11.1, §13.8, OD-24 (fanout recommendation).

- [ ] **Step 1: On drift status flip, fanout to every holding portfolio**
  Query `instruments_org` + current portfolio holdings. For each `(portfolio_id, instrument_id)` pair, write one `portfolio_alerts` row with `alert_type='drift'`, `payload.strategy_drift_alerts_id=<id>` for drill-down.

- [ ] **Step 2: Preserve lock ID 42**
  Do NOT change the existing advisory lock; just add the fanout call inside the existing locked section.

- [ ] **Step 3: Commit**
  ```bash
  git add backend/app/domains/wealth/workers/drift_check.py backend/tests/wealth/workers/test_drift_check_alert_fanout.py
  git commit -m "feat(wealth): drift_check fans out to portfolio_alerts per holding"
  ```

### Task 7.3: `regime_fit` emits `regime_change` alerts (integrates uncommitted work)

**Files:**
- Modify: `backend/app/domains/wealth/workers/regime_fit.py` (currently uncommitted per Phase 0 Task 0.4)
- Test: `backend/tests/wealth/workers/test_regime_fit_regime_change_alert.py`
**Reference:** portfolio-enterprise-db.md §11.1, Phase 0 Task 0.4 (integration option 3).

**BLOCKED ON: OD-22** (regime label set) — needed for the alert payload's `client_safe_label`.

- [ ] **Step 1: Read the uncommitted diff first**
  Per Phase 0 Task 0.4 — the existing work stays intact; this task adds alert writes alongside it.

- [ ] **Step 2: On regime transition (detected != previous)**
  Query all `live` portfolios for the org. For each, write one alert row with `alert_type='regime_change'`, `severity='warning'` (or `'critical'` if new regime is `CRISIS`), `payload.from_regime`, `payload.to_regime`, `payload.client_safe_from`, `payload.client_safe_to` using OD-22 mapping.

- [ ] **Step 3: Confirm `regime_fit` lock ID is what Phase 0 diagnostic found**
  Use the confirmed ID, NOT a guess.

- [ ] **Step 4: Commit the combined work**
  ```bash
  git add backend/app/domains/wealth/workers/regime_fit.py backend/tests/wealth/workers/test_regime_fit_regime_change_alert.py
  git commit -m "feat(wealth): regime_fit emits regime_change alerts to live portfolios"
  ```

### Task 7.4: `alert_sweeper` worker (lock 900_102)

**Files:**
- Create: `backend/app/domains/wealth/workers/alert_sweeper.py`
- Create: `backend/tests/wealth/workers/test_alert_sweeper.py`
**Reference:** portfolio-enterprise-db.md §11.2, portfolio-enterprise-ux-flow.md §7.4.

- [ ] **Step 1: Hourly loop**
  `pg_try_advisory_lock(900_102)`. Inside lock: `UPDATE portfolio_alerts SET dismissed_at = now(), dismissed_by = 'alert_sweeper' WHERE auto_dismiss_at < now() AND dismissed_at IS NULL`.

- [ ] **Step 2: Prune old failed construction runs (>90 days, DL4)**
  `DELETE FROM portfolio_construction_runs WHERE status='failed' AND requested_at < now() - interval '90 days'`. Keep succeeded runs forever (cap of 10 most recent per portfolio enforced at write time in Phase 3).

- [ ] **Step 3: Commit**
  ```bash
  git add backend/app/domains/wealth/workers/alert_sweeper.py backend/tests/wealth/workers/test_alert_sweeper.py
  git commit -m "feat(wealth): alert_sweeper worker (lock 900_102)"
  ```

### Task 7.5: SSE bridge `/alerts/stream?portfolio_id=...`

**Files:**
- Create: `backend/app/domains/wealth/routes/alerts.py`
- Create: `backend/tests/wealth/routes/test_alerts_stream.py`
**Reference:** portfolio-enterprise-ux-flow.md §7.3, portfolio-enterprise-db.md §7, CLAUDE.md §SSE.

- [ ] **Step 1: `sse-starlette` EventSourceResponse**
  On subscribe: open Redis pubsub on `portfolio:alerts:{portfolio_id}`. Also snapshot all open alerts from `portfolio_alerts WHERE dismissed_at IS NULL` for that portfolio (reconnect path — DL12).

- [ ] **Step 2: RateLimitedBroadcaster + ConnectionId UUID (DL18)**
  Per CLAUDE.md §Stability Guardrails charter §3. Never `id(ws)` for connection tracking.

- [ ] **Step 3: Heartbeat every 15s**
  Keep SSE alive across corporate firewalls.

- [ ] **Step 4: Commit**
  ```bash
  git add backend/app/domains/wealth/routes/alerts.py backend/tests/wealth/routes/test_alerts_stream.py
  git commit -m "feat(wealth): /alerts/stream SSE bridge with snapshot-on-reconnect"
  ```

### Task 7.6: `AlertsFeedPanel.svelte` — persistent feed (Tier 1)

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/AlertsFeedPanel.svelte`
- Create: `frontends/wealth/src/lib/stores/alerts-stream.svelte.ts`
**Reference:** portfolio-enterprise-components.md §E.2, portfolio-enterprise-ux-flow.md §7.3.

- [ ] **Step 1: `alerts-stream.svelte.ts` store**
  Opens `/alerts/stream?portfolio_id=X` via `fetch()+ReadableStream` (DL15 — never EventSource). Maintains `$state<PortfolioAlert[]>` sorted by `created_at DESC`. Dedupes on `dedupe_key`. On reconnect, reconciles with snapshot.

- [ ] **Step 2: Feed panel UI**
  One row per alert: severity chip + alert_type label (from Phase 10 translation table) + created_at relative time + source_worker + acknowledge button. Tall list with virtual scroll for 100+ alerts.

- [ ] **Step 3: Acknowledge + dismiss endpoints**
  `POST /alerts/{id}/acknowledge` and `POST /alerts/{id}/dismiss` with actor_id from Clerk JWT. `@idempotent` decorator on both (DL18 P5).

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/AlertsFeedPanel.svelte frontends/wealth/src/lib/stores/alerts-stream.svelte.ts
  git commit -m "feat(wealth): AlertsFeedPanel persistent feed with SSE stream"
  ```

### Task 7.7: Critical toast (Tier 2) + sub-nav badge (Tier 3)

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/CriticalAlertToast.svelte`
- Modify: `frontends/wealth/src/lib/components/portfolio/PortfolioSubNav.svelte`
- Modify: `frontends/wealth/src/routes/(app)/portfolio/+layout.svelte`
**Reference:** portfolio-enterprise-ux-flow.md §7.3.

- [ ] **Step 1: Toast on any `severity='critical'`**
  Mounted in the portfolio layout — fires on any `/portfolio/*` route. Auto-dismiss after 10s unless user interacts.

- [ ] **Step 2: Sub-nav Live pill badge count**
  Derived from alerts store: `live_portfolios_with_open_alerts = unique(alerts.map(a => a.portfolio_id)).length`.

- [ ] **Step 3: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/CriticalAlertToast.svelte frontends/wealth/src/lib/components/portfolio/PortfolioSubNav.svelte frontends/wealth/src/routes/\(app\)/portfolio/+layout.svelte
  git commit -m "feat(wealth): critical alert toast + sub-nav badge (Tiers 2 & 3)"
  ```

### Phase 7 gate

- [ ] `portfolio_eval`, `drift_check`, `regime_fit` all write to `portfolio_alerts`
- [ ] `alert_sweeper` honoring lock 900_102 and pruning stale alerts + failed runs
- [ ] `/alerts/stream` SSE delivers real-time alerts with snapshot-on-reconnect
- [ ] `AlertsFeedPanel` renders in Builder right rail (optional) and Live col1 (Phase 9)
- [ ] Critical toast fires on `severity='critical'`
- [ ] Sub-nav Live badge shows open-alert portfolio count
- [ ] Phase 8 is safe to start

---

## Phase 8 — Live workbench shell: WorkbenchLayout primitive, chartTokens('workbench') variant, density tokens, route + selector + tools state machine

**Goal:** Ship the terminal-style shell for `/portfolio/live` — new `WorkbenchLayout` primitive in `@investintell/ui`, `chartTokens('workbench')` variant, density CSS vars, route, portfolio selector, and the tool state machine that `WorkbenchCoreChart` will consume in Phase 9.
**Drafts:** portfolio-enterprise-components.md §E.1 (WorkbenchLayout spec), §E.3 (WeightVectorTable — deferred to Phase 9), portfolio-enterprise-charts.md §D.1 (chartTokens variant parameter), §D.2 (option impact), Appendix (WorkbenchCoreChart state machine), portfolio-enterprise-ux-flow.md §6.1 (shell divergence), §6.2 (layout regions), §6.3 (always-visible vs collapsible), §8.1 (portfolio selector).
**Locks consumed:** DL9 (WorkbenchCoreChart single instance + replaceMerge), DL11 (live price worker spec consumed in shell tools), DL14, DL15, DL16.
**Migrations:** none.
**New worker locks:** none.
**Depends on:** Phase 7 gate.

### Task 8.1: `WorkbenchLayout.svelte` primitive in `@investintell/ui`

**Files:**
- Create: `packages/ui/src/lib/layouts/WorkbenchLayout.svelte`
- Create: `packages/ui/src/lib/layouts/WorkbenchLayout.test.ts`
- Modify: `packages/ui/src/lib/index.ts` (export)
**Reference:** portfolio-enterprise-components.md §E.1, portfolio-enterprise-ux-flow.md §6.1, §6.2.

**BLOCKED ON: OD-11** (density tokens admin-configurable). Ship with hardcoded defaults; expose via `ConfigService` in v1.1.

- [ ] **Step 1: 12-col CSS Grid with named regions**
  Grid template: `toolbar` row (36px) spans all 3 columns, then `col1 center col3` middle row (1fr), then `col1 footer col3` bottom row (200px). Columns: 260px / 1fr / 320px. Outer box: `height: calc(100vh - 88px); padding: 24px;` per memory `feedback_layout_cage_pattern`.
  → See portfolio-enterprise-components.md §E.1 for the full style block.

- [ ] **Step 2: Named slots via Svelte 5 snippets**
  `{@render toolbar?.()}`, `{@render col1?.()}`, `{@render center?.()}`, `{@render col3?.()}`, `{@render footer?.()}`. No slot fallbacks — consumers must provide or grid renders empty.

- [ ] **Step 3: Density CSS custom properties**
  Root scope exposes `--workbench-gap: 4px`, `--workbench-row-height: 22px`, `--workbench-axis-font: 10px`, `--workbench-border`, `--workbench-panel-bg`. Admin-overridable via ConfigService in v1.1 per OD-11.
  → See portfolio-enterprise-components.md §E.1 for the token list with HSL defaults.

- [ ] **Step 4: `data-density="workbench"` attribute on root**
  Consumers can style descendants with `[data-density="workbench"] .some-child { ... }` without leaking the density to sibling FCL pages.

- [ ] **Step 5: Visual validation**
  Per memory `feedback_visual_validation` — take a screenshot in browser and compare against the component draft §E.1 sketch before moving on.

- [ ] **Step 6: Commit**
  ```bash
  git add packages/ui/src/lib/layouts/WorkbenchLayout.svelte packages/ui/src/lib/layouts/WorkbenchLayout.test.ts packages/ui/src/lib/index.ts
  git commit -m "feat(ui): WorkbenchLayout primitive for /portfolio/live terminal shell"
  ```

### Task 8.2: `chartTokens('workbench')` variant

**Files:**
- Modify: `frontends/wealth/src/lib/charts/chart-tokens.ts`
- Create: `frontends/wealth/src/lib/charts/chart-tokens.test.ts`
**Reference:** portfolio-enterprise-charts.md §D.1 (variant parameter), §D.2 (option impact).

- [ ] **Step 1: Add `variant` parameter**
  Signature `chartTokens(variant: 'default' | 'workbench' = 'default'): EChartsTokens`. When `variant === 'workbench'`, overrides base with terminal-density values (`axisLabelFontSize: 10`, `gridPaddingTop: 8`, `gridPaddingBottom: 8`, `tooltipDelay: 0`, `animationDuration: 0`, `dataZoomHeight: 18`).
  → See portfolio-enterprise-charts.md §D.2 for the full token override list.

- [ ] **Step 2: Tooltip delay = 0 for workbench (DL9 supporting spec)**
  Terminal traders don't tolerate hover delay.

- [ ] **Step 3: Animations disabled for workbench**
  `animationDuration: 0`, `animationDurationUpdate: 0` — no reflow storms during high-frequency updates (DL9, charts §B.3).

- [ ] **Step 4: Tree-shake guard**
  Per charts draft §G.2 — only register the ECharts modules actually used in workbench (`LineChart`, `ScatterChart`, `CustomChart`, `GraphChart`, axis, tooltip, grid, dataZoom, markLine, markArea). Document which modules are imported in `echarts-setup.ts`.

- [ ] **Step 5: Commit**
  ```bash
  git add frontends/wealth/src/lib/charts/chart-tokens.ts frontends/wealth/src/lib/charts/chart-tokens.test.ts
  git commit -m "feat(wealth): chartTokens('workbench') variant with terminal-density overrides"
  ```

### Task 8.3: `/portfolio/live` route + portfolio selector

**Files:**
- Create: `frontends/wealth/src/routes/(app)/portfolio/live/+page.svelte`
- Create: `frontends/wealth/src/routes/(app)/portfolio/live/+page.server.ts`
- Create: `frontends/wealth/src/lib/components/portfolio/LivePortfolioSelector.svelte`
**Reference:** portfolio-enterprise-ux-flow.md §6.2 (layout regions), §8.1 (portfolio selector), portfolio-enterprise-components.md §B.3.

**BLOCKED ON: OD-10** (route name `/portfolio/live` vs `/workbench`). Default to `/portfolio/live` per recommendation + DL1.
**BLOCKED ON: OD-12** (table vs sidebar list). Default to table (EnterpriseTable) per recommendation.

- [ ] **Step 1: Mount `WorkbenchLayout` with named snippets**
  Import `WorkbenchLayout` from `@investintell/ui` and pass 5 snippets: `toolbar` → `<WorkbenchToolbar>`, `col1` → `<LivePortfolioSelector>` + `<AlertsFeedPanel>`, `center` → Phase 9 placeholder for `<WorkbenchCoreChart>`, `col3` → Phase 9 placeholder for `<WeightVectorTable>`, `footer` → `<StrategicTacticalEffectiveComparison>`.

- [ ] **Step 2: `LivePortfolioSelector` reuses `EnterpriseTable`**
  Columns: name, state chip, NAV (formatted via `formatCurrency`), 1D change, open alerts count, Go Live/Pause action. Server-side query filters `state IN ('live','paused')`.

- [ ] **Step 3: Selected portfolio drives the rest of the shell via store**
  Selection stored in URL query (`?portfolio=<id>`), hydrated in store on route load. DL15 — no localStorage.

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/routes/\(app\)/portfolio/live/ frontends/wealth/src/lib/components/portfolio/LivePortfolioSelector.svelte
  git commit -m "feat(wealth): /portfolio/live route with WorkbenchLayout + selector"
  ```

### Task 8.4: `WorkbenchToolbar.svelte` with tool state machine

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/WorkbenchToolbar.svelte`
- Create: `frontends/wealth/src/lib/stores/workbench-tool-state.svelte.ts`
**Reference:** portfolio-enterprise-charts.md §A.3 item 10, Appendix (state machine), portfolio-enterprise-ux-flow.md §6.3.

- [ ] **Step 1: Tool enum**
  `export type WorkbenchTool = 'nav' | 'drawdown' | 'rollingSharpe' | 'rollingVol' | 'rollingCorrelation' | 'rollingTrackingError' | 'regimeOverlay' | 'intraday'` — 8 tools total.

- [ ] **Step 2: Segmented toolbar**
  8 buttons with icons. Active button highlighted. Keyboard shortcut `1..8` to switch (per charts draft §A.3 — "terminal trader muscle memory").

- [ ] **Step 3: Tool switch publishes `{tool, params}` to store — NEVER remounts chart (DL9)**
  WorkbenchCoreChart (Phase 9) subscribes and rebuilds `option` in a `$derived` with `setOption(next, { notMerge: false, lazyUpdate: true, replaceMerge: ['series','markLine','markArea'] })`.

- [ ] **Step 4: Toolbar metadata — provider label**
  Per OD-14: "Delayed 15min — Yahoo Finance" label pinned to the right of the toolbar when the active tool is `intraday`.

- [ ] **Step 5: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/WorkbenchToolbar.svelte frontends/wealth/src/lib/stores/workbench-tool-state.svelte.ts
  git commit -m "feat(wealth): WorkbenchToolbar with 8-tool state machine + shortcuts"
  ```

### Phase 8 gate

- [ ] `WorkbenchLayout` primitive exported from `@investintell/ui` and visually validated
- [ ] `chartTokens('workbench')` variant returns terminal-density tokens
- [ ] `/portfolio/live` route renders with toolbar, selector, footer, and placeholders
- [ ] Tool state machine store reacts to toolbar clicks without chart remount
- [ ] Phase 9 is safe to start

---

## Phase 9 — Live workbench data: live_price_poll worker (lock 900_100), createTickBuffer, SparklineSVG, WeightVectorTable, RebalanceSuggestionPanel

**Goal:** Wire real data into the Live shell. Ship the `live_price_poll` worker, the `createTickBuffer` runtime helper (high-frequency event discipline, DL18 P1), `SparklineSVG` (DL10), `WorkbenchCoreChart`, `WeightVectorTable`, and the `RebalanceSuggestionPanel` drawer.
**Drafts:** portfolio-enterprise-db.md §8 (live price layer), §11.2 (new workers), portfolio-enterprise-charts.md §A.3 items 10-12 (WorkbenchCoreChart + SparklineSVG), §B.4 (SSE→state→chart data path), §G.4 (typed arrays), portfolio-enterprise-components.md §E.3 (WeightVectorTable), §E.5 (RebalanceSuggestionPanel), portfolio-enterprise-quant.md §G.3 (intraday monitoring), §H.2 (rebalance contract).
**Locks consumed:** DL9 (WorkbenchCoreChart), DL10 (SparklineSVG), DL11 (live price worker), DL18 P1 (tick buffer), DL19.
**Migrations:** none.
**New worker locks:** 900_100 (`live_price_poll`) first use.
**Depends on:** Phase 8 gate.

### Task 9.1: `live_price_poll` worker (lock 900_100)

**Files:**
- Create: `backend/app/domains/wealth/workers/live_price_poll.py`
- Create: `backend/app/domains/wealth/services/live_price_cache.py`
- Test: `backend/tests/wealth/workers/test_live_price_poll.py`
**Reference:** portfolio-enterprise-db.md §8 (options + recommendation), §11.2, portfolio-enterprise-quant.md §G.3.

**BLOCKED ON: OD-14** (Yahoo v1 vs paid provider). Default to Yahoo per recommendation.
**BLOCKED ON: OD-15** (ephemeral vs hypertable). Default to ephemeral per recommendation.

- [ ] **Step 1: 60s loop with 900_100 integer-literal lock**
  `pg_try_advisory_lock(900_100)` wraps the loop body. Each tick: fetch held-instrument symbols from DB → batch 250 symbols/call through `ExternalProviderGate.bulk()` (5min variant) → write Redis hash with TTL 180s → run staleness check → `asyncio.sleep(60)`.
  → See portfolio-enterprise-db.md §8.2 for the full recommendation.

- [ ] **Step 2: Redis key format**
  `live:px:v1:{instrument_id}` → `{price, change_abs, change_pct, ts_unix, provider}`. TTL 180s.

- [ ] **Step 3: Staleness alert**
  If >30% of watched instruments have stale prices >10min, emit `price_staleness` alert with `severity='warning'` into `portfolio_alerts`. Dedupe per 30min window.

- [ ] **Step 4: Interactive variant for newly-added holdings**
  On-demand `get_live_price(instrument_id)` uses `ExternalProviderGate.interactive()` (30s) so a user who just dropped an instrument into a live portfolio gets a price within a visible polling tick.

- [ ] **Step 5: Commit**
  ```bash
  git add backend/app/domains/wealth/workers/live_price_poll.py backend/app/domains/wealth/services/live_price_cache.py backend/tests/wealth/workers/test_live_price_poll.py
  git commit -m "feat(wealth): live_price_poll worker (lock 900_100) Yahoo batch 60s"
  ```

### Task 9.2: `createTickBuffer<T>` helper + price SSE bridge

**Files:**
- Create: `packages/ui/src/lib/runtime/createTickBuffer.ts`
- Create: `packages/ui/src/lib/runtime/createTickBuffer.test.ts`
- Create: `frontends/wealth/src/lib/stores/live-price-stream.svelte.ts`
- Create: `backend/app/domains/wealth/routes/live_price.py` (SSE bridge)
**Reference:** portfolio-enterprise-charts.md §B.4 (SSE→state→chart), CLAUDE.md §Stability Guardrails charter §3 (`createTickBuffer<T>` for > 10/s events).

- [ ] **Step 1: Pure helper in `@investintell/ui/runtime`**
  Signature `createTickBuffer<T>(flushMs = 250): { push(item: T): void; subscribe(cb: (batch: T[]) => void): () => void }`. Internal pending array, debounced `setTimeout(flush, flushMs)` triggers subscriber fan-out. Never mutates `$state` per-tick — DL18 P1.

- [ ] **Step 2: `live-price-stream.svelte.ts` store**
  Opens SSE to `/live-price/stream?portfolio_id=X`. Each tick pushed into `createTickBuffer<PriceTick>`. Subscribers receive batches every 250ms.

- [ ] **Step 3: Backend SSE bridge at `/live-price/stream`**
  Redis pubsub on `live:px:events:{portfolio_id}`. `live_price_poll` worker publishes on change. Bridge relays. `RateLimitedBroadcaster` + `ConnectionId` UUID.

- [ ] **Step 4: Commit**
  ```bash
  git add packages/ui/src/lib/runtime/createTickBuffer.ts packages/ui/src/lib/runtime/createTickBuffer.test.ts frontends/wealth/src/lib/stores/live-price-stream.svelte.ts backend/app/domains/wealth/routes/live_price.py
  git commit -m "feat(ui): createTickBuffer + live price SSE bridge"
  ```

### Task 9.3: `SparklineSVG.svelte` (DL10)

**Files:**
- Create: `packages/ui/src/lib/charts/SparklineSVG.svelte`
- Create: `packages/ui/src/lib/charts/SparklineSVG.test.ts`
**Reference:** portfolio-enterprise-charts.md §A.3 item 12, §G.4 (typed arrays).

- [ ] **Step 1: Props**
  `{ values: Float64Array, width = 64, height = 18, stroke = 'currentColor' }` via `$props()`. `Float64Array` typed — zero copy from `createTickBuffer` batch (DL10 + charts §G.4).

- [ ] **Step 2: Pure SVG path**
  Compute `d` attribute via a single `$derived` expression mapping values to `M x,y L x,y ...`. No axes, no tooltip, no interactivity. Per DL10 — "a sparkline is a glyph, not a chart."

- [ ] **Step 3: Performance test — 30 sparklines update in <16ms**
  Synthetic harness with 30 sparklines each receiving one tick. Measure update frame time stays under 16ms (60fps).

- [ ] **Step 4: Commit**
  ```bash
  git add packages/ui/src/lib/charts/SparklineSVG.svelte packages/ui/src/lib/charts/SparklineSVG.test.ts
  git commit -m "feat(ui): SparklineSVG glyph with Float64Array backend"
  ```

### Task 9.4: `WorkbenchCoreChart.svelte`

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/WorkbenchCoreChart.svelte`
- Create: `frontends/wealth/src/lib/components/portfolio/workbench-core-options.ts`
**Reference:** portfolio-enterprise-charts.md Appendix (state machine sketch), §A.3 item 10, §D.2.

- [ ] **Step 1: Single ECharts instance**
  One `<canvas>` + one `chart = echarts.init(canvas)` in `onMount`. Never destroyed across tool switches.

- [ ] **Step 2: `$derived` option rebuild per tool**
  `const option = $derived.by(() => SWITCH(tool) ...)` dispatching to 8 `buildXxxOption()` helpers in `workbench-core-options.ts`. `$effect` calls `chart.setOption(option, { notMerge: false, lazyUpdate: true, replaceMerge: ['series','markLine','markArea'] })`. Per DL9.
  → See portfolio-enterprise-charts.md Appendix (WorkbenchCoreChart state machine sketch) for the 8 builder signatures.

- [ ] **Step 3: `dataZoom` with `filterMode: 'weakFilter'`**
  Brush persists across tool switches (DL9 explicit).

- [ ] **Step 4: Regime overlay markArea**
  When tool === 'regimeOverlay' or any tool with regime bands toggled on, overlay `markArea` shading regime periods from `GET /portfolio/regime/history`.

- [ ] **Step 5: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/WorkbenchCoreChart.svelte frontends/wealth/src/lib/components/portfolio/workbench-core-options.ts
  git commit -m "feat(wealth): WorkbenchCoreChart single-instance 8-tool state machine"
  ```

### Task 9.5: `WeightVectorTable.svelte` with sparkline column

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/WeightVectorTable.svelte`
**Reference:** portfolio-enterprise-components.md §E.3, memory `project_holdings_brochure_sprint` (N-PORT pct/100).

- [ ] **Step 1: Reuse `EnterpriseTable` (DL17)**
  Columns: instrument name, ticker, strategic weight, tactical weight, effective weight, live price (from `createTickBuffer` batch), 1D change, 1D change pct, intraday sparkline (`SparklineSVG`), position value (weight * portfolio NAV).

- [ ] **Step 2: Subscribe to tick buffer**
  `$effect(() => tickBuffer.subscribe(batch => updateRowsFromBatch(batch)))`. Updates once per 250ms, never per-tick.

- [ ] **Step 3: Sort by change pct descending by default**
  Biggest movers on top.

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/WeightVectorTable.svelte
  git commit -m "feat(wealth): WeightVectorTable with sparkline + tick buffer subscription"
  ```

### Task 9.6: `RebalanceSuggestionPanel.svelte` drawer

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/RebalanceSuggestionPanel.svelte`
- Modify: `backend/app/domains/wealth/routes/model_portfolios.py` (`POST /model-portfolios/{id}/rebalance/suggest` new endpoint)
**Reference:** portfolio-enterprise-components.md §E.5, portfolio-enterprise-quant.md §H.2, portfolio-enterprise-ux-flow.md §11.2.7 (OD-17 drawer).

**BLOCKED ON: OD-16** (in-place vs new draft) + **OD-17** (drawer vs route). Defaults to new-draft + drawer per recommendations.

- [ ] **Step 1: Drawer anchored to Live col3**
  Svelte 5 `<dialog>` element slid from the right. 420px wide. Closes with Esc.

- [ ] **Step 2: Contents**
  Per quant §H.2: current vs suggested weight diff table, expected turnover, estimated cost, trigger reason (drift / regime / IC view), "Open in Builder" CTA that creates a new draft with `state_metadata.parent_live_id = current_id`.

- [ ] **Step 3: Accept = spawn new draft (DL OD-16)**
  Never mutates the live portfolio in place. Preserves audit trail.

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/RebalanceSuggestionPanel.svelte backend/app/domains/wealth/routes/model_portfolios.py
  git commit -m "feat(wealth): RebalanceSuggestionPanel drawer spawns new draft"
  ```

### Task 9.7: Strategic/Tactical/Effective comparison footer

**Files:**
- Create: `frontends/wealth/src/lib/components/portfolio/StrategicTacticalEffectiveComparison.svelte`
**Reference:** portfolio-enterprise-components.md §B.3, portfolio-enterprise-ux-flow.md §6.2, DL13.

- [ ] **Step 1: Reads from `portfolio_weight_snapshots` (Phase 2.3 hypertable)**
  `GET /model-portfolios/{id}/weights/snapshot?as_of=latest` returns the 3 columns per holding.

- [ ] **Step 2: Three-column table in the footer region**
  Row per instrument, columns: strategic, tactical, effective, delta strategic→effective.

- [ ] **Step 3: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/StrategicTacticalEffectiveComparison.svelte
  git commit -m "feat(wealth): Strategic/Tactical/Effective footer comparison"
  ```

### Phase 9 gate

- [ ] `live_price_poll` running every 60s, Redis cache populated
- [ ] `/live-price/stream` SSE delivers batched ticks
- [ ] `SparklineSVG` renders 30+ instances under 16ms per update
- [ ] `WorkbenchCoreChart` switches tools without remount (DL9)
- [ ] `WeightVectorTable` rows tick at 250ms cadence via `createTickBuffer`
- [ ] `RebalanceSuggestionPanel` spawns a new draft with `parent_live_id` set
- [ ] Phase 10 is safe to start

---

## Phase 10 — Translation table, formatter sweep, legacy route deletion, visual validation, full E2E rehearsal

**Goal:** Polish. Land the normative jargon translation table, fix the 5 formatter violations, redirect legacy routes, visual-validate the 3 surfaces in browser, rehearse the full user journey Builder → Analytics → Live, and close the sprint.
**Drafts:** portfolio-enterprise-ux-flow.md §10 (translation table), §14 (validation checklist), portfolio-enterprise-components.md §F.1 (formatter violations), §F.2 (MOCK elimination final pass), portfolio-enterprise-quant.md §B.5 (translation layer).
**Locks consumed:** DL14 (jargon translation table normative), DL16 (formatter discipline), DL17, DL18.
**Migrations:** none.
**New worker locks:** none.
**Depends on:** Phase 9 gate.

### Task 10.1: Canonical jargon translation table

**Files:**
- Create: `frontends/wealth/src/lib/portfolio/jargon-translation.ts`
- Create: `frontends/wealth/src/lib/portfolio/jargon-translation.test.ts`
**Reference:** portfolio-enterprise-ux-flow.md §10 (translation table), portfolio-enterprise-quant.md §B.5 (translation layer), DL14.

- [ ] **Step 1: Normative table**
  `export const JARGON_TRANSLATION` — frozen object keyed by backend field name, valued by `{ label, tooltip?, formatter?, hidden? }`. Must include at minimum: risk terms (`cvar_95` → "Tail loss (95%)", `cvar_limit` → "Tail loss budget", `effective_cvar_limit` → "Tail loss budget (regime-adjusted)", `volatility_garch` → "Forward volatility", `sharpe_ratio` → "Risk-adjusted return", `max_drawdown` → "Worst drawdown"), regime labels per OD-22 (`NORMAL → "Balanced"`, `RISK_ON → "Expansion"`, `RISK_OFF → "Defensive"`, `CRISIS → "Stress"`, `INFLATION → "Inflation"`), and `hidden: true` entries for every optimizer jargon token (`CLARABEL`, `SOCP`, `ledoit_wolf`, `markov_filtered`, `robust_socp`, etc.) per DL14.
  → See portfolio-enterprise-ux-flow.md §10 for the full 50+ entry table.

- [ ] **Step 2: `translateLabel(field: string)` + `translateValue(field, value)` helpers**
  `translateValue` picks the right formatter based on the entry's `formatter` key and calls the `@investintell/ui` formatter.

- [ ] **Step 3: Test — no unmapped field appears in any shipped component**
  Static-analysis test: grep portfolio components for literal field names from the construct response; every found field must exist in `JARGON_TRANSLATION` or fail the test.

- [ ] **Step 4: Audit helper**
  `pnpm --filter wealth audit:jargon` script that scans for backend field names and reports missing translations. Run in CI via `make check-all`.

- [ ] **Step 5: Commit**
  ```bash
  git add frontends/wealth/src/lib/portfolio/jargon-translation.ts frontends/wealth/src/lib/portfolio/jargon-translation.test.ts
  git commit -m "feat(wealth): normative jargon translation table + audit helper"
  ```

### Task 10.2: Formatter sweep — eliminate the 5 known violations

**Files:**
- Modify: `frontends/wealth/src/lib/components/portfolio/RebalanceSimulationPanel.svelte` (lines 259, 265, 290)
- Modify: `frontends/wealth/src/lib/components/portfolio/BuilderTable.svelte` (line 233)
- Modify: `frontends/wealth/src/routes/(app)/portfolio/analytics/+page.svelte` (lines 60-61)
**Reference:** portfolio-enterprise-components.md §F.1, Phase 0 Task 0.1 Step 7 (baseline), DL16.

- [ ] **Step 1: Replace every `.toFixed(n)` with `formatNumber(value, { digits: n })`**
  Or `formatPercent`/`formatCurrency` if the context warrants.

- [ ] **Step 2: Replace every `toLocaleString(...)` with `formatNumber(value, { locale: 'en-US' })`**

- [ ] **Step 3: Replace every `new Intl.NumberFormat(...)` with the appropriate `@investintell/ui` formatter**

- [ ] **Step 4: Re-grep to confirm zero violations**
  ```bash
  rg -n "\.toFixed\(|toLocaleString\(|new Intl\." frontends/wealth/src/lib/components/portfolio frontends/wealth/src/lib/components/model-portfolio frontends/wealth/src/routes/\(app\)/portfolio
  ```
  Must return zero matches. Eslint rule enforces going forward.

- [ ] **Step 5: Commit**
  ```bash
  git add frontends/wealth/src/lib/components/portfolio/RebalanceSimulationPanel.svelte frontends/wealth/src/lib/components/portfolio/BuilderTable.svelte frontends/wealth/src/routes/\(app\)/portfolio/analytics/+page.svelte
  git commit -m "refactor(wealth): eliminate 5 formatter violations per DL16"
  ```

### Task 10.3: Legacy route redirects + deletion

**Files:**
- Modify: `frontends/wealth/src/hooks.server.ts` (or `+layout.server.ts`)
- Delete: `frontends/wealth/src/routes/(app)/portfolio/advanced/` (directory)
- Delete: `frontends/wealth/src/routes/(app)/portfolio/model/` (directory)
**Reference:** portfolio-enterprise-ux-flow.md §11.2.9, DL1, OD-18 (redirect + soft delete).

- [ ] **Step 1: `hooks.server.ts` redirect rules**
  `/portfolio/advanced/*` → `/portfolio/analytics` (302). `/portfolio/model/*` → `/portfolio/builder` (302). Preserve `url.search` so deep links stay alive.

- [ ] **Step 2: Delete the legacy routes**
  Per OD-18 — files stay in git history, removed from routing tree.

- [ ] **Step 3: Visual validation**
  Hit the 3 legacy URLs in browser, confirm redirect lands on the correct new page.

- [ ] **Step 4: Commit**
  ```bash
  git add frontends/wealth/src/hooks.server.ts
  git rm -r frontends/wealth/src/routes/\(app\)/portfolio/advanced frontends/wealth/src/routes/\(app\)/portfolio/model
  git commit -m "refactor(wealth): redirect legacy portfolio routes + delete handlers"
  ```

### Task 10.4: Visual validation of the 3 surfaces

**Files:**
- Report: `docs/superpowers/diagnostics/2026-04-08-portfolio-visual-validation.md`
**Reference:** memory `feedback_visual_validation`, portfolio-enterprise-ux-flow.md §14.

- [ ] **Step 1: Start backend + wealth frontend locally**
  `make up && make serve & make dev-wealth &`

- [ ] **Step 2: Screenshot Builder with a non-trivial portfolio in `constructed` state**
  Verify: FCL 3-column, CalibrationPanel visible, ConstructionNarrative populated after Run Construct, allocation blocks with DnD-dropped instruments, sub-nav ribbon with badges. Save screenshot.

- [ ] **Step 3: Screenshot Analytics with `Model Portfolios` scope**
  Verify: FilterRail + 3×2 AnalysisGrid + 4 chart groups reachable, BottomTabDock at bottom, portfolio-specific charts render.

- [ ] **Step 4: Screenshot Live workbench with a portfolio in `live` state**
  Verify: WorkbenchLayout 12-col grid, LivePortfolioSelector + AlertsFeedPanel in col1, WorkbenchCoreChart in center, WeightVectorTable in col3, footer comparison, toolbar with 8 tools and "Delayed 15min" label.

- [ ] **Step 5: Toggle every tool in WorkbenchCoreChart**
  Confirm no remount (Elements panel shows same `<canvas>`), zoom persists, regime overlay toggles.

- [ ] **Step 6: Fire a synthetic critical alert**
  `INSERT INTO portfolio_alerts (..., severity='critical', ...)` against a live portfolio. Confirm toast fires on any /portfolio/* page and AlertsFeedPanel shows the row.

- [ ] **Step 7: Write report**
  Document each screenshot with timestamp + any visual gaps vs the component draft sketches. File any defects as follow-up PRs.

- [ ] **Step 8: Commit**
  ```bash
  git add docs/superpowers/diagnostics/2026-04-08-portfolio-visual-validation.md
  git commit -m "docs: visual validation of 3 portfolio surfaces"
  ```

### Task 10.5: Full E2E rehearsal — Builder → Analytics → Live

**Files:**
- Create: `frontends/wealth/tests/e2e/portfolio-full-journey.spec.ts`
**Reference:** portfolio-enterprise-ux-flow.md §2.1 (canonical flow).

- [ ] **Step 1: Playwright script**
  1. Navigate to `/portfolio`. 2. Click "+Portfolio". 3. Fill NewPortfolioDialog and submit. 4. On Builder, add 5 instruments via Universe sub-pill DnD. 5. Adjust CalibrationPanel Basic fields. 6. Click Apply. 7. Click Run Construct. 8. Wait for SSE `succeeded`. 9. Assert ConstructionNarrative headline non-empty. 10. Click Validate. 11. Click Approve. 12. Click Go Live. 13. Navigate to `/portfolio/live`. 14. Select the portfolio. 15. Confirm WorkbenchCoreChart renders NAV tool. 16. Toggle Drawdown tool — assert chart instance survives. 17. Open RebalanceSuggestionPanel drawer. 18. Assert drawer visible.

- [ ] **Step 2: Run against local backend**
  `pnpm --filter wealth test:e2e portfolio-full-journey`

- [ ] **Step 3: Commit**
  ```bash
  git add frontends/wealth/tests/e2e/portfolio-full-journey.spec.ts
  git commit -m "test(wealth): E2E full Builder→Analytics→Live journey"
  ```

### Task 10.6: `make check` + `make check-all` clean

**Files:**
- none
**Reference:** CLAUDE.md §Commands.

- [ ] **Step 1: Backend**
  ```bash
  make check
  ```
  Must pass: lint + import-linter + mypy + pytest (3176+ → projected 3220+ tests).

- [ ] **Step 2: Frontend**
  ```bash
  make check-all
  ```
  Must pass: eslint (including the `no-toFixed` rule), svelte-check, unit tests.

- [ ] **Step 3: If any failure, fix and re-commit**

### Phase 10 gate

- [ ] Jargon translation table live, audit helper green
- [ ] Zero formatter violations in portfolio + model-portfolio directories
- [ ] Legacy routes redirect to new routes
- [ ] 3 surfaces visually validated in browser with screenshots committed
- [ ] Full E2E Builder→Analytics→Live passing
- [ ] `make check` + `make check-all` both green
- [ ] Sprint ready to merge to main

---

## Phase 11 — Self-Review

### 11.1 Spec coverage matrix

Every major section of every draft maps to at least one phase task.

| Draft | Section | Phase / Task |
|---|---|---|
| ux-flow | §1 URL contract | 5.5 (sub-nav), 8.3 (Live route), 10.3 (redirects) |
| ux-flow | §2 Flow gates | 5.2 (allowed_actions bindings), 10.5 (E2E) |
| ux-flow | §3 State machine | 1.1 (migration), 1.2 (state_machine.py), 1.4 (allowed_actions), 5.2 |
| ux-flow | §4 Builder | 4.1-4.5, 5.1-5.5 |
| ux-flow | §5 Analytics | 6.1-6.5 |
| ux-flow | §6 Live Workbench | 8.1-8.4, 9.1-9.7 |
| ux-flow | §7 Alerts | 2.4 (table), 7.1-7.7 |
| ux-flow | §8 Multi-portfolio nav | 8.3 (selector), 6.5 (BottomTabDock) |
| ux-flow | §9 Discovery parallel | 6.1, 6.2 (reuse), 8.1 (divergence) |
| ux-flow | §10 Jargon table | 10.1 |
| db | §2 State machine migration | 1.1, 1.2, 1.4 |
| db | §3 construction_runs | 1.3, 3.4, 3.7 |
| db | §4 calibration | 2.1, 4.1, 4.2 |
| db | §5 stress_results | 2.2, 3.5, 4.4 |
| db | §6 weight_snapshots hypertable | 2.3, 9.7 |
| db | §7 portfolio_alerts | 2.4, 7.1-7.7 |
| db | §8 Live price layer | 2.4 (staleness alert), 9.1, 9.2 |
| db | §10 Migration sequence | 1.1, 1.3, 2.1-2.6 |
| db | §11.1 Existing workers | 7.1-7.3 |
| db | §11.2 New workers | 2.7 (reserve), 3.4, 7.4, 9.1 |
| components | Part A Audit | Phase 0 (verify) |
| components | Part B Architecture | Builder 4/5, Analytics 6, Live 8/9 |
| components | Part C CalibrationPanel | 4.1, 4.2 |
| components | Part D ConstructionNarrative | 4.3 |
| components | Part E Live primitives | 8.1, 9.3-9.7 |
| components | Part F Formatter + MOCK | 10.2 |
| components | Part G Svelte 5 patterns | 4.1 (runes), 9.2 (tick buffer), 8.4 (state machine) |
| charts | Part A Chart selection | 6.3 (Analytics), 9.3-9.4 (Live) |
| charts | Part B Real-time updates | 9.2 (tick buffer), 9.4 (option rebuild) |
| charts | Part C Calibration preview | 4.1 (debounce) |
| charts | Part D chartTokens variant | 8.2 |
| charts | Part E Tooltip discipline | 8.2 (delay 0) |
| charts | Part F Chart components list | 6.3, 9.3, 9.4 |
| charts | Part G Performance budget | 8.2 (tree-shake), 9.3 (SVG), 9.4 (setOption) |
| quant | Part A 63 inputs | 2.1 (persistence), 4.1/4.2 (UI) |
| quant | Part B Run Construct payload | 3.1-3.7, 4.3 |
| quant | Part C Advisor fold-in | 3.3 |
| quant | Part D Stress scenarios | 3.5, 4.4 |
| quant | Part E Validation gate | 3.1 |
| quant | Part F Regime context | 3.6 |
| quant | Part G Live monitoring | 9.1, 9.2 |
| quant | Part H Rebalance engine | 9.6 |
| quant | Part I Scoring breakdown | (DEFERRED v1.1 per OD-4) |
| quant | Part J Templater | 3.2 |

### 11.2 Open decision traceability

Every blocking OD is referenced by the phase task that cannot proceed without it.

| OD | Decision | Phase task blocked |
|---|---|---|
| OD-1 | Calibration tier default | 4.1 |
| OD-2 | Slider vs numeric input | 4.1 |
| OD-3 | PT vs EN narrative | 3.2 (templater language), 4.3 (surfacing) |
| OD-4 | Scoring weights in calibration | 4.2 (Expert tier scope) |
| OD-5 | Activation gate strictness | 3.1 (validation_gate), 5.2 (activate button confirm) |
| OD-6 | 4-eyes single-user | 1.4 (allowed_actions policy), 5.2 (approve confirm) |
| OD-7 | Bulk approve in Universe | 5.3 |
| OD-8 | Stress panel shape | 4.4 |
| OD-9 | Stress catalog authoring | 3.5 (catalog endpoint scope) |
| OD-10 | Live route name | 8.3 |
| OD-11 | Workbench tokens admin-configurable | 8.1 |
| OD-12 | Portfolio selector UX | 8.3 |
| OD-13 | Multi-portfolio nav | 8.3, 6.5 |
| OD-14 | Real-time price provider | 9.1 |
| OD-15 | Intraday history persistence | 9.1 |
| OD-16 | Rebalance mutation semantics | 9.6 |
| OD-17 | Rebalance entry point | 9.6 |
| OD-18 | Legacy route deletion | 10.3 |
| OD-19 | Legacy `status` column | (deferred) |
| OD-20 | Strategic/tactical coexistence | 2.3 (kept), 9.7 |
| OD-21 | PortfolioOverview rename | 9.5 (WeightVectorTable is Live-specific) |
| OD-22 | Regime label translation | 3.6, 7.3, 10.1 |
| OD-23 | Alert dedup strategy | 2.4 |
| OD-24 | Drift fanout | 2.5, 7.2 |
| OD-25 | Compare Both mode | 6.1 (disabled with v1.1 badge) |
| OD-26 | MOCK data policy | Every frontend task (strict) |
| OD-27 | Sharpe isoquant overlay | (deferred v1.1) |
| OD-28 | Phase ordering | Entire plan follows Builder+Analytics first |

### 11.3 Risks acknowledged (top 8 from drafts)

- **R1 — Discovery FCL primitives not yet landed.** Phase 4 depends on `FlexibleColumnLayout`, `EnterpriseTable`, `FilterRail`, `ChartCard`, `AnalysisGrid`, `BottomTabDock`, `PanelErrorState` being exported from `@investintell/ui`. Phase 0 Task 0.3 diagnostic verifies. *Mitigation: Phase 0 coordinates with Discovery sprint owner before Phase 4 starts; if gaps, promote-in-place PR precedes this plan's Phase 4.* (drafts: components Part H#1.)
- **R2 — Uncommitted `regime_fit.py` work.** Risk of merge conflict when Phase 7 Task 7.3 extends it. *Mitigation: Phase 0 Task 0.4 documents the diff and commits the integration in the same Phase 7 commit.* (drafts: db §11.1, quant §G.2.)
- **R3 — `construction_run_executor` 120s bound may be tight for large universes.** Optimizer cascade + PCA + GARCH + 4 stress scenarios + advisor + validation + narrative under 120s for 50+ instruments is ambitious. *Mitigation: Phase 3 Task 3.4 timeout mark-failed path exists; tune bound via ConfigService before Phase 4 UI depends on it. Phase 10 Task 10.5 E2E reveals real-world latency.* (drafts: quant §B.4 caching, db §12.)
- **R4 — Live price staleness alerts noisy under weekend close.** Yahoo batch quote returns last trading session prices on weekends; naive staleness check would emit constant alerts. *Mitigation: Phase 9 Task 9.1 staleness check excludes weekends and exchange holidays; dedupe per 30min.* (drafts: db §8, quant §G.3.)
- **R5 — `portfolio_alerts` write amplification from drift fanout.** If 100 portfolios hold the same instrument and drift flips, that's 100 rows and 100 Redis publishes per event. *Mitigation: Phase 2 Task 2.4 partial unique index on `dedupe_key` dedupes cross-portfolio within a time window; Phase 7 Task 7.4 `alert_sweeper` prunes stale. Revisit if >10k alerts/day observed.* (drafts: db §7, §13.8.)
- **R6 — `WorkbenchCoreChart` tool switch may still churn under rapid switching.** `replaceMerge: ['series','markLine','markArea']` is correct but ECharts can still drop frames if a user mashes `1-8` keyboard shortcuts. *Mitigation: Phase 8 Task 8.4 debounces tool switches at 100ms; Phase 9 Task 9.4 profiles with performance.mark before commit.* (drafts: charts §A.3 item 10, §B.3.)
- **R7 — Hypertable RLS on `portfolio_weight_snapshots` chunks.** Timescale chunk inheritance can leak RLS if future chunks are created without `ALTER TABLE` inheriting from the parent. *Mitigation: Phase 2 Task 2.3 Step 3 explicit test writes rows under 2 org contexts and asserts zero cross-tenant visibility; rerun after compression policy kicks in.* (drafts: db §6, §12.)
- **R8 — Narrative templater produces stale output after engine upgrade.** If quant engine adds new metrics to `ex_ante_metrics` between sprints, the Jinja2 template will silently omit them. *Mitigation: Phase 3 Task 3.2 golden test fails on shape drift; Phase 10 Task 10.1 jargon audit helper reports any unmapped field.* (drafts: quant §J.1, components §D.1.)

### 11.4 Sprint close

On Phase 10 gate green:
- [ ] Merge sprint branch to main via PR (see `feedback_git_workflow`)
- [ ] Update `CLAUDE.md` migration head if drift occurred
- [ ] Document any decisions that Andrei locked during the sprint in a follow-up revision log entry
- [ ] Retro: which OD recommendations held vs which flipped in reality
- [ ] Queue v1.1 scope: Compare Both, Sharpe isoquant, paid live price provider, nav_intraday hypertable, scoring breakdown, PT narrative

---
