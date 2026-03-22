---
title: "feat: Full Backend-to-Frontend & Engine Integration"
type: feat
status: active
date: 2026-03-21
deepened: 2026-03-21
origin: docs/reference/2026-03-21-data-providers-api-reference.md
---

# Full Backend-to-Frontend & Engine Integration

## Enhancement Summary

**Deepened on:** 2026-03-21
**Research agents used:** 6 (Learnings Analysis, SvelteKit Patterns, FastAPI Endpoints, UX Doctrine Compliance, Chart Patterns, Worker Integration)
**Documented learnings applied:** 8 from `docs/solutions/`

### Key Improvements from Research

1. **Exact insertion point found** for `enrich_region_score()`: `macro_ingestion.py` line 162, between `build_regional_snapshot()` and `pg_insert(MacroRegionalSnapshot)`. Modify `build_regional_snapshot()` to accept optional `bis_data`/`imf_data` params.
2. **IMF provenance correction:** IMF WEO forecasts must be labeled "model inference" (economic forecasts), NOT "deterministic metric" — factual error in original plan §3.1.
3. **Chart library confirmed as ECharts** (not LayerChart) — `packages/ui/src/lib/charts/` has full component suite with dark mode auto-switch via MutationObserver on `data-theme`.
4. **Workers currently do NOT publish SSE progress** — Phase 4.1 requires modifying `_dispatch_worker()` to generate `job_id`, call `register_job_owner()`, and add `publish_event()` calls inside each worker.
5. **Route shadowing risk** on new screener endpoints — `/managers/{crd}/brochure/sections` could be shadowed by `/{crd}` param. Register literal routes first.
6. **`analyze_sponsor()` is never-raises contract** — returns `_default_output()` on failure. No try/except needed in caller. `persist_underwriting_artifact()` uses sync Session via `asyncio.to_thread()`.

### Five Systemic UX Doctrine Gaps (Cross-Cutting)

All plan items must address these — not just items that explicitly mention the doctrine:

| Gap | Doctrine § | Fix |
|-----|-----------|-----|
| Semantic spacing undefined | §13 | Every new section/page must declare spacing role: `section`, `block`, `card-padding`, `form-gap`, or `inline` |
| Border treatment missing | §11 | Dense tables: `border-default` columns + `border-subtle` rows. Failed states: `border-strong` danger |
| Dark mode under-specified | §22 | All charts use `netz-theme` auto-switch. Status badges use semantic tokens only (no hardcoded hex). Test both themes |
| Failure/rejected states omitted | §16 | Every workflow must include `failed` and/or `rejected` states alongside happy path |
| Provenance labeling inconsistent | §17 | Every data surface carries source label. Distinguish: raw evidence, deterministic metric, model inference, generated narrative |

### Critical Learnings Applied

| Learning | Applies to | Gotcha |
|----------|-----------|--------|
| Endpoint coverage wiring | All phases | Use `Promise.allSettled` (never `Promise.all`) in server loaders. Sequence counter for debounced search (not AbortController). |
| Phantom frontend calls | Phase 1-3 | Implement backend endpoints FIRST, then frontend. Never use raw `fetch()` — always `createClientApiClient(getToken)` (except SSE streams). |
| Macro intelligence suite | Phase 1.1, 3.1 | BIS data may be missing for some countries — `enrich_region_score()` gracefully returns original result. Use existing staleness decay constants (100d fresh / 180d max for quarterly data), not new magic numbers. |
| FastAPI route shadowing | Phase 1.2-1.3, 2.2 | Register `/brochure/sections` (literal) BEFORE `/{crd}` (param). Add `test_literal_routes_not_shadowed` regression test per router. |
| Wave 1 modularization | Phase 5.1-5.3 | Call only `service.py` entry points. `sponsor/` is never-raises (returns NOT_ASSESSED). `underwriting/` raises-on-failure (wrap in try/except). Run `make architecture` after every integration. |
| Wealth frontend review | All frontend | Both themes required. Use `MetricCard` for KPIs. CSS tokens only (no undeclared vars). Discriminated union types for new alert/event types. |

## Overview

The Netz Analysis Engine has accumulated significant analytical capability across data providers (BIS, IMF, SEC, ESMA), vertical engines (26 credit+wealth packages), quant services (17 services), and AI modules — but a substantial portion of this capability is invisible to the end user. This plan maps every gap between backend capacity and frontend exposure, then sequences their resolution to maximize user value while respecting the UX Doctrine (`docs/ux/system-ux-principles.md`).

**Scale of the gap:**
- **28+ wealth endpoints** with no frontend consumer
- **10+ credit endpoints** with limited/no frontend consumer
- **15 worker triggers** with zero UI
- **4 vertical engine packages** with code that is never called (fee_drag, sponsor, underwriting, lipper)
- **1 critical scoring function** (`enrich_region_score`) wired but not invoked from any worker
- **1 entire data provider** (ESMA, ~134K UCITS funds) with zero backend/frontend integration
- **Pre-computed momentum signals** (RSI, Bollinger, OBV) in DB but invisible in UI
- **Treasury, OFR, BIS, IMF hypertable data** ingested but not surfaced beyond macro composite scores

## Problem Statement

Users cannot access the full analytical power of the platform. Data is ingested, computed, and stored — but frontend surfaces only expose a fraction. This creates three problems:

1. **Wasted compute:** Workers run daily/weekly/quarterly to populate hypertables that no one sees
2. **Incomplete analysis:** Regional macro scores lack the 7th dimension (BIS credit cycle) and IMF growth blending — the function exists but isn't called
3. **Missing workflows:** IC governance (approvals, reviews, rebalancing) has backend routes but no frontend UI, forcing curl/Postman usage

## Proposed Solution

Five phases, ordered by impact/effort ratio. Each phase delivers standalone user value.

---

## Phase 1: Connect Existing Data (Wire-Only — No New Services)

**Effort:** Low (1-2 days per item)
**Impact:** High — immediately enriches existing pages with data already in the DB

### 1.1 Wire `enrich_region_score()` into Macro Pipeline

**Gap:** `enrich_region_score()` at `quant_engine/regional_macro_service.py` is a tested pure function that adds the 7th dimension (BIS credit cycle: credit_gap 50% + debt_service 30% + property_prices 20%) and blends IMF growth (FRED 70% + IMF 30%). It is **never called** — not from workers, not from routes.

**Fix:**
- `backend/app/domains/wealth/workers/macro_ingestion.py` — after `score_region()` returns `RegionalMacroResult`, call `enrich_region_score(result, bis_rows, imf_rows)` before persisting to `macro_regional_snapshots`
- BIS/IMF data is already in hypertables (`bis_statistics`, `imf_weo_forecasts`) — just query and pass
- Frontend `/macro` page already renders scores — enriched data flows through existing `GET /macro/scores` and `GET /macro/snapshot`

**Files:**
- `backend/app/domains/wealth/workers/macro_ingestion.py` — add `enrich_region_score()` call
- `quant_engine/regional_macro_service.py` — already complete (no changes)

**Acceptance Criteria:**
- [ ] `GET /macro/scores` returns 7 dimensions instead of 6 (credit_cycle present)
- [ ] `GET /macro/snapshot` shows IMF-blended growth (FRED 70% + IMF 30%)
- [ ] Existing macro page renders enriched data without frontend changes
- [ ] Test: `test_enrich_region_score_integration` in macro worker tests

### 1.2 Expose N-PORT Holdings in Manager Screener

**Gap:** `sec_nport_holdings` hypertable is populated by `nport_ingestion` worker (lock 900_018), but no REST endpoint exposes it. Manager Screener has 5 tabs (profile, holdings, drift, institutional, universe) — none shows N-PORT mutual fund portfolio data.

**Fix:**
- New endpoint: `GET /manager-screener/managers/{crd}/nport` — returns N-PORT holdings for a CRD (resolved via `sec_managers.cik`)
- New tab in Manager Screener detail drawer: "Fund Holdings" (N-PORT)
- Schema: paginated list of `NportHoldingResponse` (cusip, isin, issuer, market_value, pct_of_nav, report_date)

**Files:**
- `backend/app/domains/wealth/routes/manager_screener.py` — add `/managers/{crd}/nport` GET
- `backend/app/domains/wealth/schemas/manager_screener.py` — add `NportHoldingResponse`
- `backend/app/domains/wealth/queries/manager_screener_sql.py` — add N-PORT query
- `frontends/wealth/src/routes/(team)/manager-screener/ManagerDetailDrawer.svelte` — add "Fund Holdings" tab
- `frontends/wealth/src/lib/api/manager-screener.ts` — add `fetchNportHoldings(crd)`

**Acceptance Criteria:**
- [ ] `GET /manager-screener/managers/{crd}/nport` returns paginated N-PORT holdings
- [ ] Manager Screener drawer has 6th tab "Fund Holdings" showing N-PORT data
- [ ] Empty state when manager has no N-PORT filings
- [ ] Test: endpoint + query builder + empty CRD

### 1.3 Add Brochure Full-Text Search Endpoint

**Gap:** `sec_manager_brochure_text` has GIN full-text search index (18 classified ADV Part 2A sections), but no REST endpoint. The data is rich (advisory_business, fees_compensation, investment_philosophy, risk_management, etc.) but inaccessible.

**Fix:**
- New endpoint: `GET /manager-screener/managers/{crd}/brochure?q=&section=` — full-text search within a manager's ADV brochure
- New endpoint: `GET /manager-screener/managers/{crd}/brochure/sections` — list available sections with excerpts
- Integrate into Manager Screener Profile tab as expandable "ADV Brochure" section

**Files:**
- `backend/app/domains/wealth/routes/manager_screener.py` — add 2 brochure endpoints
- `backend/app/domains/wealth/schemas/manager_screener.py` — add `BrochureSectionResponse`, `BrochureSearchResponse`
- `frontends/wealth/src/routes/(team)/manager-screener/ManagerDetailDrawer.svelte` — Profile tab: add brochure accordion
- `frontends/wealth/src/lib/api/manager-screener.ts` — add `fetchBrochureSections(crd)`, `searchBrochure(crd, q)`

**Acceptance Criteria:**
- [ ] `GET /managers/{crd}/brochure/sections` returns 18 sections with text excerpts
- [ ] `GET /managers/{crd}/brochure?q=ESG` returns matching passages with highlights
- [ ] Profile tab shows collapsible brochure sections
- [ ] GIN index used (EXPLAIN shows index scan)
- [ ] Test: full-text search + section filter + empty results

### 1.4 Surface Pre-Computed Momentum Signals

**Gap:** `risk_calc` worker pre-computes RSI-14, Bollinger Band position, NAV momentum score, flow momentum score, and blended momentum score into `fund_risk_metrics` columns. No frontend page displays these.

**Fix:**
- Extend Risk Monitor page (`/risk`) with "Momentum Signals" section showing per-profile momentum indicators
- Extend Fund Detail page (`/funds/{fundId}`) with momentum mini-panel
- Data already available via `GET /risk/{profile}/cvar` response (or add to existing risk endpoint response)

**Files:**
- `backend/app/domains/wealth/schemas/risk.py` — ensure momentum fields in response
- `frontends/wealth/src/routes/(team)/risk/+page.svelte` — add Momentum Signals section
- `frontends/wealth/src/routes/(team)/funds/[fundId]/+page.svelte` — add momentum mini-panel

**Acceptance Criteria:**
- [ ] Risk page shows RSI-14, Bollinger position, blended momentum per profile
- [ ] Fund detail shows instrument-level momentum signals
- [ ] Color coding: RSI <30 (oversold/green), >70 (overbought/amber)
- [ ] UX: badges per UX Doctrine §17 (deterministic metric, not model inference)

### 1.5 Wire Drift Scanner Trigger

**Gap:** `POST /analytics/strategy-drift/scan` endpoint exists but Risk page only reads `GET /analytics/strategy-drift/alerts?is_current=true`. No "Run Scan" action in UI.

**Fix:**
- Add "Scan Now" button in Risk page drift alerts section
- Button calls `POST /analytics/strategy-drift/scan`, shows SSE progress, refreshes alerts on completion

**Files:**
- `frontends/wealth/src/routes/(team)/risk/+page.svelte` — add scan trigger button + SSE listener

**Acceptance Criteria:**
- [ ] "Scan Now" button calls POST endpoint
- [ ] Loading state during scan (UX Doctrine §15: motion clarifies state progression)
- [ ] Alert list refreshes after scan completes

---

## Phase 2: ESMA European Fund Universe

**Effort:** Medium (3-5 days)
**Impact:** High — opens 134K UCITS funds + European manager discovery

### 2.1 ESMA Ingestion Worker

**Gap:** `RegisterService` and `TickerResolver` are functional (e2e validated), but no worker populates the DB tables (`esma_managers`, `esma_funds`, `esma_isin_ticker_map`).

**Fix:**
- New worker: `esma_ingestion` (lock 900_019, weekly)
- Calls `RegisterService.iter_ucits_funds()` → bulk upsert `esma_funds` + `esma_managers`
- Calls `TickerResolver.resolve_all()` → upsert `esma_isin_ticker_map`
- Trigger: `POST /workers/run-esma-ingestion`

**Files:**
- `backend/app/domains/wealth/workers/esma_ingestion.py` — new worker
- `backend/app/domains/wealth/routes/workers.py` — add trigger endpoint

**Acceptance Criteria:**
- [ ] Worker populates `esma_managers` (~5K managers) and `esma_funds` (~134K funds)
- [ ] Advisory lock 900_019, idempotent via Redis
- [ ] `POST /workers/run-esma-ingestion` returns 202
- [ ] Test: worker integration with mock HTTP

### 2.2 ESMA REST Endpoints

**Fix:**
- `GET /esma/managers?country=&search=&page=&page_size=` — paginated manager list
- `GET /esma/managers/{esma_id}` — manager detail + funds
- `GET /esma/funds?domicile=&type=&search=&page=&page_size=` — fund search
- `GET /esma/funds/{isin}` — fund detail + ticker resolution
- `GET /esma/managers/{esma_id}/sec-crossref` — SEC CRD cross-reference (if available)

**Files:**
- `backend/app/domains/wealth/routes/esma.py` — new router
- `backend/app/domains/wealth/schemas/esma.py` — Pydantic response schemas
- `backend/app/domains/wealth/queries/esma_sql.py` — query builder

**Acceptance Criteria:**
- [ ] 5 endpoints functional with pagination
- [ ] Text search uses GIN index on `esma_managers.company_name` and `esma_funds.fund_name`
- [ ] Cross-reference endpoint returns SEC CRD when `sec_crd_number` is set
- [ ] Auth: `Role.INVESTMENT_TEAM` or `Role.ADMIN`

### 2.3 ESMA Frontend — European Fund Universe Page

**Fix:**
- New page: `/esma` in wealth frontend
- Tabs: "Managers" (searchable table) + "Funds" (searchable table with ISIN, domicile, type filters)
- Manager detail drawer with fund list + SEC cross-reference badge
- "Add to Universe" action (reuses `instruments_universe` flow)

**UX Doctrine compliance:**
- **§10 (Surface):** Manager/fund tables on `surface-1`, detail drawer on `surface-3`
- **§16 (Workflow):** SEC cross-reference badge indicates "matched" vs "unmatched" (process state)
- **§18 (Cross-vertical):** Same table/drawer patterns as Manager Screener
- **§21 (Page type):** Workbench page — action locality + context continuity

**Files:**
- `frontends/wealth/src/routes/(team)/esma/+page.server.ts` — server load
- `frontends/wealth/src/routes/(team)/esma/+page.svelte` — main page
- `frontends/wealth/src/routes/(team)/esma/EsmaManagerDrawer.svelte` — detail drawer
- `frontends/wealth/src/lib/api/esma.ts` — API client
- Navigation sidebar: add "ESMA Universe" under Data section

**Acceptance Criteria:**
- [ ] Paginated manager + fund tables with filters
- [ ] Manager drawer shows funds + SEC cross-ref
- [ ] "Add to Universe" button integrates with existing universe workflow
- [ ] Empty state for unresolved tickers
- [ ] Responsive layout matching Manager Screener patterns

---

## Phase 3: Analytical Surface Enrichment

**Effort:** Medium (2-3 days per item)
**Impact:** Medium-high — fills analytical gaps, especially for IC workflows

### 3.1 Macro Intelligence — Raw Hypertable Data Panels

**Gap:** Macro page shows composite scores but not the underlying BIS/IMF/Treasury/OFR data that feeds them. Analysts need to see the raw indicators.

**Fix:**
- Extend `/macro` page with expandable "Data Sources" section:
  - **BIS Panel:** Credit-to-GDP gap, DSR, property prices by country (time series)
  - **IMF Panel:** GDP growth, inflation, fiscal balance, debt by country (bar chart)
  - **Treasury Panel:** Yield curve, rates, auctions (from `treasury_data`)
  - **OFR Panel:** Hedge fund leverage, AUM, repo stress (from `ofr_hedge_fund_data`)
- New endpoints (or extend existing):
  - `GET /macro/bis?country=&indicator=` — raw BIS time series
  - `GET /macro/imf?country=&indicator=` — raw IMF forecasts
  - `GET /macro/treasury?type=` — treasury data
  - `GET /macro/ofr?metric=` — OFR hedge fund data

**UX Doctrine compliance:**
- **§17 (AI vs Determinism):** Raw data panels clearly labeled as "deterministic metric" (database-sourced), distinct from "model inference" (composite scores)
- **§7 (System model):** These are Layer 3 (Analytical Surface) — cards with charts and metadata
- **§20 (Components):** Charts "feel analytical, not promotional"

**Files:**
- `backend/app/domains/wealth/routes/macro.py` — add 4 raw data endpoints
- `backend/app/domains/wealth/schemas/macro.py` — add response schemas
- `frontends/wealth/src/routes/(team)/macro/+page.svelte` — add Data Sources section
- `frontends/wealth/src/routes/(team)/macro/BisPanel.svelte` — BIS charts
- `frontends/wealth/src/routes/(team)/macro/ImfPanel.svelte` — IMF charts
- `frontends/wealth/src/routes/(team)/macro/TreasuryPanel.svelte` — Treasury charts
- `frontends/wealth/src/routes/(team)/macro/OfrPanel.svelte` — OFR charts

**Acceptance Criteria:**
- [ ] 4 new endpoints return raw hypertable data with country/indicator filters
- [ ] Macro page has collapsible "Data Sources" section with 4 panels
- [ ] Each panel has time-series chart + latest value badges
- [ ] UX: clear "Source: BIS SDMX" / "Source: IMF WEO" provenance labels

### 3.2 Credit Market Data Page

**Gap:** `vertical_engines/credit/market_data/` reads from `macro_data` hypertable (BAA spread, yield curve, Case-Shiller 20 metros, regional indicators) but no credit frontend page shows this.

**Fix:**
- New section in Credit Dashboard or new `/market-data` page
- Cards: BAA-OAS spread, yield curve (2y/10y), Case-Shiller index, regional heat indicators
- Data flows through existing `GET /dashboard/macro-snapshot` (or extend with new endpoint)

**Files:**
- `backend/app/domains/credit/routes/dashboard.py` — extend `macro-snapshot` with full market data
- `frontends/credit/src/routes/(team)/funds/[fundId]/+layout.svelte` — add Market Data nav item
- `frontends/credit/src/routes/(team)/funds/[fundId]/market-data/+page.svelte` — new page
- `frontends/credit/src/routes/(team)/funds/[fundId]/market-data/+page.server.ts` — server load

**Acceptance Criteria:**
- [ ] BAA spread, yield curve, Case-Shiller displayed with time series
- [ ] Regional breakdown (20 Case-Shiller metros visible)
- [ ] Data sourced from `macro_data` hypertable (zero FRED API calls)

### 3.3 IC Governance Workflows — Macro Reviews

**Gap:** Backend has `PATCH /macro/reviews/{id}/approve` and `PATCH /macro/reviews/{id}/reject` but frontend `/macro` page has limited governance UI.

**Fix:**
- Enhance macro reviews section with approval/rejection workflow
- `ConsequenceDialog` for approve/reject actions (UX Doctrine §16: draft vs approved distinction)
- Show review status badges: draft → pending_review → approved → published
- Audit trail link for each review

**Files:**
- `frontends/wealth/src/routes/(team)/macro/+page.svelte` — enhance reviews section
- `frontends/wealth/src/routes/(team)/macro/MacroReviewCard.svelte` — review card with actions
- `frontends/wealth/src/lib/api/macro.ts` — add `approveReview()`, `rejectReview()`

**Acceptance Criteria:**
- [ ] Reviews show status badges (UX Doctrine §16)
- [ ] Approve/Reject buttons with ConsequenceDialog + rationale field
- [ ] Audit trail accessible per review
- [ ] Role-gated: only `ADMIN` or `INVESTMENT_TEAM` can approve

### 3.4 Rebalancing Workflow UI

**Gap:** Backend has `POST /portfolios/{profile}/rebalance/propose`, `/approve`, `/execute`, `/pending` but no frontend surfaces these IC-critical workflows.

**Fix:**
- New section in Portfolio Detail page: "Rebalancing" tab
- Workflow: Propose → Review (pending) → Approve (ConsequenceDialog) → Execute
- Show before/after weight comparison, CVaR impact, trade list

**UX Doctrine compliance:**
- **§16 (Workflow):** Proposed vs approved vs executed states clearly distinguished
- **§7 (Layer 4 — Process Layer):** Stage transitions, consequence dialogs, approval maturity

**Files:**
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/RebalancingTab.svelte` — new tab
- `frontends/wealth/src/lib/api/portfolios.ts` — add rebalance methods

**Acceptance Criteria:**
- [ ] Propose: shows weight changes + CVaR delta
- [ ] Pending: shows proposed changes awaiting approval
- [ ] Approve: ConsequenceDialog with rationale, before/after comparison
- [ ] Execute: final confirmation, audit trail entry
- [ ] Empty state when no pending rebalance

### 3.5 Content Management Enhancement

**Gap:** `/content` page lists content items but doesn't show generation status, approval workflow, or download links effectively.

**Fix:**
- Enhance content list with status pipeline: `generating → draft → pending_review → approved → published`
- Add SSE progress for active generations
- Approval workflow inline (approve/reject buttons with ConsequenceDialog)
- Download buttons for approved content (PDF/DOCX)

**Files:**
- `frontends/wealth/src/routes/(team)/content/+page.svelte` — enhance page
- `frontends/wealth/src/routes/(team)/content/ContentCard.svelte` — rich content card
- `frontends/wealth/src/lib/api/content.ts` — add approval + download methods

**Acceptance Criteria:**
- [ ] Status pipeline visible per content item (UX Doctrine §16)
- [ ] SSE progress for active generations (UX Doctrine §15)
- [ ] Approve/reject with ConsequenceDialog
- [ ] Download buttons for approved content

---

## Phase 4: Admin & Operations UI

**Effort:** Medium (3-4 days)
**Impact:** Medium — eliminates curl/Postman dependency for operations

### 4.1 Worker Management Dashboard (Admin Frontend)

**Gap:** 15 `POST /workers/run-*` endpoints exist with zero UI. Operations require manual HTTP calls.

**Fix:**
- New admin page: `/workers` — grid of worker cards showing:
  - Name, lock ID, frequency, last run time, last run status
  - "Run Now" button per worker
  - Last 10 run history with duration + status
- SSE subscription for real-time worker status updates

**UX Doctrine compliance:**
- **§7 (Layer 4 — Process Layer):** Worker states (idle, running, failed, locked) as process maturity indicators
- **§21 (Page type):** Dashboard page — summary + exception visibility

**Files:**
- `frontends/admin/src/routes/workers/+page.svelte` — worker dashboard
- `frontends/admin/src/routes/workers/+page.server.ts` — server load
- `frontends/admin/src/lib/api/workers.ts` — API client for 15 trigger endpoints
- Backend: `GET /admin/workers/status` — new endpoint returning all worker states + last run metadata

**Acceptance Criteria:**
- [ ] All 15 workers displayed as cards with status
- [ ] "Run Now" triggers worker, shows progress via SSE
- [ ] Last run history with duration + error messages
- [ ] Advisory lock status visible (locked/available)
- [ ] Role-gated: `ADMIN` only

### 4.2 Prompt Versioning Fix (Admin Frontend)

**Gap:** Admin PromptEditor has TODOs — `actor_id` and `change_summary` not returned by backend `/versions` endpoint.

**Fix:**
- Backend: add `actor_id` and `change_summary` to prompt version response schema
- Frontend: display version history with actor + summary in PromptEditor

**Files:**
- `backend/app/domains/admin/routes/prompts.py` — add fields to version response
- `frontends/admin/src/routes/tenants/[orgId]/prompts/PromptEditor.svelte` — fix TODOs at lines ~167, ~169

**Acceptance Criteria:**
- [ ] Version history shows who changed what and when
- [ ] `actor_id` resolved to display name
- [ ] `change_summary` editable on version create

### 4.3 Document Pipeline Visibility

**Gap:** Ingestion pipeline (OCR → classification → extraction → search) runs in background but no page shows processing status, validation gates, or chunk quality metrics.

**Fix:**
- Credit: add "Processing" tab to Documents page showing pipeline stage per document
- Wealth: add pipeline status column to documents list
- Both read from existing `pipeline_runs` or document status fields

**Files:**
- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/PipelineStatus.svelte` — pipeline stage viewer
- `frontends/wealth/src/routes/(team)/documents/DocumentPipelineColumn.svelte` — inline status

**Acceptance Criteria:**
- [ ] Each document shows current pipeline stage (uploaded → OCR → classified → chunked → embedded → indexed)
- [ ] Failed stages show error details
- [ ] UX Doctrine §17: pipeline stages are deterministic process indicators

---

## Phase 5: Dead Code Resolution & Engine Activation

**Effort:** Medium (3-4 days — integrations are non-trivial)
**Impact:** Medium — activates dormant analytical capability + removes dead code

### 5.1 Integrate `fee_drag/` into DD Report + Screener (DECIDED)

**Decision:** Integrate as metric in DD Report **and** as filter/sort column in Screener.

**DD Report integration:**
- Add fee drag ratio as evidence in the fees/expenses chapter of the 8-chapter DD report
- `vertical_engines/wealth/dd_report/` chapter engine calls `fee_drag.service.compute_fee_drag()` during chapter generation
- Result rendered as metric card in chapter output (fee drag %, efficiency score, peer comparison)

**Screener integration:**
- Add `fee_drag_ratio` and `fee_efficiency_score` as computed columns in screener results
- `vertical_engines/wealth/screener/` 3rd layer (quant scoring) calls `fee_drag.service.compute_fee_drag()` per instrument
- Frontend screener table: new sortable columns "Fee Drag" and "Fee Efficiency"
- Query builder: add `fee_drag_min`, `fee_drag_max` filter parameters

**Files:**
- `vertical_engines/wealth/dd_report/chapters/` — integrate fee_drag into fees chapter
- `vertical_engines/wealth/screener/quant_layer.py` — call fee_drag service
- `backend/app/domains/wealth/schemas/screener.py` — add fee_drag fields to response
- `frontends/wealth/src/routes/(team)/screener/+page.svelte` — add columns

**Acceptance Criteria:**
- [ ] DD Report fees chapter includes fee drag ratio + efficiency score
- [ ] Screener results include fee_drag_ratio sortable column
- [ ] Screener filters support fee_drag_min/max
- [ ] `fee_drag/service.py` called from 2 consumers (DD report + screener)
- [ ] Tests: fee_drag integration in both consumers

### 5.2 Integrate `sponsor/` into Deal Context + IC Memo (DECIDED)

**Decision:** Auto-enrich deal context on pipeline entry **and** use as IC Memo evidence.

**Deal context enrichment:**
- When a deal enters the pipeline (`POST /pipeline/deals`), sponsor engine auto-enriches `deal_context.json` with PE firm data (AUM, vintage, fund history, track record)
- `vertical_engines/credit/sponsor/service.py` called from deal creation flow
- Enrichment is best-effort — if sponsor data unavailable, deal proceeds without it

**IC Memo evidence:**
- Sponsor chapter in IC memo book uses enriched sponsor data as evidence
- `vertical_engines/credit/memo/chapter_prompts/` sponsor chapter template references `deal_context.sponsor_enrichment`
- Evidence pack includes sponsor track record as supporting material

**Files:**
- `backend/app/domains/credit/routes/deals.py` — call sponsor enrichment on deal creation
- `vertical_engines/credit/sponsor/service.py` — ensure returns structured sponsor data
- `vertical_engines/credit/memo/chapters/` — sponsor chapter uses enriched data
- `vertical_engines/credit/memo/evidence_pack.py` — include sponsor evidence

**Acceptance Criteria:**
- [ ] New deal creation auto-enriches `deal_context.json` with sponsor data
- [ ] IC Memo sponsor chapter references enriched sponsor evidence
- [ ] Graceful degradation: missing sponsor data does not block deal or memo
- [ ] Tests: enrichment flow + memo chapter with/without sponsor data

### 5.3 Integrate `underwriting/` into Pipeline + On-Demand Endpoint (DECIDED)

**Decision:** Auto-generate underwriting artifact after qualification **and** expose endpoint for re-generation.

**Pipeline auto-generation:**
- After `POST /pipeline/deals/{deal_id}/qualify` completes successfully, underwriting engine auto-generates artifact (term sheet draft, credit summary, risk matrix)
- Stored as deal attachment in `deal_context.underwriting_artifact`
- Visible in deal detail page

**On-demand endpoint:**
- `POST /pipeline/deals/{deal_id}/underwriting-artifact` — regenerate underwriting artifact
- Returns artifact with PDF download link
- Auth: `Role.INVESTMENT_TEAM` or `Role.ADMIN`

**Files:**
- `backend/app/domains/credit/routes/deals.py` — add underwriting-artifact endpoint
- `backend/app/domains/credit/schemas/deals.py` — add `UnderwritingArtifactResponse`
- `vertical_engines/credit/pipeline/service.py` — call underwriting after qualification
- `vertical_engines/credit/underwriting/service.py` — ensure generates structured output
- `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte` — show artifact section

**Acceptance Criteria:**
- [ ] Qualification success auto-generates underwriting artifact
- [ ] `POST /deals/{deal_id}/underwriting-artifact` regenerates on demand
- [ ] Deal detail page shows artifact (term sheet, risk matrix) with PDF download
- [ ] Graceful degradation: qualification succeeds even if underwriting fails
- [ ] Tests: auto-generation + endpoint + PDF rendering

### 5.4 Remove Dead Code (DECIDED)

**`quant_engine/lipper_service.py` — REMOVE:**
- YFinance + ESMA + SEC cover fund universe; Lipper is paid and redundant
- Delete file, remove all imports, update `__init__.py`

**`quant_engine/fred_service.py` — REMOVE:**
- Replaced by DB-first pattern (`macro_data` hypertable + `macro_ingestion` worker)
- CLAUDE.md already documents as eliminated
- Delete file, remove all imports, update `__init__.py`

**Files:**
- `quant_engine/lipper_service.py` — delete
- `quant_engine/fred_service.py` — delete (if still present)
- Any files importing these — remove stale imports

**Acceptance Criteria:**
- [ ] Both files deleted
- [ ] Zero remaining imports of `lipper_service` or `fred_service`
- [ ] `make check` passes (lint + typecheck + test + architecture)
- [ ] No test files reference deleted services

---

## System-Wide Impact

### Interaction Graph

- Phase 1.1 (`enrich_region_score`): macro_ingestion worker → `score_region()` → `enrich_region_score()` → `macro_regional_snapshots` table → `GET /macro/scores` → frontend `/macro` page. No new event chains — enrichment is synchronous within existing worker flow.
- Phase 2 (ESMA): new worker → new tables → new routes → new frontend page. Isolated — no interaction with existing wealth/credit pipelines.
- Phase 3 (analytical surfaces): read-only additions to existing pages. No write-side interactions.
- Phase 4 (admin): new admin-only pages. No interaction with team/investor flows.

### Error Propagation

- Worker failures are idempotent (advisory locks + Redis). Frontend shows stale data with "last updated" timestamps.
- New endpoints follow existing pattern: `AsyncSession` + RLS + `model_validate()`. Errors propagate via standard FastAPI exception handlers.

### State Lifecycle Risks

- Phase 1.1: `enrich_region_score` is a pure function — no state mutation beyond what `macro_ingestion` already does. If BIS/IMF query fails, worker continues with unenriched scores (graceful degradation).
- Phase 2: ESMA worker is additive (INSERT ON CONFLICT UPDATE). Partial failure leaves partial data — next run fills gaps.

### API Surface Parity

- N-PORT endpoint follows same pattern as existing 5 screener tabs (pagination, CRD lookup, auth)
- ESMA endpoints follow same pagination/filter pattern as Manager Screener
- Raw macro data endpoints follow same pattern as existing `GET /macro/scores`

### Integration Test Scenarios

1. Full macro pipeline: FRED ingest → BIS ingest → IMF ingest → `enrich_region_score()` → `GET /macro/scores` returns 7 dimensions
2. Manager Screener full journey: search → profile tab (with brochure) → holdings tab → N-PORT tab → add to universe
3. ESMA → Universe flow: browse ESMA funds → select fund → "Add to Universe" → appears in instruments list
4. Worker dashboard: trigger worker → SSE progress → completion → last-run updated
5. Rebalancing: propose → pending list → approve with ConsequenceDialog → execute → audit trail entry

---

## Acceptance Criteria (Global)

### Functional Requirements

- [ ] All 5 identified data gaps closed (enrich_region_score, N-PORT, brochure, ESMA, momentum)
- [ ] All IC governance workflows have frontend UI (macro review, rebalancing, content approval)
- [ ] Admin worker dashboard operational for all 15+ workers
- [ ] Zero curl/Postman required for standard operations

### Non-Functional Requirements

- [ ] All new pages follow UX Doctrine surface hierarchy (§10)
- [ ] All process states use consistent workflow visibility language (§16)
- [ ] All data sources labeled with provenance (§17: deterministic vs model-generated)
- [ ] Cross-vertical consistency maintained (§18: same patterns in credit + wealth)
- [ ] Dark mode functional on all new surfaces (§22)

### Quality Gates

- [ ] All new endpoints have Pydantic `response_model=` + `model_validate()`
- [ ] All new queries parameterized (no f-string SQL)
- [ ] All new frontend pages use `@netz/ui` formatters (no `.toFixed()`, no inline `Intl`)
- [ ] `make check` passes (lint + typecheck + test + architecture)
- [ ] New tests for each endpoint (unit + auth + empty state)

---

## Dependencies & Risks

| Risk | Mitigation |
|------|-----------|
| ESMA Solr API rate limits (4 req/s) | Worker uses `iter_ucits_funds` with pagination, ~134 pages at 1000/page. Conservative 4 req/s = ~35s total. |
| BIS/IMF data freshness for `enrich_region_score` | Graceful degradation: if BIS/IMF data is >90 days old, skip enrichment and log warning |
| Frontend bundle size from 4 new chart panels (Phase 3.1) | Lazy-load chart panels with dynamic imports |
| Admin frontend maturity | Admin frontend exists but has limited pages — Phase 4 extends existing structure |

---

## Phasing Summary

| Phase | Items | New Endpoints | New Pages | Effort |
|-------|-------|---------------|-----------|--------|
| **1. Wire Existing** | 1.1-1.5 | 3 | 0 (extend existing) | 3-5 days |
| **2. ESMA Universe** | 2.1-2.3 | 6 | 1 full page | 3-5 days |
| **3. Analytical Surfaces** | 3.1-3.5 | 4-6 | 2 new + 3 enhanced | 5-8 days |
| **4. Admin & Ops** | 4.1-4.3 | 1-2 | 1 full page + fixes | 3-4 days |
| **5. Engine Activation + Cleanup** | 5.1-5.4 | 1 (underwriting) | 0 (extend existing) | 3-4 days |
| **Total** | 21 items | ~17 endpoints | ~4 pages + ~8 enhanced | 18-27 days |

---

## Research Insights (Deepened)

### Phase 1.1 — Exact Integration Point for `enrich_region_score()`

**Insertion:** `macro_ingestion.py` lines 162-204. Between `build_regional_snapshot()` (line 163) and `pg_insert(MacroRegionalSnapshot)` (line 170).

**Best approach:** Modify `build_regional_snapshot()` in `macro_snapshot_builder.py` to accept optional `bis_data: list[BisDataPoint]` and `imf_data: list[ImfDataPoint]` parameters. Call `enrich_region_score()` after `score_region()` per region (line 66-69). Worker fetches BIS/IMF from DB, passes to builder. Builder stays purely computational.

**Function signature** (line 771 of `regional_macro_service.py`):
```python
def enrich_region_score(
    result: RegionalMacroResult,
    bis_data: list[BisDataPoint] | None = None,
    imf_data: list[ImfDataPoint] | None = None,
) -> RegionalMacroResult:
```

**Datapoint types** (lines 596-613): `BisDataPoint(country_code, indicator, value: float, period: date)`, `ImfDataPoint(country_code, indicator, year: int, value: float)`.

**Error handling:** Function returns original result unchanged if `bis_data`/`imf_data` is None/empty (lines 818-819). Wrap BIS/IMF DB query in try/except, log warning, pass None on failure.

**Staleness:** Use existing decay constants (quarterly: 100d fresh / 180d max) from `regional_macro_service.py`, not the hardcoded 90 days in the original plan. (Learning: wealth-macro-intelligence-suite)

**Race condition check:** Verify backend uses `.with_for_update()` on macro review approve/reject endpoints before wiring Phase 3.3 frontend. (Learning: wealth-macro-intelligence-suite P1 bug)

### Phase 1.2-1.3 — N-PORT + Brochure Endpoint Patterns

**N-PORT query pattern:**
- Resolve CRD → CIK via `_get_manager()` first (N-PORT keyed on `cik`, not `crd_number`)
- Always include `report_date` filter for chunk pruning (3-month chunks, `segmentby: cik`)
- Get latest `report_date` first, then filter by that quarter
- Schema: `NportHoldingResponse(cusip, isin, issuer_name, asset_class, sector, market_value, quantity, currency, pct_of_nav, report_date)` + paginated wrapper

**Brochure full-text search pattern** (from existing `adv_service.py` line 734):
```sql
SELECT crd_number, section, content, filing_date,
       ts_headline('english', content, plainto_tsquery('english', :query),
                   'MaxFragments=2,MaxWords=30') AS headline
FROM sec_manager_brochure_text
WHERE crd_number = :crd
  AND to_tsvector('english', content) @@ plainto_tsquery('english', :query)
ORDER BY ts_rank(to_tsvector('english', content), plainto_tsquery('english', :query)) DESC
```
- Use `plainto_tsquery` (not `to_tsquery`) for safe user input
- Use `text()` raw SQL (SQLAlchemy ORM lacks ts_vector support)
- GIN index `ix_sec_brochure_text_fts` already exists

**Route shadowing:** Register `/managers/{crd}/brochure/sections` (literal) BEFORE `/{crd}` (param) in the router. Add regression test `test_literal_routes_not_shadowed`.

**Frontend pattern:** Both load on-demand in drawer via client API. Use `api.get()` inline (no separate API file per the codebase convention). Sequence counter for brochure search debounce (not AbortController — per endpoint-coverage learning).

### Phase 1.4 — Momentum Chart Components

**Use ECharts `GaugeChart` from `@netz/ui`** (NOT LayerChart — confirmed absent from codebase).

| Signal | Component | Config |
|--------|-----------|--------|
| RSI-14 | `GaugeChart` | Zones: 0-30 `statusColors.ok`, 30-70 `statusColors.warning`, 70-100 `statusColors.breach` |
| Bollinger position | `GaugeChart` half-arc (`startAngle: 180, endAngle: 0`) or CSS horizontal bar for compact mini-panel |
| Blended momentum | `MetricCard` with color-coded value (semantic tokens, not hardcoded hex) |

**Layout:** `SectionCard title="Momentum Signals"` with 3-column grid of gauges per profile on Risk page. `MetricCard` row on Fund detail.

**Dark mode:** Fully handled by `echarts-setup.ts` MutationObserver — use `netz-theme` and CSS variables only.

### Phase 2.1 — ESMA Worker Details

**Lock ID:** 900_019 confirmed available. Current range: 42, 43, 900_001-900_018.

**Template:** Copy `nport_ingestion.py` (91 lines, cleanest example).

**Data flow:**
1. Advisory lock 900_019 → `async with RegisterService() as svc` → `iter_ucits_funds()` paging through Solr
2. `parse_manager_from_doc()` extracts managers from fund docs
3. Upsert `esma_managers` then `esma_funds` (FK dependency order — per alembic-monorepo learning)
4. `pg_insert(...).on_conflict_do_update()` in chunks of 2000
5. Unlock in `finally`

**Route addition:** Add `trigger_run_esma_ingestion` to `workers.py` following `trigger_run_nport_ingestion` pattern (lines 482-509). Dispatch: `_dispatch_worker(bg, "run-esma-ingestion", "global", run_esma_ingestion, timeout_seconds=_HEAVY_WORKER_TIMEOUT)`.

### Phase 2.2 — ESMA Endpoint Patterns

**Text search:** Use `ILIKE` with `_escape_ilike()` (same as screener). ~134K funds — offset pagination with index is fine. Consider `CREATE INDEX ix_esma_funds_name_trgm ON esma_funds USING gin (fund_name gin_trgm_ops)` if search is slow.

**Manager detail:** Two queries (avoid adding ORM relationship): `select(EsmaManager)` + `select(EsmaFund).where(esma_manager_id == esma_id)`.

**Cross-ref:** If `sec_crd_number` set, also fetch `SecManager` for firm name display.

### Phase 2.3 — ESMA Frontend Template

**Copy:** `frontends/wealth/src/routes/(team)/manager-screener/` entirely — same structure: paginated table + filter sidebar + detail drawer with tabs.

**Server load:** `Promise.allSettled` with `api.get("/esma/managers?${qs}")` or `api.get("/esma/funds?${qs}")` based on active tab.

**Components to reuse:** `PageHeader`, `PageTabs` (Managers/Funds toggle), `EmptyState`, `StatusBadge` (cross-ref matched/unmatched), same drawer pattern with `selectedEsmaId`. Pagination: URL-driven with `goto()`.

**Navigation:** Top-level TopNav item (not sidebar — per D1 navigation decision in wealth frontend review learning).

### Phase 3.1 — Hypertable Query & Chart Patterns

**TimescaleDB query rules for new endpoints:**
- `bis_statistics`: 1yr chunks, `segmentby: country_code`, filter on `period`
- `imf_weo_forecasts`: 1yr chunks, `segmentby: country_code`, filter on `period`
- `treasury_data`: 1mo chunks, `segmentby: series_id`, filter on `obs_date`
- `ofr_hedge_fund_data`: 3mo chunks, `segmentby: series_id`, filter on `obs_date`
- No `time_bucket()` needed for raw data (BIS is quarterly, IMF is annual). Use date-floor filters, not `LIMIT * entity_count`.
- Never forward-fill financial data gaps — return actual observed points only.

**CORRECTION — IMF provenance labeling:** IMF WEO forecasts are economic model forecasts (model inference), NOT deterministic metrics. Fix the §17 compliance block: BIS = deterministic, Treasury = deterministic, OFR = survey-based (deterministic), IMF = model inference.

**Chart components per panel:**

| Panel | Chart Type | Component | Notes |
|-------|-----------|-----------|-------|
| BIS (credit gap, DSR, property) | Multi-series line | `TimeSeriesChart` | Country selector filter, `--netz-chart-1..5` per country |
| IMF (GDP, inflation, fiscal, debt) | Horizontal bar | `BarChart` with `orientation="horizontal"` | Indicator `Select` dropdown, one indicator at a time |
| Treasury (yield curve) | Line with category X | Raw `ChartContainer` | X: maturities (1M..30Y). `markArea` for inverted regions (red at 8% opacity) |
| OFR (leverage, AUM, stress) | Area + bar | `TimeSeriesChart` area for AUM, `BarChart` for strategy, `GaugeChart` for repo stress |
| Case-Shiller (20 metros) | Multi-series line | `TimeSeriesChart` | `Select` filter for metro, default top 5 |

**Lazy loading:** Dynamic `{#await import('./BisPanel.svelte')}` for each panel — inside collapsible "Data Sources" section, should not block page load.

**Cache:** BIS/IMF: Redis 6h TTL. Treasury: 1h TTL. OFR: 1h TTL.

### Phase 3.4 — Rebalancing Before/After Visualization

**Paired horizontal bar chart (butterfly/tornado)** via raw `ChartContainer`:
- Two bar series sharing Y axis (fund names)
- "Before": negative values (extending left), `--netz-chart-4` (muted)
- "After": positive values (extending right), `--netz-chart-1` (bold)
- CVaR impact: `MetricCard` pair (current vs projected) with `markLine` for limit

**Additional states needed** (per UX review): proposed → pending_review → approved → executing → executed → failed. Add `ConsequenceDialog` for Execute step (not just Approve — executing triggers real portfolio changes).

### Phase 4.1 — Worker SSE Architecture Gap

**Current state:** Workers do NOT publish SSE progress events. They run in `BackgroundTasks` with idempotency tracking only.

**Required modifications:**
1. `_dispatch_worker()` → generate `job_id = uuid4()`, call `register_job_owner(job_id, org_id)`, return `job_id` in `WorkerScheduledResponse`
2. Add `publish_event(job_id, "progress", {"pct": N, "message": "..."})` at worker milestones
3. Add `publish_terminal_event(job_id, "done", {...})` on completion
4. New SSE endpoint: `GET /workers/{job_id}/stream` → `create_job_stream(request, job_id)`
5. Admin frontend subscribes via `createSSEStream` from `@netz/ui/utils`

**Worker states (expanded per UX review):** idle, queued, running, completed, failed, timeout. "Locked" is implementation detail — display as "in progress (another instance)".

**Status colors:** idle=neutral, queued=info, running=accent, completed=success, failed=danger, timeout=warning. Use semantic status tokens.

### Phase 5.1 — fee_drag Integration Points

**DD Report:** Insert in `_build_evidence()` method (line 275-311 of `dd_report_engine.py`). After `risk_metrics = gather_risk_metrics()`, call `FeeDragService().compute_portfolio_fee_drag(instruments, weights)`. Add result to `EvidencePack.scoring_data`.

**Screener:** Insert after Layer 3 quant scoring (line 135 of `screener/service.py`). Add fee_drag to `metrics_dict` and `weights` in composite score.

**Service interface:** `FeeDragService(fee_drag_threshold=0.50)`, method `compute_portfolio_fee_drag(instruments: list[dict], weights: dict | None)` returns `PortfolioFeeDrag` (frozen dataclass).

### Phase 5.2-5.3 — Error Contract Summary

| Engine | Contract | Caller Pattern |
|--------|----------|---------------|
| `sponsor/service.py` | **Never-raises** — returns `_default_output()` with `status: 'NOT_ASSESSED'` | No try/except needed. Check `result["status"]` for graceful UI handling. |
| `underwriting/service.py` | **Raises-on-failure** (transactional) | Wrap in try/except. On failure, log + continue (qualification succeeds). |
| `fee_drag/service.py` | **Never-raises** (wealth engine pattern) | No try/except needed. Check for empty results. |

**Import direction:** Call only `service.py` entry points. DD report → `fee_drag.service`, memo → `sponsor.service`, pipeline → `underwriting.service`. Run `make architecture` after every integration.

**`persist_underwriting_artifact()`** uses sync Session — must call via `asyncio.to_thread()`. Deactivates prior versions before creating new ones (lines 98-106).

---

## Sources & References

### Origin

- **Data Providers Reference:** [docs/reference/2026-03-21-data-providers-api-reference.md](../reference/2026-03-21-data-providers-api-reference.md) — identified 5 gaps + ESMA zero integration
- **Todos 198-216 Reference:** [docs/reference/2026-03-21-todos-198-216-reference.md](../reference/2026-03-21-todos-198-216-reference.md) — implementation details for all data providers

### Internal References

- UX Doctrine: `docs/ux/system-ux-principles.md` — §10 surface, §16 workflow, §17 AI/determinism, §18 cross-vertical, §22 dark mode
- `enrich_region_score`: `quant_engine/regional_macro_service.py` — pure function, tested
- Manager Screener: `backend/app/domains/wealth/routes/manager_screener.py` — 8 existing endpoints
- ESMA Services: `backend/data_providers/esma/register_service.py`, `ticker_resolver.py`
- Macro Worker: `backend/app/domains/wealth/workers/macro_ingestion.py`

### Documented Learnings Applied

- `docs/solutions/architecture-patterns/endpoint-coverage-multi-agent-review-frontend-wiring-20260317.md` — Promise.allSettled, sequence counter, ConfirmDialog mandatory
- `docs/solutions/integration-issues/phantom-calls-missing-ui-wealth-frontend-20260319.md` — backend-first implementation, never raw fetch()
- `docs/solutions/integration-issues/legacy-worker-direct-provider-WealthIngestion-20260319.md` — worker template, lock ID validation
- `docs/solutions/architecture-patterns/wealth-macro-intelligence-suite.md` — BIS data gaps, staleness decay, approve race condition
- `docs/solutions/logic-errors/fastapi-route-shadowing-and-sql-limit-bias-multi-instrument-20260317.md` — literal routes first, date-floor not LIMIT
- `docs/solutions/database-issues/alembic-monorepo-migration-fk-rls-ordering.md` — FK dependency order, global tables no RLS
- `docs/solutions/architecture-patterns/wave1-credit-vertical-modularization-MonolithToPackages-20260315.md` — service.py entry points, error contracts
- `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md` — TopNav, both themes, MetricCard for KPIs, CSS tokens only

### Architectural Constraints

- All new endpoints: `async def` + `AsyncSession` + `response_model=` + `model_validate()`
- All new tables: global (no `organization_id`, no RLS) for data providers
- All new frontend pages: `@netz/ui` formatters, semantic spacing, surface hierarchy
- All new workers: advisory lock with deterministic ID, Redis idempotency, `finally` unlock
- All new charts: ECharts via `ChartContainer` with `netz-theme` (not LayerChart)
- All frontend mutations: `$state(saving)` + `invalidateAll()` + `finally` + dismissible error banner
- All server loaders: `Promise.allSettled` (never `Promise.all`)
- All search inputs: sequence counter pattern (not AbortController)
- All new routers: literal routes registered before parameterized routes + shadowing regression test
