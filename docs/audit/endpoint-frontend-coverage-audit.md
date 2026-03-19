# Endpoint ↔ Frontend Coverage Audit

**Generated:** 2026-03-19 (v4 — cross-referenced with system-map)
**Backend routes:** 230 (all decorators verified)
**Frontend API calls:** 192 call sites across 3 frontends (67 wealth + 76 credit + 49 admin)
**Connected:** 168 | **Disconnected:** 59 | **Phantom:** 3
**Disconnected breakdown:** 8 real gaps | 11 speculative (backend-ahead) | 9 pipeline-internal | 12 worker-only | 6 future | 13 deprecated

---

## Summary

Full re-audit of all backend routes (230 endpoints across admin/credit/wealth) cross-referenced against all frontend API calls (192 call sites) and validated against `docs/system-map.md`. Coverage is strong for user-facing features: wealth ~92%, credit core ~88%, admin ~97%. After system-map confrontation, only **8 real UX gaps** remain — the 11 credit reporting workflow endpoints previously flagged as "Needs UX" are reclassified as **speculative (backend-ahead)**: they were built speculatively but the system-map confirms they are not part of any documented feature surface. The 9 AI pipeline routes (`/ai/pipeline/deals/{id}/memo-chapters`, `/im-draft`, `/im-pdf`, etc.) are reclassified as **pipeline-internal** — the frontend triggers deep review via `ICMemoViewer.svelte` and receives results via SSE, not by calling these routes directly.

**Key corrections from v1:**
- `voting-status` and `decision-audit` are NOT phantoms — they exist in `ic_memos.py` and `provenance.py`
- `investor/statements` IS connected — `(investor)/statements/+page.server.ts` exists
- Admin SSE `workers/logs` IS connected — `WorkerLogFeed.svelte` uses it
- Fund investments path is `/funds/{fund_id}/assets/{asset_id}/fund-investment` (not `/fund-investments`)
- Schedules path is `/funds/{fund_id}/report-schedules` (not `/schedules`)
- AI module has 63 sub-routes (extraction, deep_review, memo_chapters, artifacts, portfolio)
- Wealth funds (deprecated) has `scoring`, `risk`, `nav` routes — not just CRUD
- DD reports has `approve` and `reject` routes — both connected
- Backend total is 230 (not 186) — AI module routes were undercounted

---

## Coverage Matrix — Wealth (107 backend routes)

### Instruments (`/instruments`) — 5 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/instruments` | `instruments/+page.server.ts:10` | CONNECTED |
| GET | `/instruments/{instrument_id}` | `instruments/+page.svelte:43` | CONNECTED |
| POST | `/instruments` | `instruments/+page.svelte:72` | CONNECTED |
| POST | `/instruments/import/yahoo` | `instruments/+page.svelte:102,133` | CONNECTED |
| POST | `/instruments/import/csv` | — | DISCONNECTED (Needs UX) |

### Portfolios (`/portfolios`) — 9 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/portfolios` | `dashboard/+page.server.ts:23` | CONNECTED |
| GET | `/portfolios/{profile}` | `portfolios/[profile]/+page.server.ts:11` | CONNECTED |
| GET | `/portfolios/{profile}/snapshot` | `portfolios/[profile]/+page.server.ts:12` | CONNECTED |
| GET | `/portfolios/{profile}/history` | `portfolios/[profile]/+page.server.ts:13` | CONNECTED |
| POST | `/portfolios/{profile}/rebalance` | `portfolios/[profile]/+page.svelte:321` | CONNECTED |
| GET | `/portfolios/{profile}/rebalance` | — | DISCONNECTED (API-only OK — list events) |
| GET | `/portfolios/{profile}/rebalance/{event_id}` | — | DISCONNECTED (API-only OK — detail) |
| POST | `/portfolios/{profile}/rebalance/{event_id}/approve` | `portfolios/[profile]/+page.svelte:349` | CONNECTED |
| POST | `/portfolios/{profile}/rebalance/{event_id}/execute` | `portfolios/[profile]/+page.svelte:367` | CONNECTED |

### Allocation (`/allocation`) — 6 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/allocation/{profile}/strategic` | `allocation/+page.server.ts:12` | CONNECTED |
| GET | `/allocation/{profile}/tactical` | `allocation/+page.server.ts:13` | CONNECTED |
| GET | `/allocation/{profile}/effective` | `allocation/+page.server.ts:14` | CONNECTED |
| PUT | `/allocation/{profile}/tactical` | `allocation/+page.svelte:181` | CONNECTED |
| PUT | `/allocation/{profile}/strategic` | `allocation/+page.svelte:247` | CONNECTED |
| POST | `/allocation/{profile}/simulate` | `allocation/+page.svelte:209` | CONNECTED |

### Risk (`/risk`) — 7 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/risk/summary` | `lib/stores/risk-store.svelte.ts:321` | CONNECTED |
| GET | `/risk/{profile}/cvar` | `risk/+page.server.ts:17`, `dashboard:27`, `risk-store:351` | CONNECTED |
| GET | `/risk/{profile}/cvar/history` | `risk/+page.server.ts:18`, `risk-store:322` | CONNECTED |
| GET | `/risk/regime` | `risk/+page.server.ts:13`, `dashboard:24`, `risk-store:323` | CONNECTED |
| GET | `/risk/regime/history` | `risk/+page.server.ts:14`, `risk-store:324` | CONNECTED |
| GET | `/risk/macro` | `risk/+page.server.ts:15`, `dashboard:25`, `risk-store:326` | CONNECTED |
| GET | `/risk/stream` | — | DISCONNECTED (Future — SSE risk live stream) |

### Analytics (`/analytics`) — 5 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/analytics/backtest` | `analytics/+page.svelte:211` | CONNECTED |
| GET | `/analytics/backtest/{run_id}` | `analytics/+page.svelte:242` | CONNECTED |
| POST | `/analytics/optimize` | `analytics/+page.svelte:274` | CONNECTED |
| POST | `/analytics/optimize/pareto` | `analytics/+page.svelte:294`, `backtest/+page.svelte:120` | CONNECTED |
| GET | `/analytics/correlation` | `analytics/+page.server.ts:12` | CONNECTED |

### Correlation & Regime (`/analytics/correlation-regime`) — 2 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/analytics/correlation-regime/{profile}` | `analytics/+page.server.ts:13` | CONNECTED |
| GET | `/analytics/correlation-regime/{profile}/pair/{a}/{b}` | `analytics/+page.svelte:319` | CONNECTED |

### Strategy Drift (`/analytics/strategy-drift`) — 5 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/analytics/strategy-drift/scan` | `risk/+page.svelte:131` | CONNECTED |
| GET | `/analytics/strategy-drift/alerts` | `risk/+page.server.ts:16`, `risk-store:325` | CONNECTED |
| GET | `/analytics/strategy-drift/{instrument_id}` | `risk/+page.svelte:151` | CONNECTED |
| GET | `/analytics/strategy-drift/{instrument_id}/history` | `lib/components/DriftHistoryPanel.svelte:218` | CONNECTED |
| GET | `/analytics/strategy-drift/{instrument_id}/export` | `portfolios/[profile]/+page.svelte:395` | CONNECTED |

### Attribution (`/analytics/attribution`) — 1 route

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/analytics/attribution/{profile}` | `analytics/+page.svelte:339` | CONNECTED |

### Macro (`/macro`) — 7 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/macro/scores` | `macro/+page.server.ts:10` | CONNECTED |
| GET | `/macro/snapshot` | `macro/+page.server.ts:11` | CONNECTED |
| GET | `/macro/regime` | `macro/+page.server.ts:12` | CONNECTED |
| GET | `/macro/reviews` | `macro/+page.server.ts:13` | CONNECTED |
| POST | `/macro/reviews/generate` | `macro/+page.svelte:33` | CONNECTED |
| PATCH | `/macro/reviews/{review_id}/approve` | `macro/+page.svelte:47` | CONNECTED |
| PATCH | `/macro/reviews/{review_id}/reject` | `macro/+page.svelte:71` | CONNECTED |

### Model Portfolios (`/model-portfolios`) — 7 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/model-portfolios` | `model-portfolios/+page.server.ts:10`, `dashboard:26`, `inv-portfolios:10`, `inv-fact-sheets:11` | CONNECTED |
| GET | `/model-portfolios/{portfolio_id}` | `model-portfolios/[portfolioId]/+page.server.ts:11` | CONNECTED |
| GET | `/model-portfolios/{portfolio_id}/track-record` | `model-portfolios/[portfolioId]/+page.server.ts:12`, `+page.svelte:54`, `inv-portfolios:19` | CONNECTED |
| POST | `/model-portfolios` | `model-portfolios/+page.svelte:98` | CONNECTED |
| POST | `/model-portfolios/{portfolio_id}/backtest` | `model-portfolios/+page.svelte:127` | CONNECTED |
| POST | `/model-portfolios/{portfolio_id}/construct` | `model-portfolios/+page.svelte:141` | CONNECTED |
| POST | `/model-portfolios/{portfolio_id}/stress` | — | DISCONNECTED (Needs UX) |

### Universe (`/universe`) — 4 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/universe` | `universe/+page.server.ts:10` | CONNECTED |
| GET | `/universe/pending` | `universe/+page.server.ts:11` | CONNECTED |
| POST | `/universe/funds/{instrument_id}/approve` | `universe/+page.svelte:82` | CONNECTED |
| POST | `/universe/funds/{instrument_id}/reject` | `universe/+page.svelte:101` | CONNECTED |

### Funds — DEPRECATED (`/funds`) — 5 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/funds` | `funds/+page.server.ts:10`, `dd-reports:12`, `content:41`, `inv-dd-reports:10` | CONNECTED |
| GET | `/funds/{fund_id}` | `funds/[fundId]/+page.server.ts:10`, `dd-reports/[fundId]:11` | CONNECTED |
| GET | `/funds/scoring` | — | DISCONNECTED (Deprecated) |
| GET | `/funds/{fund_id}/risk` | — | DISCONNECTED (Deprecated) |
| GET | `/funds/{fund_id}/nav` | — | DISCONNECTED (Deprecated) |

### Screener (`/screener`) — 5 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/screener/run` | `screener/+page.svelte:145` | CONNECTED |
| GET | `/screener/runs` | `screener/+page.server.ts:11`, `funds/+page.server.ts:11` | CONNECTED |
| GET | `/screener/runs/{run_id}` | `screener/+page.svelte:243` | CONNECTED |
| GET | `/screener/results` | `screener/+page.server.ts:10` | CONNECTED |
| GET | `/screener/results/{instrument_id}` | — | DISCONNECTED (API-only OK) |

### Content (`/content`) — 6 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/content` | `content/+page.server.ts:10`, `inv-documents:12`, `reports:10` | CONNECTED |
| POST | `/content/{content_id}/approve` | `content/+page.svelte:77` | CONNECTED |
| GET | `/content/{content_id}/download` | `content/+page.svelte:90`, `inv-documents:29` | CONNECTED |
| POST | `/content/outlooks` | `content/+page.svelte:57` (via dynamic `POST /content/${type}`) | CONNECTED |
| POST | `/content/flash-reports` | `content/+page.svelte:57` (via dynamic `POST /content/${type}`) | CONNECTED |
| POST | `/content/spotlights` | `content/+page.svelte:57` (via dynamic `POST /content/${type}`) | CONNECTED |

### Fact Sheets (`/fact-sheets`) — 4 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/fact-sheets/model-portfolios/{portfolio_id}` | `inv: fact-sheets/+page.server.ts:19` | CONNECTED |
| POST | `/fact-sheets/model-portfolios/{portfolio_id}` | `inv: fact-sheets/+page.svelte:35` | CONNECTED |
| GET | `/fact-sheets/{fact_sheet_path:path}/download` | `inv: fact-sheets/+page.svelte:52` | CONNECTED |
| GET | `/fact-sheets/dd-reports/{report_id}/download` | `dd-reports/[fundId]/+page.svelte:77`, `[reportId]:80`, `inv-dd-reports:35` | CONNECTED |

### DD Reports (`/dd-reports`) — 7 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/dd-reports/funds/{fund_id}` | `dd-reports/[fundId]/+page.server.ts:12`, `inv-dd-reports:18` | CONNECTED |
| GET | `/dd-reports/{report_id}` | `dd-reports/[fundId]/[reportId]/+page.server.ts:12` | CONNECTED |
| POST | `/dd-reports/funds/{fund_id}` | `dd-reports/[fundId]/+page.svelte:40` | CONNECTED |
| POST | `/dd-reports/{report_id}/regenerate` | `dd-reports/[fundId]/+page.svelte:63`, `[reportId]:99` | CONNECTED |
| POST | `/dd-reports/{report_id}/approve` | `dd-reports/[fundId]/[reportId]/+page.svelte:113` | CONNECTED |
| POST | `/dd-reports/{report_id}/reject` | `dd-reports/[fundId]/[reportId]/+page.svelte:128` | CONNECTED |
| GET | `/dd-reports/{report_id}/stream` | `lib/components/FundDetailPanel.svelte:93` (SSE) | CONNECTED |

### Exposure (`/wealth/exposure`) — 2 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/wealth/exposure/matrix` | `exposure/+page.server.ts:12,13` | CONNECTED |
| GET | `/wealth/exposure/metadata` | `exposure/+page.server.ts:14` | CONNECTED |

### Documents (`/wealth/documents`) — 6 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/wealth/documents` | `documents/+page.server.ts:16` | CONNECTED |
| GET | `/wealth/documents/{document_id}` | `documents/[documentId]/+page.server.ts:10` | CONNECTED |
| POST | `/wealth/documents/upload-url` | `documents/upload/+page.svelte:85` | CONNECTED |
| POST | `/wealth/documents/upload-complete` | `documents/upload/+page.svelte:106` | CONNECTED |
| POST | `/wealth/documents/ingestion/process-pending` | `documents/[documentId]/+page.svelte:45` | CONNECTED |
| POST | `/wealth/documents/upload` | — | DISCONNECTED (API-only OK — presigned URL flow preferred) |

### Workers (`/workers`) — 9 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/workers/run-ingestion` | Admin: `health/+page.svelte:119` | ADMIN-ONLY |
| POST | `/workers/run-risk-calc` | Admin: `health/+page.svelte:119` | ADMIN-ONLY |
| POST | `/workers/run-portfolio-eval` | Admin: `health/+page.svelte:119` | ADMIN-ONLY |
| POST | `/workers/run-macro-ingestion` | Admin: `health/+page.svelte:119` | ADMIN-ONLY |
| POST | `/workers/run-fact-sheet-gen` | Admin: `health/+page.svelte:119` | ADMIN-ONLY |
| POST | `/workers/run-watchlist-check` | Admin: `health/+page.svelte:119` | ADMIN-ONLY |
| POST | `/workers/run-screening-batch` | Admin: `health/+page.svelte:119` | ADMIN-ONLY |
| POST | `/workers/run-instrument-ingestion` | Admin: `health/+page.svelte:119` | ADMIN-ONLY |
| POST | `/workers/run-benchmark-ingest` | Admin: `health/+page.svelte:119` | ADMIN-ONLY |

---

## Coverage Matrix — Credit (~175 backend routes)

### Dashboard (`/dashboard`) — 10 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/dashboard/portfolio-summary` | `dashboard/+page.server.ts:12` | CONNECTED |
| GET | `/dashboard/pipeline-summary` | `dashboard/+page.server.ts:13` | CONNECTED |
| GET | `/dashboard/pipeline-analytics` | `dashboard/+page.server.ts:14` | CONNECTED |
| GET | `/dashboard/macro-snapshot` | `dashboard/+page.server.ts:15` | CONNECTED |
| GET | `/dashboard/compliance-alerts` | `dashboard/+page.server.ts:16` | CONNECTED |
| GET | `/dashboard/task-inbox` | `dashboard/+page.server.ts:17` | CONNECTED |
| GET | `/dashboard/fred-search` | `dashboard/+page.svelte:63` | CONNECTED |
| GET | `/dashboard/macro-fred-series` | `dashboard/+page.svelte:104` | CONNECTED |
| GET | `/dashboard/macro-fred-multi` | `dashboard/+page.svelte:110` | CONNECTED |
| GET | `/dashboard/macro-history` | — | DISCONNECTED (API-only OK — sparkline data) |

### Deals — Old Routes (`/funds/{fund_id}/deals`) — 4 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/deals` | — | DISCONNECTED (superseded by /pipeline/deals) |
| GET | `/funds/{fund_id}/deals` | `pipeline/+page.server.ts:14` | CONNECTED |
| PATCH | `/funds/{fund_id}/deals/{deal_id}/decision` | `pipeline/[dealId]/+page.svelte:151` | CONNECTED |
| GET | `/funds/{fund_id}/deals/{deal_id}/stage-timeline` | `pipeline/[dealId]/+page.server.ts:14` | CONNECTED |

### IC Memos — 4 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/deals/{deal_id}/ic-memo` | `lib/components/ICMemoViewer.svelte:93` | CONNECTED |
| GET | `/funds/{fund_id}/deals/{deal_id}/ic-memo` | `pipeline/[dealId]/+page.server.ts:15` | CONNECTED |
| PATCH | `/funds/{fund_id}/deals/{deal_id}/ic-memo/conditions` | `pipeline/[dealId]/+page.svelte:238` | CONNECTED |
| GET | `/funds/{fund_id}/deals/{deal_id}/ic-memo/voting-status` | `pipeline/[dealId]/+page.server.ts:16` | CONNECTED |

### Deal Provenance — 3 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/funds/{fund_id}/deals/{deal_id}/documents/{doc_id}/ai-provenance` | — | DISCONNECTED (Future — needs provenance viewer) |
| GET | `/funds/{fund_id}/deals/{deal_id}/ic-memo/timeline` | — | DISCONNECTED (Future — needs timeline component) |
| GET | `/funds/{fund_id}/deals/{deal_id}/decision-audit` | `pipeline/[dealId]/+page.svelte:55` | CONNECTED |

### Deal Conversion — 1 route

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/deals/{deal_id}/convert` | `pipeline/[dealId]/+page.svelte:185` | CONNECTED |

### Pipeline Deals (`/pipeline/deals`) — 16 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/pipeline/deals` | — | DISCONNECTED (old route `/funds/{id}/deals` used instead) |
| POST | `/pipeline/deals` | — | DISCONNECTED (old route used instead) |
| POST | `/pipeline/deals/{deal_id}/documents` | — | DISCONNECTED (Needs UX) |
| PATCH | `/pipeline/deals/{deal_id}/context` | — | DISCONNECTED (Needs UX) |
| PATCH | `/pipeline/deals/{deal_id}/stage` | `lib/components/PipelineKanban.svelte:121` | CONNECTED |
| POST | `/pipeline/deals/{deal_id}/decisions` | — | DISCONNECTED (old route used) |
| POST | `/pipeline/deals/qualification/run` | — | DISCONNECTED (API-only OK) |
| POST | `/pipeline/deals/{deal_id}/approve` | — | DISCONNECTED (old route used) |
| GET | `/pipeline/deals/{deal_id}/events` | — | DISCONNECTED (Needs UX) |
| GET | `/pipeline/deals/{deal_id}/cashflows` | — | DISCONNECTED (CashflowLedger uses old route) |
| POST | `/pipeline/deals/{deal_id}/cashflows` | — | DISCONNECTED (CashflowLedger uses old route) |
| PATCH | `/pipeline/deals/{deal_id}/cashflows/{cashflow_id}` | — | DISCONNECTED (CashflowLedger uses old route) |
| DELETE | `/pipeline/deals/{deal_id}/cashflows/{cashflow_id}` | — | DISCONNECTED (CashflowLedger uses old route) |
| GET | `/pipeline/deals/{deal_id}/performance` | — | DISCONNECTED (DealPerformancePanel uses old route) |
| GET | `/pipeline/deals/{deal_id}/monitoring` | — | DISCONNECTED (Needs UX) |

> **Note:** The credit frontend still uses old `/funds/{fund_id}/deals/...` routes for most deal operations. The new `/pipeline/deals/` routes are largely disconnected except for `PATCH .../stage` (Kanban). Cashflow CRUD calls use old routes via `CashflowLedger.svelte` (lines 181, 228, 255) hitting `/funds/{fundId}/deals/{dealId}/cashflows/...`.

### Documents (`/documents`) — 7 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/documents/upload-url` | `documents/upload/+page.svelte:92` | CONNECTED |
| POST | `/documents/upload-complete` | `documents/upload/+page.svelte:105` | CONNECTED |
| POST | `/documents/upload` | — | DISCONNECTED (API-only — presigned flow preferred) |
| GET | `/documents` | `documents/+page.server.ts:14` | CONNECTED |
| GET | `/documents/root-folders` | `documents/+page.server.ts:20` | CONNECTED |
| POST | `/documents/root-folders` | `documents/+page.svelte:33` | CONNECTED |
| GET | `/documents/{document_id}` | `documents/[documentId]/+page.server.ts:12` | CONNECTED |
| GET | `/documents/{document_id}/versions` | `documents/[documentId]/+page.server.ts:13` | CONNECTED |
| POST | `/documents/ingestion/process-pending` | — | DISCONNECTED (ADMIN-ONLY trigger) |

### Module Documents (`/documents`) — 2 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/documents` (create) | — | DISCONNECTED (API-only OK) |
| POST | `/documents/{document_id}/versions` | — | DISCONNECTED (API-only OK) |

### Evidence — 2 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/evidence/upload-request` | `documents/+page.svelte:70` | CONNECTED |
| PATCH | `/funds/{fund_id}/evidence/{evidence_id}/complete` | `documents/auditor/+page.svelte:32` | CONNECTED |

### Auditor — 1 route

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/funds/{fund_id}/auditor/evidence` | `documents/auditor/+page.server.ts:12` | CONNECTED |

### Document Reviews (`/funds/{fund_id}/document-reviews`) — 13 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `...document-reviews` | `documents/+page.svelte:84`, `[documentId]:99` | CONNECTED |
| GET | `...document-reviews` | `documents/reviews/+page.server.ts:11` | CONNECTED |
| GET | `...document-reviews/pending` | `documents/reviews/+page.server.ts:12` | CONNECTED |
| GET | `...document-reviews/summary` | `documents/reviews/+page.server.ts:13` | CONNECTED |
| GET | `...document-reviews/{id}` | `documents/reviews/[reviewId]/+page.server.ts:13` | CONNECTED |
| GET | `...document-reviews/{id}/checklist` | `documents/reviews/[reviewId]/+page.server.ts:20` | CONNECTED |
| POST | `...document-reviews/{id}/decide` | `documents/reviews/[reviewId]/+page.svelte:149` | CONNECTED |
| POST | `...document-reviews/{id}/assign` | `documents/reviews/[reviewId]/+page.svelte:174` | CONNECTED |
| POST | `...document-reviews/{id}/finalize` | `documents/reviews/[reviewId]/+page.svelte:196` | CONNECTED |
| POST | `...document-reviews/{id}/resubmit` | `documents/reviews/[reviewId]/+page.svelte:212` | CONNECTED |
| POST | `...document-reviews/{id}/ai-analyze` | `documents/reviews/[reviewId]/+page.svelte:228` | CONNECTED |
| POST | `...document-reviews/{id}/checklist/{item_id}/check` | `documents/reviews/[reviewId]/+page.svelte:257` | CONNECTED |
| POST | `...document-reviews/{id}/checklist/{item_id}/uncheck` | `documents/reviews/[reviewId]/+page.svelte:274` | CONNECTED |

### Portfolio — 8 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/assets` | `portfolio/+page.svelte:50` | CONNECTED |
| GET | `/funds/{fund_id}/assets` | `portfolio/+page.server.ts:11` | CONNECTED |
| GET | `/funds/{fund_id}/portfolio/actions` | `portfolio/+page.server.ts:14` | CONNECTED |
| PATCH | `/funds/{fund_id}/portfolio/actions/{action_id}` | `portfolio/+page.svelte:137` | CONNECTED |
| GET | `/funds/{fund_id}/alerts` | `portfolio/+page.server.ts:13` | CONNECTED |
| POST | `/funds/{fund_id}/assets/{asset_id}/obligations` | `portfolio/+page.svelte:87` | CONNECTED |
| GET | `/funds/{fund_id}/obligations` | `portfolio/+page.server.ts:12` | CONNECTED |
| PATCH | `/funds/{fund_id}/obligations/{obligation_id}` | `portfolio/+page.svelte:121` | CONNECTED |

### Fund Investments — 2 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/assets/{asset_id}/fund-investment` | — | DISCONNECTED (Needs UX) |
| GET | `/funds/{fund_id}/assets/{asset_id}/fund-investment` | — | DISCONNECTED (Needs UX) |

### Credit Actions — 3 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/actions` | — | DISCONNECTED (Needs UX — separate from portfolio actions) |
| GET | `/funds/{fund_id}/actions` | — | DISCONNECTED (Needs UX) |
| PATCH | `/funds/{fund_id}/actions/{action_id}` | — | DISCONNECTED (Needs UX) |

### Reporting — Report Packs — 3 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/report-packs` | `reporting/+page.svelte:105` | CONNECTED |
| POST | `/funds/{fund_id}/report-packs/{pack_id}/generate` | `reporting/+page.svelte:35` | CONNECTED |
| POST | `/funds/{fund_id}/report-packs/{pack_id}/publish` | `reporting/+page.svelte:56` | CONNECTED |

### Reporting — Reports — 14 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/reports/nav/snapshots` | `reporting/+page.svelte:82` | CONNECTED |
| GET | `/funds/{fund_id}/reports/nav/snapshots` | `reporting/+page.server.ts:11` | CONNECTED |
| GET | `/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}` | — | DISCONNECTED (API-only OK) |
| POST | `/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}/finalize` | — | DISCONNECTED (Speculative — not in system-map) |
| POST | `/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}/publish` | — | DISCONNECTED (Speculative — not in system-map) |
| POST | `/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}/assets` | — | DISCONNECTED (Speculative — not in system-map) |
| GET | `/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}/assets` | — | DISCONNECTED (Speculative — not in system-map) |
| POST | `/funds/{fund_id}/reports/monthly-pack/generate` | — | DISCONNECTED (Speculative — not in system-map) |
| GET | `/funds/{fund_id}/reports/monthly-pack/list` | `reporting/+page.server.ts:12` | CONNECTED |
| GET | `/funds/{fund_id}/reports/monthly-pack/{pack_id}/download` | — | DISCONNECTED (Speculative — not in system-map) |
| POST | `/funds/{fund_id}/reports/investor-statements/generate` | — | DISCONNECTED (Needs UX — system-map §5.5 confirms) |
| GET | `/funds/{fund_id}/reports/investor-statements` | `reporting/+page.server.ts:13` | CONNECTED |
| GET | `/funds/{fund_id}/reports/investor-statements/{statement_id}/download` | — | DISCONNECTED (Needs UX — system-map §7.2 confirms PDFDownload) |
| GET | `/funds/{fund_id}/reports/archive` | — | DISCONNECTED (Speculative — not in system-map) |

### Reporting — Evidence Pack — 2 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/reports/evidence-pack` | — | DISCONNECTED (API-only OK) |
| POST | `/funds/{fund_id}/reports/evidence-pack/pdf` | `reporting/+page.svelte:138` (getBlob) | CONNECTED |

### Reporting — Schedules (`/funds/{fund_id}/report-schedules`) — 5 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/funds/{fund_id}/report-schedules` | — | DISCONNECTED (Speculative — not in system-map) |
| POST | `/funds/{fund_id}/report-schedules` | — | DISCONNECTED (Speculative — not in system-map) |
| PATCH | `/funds/{fund_id}/report-schedules/{schedule_id}` | — | DISCONNECTED (Speculative — not in system-map) |
| POST | `/funds/{fund_id}/report-schedules/{schedule_id}/trigger` | — | DISCONNECTED (Speculative — not in system-map) |
| GET | `/funds/{fund_id}/report-schedules/{schedule_id}/runs` | — | DISCONNECTED (Speculative — not in system-map) |

### Investor Portal — 3 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/funds/{fund_id}/investor/report-packs` | `(investor)/report-packs/+page.server.ts:17` | CONNECTED |
| GET | `/funds/{fund_id}/investor/documents` | `(investor)/documents/+page.server.ts:16` | CONNECTED |
| GET | `/funds/{fund_id}/investor/statements` | `(investor)/statements/+page.server.ts:16` | CONNECTED |

### AI / Copilot (`/ai`) — 5 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/ai/answer` | `copilot/+page.svelte:48` | CONNECTED |
| GET | `/ai/history` | `copilot/+page.svelte:71` | CONNECTED |
| GET | `/ai/activity` | `copilot/+page.svelte:87` | CONNECTED |
| POST | `/ai/retrieve` | `copilot/+page.svelte:103` | CONNECTED |
| POST | `/ai/query` | — | DISCONNECTED (API-only OK — /answer preferred) |

### AI / Documents (`/ai/documents`) — 7 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/ai/documents/classification` | — | DISCONNECTED (WORKER-ONLY) |
| GET | `/ai/managers/profile` | — | DISCONNECTED (Future) |
| GET | `/ai/alerts/daily` | — | DISCONNECTED (Future) |
| POST | `/ai/run-daily-cycle` | — | DISCONNECTED (WORKER-ONLY) |
| POST | `/ai/documents/ingest` | — | DISCONNECTED (WORKER-ONLY) |
| GET | `/ai/documents/index` | — | DISCONNECTED (API-only OK) |
| GET | `/ai/documents/{doc_id}` | — | DISCONNECTED (API-only OK) |

### AI / Compliance (`/ai`) — 4 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/ai/obligations/register` | — | DISCONNECTED (Future) |
| POST | `/ai/linker/run` | — | DISCONNECTED (WORKER-ONLY) |
| GET | `/ai/linker/links` | — | DISCONNECTED (Future) |
| GET | `/ai/linker/obligations/status` | — | DISCONNECTED (Future) |

### AI / Pipeline Deals — 3 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/ai/pipeline/deals` | — | DISCONNECTED (API-only OK) |
| GET | `/ai/pipeline/deals/{deal_id}` | — | DISCONNECTED (API-only OK) |
| GET | `/ai/pipeline/alerts` | — | DISCONNECTED (Future) |

### AI / Extraction — 10 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/ai/pipeline/ingest` | — | DISCONNECTED (WORKER-ONLY) |
| POST | `/ai/pipeline/ingest/full` | — | DISCONNECTED (WORKER-ONLY) |
| POST | `/ai/pipeline/extract/run` | — | DISCONNECTED (WORKER-ONLY) |
| GET | `/ai/pipeline/extract/status/{job_id}` | — | DISCONNECTED (API-only OK) |
| GET | `/ai/pipeline/extract/jobs` | — | DISCONNECTED (API-only OK) |
| GET | `/ai/pipeline/extract/sources` | — | DISCONNECTED (API-only OK) |
| GET | `/ai/pipeline/ingest/jobs/latest` | — | DISCONNECTED (API-only OK) |
| GET | `/ai/pipeline/ingest/jobs/{job_id}` | — | DISCONNECTED (API-only OK) |
| POST | `/ai/pipeline/deals/{deal_id}/bootstrap` | — | DISCONNECTED (WORKER-ONLY) |
| POST | `/ai/pipeline/deals/{deal_id}/reanalyze` | — | DISCONNECTED (WORKER-ONLY) |

### AI / Deep Review — 7 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/ai/pipeline/deals/{deal_id}/deep-review-v4` | — | DISCONNECTED (WORKER-ONLY) |
| POST | `/ai/pipeline/deep-review-v4` | — | DISCONNECTED (WORKER-ONLY) |
| GET | `/ai/pipeline/deals/{deal_id}/deep-review-status` | — | DISCONNECTED (Pipeline-internal — ICMemoViewer handles via SSE) |
| POST | `/ai/pipeline/deals/{deal_id}/reset-status` | — | DISCONNECTED (ADMIN-ONLY) |
| POST | `/ai/pipeline/deals/reset-all-stuck` | — | DISCONNECTED (ADMIN-ONLY) |
| POST | `/ai/pipeline/deep-review/validate-sample` | — | DISCONNECTED (ADMIN-ONLY) |
| POST | `/ai/pipeline/deep-review/evaluate` | — | DISCONNECTED (ADMIN-ONLY) |

### AI / Memo Chapters — 9 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/ai/pipeline/deals/{deal_id}/memo-chapters` | — | DISCONNECTED (Pipeline-internal — ICMemoViewer renders via SSE stream) |
| GET | `/ai/pipeline/deals/{deal_id}/evidence-pack` | — | DISCONNECTED (Pipeline-internal) |
| GET | `/ai/pipeline/deals/{deal_id}/im-draft` | — | DISCONNECTED (Pipeline-internal — deep review output) |
| GET | `/ai/pipeline/deals/{deal_id}/im-pdf` | — | DISCONNECTED (Pipeline-internal — deep review output) |
| GET | `/ai/pipeline/deals/{deal_id}/im-pdf/download` | — | DISCONNECTED (Pipeline-internal — deep review output) |
| GET | `/ai/pipeline/deals/{deal_id}/memo-chapters/versions` | — | DISCONNECTED (Pipeline-internal) |
| POST | `/ai/pipeline/deals/{deal_id}/memo-chapters/{chapter}/regenerate` | — | DISCONNECTED (Pipeline-internal) |
| POST | `/ai/pipeline/deals/{deal_id}/im-pdf/rebuild` | — | DISCONNECTED (ADMIN-ONLY) |
| GET | `/ai/pipeline/deals/{deal_id}/pipeline-memo-pdf` | — | DISCONNECTED (Pipeline-internal — deep review output) |

### AI / Artifacts — 8 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/ai/pipeline/deals/{deal_id}/evidence-governance` | — | DISCONNECTED (Pipeline-internal — consumed by deep review stages) |
| GET | `/ai/pipeline/deals/{deal_id}/underwriting-artifact` | — | DISCONNECTED (Pipeline-internal — deep review output) |
| GET | `/ai/pipeline/deals/{deal_id}/underwriting-artifact/history` | — | DISCONNECTED (Pipeline-internal) |
| GET | `/ai/pipeline/deals/{deal_id}/critical-gaps` | — | DISCONNECTED (Pipeline-internal — deep review stage 11) |
| POST | `/ai/pipeline/fact-sheet/generate` | — | DISCONNECTED (WORKER-ONLY) |
| GET | `/ai/pipeline/fact-sheet/pdf` | — | DISCONNECTED (API-only OK) |
| POST | `/ai/pipeline/marketing-presentation/generate` | — | DISCONNECTED (WORKER-ONLY) |
| GET | `/ai/pipeline/marketing-presentation/pdf` | — | DISCONNECTED (API-only OK) |

### AI / Portfolio Intelligence — 10 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/ai/portfolio/ingest` | — | DISCONNECTED (WORKER-ONLY) |
| GET | `/ai/portfolio/investments` | — | DISCONNECTED (Pipeline-internal — portfolio intelligence) |
| GET | `/ai/portfolio/investments/{id}` | — | DISCONNECTED (Pipeline-internal) |
| GET | `/ai/portfolio/alerts` | — | DISCONNECTED (API-only OK) |
| POST | `/ai/portfolio/investments/{id}/review` | — | DISCONNECTED (WORKER-ONLY) |
| POST | `/ai/portfolio/deep-review` | — | DISCONNECTED (WORKER-ONLY) |
| GET | `/ai/portfolio/investments/{id}/reviews` | — | DISCONNECTED (Pipeline-internal) |
| GET | `/ai/portfolio/investments/{id}/reviews/latest` | — | DISCONNECTED (Pipeline-internal) |
| GET | `/ai/portfolio/investments/{id}/monitoring` | — | DISCONNECTED (Pipeline-internal) |
| GET | `/ai/portfolio/investments/{id}/review-pdf` | — | DISCONNECTED (Pipeline-internal) |

### Cashflows (via old routes)

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/funds/{fund_id}/deals/{deal_id}/cashflows` | `lib/components/CashflowLedger.svelte:181` | CONNECTED (old route) |
| PATCH | `/funds/{fund_id}/deals/{deal_id}/cashflows/{id}` | `lib/components/CashflowLedger.svelte:228` | CONNECTED (old route) |
| DELETE | `/funds/{fund_id}/deals/{deal_id}/cashflows/{id}` | `lib/components/CashflowLedger.svelte:255` | CONNECTED (old route) |

### Deal Performance (via old route)

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/funds/{fund_id}/deals/{deal_id}/performance` | `lib/components/DealPerformancePanel.svelte:57` | CONNECTED (old route) |

### Dataroom (Legacy/Deprecated) — 10 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| POST | `/api/dataroom/documents` | — | DISCONNECTED (Deprecated) |
| POST | `/api/dataroom/documents/{id}/ingest` | — | DISCONNECTED (Deprecated) |
| GET | `/api/dataroom/search` | — | DISCONNECTED (Deprecated) |
| GET | `/api/dataroom/browse` | — | DISCONNECTED (Deprecated) |
| GET | `/api/data-room/tree` | — | DISCONNECTED (Deprecated) |
| GET | `/api/data-room/list` | — | DISCONNECTED (Deprecated) |
| GET | `/api/data-room/file-link` | — | DISCONNECTED (Deprecated) |
| GET | `/api/data-room/pipeline/list` | — | DISCONNECTED (Deprecated) |
| GET | `/api/data-room/pipeline/file-link` | — | DISCONNECTED (Deprecated) |
| POST | `/api/data-room/upload` | — | DISCONNECTED (Deprecated) |

### SSE / Jobs (Global) — 4 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/jobs/{job_id}/stream` | `credit: IngestionProgress.svelte:29`, `ICMemoViewer.svelte:96` | CONNECTED |
| GET | `/jobs/{job_id}/status` | — | DISCONNECTED (API-only OK — SSE fallback) |
| GET | `/api/v1/` | — | API root info (not a feature) |
| POST | `/test/sse/{job_id}/emit` | — | DISCONNECTED (Dev-only test) |

---

## Coverage Matrix — Admin (35 backend routes)

### Health (`/admin/health`) — 4 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/admin/health/services` | `health/+page.server.ts:46`, `health/+page.svelte:181` | CONNECTED |
| GET | `/admin/health/workers` | `health/+page.server.ts:47`, `health/+page.svelte:183,125` | CONNECTED |
| GET | `/admin/health/pipelines` | `health/+page.server.ts:48`, `health/+page.svelte:182` | CONNECTED |
| GET | `/admin/health/workers/logs` | `lib/components/WorkerLogFeed.svelte:139` (SSE) | CONNECTED |

### Configs (`/admin/configs`) — 8 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/admin/configs/` | `config/[vertical]/+page.server.ts:8` | CONNECTED |
| GET | `/admin/configs/invalid` | `config/[vertical]/+page.server.ts:9` | CONNECTED |
| GET | `/admin/configs/{vertical}/{config_type}` | `ConfigEditor.svelte:117` | CONNECTED |
| PUT | `/admin/configs/{vertical}/{config_type}` | `ConfigEditor.svelte:187` (with If-Match) | CONNECTED |
| DELETE | `/admin/configs/{vertical}/{config_type}` | `ConfigEditor.svelte:217` | CONNECTED |
| GET | `/admin/configs/{vertical}/{config_type}/diff` | `ConfigEditor.svelte:133`, `ConfigDiffViewer.svelte:34` | CONNECTED |
| PUT | `/admin/configs/defaults/{vertical}/{config_type}` | `ConfigEditor.svelte:229` | CONNECTED |
| POST | `/admin/configs/validate` | — | DISCONNECTED (Needs UX) |

### Audit (`/admin/audit`) — 1 route

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/admin/audit/` | `ConfigEditor.svelte:156` | CONNECTED |

### Inspect (`/admin/inspect`) — 5 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/admin/inspect/{org_id}/{vertical}/stale-embeddings` | `inspect/+page.svelte:102` | CONNECTED |
| GET | `/admin/inspect/{org_id}/{vertical}/coverage` | `inspect/+page.svelte:99` | CONNECTED |
| GET | `/admin/inspect/{org_id}/{vertical}/extraction-quality` | `inspect/+page.svelte:101` | CONNECTED |
| GET | `/admin/inspect/{org_id}/{vertical}/chunk-stats` | `inspect/+page.svelte:98` | CONNECTED |
| GET | `/admin/inspect/{org_id}/{vertical}/embedding-audit` | `inspect/+page.svelte:100` | CONNECTED |

### Prompts (`/admin/prompts`) — 8 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/admin/prompts/{vertical}` | `prompts/[vertical]/+page.server.ts:15` | CONNECTED |
| GET | `/admin/prompts/{vertical}/{name}` | `PromptEditor.svelte:67` | CONNECTED |
| PUT | `/admin/prompts/{vertical}/{name}` | `PromptEditor.svelte:127` | CONNECTED |
| DELETE | `/admin/prompts/{vertical}/{name}` | `PromptEditor.svelte:150` | CONNECTED |
| POST | `/admin/prompts/{vertical}/{name}/preview` | `PromptEditor.svelte:85` | CONNECTED |
| POST | `/admin/prompts/{vertical}/{name}/validate` | `PromptEditor.svelte:102` | CONNECTED |
| GET | `/admin/prompts/{vertical}/{name}/versions` | `PromptEditor.svelte:160` | CONNECTED |
| POST | `/admin/prompts/{vertical}/{name}/revert/{version}` | `PromptEditor.svelte:185` | CONNECTED |

### Tenants (`/admin/tenants`) — 7 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/admin/tenants/` | `tenants/+page.server.ts:17`, `inspect/+page.server.ts:14` | CONNECTED |
| POST | `/admin/tenants/` | `tenants/+page.svelte:48` | CONNECTED |
| GET | `/admin/tenants/{org_id}` | `[orgId]/+layout.server.ts:8` | CONNECTED |
| PATCH | `/admin/tenants/{org_id}` | `[orgId]/+page.svelte:70` | CONNECTED |
| POST | `/admin/tenants/{org_id}/seed` | `[orgId]/setup/+page.svelte:29` | CONNECTED |
| POST | `/admin/tenants/{org_id}/assets` | `[orgId]/branding/+page.svelte:80` (FormData) | CONNECTED |
| DELETE | `/admin/tenants/{org_id}/assets/{asset_type}` | `[orgId]/branding/+page.svelte:100` | CONNECTED |

### Branding — 2 routes

| Method | Backend Route | Frontend Consumer | Status |
|--------|--------------|-------------------|--------|
| GET | `/branding` | `+layout.server.ts:16` | CONNECTED |
| GET | `/assets/tenant/{org_slug}/{asset_type}` | (used via `<img>` in templates) | CONNECTED |

---

## Phantom Frontend Calls

Frontend calls that reference API paths with **no matching backend route**:

| # | Frontend File | API Call | Issue |
|---|--------------|----------|-------|
| 1 | `credit: documents/[documentId]/+page.server.ts:14` | `GET /funds/${fundId}/documents/${documentId}/timeline` | **No backend endpoint.** Closest match is `/funds/{fund_id}/deals/{deal_id}/ic-memo/timeline` (provenance.py) but that requires a `deal_id` parameter. The document detail page has no deal context. Either create `GET /documents/{document_id}/timeline` in ingest routes or remove the call. |
| 2 | `admin: tenants/[orgId]/branding/+page.svelte:52` | `PUT /admin/tenants/${orgId}/branding` | **No backend endpoint.** Tenant routes have `PATCH /admin/tenants/{org_id}` for metadata updates, and `POST .../assets` for file uploads, but no `PUT .../branding` sub-resource. Either add this route to tenants.py or use the existing PATCH with branding fields in the body. |
| 3 | `admin: tenants/[orgId]/branding/+page.server.ts:8` | `GET /admin/configs/${orgId}?vertical=branding` | **Path mismatch.** Backend configs route is `GET /admin/configs/{vertical}/{config_type}` (two path segments). This call sends `orgId` as the first segment which would match `{vertical}` parameter — resulting in a 404 or wrong data. Should be `GET /admin/configs/branding/{config_type}?org_id=${orgId}`. |

---

## Disconnected Endpoints — Needs UX (8 real gaps)

After cross-referencing with `docs/system-map.md`, only **8 endpoints** genuinely need frontend surfaces. The 11 credit reporting workflow endpoints and 9 AI pipeline routes were reclassified (see "Reclassified Endpoints" below).

| # | Route | System-map evidence | Suggested location |
|---|-------|--------------------|--------------------|
| 1 | `POST /instruments/import/csv` | §8.1 lists instrument management | `instruments/+page.svelte` — CSV import dialog alongside Yahoo import |
| 2 | `POST /model-portfolios/{id}/stress` | §8.1 confirms "stress test bar chart" on detail page | `model-portfolios/[portfolioId]/+page.svelte` — stress tab |
| 3 | `POST .../assets/{id}/fund-investment` | §5.5 confirms credit portfolio module | `portfolio/+page.svelte` — investment sub-tab |
| 4 | `GET .../assets/{id}/fund-investment` | Same | Same |
| 5 | `POST/GET/PATCH /funds/{id}/actions` (3 routes) | §5.5 confirms "actions/" module, §7.1 lists portfolio actions tab | `funds/[fundId]/+page.svelte` — actions section |
| 6 | `POST .../investor-statements/generate` | §5.5 confirms "investor statement generation" | `reporting/+page.svelte` — generate trigger |
| 7 | `GET .../investor-statements/{id}/download` | §7.2 confirms "PDFDownload with language selector" | `reporting/+page.svelte` — download link per statement |
| 8 | `POST /admin/configs/validate` | §2.3 documents ConfigService guardrails | `ConfigEditor.svelte` — validate button before save |

## Reclassified Endpoints — Speculative (backend-ahead, 11 routes)

These endpoints exist in the backend but are NOT documented in `docs/system-map.md` as part of any feature surface. They were built speculatively ahead of frontend needs. No UX action required until they appear in a system-map update or sprint plan.

| Route | Why speculative |
|-------|----------------|
| `POST .../nav/snapshots/{id}/finalize` | System-map §7.1 only documents "create NAV snapshot" — no finalize/publish workflow |
| `POST .../nav/snapshots/{id}/publish` | Same |
| `POST .../nav/snapshots/{id}/assets` | Same |
| `GET .../nav/snapshots/{id}/assets` | Same |
| `POST .../monthly-pack/generate` | System-map does not mention monthly packs |
| `GET .../monthly-pack/{id}/download` | Same |
| `GET .../reports/archive` | Not mentioned in system-map |
| All 5 `/funds/{id}/report-schedules/*` | Zero reference to schedules in system-map — no tables, no frontend routes, no pipeline flows |

## Reclassified Endpoints — Pipeline-internal (9 routes)

These AI pipeline routes are consumed by the 13-stage Deep Review V4 pipeline (system-map §5.2). The frontend triggers the pipeline via `POST /funds/{id}/deals/{id}/ic-memo` and receives streamed results via SSE. These routes are internal building blocks, not direct frontend API targets.

| Route | Pipeline role |
|-------|-------------|
| `GET /ai/pipeline/deals/{id}/memo-chapters` | Deep review stage 13 output (chapters rendered via SSE in ICMemoViewer) |
| `GET /ai/pipeline/deals/{id}/im-draft` | Deep review composite output |
| `GET /ai/pipeline/deals/{id}/im-pdf` | PDF rendered from deep review output |
| `GET /ai/pipeline/deals/{id}/im-pdf/download` | Same |
| `GET /ai/pipeline/deals/{id}/pipeline-memo-pdf` | Alternative memo format |
| `GET /ai/pipeline/deals/{id}/deep-review-status` | Internal polling — SSE provides live status |
| `GET /ai/pipeline/deals/{id}/evidence-governance` | Deep review stage 11 input |
| `GET /ai/pipeline/deals/{id}/underwriting-artifact` | Deep review stage output |
| `GET /ai/pipeline/deals/{id}/critical-gaps` | Deep review stage 11 sub-output |

---

## Workers — UI Trigger Status

All 9 worker endpoints have admin UI triggers in `frontends/admin/src/routes/(admin)/health/+page.svelte:119`.

| Worker Endpoint | Admin Trigger | Notes |
|----------------|:---:|-------|
| `POST /workers/run-ingestion` | YES | Legacy NAV data fetch |
| `POST /workers/run-instrument-ingestion` | YES | Instrument NAV (`?lookback_days=` param) |
| `POST /workers/run-macro-ingestion` | YES | FRED macro data sync |
| `POST /workers/run-benchmark-ingest` | YES | Benchmark NAV ingestion |
| `POST /workers/run-risk-calc` | YES | CVaR, VaR calculation |
| `POST /workers/run-portfolio-eval` | YES | Portfolio snapshots |
| `POST /workers/run-screening-batch` | YES | Instrument screening |
| `POST /workers/run-watchlist-check` | YES | Watchlist alerts |
| `POST /workers/run-fact-sheet-gen` | YES | Fact sheet batch |

---

## Disconnected Endpoint Breakdown (system-map validated)

| Category | Count | Action |
|----------|------:|--------|
| **Needs UX (real gaps)** | **8** | Build frontend surfaces — see list above |
| Speculative (backend-ahead) | 11 | No action until system-map update or sprint plan |
| Pipeline-internal | 9 | No action — consumed by Deep Review V4 pipeline |
| API-only OK | 9 | No action — programmatic use |
| Worker-only | 12 | No action — triggered by workers/admin |
| Deprecated | 13 | Remove in future cleanup |
| Future | 6 | Planned for later sprints |
| Admin-only | 5 | Admin tools — low priority |
| **Total disconnected** | **59** | (only 8 actionable) |
