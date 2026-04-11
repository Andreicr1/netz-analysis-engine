# Terminal Unification Master Plan

**Date:** 2026-04-11
**Branch target:** `feat/terminal-unification` (off `main`)
**Owner:** Andrei
**Status:** Planning — awaiting `/ce:work`

Synthesis of five specialist plans (ECharts, Navigation Flow, Svelte Architecture, Quant Surface, Data Plane) covering the full integration of operational portfolio management into the brutalist terminal surface at `frontends/wealth/src/routes/(terminal)/`. All five plans converged without conflict.

---

## 0. Strategic Decisions (already made — not up for debate)

1. **`(terminal)/` becomes the single operational surface** for Wealth OS. Bloomberg-class brutalism (monospace, 1px borders, zero radius, black/amber/cyan tokens) is the product identity.
2. **`(app)/` is demoted to read-only reports only:** Snapshots, Monthly Report, Macro Outlook, Investment Outlook, Flash Reports, Fact Sheets, Committee Packs, DD Chapter Viewers, Documents, Settings. Everything operational is deleted from `(app)/` or redirected into the terminal.
3. **Fast flow replaces the MFO theoretical lifecycle.** Liquid universes (`registered_us`, `etf`, `ucits_eu`, `money_market`) flow **Screener → Approved Universe** directly, no DD gate. Only `private_us` and `bdc` retain the 8-chapter DD report track.
4. **"ELITE" is a first-class category** in the Screener — single-click best-in-class filter, amber star badge on qualifying rows.
5. **Approved Universe lives as Column 2 of the Portfolio Builder** — never a standalone route. Drag-drop into allocation blocks on one screen.
6. **Phase 4.2 War Room's cascade animation is the correct aesthetic** — but its one-off implementation is a failure. Must be generalized into a system primitive (`FocusMode`) before any new surface ships.
7. **Smart backend, dumb frontend.** The UI never sees `CVaR`, `DTW`, `CLARABEL`, `SCS`, `REGIME_CRISIS`, `Ledoit-Wolf`, `Black-Litterman`, `Marchenko-Pastur`. Backend sanitizes every public event before it crosses the wire.

---

## 1. Convergent Architectural Primitives

All five specialists arrived at the same set of primitives, named the same way. These are the non-negotiable foundations.

### 1.1 Motion grammar — `choreo`
One shared timing system, owned in `packages/ui/src/lib/charts/choreo.ts`, consumed by every Svelte transition AND every ECharts `animationDelay`. Named slots:

| Slot | Delay | Purpose |
|---|---|---|
| `choreo.chrome` | 0ms | Shell chrome, header reveal |
| `choreo.primary` | 120ms | Hero chart / reactor panel |
| `choreo.secondary` | 220ms | Supporting panels |
| `choreo.tail` | 320ms | Tertiary strips, sparklines |
| `choreo.ambient` | 420ms | Legends, footers |

One easing (`cubicOut` for ECharts / `quintOut` for Svelte), one default duration (`900ms` opening / `320ms` update). Lint rule forbids inline `animationDuration`/`delay` outside `packages/ui/src/lib/charts/**`. Phase 4.2 War Room becomes one consumer, not a special case.

### 1.2 `createTerminalChartOptions()` factory
Single factory in `packages/ui/src/lib/charts/terminal-options.ts`. Every chart in `(terminal)/` goes through it. Owns: grid, axis styling, splitLine dashing, tooltip chrome, legend, monospace typography, dataviz palette, animation via `choreo`. Callers supply only `series`/`dataset`/`markArea`. ECharts `renderer` set to Canvas for hero/heatmap/scatter, SVG for small counts.

### 1.3 `FocusMode` system primitive
Generalization of `FundWarRoomModal`. Lives at `frontends/wealth/src/lib/components/terminal/focus-mode/FocusMode.svelte`. Accepts any entity type (`fund`, `portfolio`, `manager`, `sector`, `regime`) via a registry and snippet-based composition. Owns: scrim, 95vw×95vh cage, top bar with entity label, keyboard trap (ESC/TAB), scroll lock, focus return, reduced-motion honoring, URL deep link (`?focus=<type>:<id>`), reload-safe mount. Any grid row on any surface triggers it via `openFocus(...)`.

### 1.4 `TerminalShell` + layer taxonomy
Four-layer component hierarchy. Dependencies flow downward only:

- **Layer 1 — Shell** (`terminal/shell/`): `TerminalShell`, `TerminalTopNav`, `TerminalContextRail`, `TerminalStatusBar`, `CommandPalette`, `AlertTicker`, `LayoutCage` (the canonical `calc(100vh-88px) + padding:24px` cage).
- **Layer 2 — Layout** (`terminal/layout/`): `Panel`, `PanelHeader`, `PanelBody`, `PanelFooter`, `SplitPane`, `StackedPanels`, `FocusMode`.
- **Layer 3 — Data** (`terminal/data/`): `DataGrid` (virtualized, 9k+ rows), `DataTable`, `StatSlab`, `KeyValueStrip`, `Ribbon`, `ChipBar`, `Sparkline`, `StreamingTicker`, `LiveDot`.
- **Layer 4 — Charts** (`terminal/charts/`): `TerminalChart` + thin wrappers per pattern (`TerminalLineChart`, `TerminalHeatmap`, `TerminalTreemap`, etc.).

`@tanstack/svelte-table` stays banned (known Svelte 5 breakage per memory). `DataGrid` uses a headless column-def API and IntersectionObserver virtualization.

### 1.5 `createTerminalStream<T>` — unified SSE/polling primitive
One runtime primitive in `terminal/runtime/stream.ts` consumed by all streaming surfaces. Uses `fetch()` + `ReadableStream` (never `EventSource`). Back-pressure via `createTickBuffer<T>` for any source > 10 ev/s (mandatory per Stability Guardrails P2). Exponential backoff reconnect (1→2→4→8s, cap 30s, ±200ms jitter). `LiveDot` reflects state.

### 1.6 `sanitize_public_event()` — Netz IP firewall
New central module at `backend/vertical_engines/wealth/shared_protocols.py`. Every SSE publisher (`construction_run_executor`, `rebalancing.service`, `drift_monitor`, `alert_engine`, `stress_scenarios`) routes public events through it. Strips raw jargon, maps to the glossary in Appendix D. Unit test: feed every raw enum value and assert output contains none of the banned substrings.

---

## 2. Non-Negotiable Constraints

Enforced by lint/import-linter/review — rejected at PR time, not at merge:

1. **No hex values** in `.svelte` files under `terminal/**`. Stylelint `color-no-hex` scoped to terminal namespace.
2. **No `.toFixed()`, `.toLocaleString()`, `new Intl.*Format`.** Already enforced by `frontends/eslint.config.js`. Current violations (~23 files listed in Appendix F) must be fixed before the sprint starts.
3. **No `localStorage` / `sessionStorage`** for domain data. ESLint `no-restricted-globals`.
4. **No direct `svelte-echarts` import** outside `terminal/charts/TerminalChart.svelte`. ESLint `no-restricted-imports`.
5. **No `EventSource`.** SSE via `fetch()` + `ReadableStream` only (auth headers required for Clerk JWT).
6. **No module-level `$state`** or stores for component-local state. AST rule in `eslint-plugin-netz-runtime`.
7. **No `$effect` that derives state.** Use `$derived`. AST rule.
8. **Every `$effect` starting a stream/timer/observer must return cleanup.** AST rule.
9. **No `(app)` ↔ `(terminal)` cross-imports.** Frontend-level import-linter contract.
10. **Shell cage is `calc(100vh-88px) + padding:24px`.** `flex`/`grid min-h-0` is banned (proven to fail, per memory).
11. **Sidebar fully hides on collapse** — not icon-only. Hamburger toggle. Logo at bottom.
12. **Tokens are semantic** (e.g., `terminal.accent.amber`, not `#ffaa00`). Never ship hex in a token.
13. **Raw quant jargon never crosses the wire.** `sanitize_public_event()` is the contract. Lint rule greps SSE emitters for banned substrings.
14. **Mutating routes are idempotent** — `@idempotent` decorator + triple-layer dedup (Redis + `SingleFlightLock` + `pg_advisory_xact_lock`) per Stability Guardrails P5.
15. **Advisory lock keys use `zlib.crc32`**, never Python `hash()` (non-deterministic across processes).

---

## 3. Phased Rollout (10 sprints)

Each phase = one feature branch, one PR set, one working surface before the next phase starts. Product-facing phases prioritized (per `feedback_phase_ordering.md`).

### Phase 0 — Formatter compliance (prep, 1-2 days)
- Fix all `.toFixed()` / `.toLocaleString()` / `new Intl.*` violations in the terminal namespace (23 files enumerated in Appendix F).
- Run `pnpm --filter @investintell/wealth exec eslint src/` to zero.
- Commit as `chore(terminal): zero formatter violations before primitives sprint`.

### Phase 1 — Foundations (tokens + motion + chart factory + FocusMode refactor)
**Goal:** every future PR inherits the shared grammar from day one. No surface work yet.

- Ship semantic token inventory (Appendix C) as `packages/ui/src/lib/tokens/terminal.css` — colors, spacing, radii, borders, typography, motion slots, z-stack. Zero hex.
- Ship `choreo.ts` motion grammar with `.chrome/.primary/.secondary/.tail/.ambient` slots.
- Ship `createTerminalChartOptions()` factory.
- Ship `TerminalChart.svelte` wrapper + one thin pattern wrapper (`TerminalLineChart`) as reference.
- Ship `FocusMode.svelte` + generic entity registry. Refactor `FundWarRoomModal.svelte` → `FundFocusMode.svelte` composing `FocusMode` with 7 module snippets. Delete `FundWarRoomModal.svelte`.
- Ship `TerminalShell.svelte` + `TerminalTopNav.svelte` + `LayoutCage.svelte` + `TerminalStatusBar.svelte`.
- Ship `createTerminalStream` runtime primitive.
- Add lint rules: `no-restricted-imports` for `svelte-echarts`, `color-no-hex` scoped, `no-restricted-globals` for `localStorage`/`sessionStorage`, `no-restricted-imports` cross-route-group.
- Import-linter contract: `(app)` ↔ `(terminal)` isolation.

**Exit criteria:** `svelte-autofixer` green; Phase 4.2 War Room surface works through `FocusMode`; screener surface still works unchanged (since nothing touched it yet); lint suite rejects any new hex/toFixed/localStorage commit.

### Phase 2 — Data plane (ELITE flag + MVs + compression fixes + sanitization module)
**Goal:** the database can answer the fast-flow queries at 50k catalog size before the UI asks them.

Alembic chain (current head is **`0109_fund_risk_audit_columns`**, not 0105 — CLAUDE.md is stale and should be corrected in this phase):

1. `0110_fund_risk_metrics_elite_flag` — ADD `elite_flag bool`, `elite_tier smallint`, partial index `idx_frm_elite_partial`, backfill.
2. `0111_fund_risk_metrics_compression_segmentby` — fix the critical bug: segmentby is `organization_id` which is always NULL; change to `instrument_id`. Decompress last 3 chunks, alter, recompress. **This alone doubles compression ratio and cuts screener cold reads in half.**
3. `0112_nav_timeseries_chunk_3mo` — adjust chunk interval for future chunks.
4. `0113_mv_fund_risk_latest` — pointer MV so screener join is O(1).
5. `0114_mv_nav_monthly_agg_cagg` — continuous aggregate for screener inline sparklines (9k × 1.3k rows = 12M — direct reads are disqualified).
6. `0115_v_screener_org_membership` — RLS-enforced view with `security_barrier=true` so the `in_universe` flag is a simple column read instead of a 3-way join on every filter tweak.
7. `0116_mv_unified_funds_refresh_concurrent` — switch to `REFRESH MATERIALIZED VIEW CONCURRENTLY`.
8. `0117_portfolio_construction_runs_hypertable` — convert to HT, 1mo chunks, segmentby `organization_id`.
9. `0118_mv_construction_run_diff` — run N vs N-1 diffs for preview panel.
10. `0119_mv_drift_heatmap_weekly_cagg` — CAGG over `strategy_drift_alerts`.
11. `0120_rls_policy_audit_check` — assertion migration that fails if any policy uses bare `current_setting()`.
12. `0121_wealth_vector_chunks_segmentby_source` — change to `source_type` (mostly global, NULL org breaks current segmentation).
13. `0122_screener_facets_indexes` — GIN on `(investment_geography, strategy_label)`.

Worker changes:
- `global_risk_metrics` (lock `900_071`): emit `elite_flag`, `elite_tier`; refresh `mv_fund_risk_latest` at tail.
- `view_refresh.py`: REFRESH CONCURRENTLY + bust `screener:catalog:*` Redis keys.
- `live_price_poll` (`900_100`): confirm symbol selection joins only `live`/`paused` portfolios.
- `construction_run_executor` (`900_101`): publish per-phase events with monotonic `seq` through `sanitize_public_event()`.
- New worker `screener_elite_audit` (lock `900_103`, hourly): diffs ELITE set against prior snapshot.

Central sanitization:
- Create `backend/vertical_engines/wealth/shared_protocols.py::sanitize_public_event()` with the glossary in Appendix D.
- Retrofit `construction_run_executor`, `rebalancing.service`, `drift_monitor`, `alert_engine`, `stress_scenarios` to route through it.
- Unit test asserting zero banned substrings in output.

**Exit criteria:** `make loadtest` (new target) runs the screener scenario and asserts p95 < 300ms at 50k rows with ELITE+4 filters. `EXPLAIN (ANALYZE, BUFFERS)` confirms `idx_frm_elite_partial` is used. Compression ratio on `fund_risk_metrics` > 5×. No CLI can curl a construction run event and find any banned word.

### Phase 3 — Screener fast path
**Goal:** the screener fully powers liquid approvals.

- Reference implementation of the new component architecture. Everything learned here shapes the remaining phases.
- Rebuild `TerminalScreenerShell.svelte` on `TerminalShell` + `SplitPane` + `Panel`.
- Promote `TerminalDataGrid.svelte` to `terminal/data/DataGrid.svelte` (virtualized, 9k+ rows).
- ELITE chip as a first-class filter ribbon with amber star badge.
- Row click → `openFocus({ type: 'fund', id })` via `registerFocusTrigger` attachment — not a local modal prop.
- Fast-path action column: `[→ UNIVERSE]` for liquids (`POST /universe/approve` idempotent), `[+ DD]` for `private_us`/`bdc` (`POST /dd-reports/queue`). Disclosure matrix drives which action shows per row.
- Backend: `POST /universe/approve` adds `fast_track=true` branch for liquids; enforces DD completion for privates (409 with `{error:"dd_required", queueId}`).
- Inline sparklines read from `mv_nav_monthly_agg` CAGG — only visible rows mount `<svelte-echarts>`, scrolled-out rows render cached SVG path strings.
- Keyboard: `/` focus search, `↑↓` navigate, `Enter` Focus Mode, `u` send to universe, `d` queue DD, `e` toggle ELITE.

**Exit criteria:** Andrei can screen 9k funds, filter to ELITE, click a row to open FocusMode, return, hit `u`, and see 3 funds land in Approved Universe in <1 second — entirely in the terminal.

### Phase 4 — Portfolio Builder + Construction Run keystone
**Goal:** the construction cascade is the visual centerpiece of the terminal.

- Rebuild Portfolio Builder at `(terminal)/portfolio/builder` as three-column: Allocation Blocks | Approved Universe | Construction Preview.
- Drag-drop universe cards into allocation blocks. Double-click → FocusMode over builder.
- Construction Run control panel in the footer strip.
- Wire `POST /model-portfolios/{id}/construction/run` (exists at `routes/model_portfolios.py` L502) to return 202 + `job_id`.
- SSE stream via `/jobs/{job_id}/stream` — 5-pill Cascade Strip visualization:
  1. Inputs (Expected Returns, Covariance, Volatility, Factors sub-dots)
  2. Primary Objective
  3. Robust Optimization
  4. Variance-Capped
  5. Minimum Variance / Heuristic Recovery
- Each pill: idle → running (pulsing) → done (check) → skipped (dashed) → failed (red).
- Click pill opens side drawer with sanitized details (no CLARABEL/SCS/SOCP/Ledoit-Wolf in any label).
- Live stress fan chart (`TerminalRollingBand` pattern) builds as `stage.stress` events stream.
- Validation gate checklist fills in real-time.
- Diff vs previous run via `GET /model-portfolios/{id}/construction/runs/{runId}/diff?against=previous` (new endpoint).
- Cancel via `DELETE /jobs/{jobId}` with cooperative cancellation token.
- Failure modes: Phase 1 infeasible → pill "skipped", auto-advance to 1.5; solver fallback → subtle clock icon only; all-fail → Heuristic Recovery with `validation.gate='warn'` and Activation button disabled until advisor note acknowledged.
- Activation: 4-eyes dialog → `POST /model-portfolios/{id}/activate` → `draft → live`, `AuditEvent` written.

**Exit criteria:** Andrei can build, run construction with streaming cascade, review stress, and activate a model portfolio end-to-end in the terminal without ever seeing the word CVaR/CLARABEL/DTW.

### Phase 5 — Live Workbench + Rebalance + Alerts
**Goal:** ongoing operations.

- Rebuild `LiveWorkbenchShell` on `TerminalShell` + `StackedPanels`. NAV ticker strip from `live_price_poll` Redis hash via `/portfolios/{id}/prices/stream` SSE (Redis pub/sub bridged through `RateLimitedBroadcaster`).
- Staleness > 3min: amber pulse + `price_staleness` alert.
- Drift monitor panel with `driftStatus: "Aligned"|"Watch"|"Breach"` (no DTW anywhere).
- Alert stream panel scoped to portfolio. Redis Streams (not pub/sub) for replay on reconnect.
- Rebalance overlay (inside Live Workbench, not a route change, URL gains `?rebalance=open`):
  - Left: proposed weight deltas from `weight_proposer`
  - Right: `impact_analyzer` output — turnover %, expected return lift, expected risk delta, warnings
  - One-click `[SUBMIT PROPOSAL]` → `POST /rebalancing/{id}/submit` idempotent.
- **Promote `POST /rebalancing/impact` to Job-or-Stream** before the fast flow cutover — fast-flow universe size (500-5000) blows past 500ms p95.
- Global alert ticker at bottom of terminal: multiplex `portfolio_alerts` SSE + construction run progress + live price staleness + macro flashes.
- Alerts inbox at `/alerts` with filter by severity/source/portfolio/status, keyboard J/K/E navigation.

**Exit criteria:** live portfolio with streaming prices, drift monitor, alert ticker, and one-click rebalance all in the terminal.

### Phase 6 — DD Track (illiquids parallel lane)
**Goal:** private funds and BDCs have a dignified DD path that does not clutter the fast flow.

- `/(terminal)/dd` — 3-column Kanban: Pending / In Report (streaming chapters) / In Critic Review / Approved.
- DD Queue aggregator endpoint `GET /dd-reports/queue` (new — current backend is missing an aggregator).
- Long-form DD SSE stream (8 chapters) via `long_form_report` engine — already built with Semaphore(2).
- Chapter Viewer with evidence pack, confidence score, critic observations. Netz IP (raw critic prompts, adversarial reasoning) stays server-side.
- `[APPROVE]`/`[REJECT]` gates fund into or out of universe via the same `/universe/approve` endpoint (branches on `universe IN ('private_us','bdc')` + `dd_queue.status='complete'`).
- DD Queue badge on top nav only when > 0 items pending.

**Exit criteria:** private funds never appear in the fast-path universe without a completed, critic-approved DD report.

### Phase 7 — Macro Desk + Allocation Blocks
**Goal:** top-down inputs feed the fast flow.

- `/(terminal)/macro` — 12-column grid: 4 regional regime tiles (US/EU/JP/EM), yield curves, macro indicator sparkline wall, flash feed (SSE).
- Regime labels sanitized: `Normal`/`Risk On`/`Risk Off`/`Crisis` (not `REGIME_*` enums).
- `/(terminal)/allocation` — strategic allocation editor. 3-column: block tree | weights editor with regime-conditioned suggestions | impact preview.
- Forward link: `[→ BUILDER]` carries template UUID in URL.
- Context pinning: `[PIN REGIME]` writes to context rail for downstream screens.

**Exit criteria:** portfolio construction can be triggered from a macro reading in three clicks.

### Phase 8 — Research + Entity Vitrines (supporting surfaces)
- Rebuild `TerminalResearchShell` on primitives.
- Port `EntityAnalyticsVitrine` → FocusMode fund preset snippets.
- Port remaining `(app)/` analytics screens into terminal Focus Mode presets for `portfolio`, `manager`, `sector`, `regime`.

### Phase 9 — `(app)/` read-only freeze
- Add `ReadOnlyRouteGate` middleware to every legacy `(app)/portfolio/*`, `(app)/screener/*`, `(app)/discovery/*`, `(app)/market/*`, `(app)/dashboard/*` route — blocks mutations, logs attempts.
- Delete operational `(app)/` routes: `dashboard`, `discovery`, `discovery/funds`, `screener/*`, `portfolio/*`, `sandbox`.
- Keep read-only: `macro`, `market/reviews`, `market`, `library/[...path]`, `content/[id]`, `documents/*`, `settings/*`.
- Each remaining `(app)/` layout gets a banner: "Read-only report surface — operational work happens in the terminal."

**Exit criteria:** the only way to operate on a portfolio is through `(terminal)/`. `(app)/` serves reports only.

---

## 4. Migration Guardrails (continuous, applied from Phase 1 onward)

Drift is cheapest to prevent on the first merge. No sprint-time exceptions.

- **PR template** gets two new checkboxes:
  - [ ] Uses `TerminalChart` for any chart
  - [ ] Uses `@netz/ui` formatters exclusively
- **`make check` gate** must be green: lint + architecture (import-linter) + typecheck + test.
- **Reference implementation rule:** no second terminal surface ships before the first (Screener, Phase 3) is merged and reviewed. Prevents parallel drift.
- **Visual identity review:** every PR touching `(terminal)/` goes through `svelte5-frontend-consistency` agent review before merge. No exceptions.
- **Sanitization lint:** greps SSE emitter files for the banned substring list. CI-blocking.

---

## 5. Risks & Race Conditions

Enumerated so each phase can test them explicitly:

1. **Dual SSE streams** — top nav regime ticker + bottom status ticker + Focus Mode live streams may conflict. Solution: `TerminalEventBus` singleton that demultiplexes one connection per resource; components subscribe.
2. **Focus Mode URL collision** — two panels mutating `?focus=` simultaneously. Rule: only outermost `FocusMode` writes to URL; nested calls rejected.
3. **Screener double-click on Send to Universe** — handled by triple-layer idempotency (header-based Redis key + `SingleFlightLock` + `pg_advisory_xact_lock(crc32(...))`) and 1.5s button disable.
4. **Construction run resume after session expiry** — mid-run Clerk session expiry must silent-refresh then resubscribe; don't drop the job.
5. **Stale universe in Builder** — if a peer approves a fund mid-session, Col 2 must re-query on SSE `universe_updated` event, not poll.
6. **MV refresh during screener reads** — `REFRESH CONCURRENTLY` is mandatory.
7. **Compression decompress/recompress during Phase 2** — must run off-peak; migration 0111 blocks writes to affected chunks briefly.
8. **Client cannot drain live prices** — coalesce to latest-per-symbol, drop intermediate frames, `RateLimitedBroadcaster` caps at 10 msg/s/connection.
9. **Focus Mode deep link to dead entity** — render `Err` component with code `ERR-404 // entity not found`, don't crash.
10. **Heuristic recovery on construction** — Activation must be disabled until advisor note acknowledged so users don't ship a half-solved portfolio.

---

## 6. Validation Gates per Phase

- [ ] `svelte-autofixer` clean on every new terminal component (Svelte MCP).
- [ ] Browser validated against real backend (Railway prod or local `make serve`) — not just dev mocks. Per `feedback_visual_validation.md`.
- [ ] Zero quant jargon leak — grep public API responses for banned substrings.
- [ ] Every operational surface reload-safe (deep link test).
- [ ] ESC stack contract verified across 3 layered panels.
- [ ] SSE via `fetch()+ReadableStream`, never `EventSource`.
- [ ] No `localStorage` — state is in-memory, URL, SSE, polling.
- [ ] `make loadtest` screener scenario p95 < 300ms at 50k rows with ELITE filter.
- [ ] `EXPLAIN (ANALYZE, BUFFERS)` on every screener query shows partial index usage and chunk exclusion.
- [ ] Construction run cancel/diff/replay endpoints work with idempotency.

---

## 7. Backend Gaps Summary (Phase 2 closes these)

1. `elite_flag` + `elite_tier` columns on `fund_risk_metrics` — migration 0110, worker 900_071 update.
2. `fast_track` column on `instruments_org` — migration piggybacked on 0110.
3. Centralized `sanitize_public_event()` module — new file, retrofitted call sites.
4. `GET /dd-reports/queue` aggregator — new route.
5. Fast-track branch in `POST /universe/approve` with DD guardrail for privates.
6. `GET /model-portfolios/{id}/construction/runs/{runId}/diff` endpoint.
7. `portfolio_construction_runs.event_log JSONB` — verify 0109 covers it, else add column.
8. `DELETE /jobs/{jobId}` cancel endpoint wired to executor cancellation token.
9. Live workbench response sanitization (retrofit `routes/risk_timeseries.py`, `routes/exposure.py`, `routes/entity_analytics.py` through the sanitizer).
10. `ReadOnlyRouteGate` middleware for `(app)/` operational routes.
11. `POST /rebalancing/impact` promoted to Job-or-Stream.

---

## 8. Infrastructure Notes

- **Alembic head is `0109_fund_risk_audit_columns`**, not `0105_portfolio_calibration_fk_on_construction_runs`. CLAUDE.md is stale and gets corrected as a doc-only edit in Phase 2.
- **Redis keys to provision:** `live:px:v1:{symbol}`, `runs:v1:{run_id}`, `alerts:v1:{org}` (Stream), `flash:v1:global` (Stream), `screener:catalog:*`, `screener:catalog:facets:*`, `construction:{sha256}`.
- **Advisory lock `900_103`** for new `screener_elite_audit` worker — generated via `zlib.crc32(b'screener_elite_audit') & 0x7FFFFFFF`.

---

# Appendix A — Chart Catalog (from ECharts specialist)

14 patterns, each as a thin wrapper under `packages/ui/src/lib/charts/patterns/`:

| # | Pattern | Chart type | Density | Cascade | Consumers |
|---|---|---|---|---|---|
| 1 | NAV time series | line + gradient area, LTTB sampling, progressive 2000 | hero | primary | Live Workbench, Builder preview, Focus Mode |
| 2 | Underwater drawdown | inverted area, markPoint on max-DD | compact | secondary | Focus Mode, DD report (read-only) |
| 3 | Rolling returns | line + brush, 1y/3y/5y toggle via legendSelected | compact | secondary | Focus Mode, Screener col3 |
| 4 | Return distribution + tails | histogram 30 bins, markLine at mean/VaR95/CVaR95 labeled "95% Worst Case" | compact | secondary | Focus Mode, Fact Sheet |
| 5 | Capture ratios | grouped horizontal bar with markLine at 100% | compact | tail | Capture panel, peer drawer |
| 6 | Correlation heatmap | heatmap + visualMap, pre-denoised by backend, labeled "Correlation (denoised)" | hero | secondary | Live Workbench risk, Builder |
| 7 | Attribution waterfall | two-series bar trick, labels "Allocation/Selection/Mix Contribution" | compact | secondary | Attribution panel, Monthly Report |
| 8 | Risk/return scatter + frontier | scatter + line, bubble size = AUM, markLine Sharpe=1 | compact | secondary | Construction panel, Screener col3 |
| 9 | Factor exposure | radar if ≤6, horizontal bar if >6 | compact | tail | Factor drawer, DD |
| 10 | Allocation treemap | treemap leafDepth 2 | hero | primary | Allocator, Builder preview |
| 11 | Live price sparklines | 48×16 canvas, 60 points, virtualized (visible rows only) | spark | live (no animation) | Screener grid, Ticker strip, watchlist |
| 12 | Macro curves | multi-series line with markArea for regime bands | hero | primary | Macro Desk |
| 13 | Stress test fan chart | line + 4 translucent scenario bands, labels like "Global Financial Crisis" | hero | secondary | Construction output |
| 14 | Construction run convergence | step chart, 5 phase categories with status markers | compact | primary | Construction SSE stream |

Performance budgets per pattern defined in `packages/ui/src/lib/charts/budgets.ts`. Screener 9k-row grid uses virtualized sparklines — only visible rows (~40) mount ECharts; scrolled-out rows render cached SVG path strings keyed by `instrumentId`.

---

# Appendix B — Navigation Flow Detail (from UX Flow architect)

**Global shell:**
- `TerminalTopNav` (32px, monospace): `[NETZ // WEALTH]` brand · MACRO · ALLOC · SCREENER · BUILDER · LIVE · ALERTS · DD · `[⌘K]` · Regime ticker · Tenant · Alert pill · Session chip.
- `TerminalContextRail` (280px, right, collapsible with `[`/`]`): only appears when entity pinned via `?entity=fund:abc`. Entity-type-specific content.
- `TerminalStatusBar` (24px, bottom): multiplexed ticker of alerts + construction runs + price staleness + macro flashes. Click expands inline to 60vh drawer.
- Keyboard: `⌘K` palette, `g m/a/s/p/l/u/r/d` go-to shortcuts, `f` Focus Mode, `Esc` stack-pop, `[`/`]` rail, `/` filter, `.` density, `?` cheatsheet.

**URL contract (every surface reload-safe):**

| Surface | URL |
|---|---|
| Macro Desk | `/macro` |
| Allocation | `/allocation?template={uuid}` |
| Screener | `/terminal-screener?q=&universe=&elite=1&strategy=&sort=&page=` |
| Screener + Focus | append `&focus=fund:<id>` |
| Builder | `/builder?portfolio={uuid}&template={uuid}` |
| Construction in-flight | add `&run={job_id}` |
| Live | `/portfolio/live?portfolio={uuid}` |
| Rebalance overlay | add `&rebalance=open` |
| Alerts | `/alerts?severity=&portfolio=&since=` |
| DD Queue | `/dd?status=` |
| DD Chapter | `/dd/{run_id}/chapter/{n}` |

**Focus Mode URL:** `?focus=<type>:<id>` layered on any host surface. Reload-safe, shareable. ESC writes URL without focus param (not `history.back()`).

**Empty/loading/error patterns:** terminal-native, never Web-Modern spinners. Loading = CSS hatching + `█ LOADING // 0.34s` live counter. Empty = ASCII box `[ NO DATA // FILTERS=3 // RESET? ]`. Error = red border + `[ ERR // HTTP 500 // JOB 27e4 ]`. Stale = amber pulse + `STALE · 4m 12s`. Degraded = cyan stripes + `PARTIAL · 3/7`.

**`(app)/` deprecation verdict table:**

| Route | Verdict |
|---|---|
| `(app)/dashboard` | DELETE |
| `(app)/discovery`, `discovery/funds` | DELETE |
| `(app)/screener/*` | DELETE |
| `(app)/portfolio/*` | DELETE |
| `(app)/sandbox` | DELETE |
| `(app)/macro` | KEEP READ-ONLY |
| `(app)/market`, `market/reviews` | KEEP READ-ONLY |
| `(app)/library/[...path]` | KEEP READ-ONLY |
| `(app)/content/[id]` | KEEP READ-ONLY |
| `(app)/documents/*` | KEEP READ-ONLY |
| `(app)/settings/*` | KEEP READ-ONLY |

---

# Appendix C — Design Token Inventory (from Svelte consistency specialist)

All tokens semantic. No hex in components. Single source: `packages/ui/src/lib/tokens/terminal.css`.

- **Background layers:** `terminal.bg.void`, `.panel`, `.panel-raised`, `.panel-sunken`, `.overlay`, `.scrim`
- **Foreground tiers:** `terminal.fg.primary`, `.secondary`, `.tertiary`, `.muted`, `.disabled`, `.inverted`
- **Accents:** `terminal.accent.amber` (primary), `.cyan` (live data), `.violet` (AI surfaces)
- **Status:** `terminal.status.success`, `.warn`, `.error`, `.neutral`
- **Dataviz palette:** `terminal.dataviz.1` through `.8` — ordinal, colorblind-safe, derived from accents
- **Spacing:** `terminal.space.1/2/3/4/6/8/12` = 4/8/12/16/24/32/48
- **Radii:** `terminal.radius.none = 0` — one token, one value
- **Borders:** `.hairline = 1px fg.muted`, `.strong = 1px fg.secondary`, `.focus = 2px accent.amber`
- **Typography:** `terminal.font.mono` (JetBrains Mono / IBM Plex Mono), `terminal.font.sans` (narrative only); scales `.text.10/11/12/14/16/20/24`
- **Motion:** `terminal.motion.choreo.chrome/primary/secondary/tail/ambient` — matched to `choreo.ts` slots. `terminal.motion.tick` for ticker flashes. `terminal.motion.reduced` honors `prefers-reduced-motion`.
- **Z-index stack:** `base=0, panel=10, rail=20, statusbar=30, dropdown=40, modal=50, focusmode=60, palette=70, toast=80`

---

# Appendix D — Sanitization Glossary (from Quant specialist)

Contract between quant engine and UI. `sanitize_public_event()` enforces this before any SSE/HTTP response leaves the backend. New quant terms MUST update this table before being consumable by the terminal.

| Raw backend term | User-facing terminal term |
|---|---|
| `CVaR 95` / `cvar_95_conditional` | **Tail Loss (95% confidence)** |
| `CVaR 99` | **Extreme Tail Loss** |
| `VaR 95` | **Value at Risk (95%)** |
| `DTW drift` / `dtw_distance` | **Strategy Drift** |
| `REGIME_RISK_ON` | **Risk On Regime** |
| `REGIME_NORMAL` | **Normal Regime** |
| `REGIME_RISK_OFF` | **Risk Off Regime** |
| `REGIME_CRISIS` | **Crisis Regime** |
| `Ledoit-Wolf shrinkage` | *internal only — never shown* |
| `sample_covariance` | *internal only* |
| `Black-Litterman prior` | **Expected Returns — Baseline** |
| `Black-Litterman posterior` | **Expected Returns — With Views** |
| `IC view` | **Investment View** |
| `GARCH(1,1)` / `garch_cond_vol` | **Conditional Volatility** |
| `EWMA volatility` | **Trailing Volatility** |
| `PCA factor model` | **Factor Decomposition** |
| `PC1 / PC2 / PC3` | **Market / Style / Sector Factors** |
| `Phase 1` | **Primary Objective** |
| `Phase 1.5 robust SOCP` | **Robust Optimization** |
| `Phase 2 variance-capped` | **Variance-Capped** |
| `Phase 3 min-variance` | **Minimum Variance** |
| `heuristic fallback` | **Heuristic Recovery** |
| `CLARABEL solver` | *internal only* |
| `SCS solver` | *internal only* |
| `turnover L1 penalty` | **Turnover Budget** |
| `ellipsoidal uncertainty set` | *internal only* |
| `Brinson-Fachler` | **Performance Attribution** |
| `allocation / selection / interaction effect` | **Allocation / Selection / Mix Contribution** |
| `Marchenko-Pastur denoising` | *internal only* |
| `absorption ratio` | **Market Stress Indicator** |
| `rolling correlation` | **Correlation over Time** |
| `scoring composite` | **Quality Score** |
| `return_consistency / drawdown_control / fee_efficiency / …` | **Consistency / Drawdown Control / Fee Efficiency / …** |
| `mandate_fit_score` | **Mandate Fit** |
| `concentration penalty` | **Concentration Flag** |
| `solver infeasible` | **Could not meet all constraints** |
| `advisor remediation` | **Construction Note** |
| `stress scenario GFC / COVID / TAPER / RATE_SHOCK` | **Global Financial Crisis / COVID / Taper Tantrum / Rate Shock** |
| `peak_to_trough` | **Peak-to-Trough Loss** |
| `validation gate` | **Readiness Check** |
| `fund_risk_metrics.elite_flag` | **Elite** (top-decile risk-adjusted within asset class, no fatal flaw) |

---

# Appendix E — Idempotency Key Map (from Quant specialist)

All mutating terminal routes use triple-layer dedup: Redis `Idempotency-Key` header (24h or 1h) + `SingleFlightLock` + `pg_advisory_xact_lock(zlib.crc32(...))`.

| Operation | Route | Lock key | Window |
|---|---|---|---|
| Universe approve (liquids) | `POST /universe/approve` | `crc32("universe_approve", org, block)` | 24h |
| Queue DD | `POST /dd-reports/queue` | `crc32("dd_queue", org, fund)` | 24h |
| Stress run | `POST /model-portfolios/{id}/stress-test` | `crc32("stress", portfolio)` | 1h |
| Construction run | `POST /model-portfolios/{id}/construction/run` | `crc32("construction", portfolio)` | 1h (returns existing job on replay) |
| Construction cancel | `DELETE /jobs/{id}` | `crc32("job_cancel", job)` | — |
| Rebalance propose | `POST /rebalancing/{id}/propose` | `crc32("rebal_propose", portfolio)` | 10min |
| Rebalance submit | `POST /rebalancing/{id}/submit` | `crc32("rebal_submit", portfolio)` | 24h |
| Activate | `POST /model-portfolios/{id}/activate` | `crc32("activate", portfolio)` | 24h |
| Pause | `POST /model-portfolios/{id}/pause` | `crc32("pause", portfolio)` | 1h |
| Resume | `POST /model-portfolios/{id}/resume` | `crc32("resume", portfolio)` | 1h |

**409 UX contract:** on in-flight conflict, return `{code:"inflight", jobId?}` and the terminal auto-subscribes to the existing stream instead of failing the user.

---

# Appendix F — Formatter Violation Inventory (Phase 0 prep)

Files with `.toFixed()`, `.toLocaleString()`, or inline `Intl.*Format` that must be fixed before Phase 1 starts:

- `frontends/wealth/src/lib/components/analytics/entity/EntityAnalyticsVitrine.svelte` (lines 40, 41, 42, 47)
- `frontends/wealth/src/lib/components/analytics/entity/CaptureRatiosPanel.svelte` (lines 45, 63, 86, 92)
- `frontends/wealth/src/lib/components/analytics/entity/DrawdownChart.svelte` (lines 34, 43, 95)
- `frontends/wealth/src/lib/components/analytics/entity/MonteCarloPanel.svelte` (lines 62, 63, 105)
- `frontends/wealth/src/lib/components/analytics/entity/ReturnDistributionChart.svelte` (lines 55, 74, 75, 78)
- `frontends/wealth/src/lib/components/analytics/entity/RollingReturnsChart.svelte` (lines 42, 51)
- `frontends/wealth/src/lib/components/analytics/entity/TailRiskPanel.svelte` (lines 51, 65)
- `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte`
- `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerFilters.svelte`
- `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerQuickStats.svelte`
- `frontends/wealth/src/lib/components/portfolio/live/TerminalAllocator.svelte`
- `frontends/wealth/src/lib/components/portfolio/live/TerminalBlotter.svelte`
- `frontends/wealth/src/lib/components/portfolio/live/TerminalOmsPanel.svelte`
- `frontends/wealth/src/lib/components/portfolio/live/TerminalTickerStrip.svelte`
- `frontends/wealth/src/lib/components/portfolio/live/TerminalTradeLog.svelte`
- `frontends/wealth/src/lib/components/portfolio/live/TradeConfirmationDialog.svelte`
- `frontends/wealth/src/lib/components/portfolio/live/InitialFundingModal.svelte`
- `frontends/wealth/src/lib/components/research/terminal/TerminalRiskKpis.svelte`
- `frontends/wealth/src/lib/components/research/terminal/TerminalAssetTree.svelte`
- `frontends/wealth/src/lib/components/research/terminal/TerminalResearchChart.svelte`
- `frontends/wealth/src/lib/components/research/terminal/ScoreBreakdownPopover.svelte`
- `frontends/wealth/src/lib/components/execution/TradeBlotter.svelte`
- `frontends/wealth/src/lib/components/charts/tooltips.ts`

---

# Appendix G — File Structure Target

```
frontends/wealth/src/lib/components/terminal/
├── shell/
│   ├── TerminalShell.svelte
│   ├── TerminalTopNav.svelte
│   ├── TerminalContextRail.svelte
│   ├── TerminalStatusBar.svelte
│   ├── CommandPalette.svelte
│   ├── AlertTicker.svelte
│   └── LayoutCage.svelte
├── layout/
│   ├── Panel.svelte
│   ├── PanelHeader.svelte
│   ├── PanelBody.svelte
│   ├── PanelFooter.svelte
│   ├── SplitPane.svelte
│   └── StackedPanels.svelte
├── focus-mode/
│   ├── FocusMode.svelte
│   ├── registry.ts
│   ├── fund/
│   │   ├── FundFocusMode.svelte
│   │   └── modules/
│   │       ├── FundIdentityHeader.svelte
│   │       ├── FundRiskStats.svelte
│   │       ├── FundNavChart.svelte
│   │       ├── FundHoldingsGrid.svelte
│   │       ├── FundPeerGroup.svelte
│   │       ├── FundFeeDrag.svelte
│   │       └── FundWatchlistStatus.svelte
│   ├── portfolio/
│   │   └── PortfolioFocusMode.svelte
│   ├── manager/
│   │   └── ManagerFocusMode.svelte
│   ├── sector/
│   │   └── SectorFocusMode.svelte
│   └── regime/
│       └── RegimeFocusMode.svelte
├── data/
│   ├── DataGrid.svelte
│   ├── DataTable.svelte
│   ├── StatSlab.svelte
│   ├── KeyValueStrip.svelte
│   ├── Ribbon.svelte
│   ├── ChipBar.svelte
│   ├── Sparkline.svelte
│   ├── StreamingTicker.svelte
│   └── LiveDot.svelte
├── charts/
│   ├── TerminalChart.svelte
│   ├── TerminalLineChart.svelte
│   ├── TerminalAreaChart.svelte
│   ├── TerminalHeatmap.svelte
│   ├── TerminalTreemap.svelte
│   ├── TerminalRadar.svelte
│   ├── TerminalRollingBand.svelte
│   ├── TerminalDistribution.svelte
│   └── TerminalCandlestick.svelte
├── runtime/
│   ├── stream.ts            // createTerminalStream
│   ├── poll.ts              // createPoll
│   └── context.ts           // typed context keys
├── focus-attach.ts          // registerFocusTrigger {@attach}
└── index.ts                 // public barrel; deep imports blocked
```

---

## Next Action

Awaiting `/ce:work` to open `feat/terminal-unification` off `main` and execute Phase 0 → Phase 1 in the first PR pair.
