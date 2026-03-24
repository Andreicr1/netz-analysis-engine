# Executed: Wealth Frontend Wiring Backlog
**Plan:** `docs/plans/wm-frontend-backlog-2026-03-23.md`
**Executed:** 2026-03-24
**Status:** COMPLETE — 22/22 tasks delivered

---

## Execution Summary

| Phase | Tasks | Commits | Status |
|-------|-------|---------|--------|
| Backend Pre-requisites | WM-BE-01, WM-BE-02 | `69200ea` | DONE |
| S1 — Macro Intelligence | WM-S1-PRE..05 (6 tasks) | `583c487` | DONE |
| S2 — Screener Unificado | WM-S2-PRE..04 (5 tasks) | `9ebb8ba` | DONE |
| S3 — Model Portfolios + Fact Sheets | WM-S3-01..03 (3 tasks) | `6c25b57` | DONE |
| S4 — Analytics + Pontuais + Bug Fix | WM-S4-01..06 (6 tasks) | `6c25b57` | DONE |
| Infra — CORS fix | — | `0246f84` | DONE |
| Infra — Treasury worker fix | — | `a0726c5` | DONE |

**Total: 2 backend + 20 frontend = 22 tasks. 0 regressions. svelte-check 0 errors.**

---

## Phase 1 — Backend Pre-requisites

### WM-BE-01 — Expose `mp_threshold` + `n_signal_eigenvalues`
- **Commit:** `69200ea`
- **Files:** `vertical_engines/wealth/correlation/models.py`
- **What:** Added `mp_threshold: float` and `n_signal_eigenvalues: int` to `ConcentrationAnalysis` schema. Propagated from internal `_marchenko_pastur_denoise()` result.
- **Unlocked:** WM-S4-02 (eigenvalue bar chart), WM-S4-04 (rolling correlation with MP line)

### WM-BE-02 — Rolling correlation endpoint
- **Commit:** `69200ea`
- **Files:** `app/domains/wealth/routes/analytics.py`
- **What:** `GET /analytics/rolling-correlation?inst_a={id}&inst_b={id}&profile={profile}&window_days={int}` — returns `{ dates, values, instrument_a, instrument_b }`. RLS enforced, `window_days` default 90, max 252.
- **Unlocked:** WM-S4-04

---

## Phase 2 — S1: Macro Intelligence

### WM-S1-PRE — Validate sort ascending
- **Commit:** `583c487`
- **What:** Verified all macro endpoints (`/macro/bis`, `/macro/imf`, `/macro/treasury`, `/macro/ofr`) return date-sorted ascending. Fixed where needed to prevent ECharts `step: 'end'` inversion.

### WM-S1-01 — ECharts multi-grid chart
- **Commit:** `583c487`
- **Files:** `lib/components/macro/MacroChart.svelte` (new)
- **What:** Dual Y-axis chart wrapping `ChartContainer` with main grid (55%) + sub-chart (15%). `axisPointer.link`, `dataZoom` with `filterMode: 'weakFilter'`, time range buttons (1M–2Y), `step: 'end'` for monthly/quarterly, mixed frequency banner, `$state.raw()` for series data.

### WM-S1-02 — Series picker
- **Commit:** `583c487`
- **Files:** `lib/components/macro/SeriesPicker.svelte` (new)
- **What:** 11-group catalog (~120 series), hybrid search-first + browse UX, region/frequency chips, favorites backed by `user_indicator_favorites`, frequency badge pills, hard cap 8 series with warning at 6. State as `MacroChartState` with debounced `$derived.by()`.

### WM-S1-03 — Endpoint wiring
- **Commit:** `583c487`
- **Files:** `routes/(app)/macro/+page.svelte`, `+page.server.ts`
- **What:** Wired BIS, IMF, Treasury, OFR, scores, regime, risk/macro endpoints. AbortController in `$effect` for race condition prevention. IMF WEO forecast renders as solid + dashed series with `markLine` vertical boundary.

### WM-S1-04 — Snapshot badge
- **Commit:** `583c487`
- **Files:** `routes/(app)/macro/+page.server.ts`
- **What:** Added `GET /macro/snapshot` to server load. Regime badge in header (risk-on green, risk-off red, transition yellow) per region (US, Europe, EM, Global). SSR-visible.

### WM-S1-05 — Committee Reviews
- **Commit:** `583c487`
- **Files:** `lib/components/macro/CommitteeReviews.svelte` (new)
- **What:** List + generate + approve/reject with role-gating (`INVESTMENT_TEAM` for generate, `DIRECTOR|ADMIN` for approve/reject). `ConsequenceDialog` with rationale, 409 handling for concurrent approve/reject, paginated list.

---

## Phase 3 — S2: Screener Unificado

### WM-S2-PRE — Component extraction (2473 → 7 components)
- **Commit:** `9ebb8ba`
- **Files:** 7 new components in `lib/components/screener/`
- **What:** Extracted `InstrumentFilterSidebar`, `ManagerFilterSidebar`, `InstrumentTable`, `PeerComparisonView`, `ManagerHierarchyTable`, `ManagerDetailPanel`, `InstrumentDetailPanel`. Panel state via `setContext('screener:panel')`. Main page reduced to ~400 lines.

### WM-S2-01 — Drift tab
- **Commit:** `9ebb8ba`
- **Files:** `lib/components/screener/DriftTab.svelte` (new)
- **What:** `GET /manager-screener/managers/{crd}/drift`. Bar chart (turnover timeline), churn metrics. AbortController cleanup. SvelteMap cache per `${crd}:drift`. Empty state for missing SEC registration.

### WM-S2-02 — Holdings/NPort tab
- **Commit:** `9ebb8ba`
- **Files:** `lib/components/screener/HoldingsTab.svelte` (new)
- **What:** `GET /manager-screener/managers/{crd}/nport`. Server-side pagination (page_size=50). N-PORT merge when more recent than quarterly 13F. Three empty states (no CIK, zero holdings, fetch error).

### WM-S2-03 — Docs tab
- **Commit:** `9ebb8ba`
- **Files:** `lib/components/screener/DocsTab.svelte` (new)
- **What:** `GET /manager-screener/managers/{crd}/brochure/sections` + search endpoint. Debounce 300ms. Label "Docs" (never "ADV Part 2A Brochure").

### WM-S2-04 — Dynamic facets
- **Commit:** `9ebb8ba`
- **Files:** `lib/components/screener/InstrumentFilterSidebar.svelte`
- **What:** `CHIP_FACETS` record maps asset type → visible facets. `transition:slide` reveal. Inapplicable facets disabled with tooltip.

---

## Phase 4 — S3 + S4: Model Portfolios, Analytics, Pontuais

### WM-S3-01 — Model portfolio creation dialog
- **Commit:** `6c25b57`
- **Files:** `routes/(app)/model-portfolios/+page.server.ts`, `+page.svelte`
- **What:** "New Portfolio" button role-gated to `investment_team|director|admin`. Modal dialog with form (profile, display_name, description, benchmark_composite, inception_date, backtest_start_date). POST → redirect to detail page. 409 inline error: "A portfolio with this profile already exists."

### WM-S3-02 — Fact sheets: generate + list + download
- **Commit:** `6c25b57`
- **Files:** `routes/(app)/model-portfolios/[portfolioId]/+page.server.ts`, `+page.svelte`
- **What:** "Fact Sheets" section below Fund Selection. Language selector (pt/en), generate button (`POST /fact-sheets/model-portfolios/{id}`), list from SSR, per-item download via `getBlob()` + `URL.revokeObjectURL()`.

### WM-S3-03 — Portfolio history tab
- **Commit:** `6c25b57`
- **Files:** `routes/(app)/portfolios/[profile]/+page.svelte`
- **What:** "History" tab added to portfolio workbench. Lazy load `GET /portfolios/{profile}/history` via `$effect` + `AbortController`. Table: date, NAV, breach status (StatusBadge), regime (StatusBadge).

### WM-S4-01 — CorrelationHeatmap component
- **Commit:** `6c25b57`
- **Files:** `packages/ui/src/lib/charts/CorrelationHeatmap.svelte` (new), `charts/index.ts`
- **What:** Diverging blue-white-red palette (Brewer RdBu, colorblind-safe). 50x50 config (rotated labels, no in-cell labels). Click handler via `echarts.getInstanceByDom()` → `onPairSelect(a, b)`. Greedy nearest-neighbor clustering toggle. Exported from `@netz/ui/charts`.

### WM-S4-02 — Correlation page wiring
- **Commit:** `6c25b57`
- **Files:** `routes/(app)/analytics/+page.server.ts`, `+page.svelte`, `lib/types/analytics.ts`
- **What:** `GET /analytics/correlation` fetched in SSR. CorrelationHeatmap with real data. Absorption ratio MetricCard (>0.80 warning, >0.90 critical). Eigenvalue bar chart: blue (#2166ac) for signal, gray (#94a3b8) for noise, dashed red markLine at MP threshold.

### WM-S4-03 — Backtest wiring
- **Commit:** `6c25b57`
- **Files:** `routes/(app)/analytics/+page.svelte`
- **What:** `POST /analytics/backtest` with `timeoutMs: 180000`. Elapsed timer: 0–15s pulsing, 15–90s visible counter, 90s+ warning banner. Result display: 3-column KPI row (mean Sharpe, std Sharpe, positive folds) + folds table (fold #, period, Sharpe, CVaR 95%, max DD).

### WM-S4-04 — Rolling correlation drill-down
- **Commit:** `6c25b57`
- **Files:** `routes/(app)/analytics/+page.svelte`
- **What:** Click heatmap cell → lazy load `GET /analytics/rolling-correlation`. Panel below heatmap with title "Rolling Correlation: {a} vs {b}". RegimeChart with `yAxis: [-1, 1]`, markLine at y=0. AbortController cancels previous fetch on new cell click.

### WM-S4-05a — DELETE blended benchmark
- **Commit:** `6c25b57`
- **Files:** `lib/components/BlendedBenchmarkEditor.svelte`
- **What:** "Delete" button (variant=destructive) next to "Save Benchmark". ConsequenceDialog with rationale (min 10 chars). Calls `DELETE /blended-benchmarks/{id}`. Clears local state on success.

### WM-S4-05b — Universe fund audit-trail
- **Commit:** `6c25b57`
- **Files:** `lib/components/UniverseView.svelte`
- **What:** Per-fund toggle buttons in Approved tab. Click loads `GET /universe/funds/{id}/audit-trail` with AbortController. Displays event_type badge, actor, date. Previous fetch aborted on fund switch.

### WM-S4-05c — Screener run detail expand
- **Commit:** `6c25b57`
- **Files:** `routes/(app)/screener/+page.svelte`, `lib/components/screener/ManagerFilterSidebar.svelte`, `screener.css`
- **What:** "View Details" toggle in Last Run section. Parent page fetches `GET /screener/runs/{run_id}` and passes result as props. Inline key-value display of run detail data.

### WM-S4-06 — Exposure path bug fix
- **Commit:** `6c25b57`
- **Files:** `routes/(app)/exposure/+page.server.ts`
- **What:** Fixed `api.get("/exposure/matrix")` → `api.get("/wealth/exposure/matrix")`. Was causing silent 404 on exposure page.

---

## Additional Fixes (out of plan scope)

| Commit | Description |
|--------|-------------|
| `a0726c5` | Treasury ingestion: `setdefault("metadata_json", None)` for consistent pg_insert keys + `--lookback` CLI arg |
| `0246f84` | CORS: `allow_origin_regex` for Cloudflare Pages preview subdomain origins (`*.netz-{wealth,credit,admin}.pages.dev`) |

---

## Quality Gates

| Check | Result |
|-------|--------|
| `svelte-check --threshold error` (wealth) | 0 errors, 14 pre-existing warnings |
| `@netz/ui` build | Clean |
| `make test` (backend) | 2554 passed, 76 pre-existing failures (unrelated) |
| Regressions | 0 |

---

## Endpoints Connected (22 total)

### Newly wired (S3 + S4):
| Endpoint | Component | Method |
|----------|-----------|--------|
| `POST /model-portfolios` | Model portfolio creation dialog | POST |
| `POST /fact-sheets/model-portfolios/{id}` | Fact sheet generate | POST |
| `GET /fact-sheets/model-portfolios/{id}` | Fact sheet list | SSR |
| `GET /fact-sheets/{path}/download` | Fact sheet download | getBlob |
| `GET /portfolios/{profile}/history` | Portfolio history tab | Lazy |
| `GET /analytics/correlation` | Correlation heatmap + eigenvalue | SSR |
| `GET /analytics/rolling-correlation` | Rolling correlation drill-down | Lazy |
| `POST /analytics/backtest` | Walk-forward backtest | POST (180s) |
| `DELETE /blended-benchmarks/{id}` | Delete benchmark | DELETE |
| `GET /universe/funds/{id}/audit-trail` | Universe audit trail | Lazy |
| `GET /screener/runs/{run_id}` | Screener run detail | Lazy |

### Previously wired (S1 + S2):
| Endpoint | Component | Method |
|----------|-----------|--------|
| `GET /macro/bis` | Macro chart | Lazy |
| `GET /macro/imf` | Macro chart | Lazy |
| `GET /macro/treasury` | Macro chart | Lazy |
| `GET /macro/ofr` | Macro chart | Lazy |
| `GET /macro/snapshot` | Snapshot badge | SSR |
| `GET /macro/reviews` | Committee reviews list | SSR |
| `POST /macro/reviews/generate` | Generate review | POST |
| `PATCH /macro/reviews/{id}/approve` | Approve review | PATCH |
| `PATCH /macro/reviews/{id}/reject` | Reject review | PATCH |
| `GET /manager-screener/managers/{crd}/drift` | Drift tab | Lazy |
| `GET /manager-screener/managers/{crd}/nport` | Holdings tab | Lazy |
| `GET /manager-screener/managers/{crd}/brochure/sections` | Docs tab | Lazy |

---

## New Components Created

| Component | Package | Purpose |
|-----------|---------|---------|
| `CorrelationHeatmap.svelte` | `@netz/ui/charts` | Diverging heatmap with clustering + click |
| `MacroChart.svelte` | wealth frontend | Multi-grid ECharts with dual Y-axis |
| `SeriesPicker.svelte` | wealth frontend | Indicator catalog with search + favorites |
| `CommitteeReviews.svelte` | wealth frontend | Role-gated review CRUD |
| `DriftTab.svelte` | wealth frontend | Manager drift visualization |
| `HoldingsTab.svelte` | wealth frontend | 13F/NPort holdings with pagination |
| `DocsTab.svelte` | wealth frontend | Brochure section search |
| `InstrumentFilterSidebar.svelte` | wealth frontend | Screener instrument filters |
| `ManagerFilterSidebar.svelte` | wealth frontend | Screener manager filters |
| `InstrumentTable.svelte` | wealth frontend | Paginated instrument results |
| `PeerComparisonView.svelte` | wealth frontend | Peer comparison cards |
| `ManagerHierarchyTable.svelte` | wealth frontend | Manager→fund hierarchy |
| `ManagerDetailPanel.svelte` | wealth frontend | Manager detail with 4 tabs |
| `InstrumentDetailPanel.svelte` | wealth frontend | Fund detail context panel |
