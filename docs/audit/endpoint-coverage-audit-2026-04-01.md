# Endpoint Coverage Audit — Wealth Vertical

```
Data: 2026-04-01 (atualizado pós-sprint H — ESMA import wired)
Total endpoints backend wealth (excl. infra/workers): 167  (176 - 9 deletados)
Conectados: 165  (164 + 1 ESMA import)
Desconectados (deferred): 5
Infra/workers (excluídos): 28
Phantom calls (frontend → backend inexistente): 0
Coverage: ~98.8% (excluindo deferred como "intended gap")
```

Previous audit (2026-03-23): 93 endpoints, 62 connected (67%).
Sprint G delta: 9 deprecated handlers deleted, 6 new wirings, 1 false negative fixed (risk/stream).

---

## 1. CONNECTED (158 endpoints)

| # | Method | Path | Backend File | Frontend File(s) |
|---|--------|------|-------------|-------------------|
| 1 | GET | /allocation/{profile}/strategic | allocation.py | AllocationView.svelte, portfolios/[profile]/+page.server.ts |
| 2 | PUT | /allocation/{profile}/strategic | allocation.py | AllocationView.svelte |
| 3 | GET | /allocation/{profile}/tactical | allocation.py | AllocationView.svelte |
| 4 | PUT | /allocation/{profile}/tactical | allocation.py | AllocationView.svelte |
| 5 | GET | /allocation/{profile}/effective | allocation.py | AllocationView.svelte, portfolios/[profile]/+page.server.ts |
| 6 | POST | /allocation/{profile}/simulate | allocation.py | AllocationView.svelte |
| 7 | POST | /analytics/backtest | analytics.py | analytics/+page.svelte |
| 8 | POST | /analytics/optimize/pareto | analytics.py | analytics/+page.svelte |
| 9 | GET | /analytics/optimize/pareto/{job_id}/stream | analytics.py | analytics/+page.svelte (SSE fetch) |
| 10 | GET | /analytics/correlation | analytics.py | analytics/+page.server.ts |
| 11 | GET | /analytics/rolling-correlation | analytics.py | analytics/+page.svelte |
| 12 | POST | /analytics/risk-budget/{profile} | analytics.py | analytics/+page.svelte |
| 13 | GET | /analytics/factor-analysis/{profile} | analytics.py | analytics/+page.svelte |
| 14 | POST | /analytics/monte-carlo | analytics.py | analytics/+page.svelte, analytics/[entityId]/+page.svelte |
| 15 | GET | /analytics/peer-group/{entity_id} | analytics.py | analytics/+page.svelte, analytics/[entityId]/+page.server.ts |
| 16 | GET | /analytics/entity/{entity_id} | entity_analytics.py | analytics/+page.svelte, analytics/[entityId]/+page.server.ts |
| 17 | GET | /analytics/attribution/{profile} | attribution.py | analytics/+page.server.ts |
| 18 | GET | /analytics/strategy-drift/alerts | strategy_drift.py | dashboard/+page.server.ts, risk/+page.server.ts, analytics/+page.server.ts, risk-store.svelte.ts |
| 19 | GET | /analytics/strategy-drift/{instrument_id}/history | strategy_drift.py | DriftHistoryPanel.svelte |
| 20 | GET | /analytics/strategy-drift/{instrument_id}/export | strategy_drift.py | DriftHistoryPanel.svelte (fetch) |
| 21 | GET | /blended-benchmarks/blocks | blended_benchmark.py | BlendedBenchmarkEditor.svelte, AllocationView.svelte, portfolios/[profile]/+page.server.ts |
| 22 | GET | /blended-benchmarks/{profile} | blended_benchmark.py | BlendedBenchmarkEditor.svelte |
| 23 | POST | /blended-benchmarks/{profile} | blended_benchmark.py | BlendedBenchmarkEditor.svelte |
| 24 | GET | /blended-benchmarks/{benchmark_id}/nav | blended_benchmark.py | BlendedBenchmarkEditor.svelte |
| 25 | DELETE | /blended-benchmarks/{benchmark_id} | blended_benchmark.py | BlendedBenchmarkEditor.svelte |
| 26 | POST | /content/outlooks | content.py | content/+page.svelte |
| 27 | POST | /content/flash-reports | content.py | content/+page.svelte |
| 28 | POST | /content/spotlights | content.py | content/+page.svelte |
| 29 | GET | /content | content.py | content/+page.server.ts |
| 30 | GET | /content/{content_id} | content.py | content/[id]/+page.server.ts |
| 31 | POST | /content/{content_id}/approve | content.py | content/[id]/+page.svelte, content/+page.svelte |
| 32 | GET | /content/{content_id}/download | content.py | content/[id]/+page.svelte, content/+page.svelte (getBlob) |
| 33 | GET | /content/{content_id}/stream/{job_id} | content.py | content/+page.svelte (SSE fetch) |
| 34 | GET | /dd-reports/ | dd_reports.py | dd-reports/+page.server.ts |
| 35 | POST | /dd-reports/funds/{fund_id} | dd_reports.py | dd-reports/[fundId]/+page.svelte, screener/+page.svelte, CatalogDetailPanel, InstrumentDetailPanel, ManagerDetailPanel |
| 36 | GET | /dd-reports/funds/{fund_id} | dd_reports.py | dd-reports/[fundId]/+page.server.ts |
| 37 | GET | /dd-reports/{report_id}/audit-trail | dd_reports.py | dd-reports/[fundId]/[reportId]/+page.svelte |
| 38 | GET | /dd-reports/{report_id} | dd_reports.py | dd-reports/[fundId]/[reportId]/+page.server.ts |
| 39 | POST | /dd-reports/{report_id}/regenerate | dd_reports.py | dd-reports/[fundId]/[reportId]/+page.svelte |
| 40 | POST | /dd-reports/{report_id}/approve | dd_reports.py | dd-reports/[fundId]/[reportId]/+page.svelte |
| 41 | POST | /dd-reports/{report_id}/reject | dd_reports.py | dd-reports/[fundId]/[reportId]/+page.svelte |
| 42 | GET | /dd-reports/{report_id}/stream | dd_reports.py | dd-reports/[fundId]/[reportId] (SSE), FundDetailPanel.svelte |
| 43 | POST | /wealth/documents/upload-url | documents.py | documents/upload/+page.svelte |
| 44 | POST | /wealth/documents/upload-complete | documents.py | documents/upload/+page.svelte |
| 45 | POST | /wealth/documents/ingestion/process-pending | documents.py | documents/+page.svelte, documents/[documentId]/+page.svelte, documents/upload/+page.svelte |
| 46 | GET | /wealth/documents | documents.py | documents/+page.server.ts |
| 47 | GET | /wealth/documents/{document_id} | documents.py | documents/[documentId]/+page.server.ts |
| 48 | GET | /wealth/documents/{document_id}/preview-url | documents.py | documents/[documentId]/+page.svelte |
| 49 | GET | /wealth/exposure/matrix | exposure.py | exposure/+page.server.ts, ExposureView.svelte |
| 50 | GET | /wealth/exposure/metadata | exposure.py | ExposureView.svelte |
| 51 | POST | /fact-sheets/model-portfolios/{portfolio_id} | fact_sheets.py | portfolios/[profile]/+page.svelte, model-portfolios/[portfolioId]/+page.svelte |
| 52 | GET | /fact-sheets/model-portfolios/{portfolio_id} | fact_sheets.py | portfolios/[profile]/+page.server.ts, model-portfolios/[portfolioId]/+page.server.ts |
| 53 | GET | /fact-sheets/{path}/download | fact_sheets.py | portfolios/[profile]/+page.svelte, model-portfolios/[portfolioId]/+page.svelte (getBlob) |
| 54 | GET | /fact-sheets/dd-reports/{report_id}/download | fact_sheets.py | dd-reports/[fundId]/[reportId]/+page.svelte (fetch) |
| 55 | GET | /funds | funds.py | FundsView.svelte, content/+page.server.ts |
| 56 | GET | /funds/{fund_id} | funds.py | dd-reports/[fundId]/+page.server.ts |
| 57 | GET | /funds/{fund_id}/risk | funds.py | universe/+page.svelte |
| 58 | GET | /instruments | instruments.py | InstrumentsView.svelte |
| 59 | GET | /instruments/{instrument_id} | instruments.py | InstrumentsView.svelte |
| 60 | PATCH | /instruments/{instrument_id} | instruments.py | InstrumentsView.svelte |
| 61 | PATCH | /instruments/{instrument_id}/org | instruments.py | universe/+page.svelte, ConstructionAdvisor.svelte |
| 62 | POST | /instruments | instruments.py | InstrumentsView.svelte |
| 63 | POST | /instruments/import/yahoo | instruments.py | InstrumentsView.svelte |
| 64 | POST | /reporting/.../long-form-report | long_form_reports.py | LongFormReportPanel.svelte |
| 65 | GET | /reporting/.../long-form-report/stream/{job_id} | long_form_reports.py | LongFormReportPanel.svelte (SSE fetch) |
| 66 | GET | /reporting/.../long-form-report/{job_id}/pdf | long_form_reports.py | LongFormReportPanel.svelte (getBlob) |
| 67 | POST | /reporting/.../monthly-report | monthly_report.py | MonthlyReportPanel.svelte |
| 68 | GET | /reporting/.../monthly-report/stream/{job_id} | monthly_report.py | MonthlyReportPanel.svelte (SSE fetch) |
| 69 | GET | /reporting/.../monthly-report/{job_id}/pdf | monthly_report.py | MonthlyReportPanel.svelte (getBlob) |
| 70 | GET | /macro/scores | macro.py | macro/+page.server.ts |
| 71 | GET | /macro/snapshot | macro.py | macro/+page.server.ts |
| 72 | GET | /macro/regime | macro.py | macro/+page.server.ts |
| 73 | GET | /macro/reviews | macro.py | macro/+page.server.ts, CommitteeReviews.svelte, model-portfolios/create/+page.server.ts |
| 74 | POST | /macro/reviews/generate | macro.py | CommitteeReviews.svelte |
| 75 | PATCH | /macro/reviews/{review_id}/approve | macro.py | CommitteeReviews.svelte |
| 76 | PATCH | /macro/reviews/{review_id}/reject | macro.py | CommitteeReviews.svelte |
| 77 | GET | /macro/reviews/{review_id}/download | macro.py | CommitteeReviews.svelte (getBlob) |
| 78 | GET | /macro/bis | macro.py | macro/+page.svelte |
| 79 | GET | /macro/imf | macro.py | macro/+page.svelte |
| 80 | GET | /macro/treasury | macro.py | macro/+page.svelte |
| 81 | GET | /macro/ofr | macro.py | macro/+page.svelte |
| 82 | GET | /manager-screener/managers/{crd}/profile | manager_screener.py | ManagerDetailPanel.svelte, FundDetailsTab.svelte, screener/managers/[crd]/+page.server.ts |
| 83 | GET | /manager-screener/managers/{crd}/holdings | manager_screener.py | ManagerDetailPanel.svelte |
| 84 | GET | /manager-screener/managers/{crd}/drift | manager_screener.py | DriftTab.svelte |
| 85 | GET | /manager-screener/managers/{crd}/institutional | manager_screener.py | ManagerDetailPanel.svelte |
| 86 | GET | /manager-screener/managers/{crd}/universe-status | manager_screener.py | ManagerDetailPanel.svelte |
| 87 | GET | /manager-screener/managers/{crd}/nport | manager_screener.py | HoldingsTab.svelte |
| 88 | GET | /manager-screener/managers/{crd}/brochure/sections | manager_screener.py | DocsTab.svelte |
| 89 | GET | /manager-screener/managers/{crd}/brochure | manager_screener.py | DocsTab.svelte |
| 90 | GET | /manager-screener/managers/{crd}/brochure/key-sections | manager_screener.py | ManagerDetailPanel.svelte, FundDetailsTab.svelte |
| 91 | GET | /manager-screener/managers/{crd}/registered-funds | manager_screener.py | ManagerDetailPanel.svelte |
| 92 | POST | /manager-screener/managers/{crd}/add-to-universe | manager_screener.py | ManagerDetailPanel.svelte |
| 93 | POST | /model-portfolios | model_portfolios.py | model-portfolios/create/+page.svelte |
| 94 | GET | /model-portfolios | model_portfolios.py | model-portfolios/+page.server.ts, portfolios/[profile]/+page.server.ts, model-portfolios/create |
| 95 | GET | /model-portfolios/{portfolio_id} | model_portfolios.py | model-portfolios/[portfolioId]/+page.server.ts |
| 96 | POST | /model-portfolios/{portfolio_id}/construct | model_portfolios.py | model-portfolios/[portfolioId]/+page.svelte, create/+page.svelte, ConstructionAdvisor.svelte |
| 97 | GET | /model-portfolios/{portfolio_id}/track-record | model_portfolios.py | model-portfolios/[portfolioId]/+page.server.ts |
| 98 | POST | /model-portfolios/{portfolio_id}/backtest | model_portfolios.py | model-portfolios/[portfolioId]/+page.svelte |
| 99 | POST | /model-portfolios/{portfolio_id}/stress | model_portfolios.py | model-portfolios/[portfolioId]/+page.svelte |
| 100 | POST | /model-portfolios/{portfolio_id}/stress-test | model_portfolios.py | model-portfolios/[portfolioId]/+page.svelte |
| 101 | GET | /model-portfolios/{portfolio_id}/overlap | model_portfolios.py | model-portfolios/[portfolioId]/+page.server.ts, portfolios/[profile]/+page.server.ts |
| 102 | POST | /model-portfolios/{portfolio_id}/construction-advice | model_portfolios.py | ConstructionAdvisor.svelte |
| 103 | POST | /model-portfolios/{portfolio_id}/activate | model_portfolios.py | model-portfolios/[portfolioId]/+page.svelte, create/+page.svelte |
| 104 | GET | /portfolios | portfolios.py | portfolios/+page.server.ts, exposure/+page.server.ts |
| 105 | GET | /portfolios/{profile} | portfolios.py | portfolios/[profile]/+page.server.ts |
| 106 | GET | /portfolios/{profile}/snapshot | portfolios.py | dashboard/+page.server.ts, portfolios/[profile]/+page.server.ts |
| 107 | GET | /portfolios/{profile}/history | portfolios.py | portfolios/[profile]/+page.svelte |
| 108 | POST | /portfolios/{profile}/rebalance | portfolios.py | portfolios/[profile]/+page.svelte, RebalancingTab.svelte |
| 109 | GET | /portfolios/{profile}/rebalance | portfolios.py | RebalancingTab.svelte |
| 110 | GET | /portfolios/{profile}/rebalance/{event_id} | portfolios.py | RebalancingTab.svelte |
| 111 | POST | /portfolios/{profile}/rebalance/{event_id}/approve | portfolios.py | RebalancingTab.svelte |
| 112 | POST | /portfolios/{profile}/rebalance/{event_id}/execute | portfolios.py | RebalancingTab.svelte |
| 113 | POST | /model-portfolios/{portfolio_id}/views | portfolio_views.py | ICViewsPanel.svelte |
| 114 | GET | /model-portfolios/{portfolio_id}/views | portfolio_views.py | model-portfolios/[portfolioId]/+page.server.ts |
| 115 | DELETE | /model-portfolios/{portfolio_id}/views/{view_id} | portfolio_views.py | ICViewsPanel.svelte |
| 116 | GET | /risk/summary | risk.py | dashboard/+page.server.ts, risk/+page.server.ts, risk-store.svelte.ts |
| 117 | GET | /risk/{profile}/cvar | risk.py | risk-store.svelte.ts |
| 118 | GET | /risk/{profile}/cvar/history | risk.py | risk-store.svelte.ts |
| 119 | GET | /risk/regime | risk.py | dashboard/+page.server.ts, risk/+page.server.ts, risk-store.svelte.ts |
| 120 | GET | /risk/regime/history | risk.py | risk-store.svelte.ts |
| 121 | GET | /risk/macro | risk.py | risk-store.svelte.ts, macro/+page.server.ts |
| 122 | GET | /screener/results/{instrument_id} | screener.py | FundDetailPanel.svelte |
| 123 | GET | /screener/search | screener.py | InstrumentTable.svelte |
| 124 | POST | /screener/import/{identifier} | screener.py | screener/+page.svelte, CatalogDetailPanel, InstrumentDetailPanel, ConstructionAdvisor |
| 125 | POST | /screener/import-sec/{ticker} | screener.py | ManagerDetailPanel.svelte |
| 126 | GET | /screener/catalog | screener.py | screener/+page.server.ts |
| 127 | GET | /screener/catalog/facets | screener.py | screener/+page.server.ts |
| 128 | GET | /search | search.py | GlobalSearch.svelte |
| 129 | GET | /sec/managers/{cik} | sec_analysis.py | screener/+page.svelte |
| 130 | GET | /sec/holdings/reverse | sec_analysis.py | SecReverseLookup.svelte |
| 131 | GET | /sec/managers/compare | sec_analysis.py | SecPeerCompare.svelte |
| 132 | GET | /sec/managers/{crd_number}/funds | sec_analysis.py | screener/+page.svelte |
| 133 | GET | /sec/holdings/history | sec_analysis.py | SecReverseLookup.svelte |
| 134 | GET | /sec/funds/{cik} | sec_funds.py | screener/[cik]/+page.server.ts |
| 135 | GET | /sec/funds/{cik}/holdings | sec_funds.py | screener/[cik]/+page.server.ts, SecHoldingsTable.svelte |
| 136 | GET | /sec/funds/{cik}/holdings-history | sec_funds.py | screener/[cik]/+page.server.ts |
| 137 | GET | /sec/funds/{cik}/peer-analysis | sec_funds.py | screener/[cik]/+page.server.ts |
| 138 | GET | /sec/funds/{cik}/reverse-holdings | sec_funds.py | screener/[cik]/+page.server.ts |
| 139 | GET | /sec/funds/{cik}/prospectus | sec_funds.py | screener/[cik]/+page.server.ts, FundDetailsTab.svelte |
| 140 | GET | /universe | universe.py | universe/+page.server.ts, UniverseView.svelte, model-portfolios pages |
| 141 | GET | /universe/pending | universe.py | universe/+page.server.ts, UniverseView.svelte |
| 142 | POST | /universe/funds/{instrument_id}/approve | universe.py | universe/+page.svelte, UniverseView.svelte |
| 143 | POST | /universe/funds/{instrument_id}/reject | universe.py | UniverseView.svelte |
| 144 | GET | /universe/funds/{instrument_id}/audit-trail | universe.py | UniverseView.svelte |
| 145 | POST | /wealth/agent/chat | agent.py | AiAgentDrawer.svelte (SSE fetch) |
| 146 | PATCH | /model-portfolios/{portfolio_id} | model_portfolios.py | model-portfolios/create/+page.svelte |
| 147 | GET | /instruments/{instrument_id}/risk-metrics | instruments.py | ScoreBreakdownPopover.svelte |
| 148 | GET | /analytics/correlation-regime/{profile} | correlation_regime.py | analytics/+page.server.ts |
| 149 | GET | /analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b} | correlation_regime.py | CorrelationRegimePanel.svelte |
| 150 | GET | /analytics/active-share/{entity_id} | entity_analytics.py | analytics/[entityId]/+page.server.ts |
| 151 | GET | /manager-screener/ | manager_screener.py | screener/managers/+page.server.ts |
| 152 | POST | /manager-screener/managers/compare | manager_screener.py | screener/managers/+page.svelte |
| 153 | POST | /screener/run | screener.py | ScreeningRunPanel.svelte |
| 154 | GET | /screener/runs | screener.py | ScreeningRunPanel.svelte |
| 155 | GET | /screener/runs/{run_id} | screener.py | screener/runs/[runId]/+page.server.ts |
| 156 | GET | /screener/results | screener.py | ScreeningRunPanel.svelte |
| 157 | GET | /screener/facets | screener.py | ScreeningRunPanel.svelte |
| 158 | GET | /risk/stream | risk.py | risk-store.svelte.ts (via `createSSEStream`) |
| 159 | POST | /rebalancing/proposals/{proposal_id}/apply | rebalancing.py | RebalancingTab.svelte |
| 160 | GET | /screener/catalog/{external_id}/detail | screener.py | screener/+page.svelte (CatalogDetailPanel enrichment) |
| 161 | POST | /analytics/strategy-drift/scan | strategy_drift.py | analytics/+page.svelte |
| 162 | GET | /sec/managers/{crd}/private-funds | sec_funds.py | ManagerDetailPanel.svelte (Private Funds tab) |
| 163 | GET | /sec/funds/{cik}/style-history | sec_funds.py | screener/[cik]/+page.server.ts, +page.svelte (Style tab) |
| 164 | POST | /workers/run-sec-13f-ingestion | workers.py | settings/system/+page.svelte |
| 165 | POST | /workers/run-sec-adv-ingestion | workers.py | settings/system/+page.svelte |
| 166 | POST | /workers/run-nport-ingestion | workers.py | settings/system/+page.svelte |
| 167 | POST | /workers/run-esma-ingestion | workers.py | settings/system/+page.svelte |
| 168 | POST | /workers/run-regime-fit | workers.py | settings/system/+page.svelte |
| 169 | POST | /screener/import-esma/{isin} | screener.py | CatalogDetailPanel.svelte (UCITS funds via dedicated ESMA endpoint) |

---

## 2. DEFERRED (5 endpoints — maintained in backend, not wired)

Endpoints with potential value but covered by alternatives in frontend. Maintained for API consumers or future evolution.

| Method | Path | Backend File | Motivo |
|--------|------|-------------|--------|
| GET | /screener/securities | screener.py | Post-screening view — value when approval flow evolves |
| GET | /screener/securities/facets | screener.py | Accompanies securities above |
| GET | /analytics/backtest/{run_id} | analytics.py | Useful if backtest becomes async with history |
| POST | /analytics/optimize | analytics.py | Single-point for API consumers (frontend uses Pareto) |
| GET | /analytics/strategy-drift/{instrument_id} | strategy_drift.py | Frontend uses /history; may serve future webhook |

---

| Method | Path | Former Backend File | Motivo |
|--------|------|-------------------|--------|
| GET | /sec/managers/search | sec_analysis.py | Duplicated by `GET /manager-screener/` (connected) |
| GET | /sec/managers/{cik}/holdings | sec_analysis.py | Duplicated by `GET /manager-screener/managers/{crd}/holdings` |
| GET | /sec/managers/{cik}/style-drift | sec_analysis.py | Duplicated by `GET /manager-screener/managers/{crd}/drift` |
| GET | /sec/managers/sic-codes | sec_analysis.py | Static reference with no consumer |
| GET | /sec/managers/{crd}/registered-funds | sec_funds.py | Duplicated by `/manager-screener/managers/{crd}/registered-funds` |
| POST | /wealth/documents/upload | documents.py | Legacy — frontend uses pre-signed URL flow |
| GET | /funds/scoring | funds.py | Deprecated — replaced by /instruments + fund_risk_metrics |
| GET | /funds/{fund_id}/nav | funds.py | Deprecated — NAV via entity analytics |
| POST | /instruments/import/csv | instruments.py | Frontend uses Yahoo import or screener import |

---

## 4. INFRA (28 endpoints — excluded from coverage)

All endpoints in `workers.py` — worker trigger endpoints used by system settings page and cron jobs:

| Method | Path | File |
|--------|------|------|
| POST | /workers/run-ingestion | workers.py |
| POST | /workers/run-risk-calc | workers.py |
| POST | /workers/run-global-risk-metrics | workers.py |
| POST | /workers/run-portfolio-eval | workers.py |
| POST | /workers/run-macro-ingestion | workers.py |
| POST | /workers/run-fact-sheet-gen | workers.py |
| POST | /workers/run-watchlist-check | workers.py |
| POST | /workers/run-screening-batch | workers.py |
| POST | /workers/run-instrument-ingestion | workers.py |
| POST | /workers/run-benchmark-ingest | workers.py |
| POST | /workers/run-treasury-ingestion | workers.py |
| POST | /workers/run-ofr-ingestion | workers.py |
| POST | /workers/run-sec-refresh | workers.py |
| POST | /workers/run-nport-ingestion | workers.py |
| POST | /workers/run-bis-ingestion | workers.py |
| POST | /workers/run-imf-ingestion | workers.py |
| POST | /workers/run-brochure-download | workers.py |
| POST | /workers/run-brochure-extract | workers.py |
| POST | /workers/run-esma-ingestion | workers.py |
| POST | /workers/run-sec-13f-ingestion | workers.py |
| POST | /workers/run-sec-adv-ingestion | workers.py |
| POST | /workers/run-portfolio-nav-synthesizer | workers.py |
| POST | /workers/run-wealth-embedding | workers.py |
| POST | /workers/run-regime-fit | workers.py |
| POST | /workers/run-nport-fund-discovery | workers.py |
| POST | /workers/run-sec-bulk-ingestion | workers.py |
| POST | /workers/run-form345-ingestion | workers.py |
| POST | /workers/run-geography-enrichment | workers.py |

Note: 9 of these worker endpoints are already wired in the frontend settings/system page (instrument-ingestion, macro-ingestion, benchmark-ingest, risk-calc, portfolio-eval, screening-batch, watchlist-check, portfolio-nav-synthesizer, wealth-embedding).

**P3 — Candidates for settings page (5):** sec-13f-ingestion, sec-adv-ingestion, nport-ingestion, esma-ingestion, regime-fit. Useful for admin-triggered refresh before DD reports or screener runs.

---

## 5. Phantom Calls (frontend → backend inexistente)

Nenhum phantom call remanescente após sprint de wiring (Prompts A-E, 2026-04-01).

### Cross-domain calls (wealth frontend → admin backend)

These are NOT phantoms (the admin endpoints exist) but are cross-domain calls worth noting:

| Method | Path | Frontend File | Admin Route |
|--------|------|--------------|-------------|
| GET | /admin/configs/liquid_funds/{config_type} | investment-policy/+page.server.ts | configs.py |
| PUT | /admin/configs/defaults/liquid_funds/calibration | investment-policy/+page.svelte | configs.py |
| PUT | /admin/configs/defaults/liquid_funds/scoring | investment-policy/+page.svelte | configs.py |
| GET | /admin/health/services | settings/system/+page.server.ts | health.py |
| GET | /admin/health/workers | settings/system/+page.server.ts | health.py |
| GET | /admin/health/pipelines | settings/system/+page.server.ts | health.py |
| GET | /admin/configs/ | settings/config/+page.server.ts | configs.py |
| GET | /admin/configs/invalid | settings/config/+page.server.ts | configs.py |

---

## 6. Top 4 por valor de negócio (resolved in Sprint G)

| # | Method | Path | Wiring Complexity | Impacto |
|---|--------|------|-------------------|---------|
| 1 | POST | /rebalancing/proposals/{id}/apply | Medium (form + confirmation) | Entire advanced rebalancing workflow dead-ends |
| 2 | GET | /risk/stream | High (SSE + live dashboard) | Real-time risk monitoring without polling |
| 3 | GET | /screener/catalog/{external_id}/detail | Medium (detail panel) | Catalog drill-down unlocks pre-import fund analysis |
| 4 | GET | /sec/managers/{crd}/private-funds | Low (tab in manager panel) | Private fund visibility for PE/VC/HF managers |

---

## Coverage by Route File (post Sprint G)

| File | Total | Connected | Deferred | Coverage |
|------|-------|-----------|----------|----------|
| allocation.py | 6 | 6 | 0 | 100% |
| analytics.py | 9 | 8 | 1 | 89% |
| entity_analytics.py | 2 | 2 | 0 | 100% |
| attribution.py | 1 | 1 | 0 | 100% |
| correlation_regime.py | 2 | 2 | 0 | 100% |
| strategy_drift.py | 5 | 4 | 1 | 80% |
| blended_benchmark.py | 5 | 5 | 0 | 100% |
| content.py | 8 | 8 | 0 | 100% |
| dd_reports.py | 9 | 9 | 0 | 100% |
| documents.py | 6 | 6 | 0 | 100% |
| exposure.py | 2 | 2 | 0 | 100% |
| fact_sheets.py | 4 | 4 | 0 | 100% |
| funds.py | 3 | 3 | 0 | 100% |
| instruments.py | 6 | 6 | 0 | 100% |
| long_form_reports.py | 3 | 3 | 0 | 100% |
| monthly_report.py | 3 | 3 | 0 | 100% |
| macro.py | 12 | 12 | 0 | 100% |
| manager_screener.py | 13 | 13 | 0 | 100% |
| model_portfolios.py | 12 | 12 | 0 | 100% |
| portfolios.py | 9 | 9 | 0 | 100% |
| portfolio_views.py | 3 | 3 | 0 | 100% |
| rebalancing.py | 1 | 1 | 0 | 100% |
| risk.py | 7 | 7 | 0 | 100% |
| screener.py | 14 | 12 | 2 | 86% |
| search.py | 1 | 1 | 0 | 100% |
| sec_analysis.py | 5 | 5 | 0 | 100% |
| sec_funds.py | 8 | 8 | 0 | 100% |
| universe.py | 5 | 5 | 0 | 100% |
| agent.py | 1 | 1 | 0 | 100% |

**Files at 100% coverage (26/29):** agent, allocation, attribution, blended_benchmark, content, correlation_regime, dd_reports, documents, entity_analytics, exposure, fact_sheets, funds, instruments, long_form_reports, macro, manager_screener, model_portfolios, monthly_report, portfolios, portfolio_views, rebalancing, risk, search, sec_analysis, sec_funds, universe.

**Remaining deferred (3 files):** analytics (1 deferred), strategy_drift (1 deferred), screener (2 deferred).

---

## Notes

- All paths shown without `/api/v1` prefix (added by API client automatically).
- `funds.py` is deprecated — 3 endpoints still consumed by frontend (`GET /funds`, `GET /funds/{fund_id}`, `GET /funds/{fund_id}/risk`). Scoring and NAV endpoints deleted in Sprint G.
- Sprint G deleted 4 `sec_analysis.py` duplicate handlers (search, holdings, style-drift, sic-codes) — all duplicated by `manager_screener.py` routes. 5 remaining handlers are at 100%.
- `GET /risk/stream` connected via `createSSEStream` in `risk-store.svelte.ts` — pattern not detected by scanner regex `api.(get|post|...)`.
- Workers wired in settings page: 14/28 (9 original + 5 added in Sprint G).
- `POST /screener/import-esma/{isin}` is technically reachable via the generic `POST /screener/import/{identifier}` which handles ESMA ISINs. The dedicated ESMA route adds ESMA-specific enrichment. Deferred.
- Worker endpoints in settings/system page are correctly wired (9/28 workers exposed in UI for manual triggers).
- Updated 2026-04-01 after wiring sprint (Prompts A-E).
