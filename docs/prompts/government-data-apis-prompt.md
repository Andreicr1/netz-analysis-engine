# Government Data APIs Integration — Implementation Prompt

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Context

The Netz Analysis Engine uses several external data APIs for macro analysis, fund screening, and IC memo context. Currently integrated: FRED (45 macro series), SEC EDGAR (company filings), Yahoo Finance (NAV/prices).

Three additional **free government APIs** must be integrated to enrich analysis with authoritative data that replaces expensive paid sources (Bloomberg, Lipper, Refinitiv):

1. **U.S. Treasury Fiscal Data API** — federal debt, treasury rates, auctions, exchange rates
2. **Data Commons API** (Google) — demographics, GDP, unemployment, geographic hierarchies
3. **OFR Hedge Fund Monitor API** — hedge fund leverage, AUM, counterparty risk, Form PF stats

All three follow the same integration pattern as the existing `fred_service.py`: httpx client, rate limiting, error handling, data normalization, storage to data lake and/or PostgreSQL.

## Reference Files (read these first)

```
# Existing pattern to follow
backend/quant_engine/fred_service.py              # FRED client (TokenBucket rate limiter, batch fetch)
backend/vertical_engines/credit/market_data/service.py  # Market data orchestrator
backend/vertical_engines/credit/market_data/fred_client.py  # FRED wrapper for credit vertical

# Wealth workers (where macro/screening data is consumed)
backend/app/domains/wealth/workers/macro_ingestion.py   # FRED macro ingestion worker
backend/app/domains/wealth/workers/screening_batch.py   # Screening batch worker

# Storage routing (for gold layer persistence)
backend/ai_engine/pipeline/storage_routing.py      # Path helpers

# Skill documentation (API specs)
.claude/skills/scientific-skills/usfiscaldata/SKILL.md
.claude/skills/scientific-skills/usfiscaldata/references/   # All reference files
.claude/skills/scientific-skills/datacommons-client/SKILL.md
.claude/skills/scientific-skills/datacommons-client/references/
.claude/skills/scientific-skills/hedgefundmonitor/SKILL.md
.claude/skills/scientific-skills/hedgefundmonitor/references/

# Settings
backend/app/core/config/settings.py
.env.example
```

## Architecture Decision

All three clients go in `backend/quant_engine/` alongside `fred_service.py` — they are vertical-agnostic data services consumed by both credit and wealth verticals.

```
quant_engine/
  fred_service.py          (existing)
  fiscal_data_service.py   (NEW — US Treasury)
  data_commons_service.py  (NEW — Data Commons)
  ofr_hedge_fund_service.py (NEW — OFR HFM)
```

Workers that ingest the data go in their respective domain workers. The data lands in:
- `macro_data` PostgreSQL table (operational: regime detection, daily pipeline)
- `gold/_global/` R2 paths (analytical: backtesting, cross-fund correlation)

---

## Implementation: Service 1 — US Treasury Fiscal Data

### 1.1 Client: `quant_engine/fiscal_data_service.py`

**Base URL:** `https://api.fiscaldata.treasury.gov/services/api/fiscal_service`
**Auth:** None (fully open)

**Class: `FiscalDataService`**

Constructor parameters:
- `http_client: httpx.AsyncClient` (injected, allows test mocking)
- `rate_limiter: TokenBucketRateLimiter | None` (optional, API has no documented rate limit but be polite — 5 req/sec)

**Methods:**

```python
async def fetch_treasury_rates(self, start_date: str) -> list[TreasuryRate]:
    """Average interest rates on Treasury securities.
    Endpoint: /v2/accounting/od/avg_interest_rates
    Fields: record_date, security_desc, avg_interest_rate_amt
    Filter: record_date:gte:{start_date}
    """

async def fetch_debt_to_penny(self, start_date: str) -> list[DebtSnapshot]:
    """Daily national debt outstanding.
    Endpoint: /v2/accounting/od/debt_to_penny
    Fields: record_date, tot_pub_debt_out_amt, intragov_hold_amt, debt_held_public_amt
    """

async def fetch_treasury_auctions(self, start_date: str) -> list[AuctionResult]:
    """Recent Treasury securities auction results.
    Endpoint: /v1/accounting/od/auctions_query
    Fields: auction_date, security_type, security_term, high_yield, bid_to_cover_ratio
    """

async def fetch_exchange_rates(self, start_date: str) -> list[ExchangeRate]:
    """Treasury reporting rates of exchange.
    Endpoint: /v1/accounting/od/rates_of_exchange
    Fields: country_currency_desc, exchange_rate, record_date
    """

async def fetch_interest_expense(self, start_date: str) -> list[InterestExpense]:
    """Monthly interest expense on the public debt.
    Endpoint: /v2/accounting/od/interest_expense
    Fields: record_date, expense_catg_desc, month_expense_amt, fytd_expense_amt
    """
```

**Data models:** Frozen dataclasses in same file (like `fred_service.py` pattern). All values parsed from strings to proper types (float, date).

**Pagination:** Use `page[size]=10000` to minimize requests. Handle `links.next` for datasets exceeding page size.

**Error handling:** Never-raises pattern. Return empty list on failure, log warning.

### 1.2 Integration Points

- **Credit IC Memos:** Treasury rate context for deal analysis (current 10Y rate, auction demand via bid-to-cover)
- **Credit Market Data:** Add treasury rates to `get_macro_snapshot()` in `vertical_engines/credit/market_data/service.py`
- **Wealth Macro Intelligence:** National debt trend, interest expense trajectory for macro committee reports
- **Gold layer:** `gold/_global/fiscal_data/treasury_rates.parquet`, `gold/_global/fiscal_data/debt_daily.parquet`

---

## Implementation: Service 2 — Data Commons

### 2.1 Client: `quant_engine/data_commons_service.py`

**Base URL:** `https://api.datacommons.org/v2/`
**Auth:** API key (free, set via `DC_API_KEY` env var)

**Dependency:** `datacommons-client[Pandas]` — add to `pyproject.toml` under `[project.optional-dependencies] quant`.

**Class: `DataCommonsService`**

Constructor parameters:
- `api_key: str` (from settings)

**Methods:**

```python
async def fetch_economic_indicators(
    self, entity_dcids: list[str], variables: list[str], date: str = "latest"
) -> list[EconomicObservation]:
    """Fetch economic indicators (GDP, unemployment, income) for given entities.
    Variables: UnemploymentRate_Person, Amount_EconomicActivity_GrossDomesticProduction,
               MedianIncome_Household, Count_Person, etc.
    """

async def fetch_demographic_profile(
    self, geo_dcid: str
) -> DemographicProfile:
    """Aggregate demographic snapshot for a geography.
    Population, age distribution, income, unemployment.
    Used for regional market context in IC memos and DD reports.
    """

async def resolve_entity(self, name: str, entity_type: str = "State") -> str | None:
    """Resolve a place name to a DCID for subsequent queries."""

async def fetch_geographic_hierarchy(
    self, parent_dcid: str, child_type: str = "County"
) -> list[GeoEntity]:
    """List child entities for a geography (e.g., all counties in a state)."""
```

**Note:** The `datacommons-client` library is sync. Wrap calls with `asyncio.to_thread()` (same pattern as EDGAR's `edgartools`).

### 2.2 Settings

Add to `settings.py`:
```python
# ── Data Commons ──────────────────────────────────────────
dc_api_key: str = ""  # Free key from https://apikeys.datacommons.org/
```

Add to `.env.example`:
```
DC_API_KEY=
```

### 2.3 Integration Points

- **Credit IC Memos:** Regional economic context for deal geography (unemployment, income, population trends)
- **Wealth DD Reports:** Demographic backdrop for fund strategy assessment
- **Wealth Screening:** Market context data for instrument screening
- **Gold layer:** `gold/_global/data_commons/economic_indicators.parquet`

---

## Implementation: Service 3 — OFR Hedge Fund Monitor

### 3.1 Client: `quant_engine/ofr_hedge_fund_service.py`

**Base URL:** `https://data.financialresearch.gov/hf/v1`
**Auth:** None (fully open)

**Class: `OFRHedgeFundService`**

Constructor parameters:
- `http_client: httpx.AsyncClient` (injected)
- `rate_limiter: TokenBucketRateLimiter | None` (optional — 5 req/sec)

**Methods:**

```python
async def fetch_industry_leverage(self, start_date: str) -> list[LeverageSnapshot]:
    """Hedge fund industry leverage ratios over time.
    Mnemonic: FPF-ALLQHF_LEVERAGERATIO_GAVWMEAN (GAV-weighted mean)
    Also: P5, P50, P95 for distribution.
    """

async def fetch_industry_size(self, start_date: str) -> list[IndustrySizeSnapshot]:
    """Hedge fund industry total AUM (GAV, NAV, fund count).
    Mnemonics: FPF-ALLQHF_GAV_SUM, FPF-ALLQHF_NAV_SUM, FPF-ALLQHF_COUNT
    """

async def fetch_strategy_breakdown(self, start_date: str) -> list[StrategySnapshot]:
    """AUM by strategy (credit, equity, macro, multi, relative value).
    Mnemonics: FPF-STRATEGY_{name}_GAV_SUM for each strategy.
    """

async def fetch_counterparty_concentration(self, start_date: str) -> list[CounterpartySnapshot]:
    """Prime broker concentration and counterparty risk metrics.
    Mnemonic patterns: FPF-ALLQHF_COUNTERPARTY_*
    """

async def fetch_repo_volumes(self, start_date: str) -> list[RepoVolumeSnapshot]:
    """FICC sponsored repo service volumes.
    Mnemonic: FICC-SPONSORED_REPO_VOL
    """

async def fetch_risk_scenarios(self, start_date: str) -> list[RiskScenarioSnapshot]:
    """Stress test results: CDS spread, equity decline, rate shock, FX scenarios.
    Mnemonic patterns: FPF-ALLQHF_STRESS_*
    """

async def search_series(self, query: str) -> list[SeriesMetadata]:
    """Search available mnemonics by keyword.
    Endpoint: /metadata/search?query={query}
    """

async def fetch_timeseries(
    self, mnemonic: str, start_date: str, periodicity: str = "Q"
) -> list[tuple[str, float]]:
    """Generic single-series fetch. Used by all specific methods above.
    Endpoint: /series/timeseries?mnemonic={mnemonic}&start_date={start_date}
    """
```

### 3.2 Integration Points

- **Wealth Fund Screening:** Compare fund leverage/AUM against industry benchmarks (OFR provides the benchmark)
- **Wealth DD Reports:** "Industry Context" chapter — where does this fund sit vs. industry leverage/size distribution?
- **Wealth Peer Comparison:** Strategy-level AUM and leverage percentiles (P5/P50/P95 from Form PF)
- **Credit IC Memos:** Systemic risk context — repo volumes, counterparty concentration trends
- **Macro Committee Reports:** Industry-level risk indicators for weekly macro assessment
- **Gold layer:** `gold/_global/ofr_hedge_fund/industry_leverage.parquet`, `gold/_global/ofr_hedge_fund/strategy_breakdown.parquet`

---

## Implementation: Service 4 — Worker Integration

### 4.1 New Worker: `macro_government_data_ingestion`

Add to `backend/app/domains/wealth/workers/` or create a shared worker.

**Trigger:** `POST /api/v1/workers/run-government-data-ingestion`
**Schedule:** Weekly (data updates quarterly for Form PF, monthly for FICC/TFF)

**Flow:**
1. Fetch US Treasury rates + debt + auctions (FiscalDataService)
2. Fetch OFR industry leverage + size + strategy (OFRHedgeFundService)
3. Fetch Data Commons economic indicators for tracked geographies (DataCommonsService)
4. Write Parquet files to `gold/_global/` paths in R2
5. Upsert key series to `macro_data` PostgreSQL table (for runtime queries)

### 4.2 R2 Structure (add to seed script)

```
gold/_global/fiscal_data/
  treasury_rates.parquet
  debt_daily.parquet
  auction_results.parquet
  exchange_rates.parquet
gold/_global/ofr_hedge_fund/
  industry_leverage.parquet
  industry_size.parquet
  strategy_breakdown.parquet
  counterparty_concentration.parquet
  repo_volumes.parquet
gold/_global/data_commons/
  economic_indicators.parquet
```

---

## Implementation: Step-by-Step

### Step 1: Dependencies

Add to `pyproject.toml` under `quant` optional dependencies:
```toml
"datacommons-client[Pandas]>=1.0",
```

No new dependencies needed for Treasury Fiscal Data or OFR — they use `httpx` (already in core deps).

### Step 2: Settings

Add to `backend/app/core/config/settings.py`:
```python
# ── Data Commons ──────────────────────────────────────────
dc_api_key: str = ""
```

Add to `.env.example` and `.env.production`.

### Step 3: Implement Services

Create in order:
1. `quant_engine/fiscal_data_service.py`
2. `quant_engine/ofr_hedge_fund_service.py`
3. `quant_engine/data_commons_service.py`

Follow `fred_service.py` patterns exactly:
- Config as constructor parameter (no global state, no `@lru_cache`)
- `httpx.AsyncClient` injected (test-mockable)
- Rate limiting via `TokenBucketRateLimiter` (from fred_service or shared)
- Never-raises pattern (return empty on failure, log warning)
- Frozen dataclasses for all return types

### Step 4: Import-Linter Contracts

Add vertical-agnosticism contracts in `pyproject.toml` for all three services:
```toml
[tool.importlinter:contract:fiscal_data_vertical_agnostic]
name = "fiscal_data_service must not import wealth domain"
type = "forbidden"
source_modules = ["quant_engine.fiscal_data_service"]
forbidden_modules = ["app.domains.wealth"]

# Same for ofr_hedge_fund_service and data_commons_service
```

### Step 5: Worker Route

Add `POST /api/v1/workers/run-government-data-ingestion` to wealth workers (or shared admin workers).

### Step 6: R2 Folder Structure

Add new `gold/_global/` subfolders via seed script or manually.

### Step 7: Integrate into Existing Consumers

- Add treasury rate context to `vertical_engines/credit/market_data/service.py::get_macro_snapshot()`
- Add OFR industry benchmarks to `vertical_engines/wealth/screener/service.py`
- Add OFR leverage context to wealth DD report chapters
- Add Data Commons demographic context to credit IC memo regional analysis

### Step 8: Tests

Create:
- `backend/tests/test_fiscal_data_service.py` — mock httpx responses, test parsing, test error handling
- `backend/tests/test_ofr_hedge_fund_service.py` — same pattern
- `backend/tests/test_data_commons_service.py` — mock datacommons-client responses

### Step 9: Verify

```bash
make check  # Must pass: lint + architecture + typecheck + all tests
```

---

## Critical Rules (from CLAUDE.md)

- All services receive config as parameter (no YAML loading, no `@lru_cache`)
- Config resolved once at async entry point via `ConfigService.get()`, passed down to sync functions
- `quant_engine/` services must NOT import from `app.domains.wealth` or `app.domains.credit` (import-linter enforced)
- StorageClient for all storage writes — never call boto3 directly
- `gold/_global/` paths via `global_reference_path()` — never build with f-strings
- Parquet files must use zstd compression
- Never-raises pattern for all data fetch methods

## What NOT to Do

- Do not modify `fred_service.py` — the new services are peers, not extensions
- Do not create vertical-specific clients — all three services go in `quant_engine/`
- Do not add these APIs to the unified pipeline — they are reference data, not document processing
- Do not store API responses in Redis — they go to PostgreSQL (`macro_data`) and R2 (`gold/_global/`)
- Do not add new feature flags — these are core data services, always available
