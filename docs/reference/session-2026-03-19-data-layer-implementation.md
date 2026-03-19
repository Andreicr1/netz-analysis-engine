# Session Reference — Data Layer Implementation (2026-03-19)

**Date:** 2026-03-19
**Session:** Crashed before completion — this document records all work executed.
**Prompts used:** 3 fresh-session prompts + 1 in-session edit (the crash)

---

## Summary

Four parallel workstreams were executed in a single session to build the data acquisition and document ingestion layer for the Netz Analysis Engine. Three workstreams were driven by self-contained prompts sent to fresh agents; the fourth (FE fundinfo API swap) was an in-session edit that crashed mid-test-run but completed successfully.

| # | Workstream | Prompt | Status | Files Created | Files Modified | Tests |
|---|-----------|--------|--------|---------------|----------------|-------|
| 1 | FE fundinfo Provider | `docs/prompts/fefundinfo-provider-prompt.md` | Done | 2 new + 1 test | 3 modified | 28 pass |
| 2 | Government Data APIs | `docs/prompts/government-data-apis-prompt.md` | Done | 3 new + 3 tests | 2 modified | ~60 pass |
| 3 | Wealth Document Ingestion | `docs/prompts/wealth-document-ingestion-prompt.md` | Done | 5 new + 1 migration + 1 test | 4 modified | ~12 pass |
| 4 | FE fundinfo API Swap (crash session) | In-session edit (no prompt file) | Done | 0 | 5 modified | 28 pass |

**Total new files:** 16
**Total modified files:** ~14 (some overlap between workstreams)
**Total tests added:** ~100+

---

## Workstream 1: FE fundinfo Provider Integration

**Prompt:** `docs/prompts/fefundinfo-provider-prompt.md`
**Goal:** Replace Yahoo Finance with FE fundinfo as the production fund data source for the wealth vertical.

### Architecture

```
app/services/providers/
  protocol.py                    (existing — NOT modified)
  yahoo_finance_provider.py      (existing — NOT modified)
  fefundinfo_client.py           (NEW — 572 lines)
  fefundinfo_provider.py         (NEW — 275 lines)
  __init__.py                    (MODIFIED — factory function)
```

### New Files

**`fefundinfo_client.py` (572 lines)**
- `_AsyncTokenBucket` — async rate limiter (10 req/s default, lazy lock creation)
- `FEFundInfoTokenManager` — OAuth2 client_credentials flow, 60s refresh margin, in-memory cache
- `FEFundInfoClient` — low-level async HTTP client wrapping 7 FE fundinfo REST APIs:
  - Static API: `get_fees()`, `get_portfolio_managers()`, `get_country_registration()`
  - Static Key Facts API: `get_listing()`, `get_classification()`, `get_fund_information()`, `get_company()`, `get_umbrella()`, `get_share_class()`, `get_sdr()`
  - Dynamic API: `get_pricing()`, `get_aum()`, `get_dividends()`, `get_analytics()`, `get_ratings()`
  - Dynamic Data Series API: `get_nav_series()`, `get_series_delta()`
  - Dynamic Performance API: `get_cumulative_performance_v2()`, `get_annualised_performance()`
  - Ratios & Exposures API: `get_holdings_breakdown()`, `get_exposures_breakdown()`
- Internal: batching (max 10 ISINs), retry with backoff (3 attempts), error classification, correlation ID headers

**`fefundinfo_provider.py` (275 lines)**
- `FEFundInfoProvider` — implements `InstrumentDataProvider` protocol
- Protocol methods (sync, via `_run_async()` bridge):
  - `fetch_instrument(ticker)` → `RawInstrumentData | None`
  - `fetch_batch(tickers)` → `list[RawInstrumentData]`
  - `fetch_batch_history(tickers, period)` → `dict[str, pd.DataFrame]`
- Extended async methods:
  - `fetch_risk_profile()`, `fetch_performance_summary()`, `fetch_fees()`, `fetch_exposures()`, `fetch_holdings()`, `fetch_fund_snapshot()`
- `infer_asset_class()` — classifies fund type from SectorName (bond, money_market, multi_asset, commodity, property, equity)

### Modified Files

- **`__init__.py`** — `get_instrument_provider()` factory: returns `FEFundInfoProvider` when `feature_fefundinfo_enabled=True`
- **`settings.py`** — added `feature_fefundinfo_enabled`, `fefundinfo_client_id`, `fefundinfo_client_secret`, `fefundinfo_subscription_key`, `fefundinfo_token_url`
- **`.env.example`** — added corresponding env vars

### Tests (28 passing)

**`test_fefundinfo_provider.py` (541 lines)**
- `TestTokenManager` (2) — caching, refresh on expiry
- `TestGetAnalytics` (1) — Dynamic API response parsing
- `TestGetCumulativePerformanceV2` (1) — Performance API parsing
- `TestGetFees` (1) — Static API parsing
- `TestGetKeyFacts` (4) — Key Facts API: listing, classification, fund_information, share_class
- `TestBatching` (1) — chunks 25 ISINs into 3 requests (10+10+5)
- `TestErrorHandling` (3) — API error, unsuccessful response, retry on 500
- `TestAuthHeaders` (1) — Bearer token + subscription key headers
- `TestProviderFetchInstrument` (2) — protocol compliance, not-found handling
- `TestProviderFetchBatch` (2) — batch results, error fallback
- `TestProviderFetchBatchHistory` (1) — NAV series as DataFrame
- `TestProviderExtendedMethods` (3) — risk profile, error fallback, fund snapshot aggregation
- `TestAssetClassInference` (3) — bond, money_market, multi_asset classification
- `TestProviderFactory` (2) — Yahoo when disabled, FEFundInfo when enabled
- `TestAsyncTokenBucket` (1) — rate limiter acquire

---

## Workstream 2: Government Data APIs

**Prompt:** `docs/prompts/government-data-apis-prompt.md`
**Goal:** Integrate 3 free government APIs for macro analysis context (Treasury, Data Commons, OFR).

### Architecture

```
quant_engine/
  fred_service.py              (existing — NOT modified)
  fiscal_data_service.py       (NEW — 406 lines)
  data_commons_service.py      (NEW — 332 lines)
  ofr_hedge_fund_service.py    (NEW — 382 lines)
```

### New Files

**`fiscal_data_service.py` (406 lines)**
- `AsyncTokenBucketRateLimiter` — 5 req/s (polite default for unauthenticated API)
- Data models: `TreasuryRate`, `DebtSnapshot`, `AuctionResult`, `ExchangeRate`, `InterestExpense` (frozen dataclasses)
- `FiscalDataService` — async client for `api.fiscaldata.treasury.gov`:
  - `fetch_treasury_rates()` — average interest rates on Treasury securities
  - `fetch_debt_to_penny()` — daily national debt outstanding
  - `fetch_treasury_auctions()` — auction results (yield, bid-to-cover)
  - `fetch_exchange_rates()` — Treasury reporting rates of exchange
  - `fetch_interest_expense()` — monthly interest expense on public debt
- Pagination: `page[size]=10000`, handles `links.next`
- Never-raises pattern, `_parse_float()` with missing-value tolerance

**`data_commons_service.py` (332 lines)**
- Data models: `EconomicObservation`, `DemographicProfile`, `GeoEntity` (frozen dataclasses)
- `DataCommonsService` — async wrapper around `datacommons_client` (sync library → `asyncio.to_thread()`)
  - `fetch_economic_indicators()` — GDP, unemployment, income per geography
  - `fetch_demographic_profile()` — population, age, income, unemployment snapshot
  - `resolve_entity()` — place name → DCID lookup
  - `fetch_geographic_hierarchy()` — parent/child geography relations
- Requires `DC_API_KEY` (free from Google)

**`ofr_hedge_fund_service.py` (382 lines)**
- Data models: `LeverageSnapshot`, `IndustrySizeSnapshot`, `StrategySnapshot`, `CounterpartySnapshot`, `RepoVolumeSnapshot`, `RiskScenarioSnapshot`, `SeriesMetadata` (frozen dataclasses)
- `OFRHedgeFundService` — async client for `data.financialresearch.gov/hf/v1`:
  - `fetch_timeseries()` — generic single-series fetch (base for all specific methods)
  - `fetch_industry_leverage()` — GAV-weighted mean + P5/P50/P95
  - `fetch_industry_size()` — total AUM (GAV, NAV, fund count)
  - `fetch_strategy_breakdown()` — AUM by strategy (credit, equity, macro, etc.)
  - `fetch_counterparty_concentration()` — prime broker concentration
  - `fetch_repo_volumes()` — FICC sponsored repo service volumes
  - `fetch_risk_scenarios()` — stress test results (CDS, equity, rate, FX)
  - `search_series()` — search available mnemonics by keyword
- No auth required (fully open API)

### Modified Files

- **`settings.py`** — added `dc_api_key: str = ""`
- **`.env.example`** — added `DC_API_KEY=`
- **`pyproject.toml`** — added `datacommons-client[Pandas]>=1.0` to quant dependencies

### Tests (~60 passing)

**`test_fiscal_data_service.py` (333 lines)**
- `TestParseFloat`, `TestFetchTreasuryRates`, `TestFetchDebtToPenny`, `TestFetchTreasuryAuctions`, `TestFetchExchangeRates`, `TestFetchInterestExpense`, `TestErrorHandling`, `TestPagination`, `TestAsyncRateLimiter`

**`test_data_commons_service.py` (225 lines)**
- `TestFetchEconomicIndicators`, `TestFetchDemographicProfile`, `TestResolveEntity`, `TestFetchGeographicHierarchy`

**`test_ofr_hedge_fund_service.py` (291 lines)**
- `TestParseValue`, `TestFetchTimeseries`, `TestFetchIndustryLeverage`, `TestFetchIndustrySize`, `TestFetchStrategyBreakdown`, `TestFetchCounterpartyConcentration`, `TestFetchRepoVolumes`, `TestFetchRiskScenarios`, `TestSearchSeries`

---

## Workstream 3: Wealth Document Ingestion

**Prompt:** `docs/prompts/wealth-document-ingestion-prompt.md`
**Goal:** Give the wealth vertical document upload and ingestion capability, reusing the existing unified pipeline.

### Architecture

```
app/domains/wealth/
  models/document.py              (NEW — 78 lines)
  schemas/document.py             (NEW — 100 lines)
  services/document_service.py    (NEW — 245 lines)
  routes/documents.py             (NEW — 371 lines)
  models/__init__.py              (MODIFIED — exports new models)

app/core/db/migrations/versions/
  0020_wealth_documents.py        (NEW — migration)

app/shared/enums.py               (MODIFIED — DocumentIngestionStatus moved here)
app/domains/credit/documents/enums.py  (MODIFIED — now imports from shared)
app/main.py                       (MODIFIED — router registration)
backend/manifests/routes.json     (MODIFIED — route manifest)
```

### New Files

**`models/document.py` (78 lines)**
- `WealthDocument` — ORM model scoped to portfolios/instruments (not deals):
  - Fields: `portfolio_id`, `instrument_id`, `title`, `filename`, `content_type`, `root_folder`, `subfolder_path`, `domain`, `current_version`
  - Indexes: org+portfolio, org+instrument
  - Unique constraint: org+folder+subfolder+title
  - All relationships with `lazy="raise"`
- `WealthDocumentVersion` — versioning + ingestion tracking:
  - Fields: `document_id` (FK), `version_number`, `blob_uri`, `blob_path`, `checksum`, `file_size_bytes`
  - Ingestion: `ingestion_status` (shared enum), `ingestion_error`, `indexed_at`
  - Audit: `uploaded_by`, `uploaded_at`

**`schemas/document.py` (100 lines)**
- `WealthDocumentOut`, `WealthDocumentVersionOut` — response models
- `WealthUploadUrlRequest`, `WealthUploadUrlResponse` — presigned URL flow
- `WealthUploadCompleteRequest`, `WealthUploadCompleteResponse` — finalize upload
- `WealthProcessPendingRequest`, `WealthProcessPendingResponse` — trigger pipeline
- `WealthDocumentPage` — paginated list

**`services/document_service.py` (245 lines)**
- `UploadResult` — dataclass for upload metadata
- `create_document_pending()` — create document + version with PENDING status
- `upload_document()` — write to storage, create records
- `list_documents()` — paginated, filtered by portfolio/instrument/domain

**`routes/documents.py` (371 lines)**
- `POST /api/v1/wealth/documents/upload-url` — presigned URL generation
- `POST /api/v1/wealth/documents/upload-complete` — mark PROCESSING, emit SSE
- `POST /api/v1/wealth/documents/upload` — direct upload (multipart)
- `POST /api/v1/wealth/documents/ingestion/process-pending` — trigger unified pipeline
- `GET /api/v1/wealth/documents` — list with filters
- `GET /api/v1/wealth/documents/{document_id}` — single document
- Auth: all routes require `Role.INVESTMENT_TEAM` or `Role.ADMIN`

**`0020_wealth_documents.py` (migration)**
- Creates `wealth_documents` and `wealth_document_versions` tables
- Reuses existing `document_ingestion_status_enum` from credit migration
- RLS policies with `(SELECT current_setting(...))` subselect pattern

### Modified Files

- **`app/shared/enums.py`** — `DocumentIngestionStatus` moved here (shared between credit and wealth)
- **`app/domains/credit/documents/enums.py`** — now imports from `app.shared.enums`
- **`app/domains/wealth/models/__init__.py`** — exports `WealthDocument`, `WealthDocumentVersion`
- **`app/main.py`** — registers `wealth_documents_router`
- **`backend/manifests/routes.json`** — 6 new wealth document endpoints

### Tests (~12 passing)

**`test_wealth_documents.py` (187 lines)**
- `TestRouteRegistration`, `TestAuthEnforcement`, `TestUploadValidation`, `TestSchemaImports`, `TestUploadUrlFlow`

---

## Workstream 4: FE fundinfo API Swap (Crash Session)

**Context:** After Workstream 1 was implemented with Custom Data API methods, the session that was editing the fefundinfo client to replace Custom Data API with Static Key Facts API crashed mid-execution. All edits were applied successfully before the crash.

**No prompt file** — this was an in-session correction based on API review.

### Changes Made

**Removed: Custom Data API (7 methods + URL + scopes + `data_client_id`)**

```
REMOVED from FEFundInfoClient:
  URL_CUSTOM = "https://api.fefundinfo.com/customdata/1.0.0"
  get_additional_instruments()
  get_risk_data()
  get_discrete_performance()
  get_calendar_performance()
  get_cumulative_performance()
  get_chart_data()
  get_since_launch()

REMOVED scopes:
  additional-instruments-read, riskdata-read, discreteperformance-read,
  calendarperformance-read, cumulativeperformanceandrank-read,
  chartdata-read, since-launch-read

REMOVED setting:
  fefundinfo_data_client_id (settings.py, .env.example, factory)
```

**Added: Static Key Facts API (7 endpoints)**

```
ADDED to FEFundInfoClient:
  URL_KEY_FACTS = "https://api.fefundinfo.com/funds/StaticKeyFacts/1.0.0"
  _key_facts_get() — helper (identifierType=isins pattern)
  get_listing()         — Bloomberg/Reuters codes, exchange, launch price
  get_classification()  — MiFID, EFAMA, Sharia compliance
  get_fund_information() — structure, domicile, objectives, benchmark
  get_company()         — management company data
  get_umbrella()        — fund family data
  get_share_class()     — distribution type, hedging, minimum investment
  get_sdr()             — Sustainability Disclosure Requirements, ESG labels

ADDED scopes:
  static-key-facts-read, sdr-read
```

**Provider method remapping:**

| Before (Custom Data) | After (remaining APIs) |
|---|---|
| `get_additional_instruments()` | `get_fund_information()` (Key Facts) |
| `get_risk_data()` | `get_analytics()` (Dynamic API) |

### Files Modified

1. **`fefundinfo_client.py`** — removed Custom Data section (116 lines), added Key Facts section (46 lines), updated docstrings/URLs/scopes
2. **`fefundinfo_provider.py`** — `fetch_instrument`/`fetch_batch` → `get_fund_information()`, `fetch_risk_profile`/`fetch_fund_snapshot` → `get_analytics()`
3. **`__init__.py`** — removed `data_client_id` param from factory
4. **`settings.py`** — removed `fefundinfo_data_client_id`
5. **`.env.example`** — removed `FEFUNDINFO_DATA_CLIENT_ID`

### Test Updates

All 28 tests updated to use new method names. All passing.

---

## Cross-Cutting Changes

### Shared Enum Extraction

`DocumentIngestionStatus` was moved from `app.domains.credit.documents.enums` to `app.shared.enums` so both credit and wealth document models can reference the same enum type. The credit enum module now re-imports from shared.

### Settings Summary (all new settings added)

```python
# FE fundinfo
feature_fefundinfo_enabled: bool = False
fefundinfo_client_id: str = ""
fefundinfo_client_secret: str = ""
fefundinfo_subscription_key: str = ""
fefundinfo_token_url: str = "https://auth.fefundinfo.com/connect/token"

# Data Commons
dc_api_key: str = ""
```

### Dependencies Added

- `datacommons-client[Pandas]>=1.0` — in `pyproject.toml` under `[quant]` extras

---

## File Inventory

### New Files (16)

| File | Lines | Workstream |
|------|-------|------------|
| `backend/app/services/providers/fefundinfo_client.py` | 572 | 1 + 4 |
| `backend/app/services/providers/fefundinfo_provider.py` | 275 | 1 + 4 |
| `backend/quant_engine/fiscal_data_service.py` | 406 | 2 |
| `backend/quant_engine/data_commons_service.py` | 332 | 2 |
| `backend/quant_engine/ofr_hedge_fund_service.py` | 382 | 2 |
| `backend/app/domains/wealth/models/document.py` | 78 | 3 |
| `backend/app/domains/wealth/schemas/document.py` | 100 | 3 |
| `backend/app/domains/wealth/services/document_service.py` | 245 | 3 |
| `backend/app/domains/wealth/routes/documents.py` | 371 | 3 |
| `backend/app/core/db/migrations/versions/0020_wealth_documents.py` | ~150 | 3 |
| `backend/tests/test_fefundinfo_provider.py` | 541 | 1 + 4 |
| `backend/tests/test_fiscal_data_service.py` | 333 | 2 |
| `backend/tests/test_data_commons_service.py` | 225 | 2 |
| `backend/tests/test_ofr_hedge_fund_service.py` | 291 | 2 |
| `backend/tests/test_wealth_documents.py` | 187 | 3 |
| `docs/reference/data-architecture-and-safeguards.md` | 427 | — |

### Modified Files

| File | Changes | Workstream |
|------|---------|------------|
| `backend/app/services/providers/__init__.py` | Factory function (removed `data_client_id`) | 1 + 4 |
| `backend/app/core/config/settings.py` | Added fefundinfo + dc settings, removed `data_client_id` | 1 + 2 + 4 |
| `.env.example` | Added env vars, removed `DATA_CLIENT_ID` | 1 + 2 + 4 |
| `backend/app/shared/enums.py` | Added `DocumentIngestionStatus` | 3 |
| `backend/app/domains/credit/documents/enums.py` | Re-import from shared | 3 |
| `backend/app/domains/wealth/models/__init__.py` | Export new models | 3 |
| `backend/app/main.py` | Register wealth documents router | 3 |
| `backend/manifests/routes.json` | 6 new wealth document endpoints | 3 |
| `pyproject.toml` | `datacommons-client[Pandas]` dependency | 2 |

---

## What Was NOT Implemented (deferred)

These items were specified in the prompts but not yet executed:

1. **FE fundinfo ingestion worker** (`workers/fefundinfo_ingestion.py`) — periodic sync of fund universe data to R2
2. **Government data ingestion worker** (`workers/macro_government_data_ingestion`) — weekly sync to `gold/_global/` and `macro_data` table
3. **Integration into vertical engines** — connecting government data to credit IC memos, wealth DD reports, screener
4. **R2 gold layer folder structure** for `fefundinfo/`, `fiscal_data/`, `ofr_hedge_fund/`, `data_commons/`
5. **Import-linter contracts** for the 3 new quant_engine services

These are Phase 2 items that depend on the clients working correctly (which they now do).
