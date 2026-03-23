# FE fundinfo Provider Integration — Implementation Prompt

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Context

The Netz wealth vertical uses `InstrumentDataProvider` protocol (`backend/app/services/providers/protocol.py`) to abstract market data sources. Currently only `YahooFinanceProvider` implements it (dev/internal use). FE fundinfo is the production data source replacing Yahoo Finance for fund screening, DD reports, peer comparison, watchlist monitoring, and portfolio analytics.

FE fundinfo provides 6 REST APIs with OAuth2 client credentials auth. OpenAPI specs are in `docs/api_docs/`. The provider must implement the existing `InstrumentDataProvider` protocol AND expose additional methods for the richer data FE fundinfo offers (risk, exposures, performance series, fees, holdings).

## Reference Files (read these first)

```
# Provider protocol and existing implementation
backend/app/services/providers/protocol.py              # InstrumentDataProvider protocol + RawInstrumentData
backend/app/services/providers/yahoo_finance_provider.py # Pattern to follow

# Wealth engines that consume provider data
backend/vertical_engines/wealth/screener/service.py
backend/vertical_engines/wealth/dd_report/
backend/vertical_engines/wealth/peer_group/service.py
backend/vertical_engines/wealth/watchlist/service.py
backend/vertical_engines/wealth/monitoring/service.py

# Existing workers
backend/app/domains/wealth/workers/benchmark_ingest.py   # Worker pattern

# FE fundinfo OpenAPI specs (ALL 6 — read schemas carefully)
docs/api_docs/Custom Data APIs.yaml                      # Performance, risk, chart data
docs/api_docs/Fund Data Static API.yaml                  # Fees, managers, country registration
docs/api_docs/Fund Data Dynamic API.yaml                 # NAV, AUM, dividends, ratings, analytics
docs/api_docs/Fund Data Dynamic Data Series.yaml         # NAV time series (49 series types), delta sync
docs/api_docs/Fund Data Dynamic Data Performance API.yaml # Cumulative, annualised, calendar, discrete performance
docs/api_docs/Fund Ratios and Exposures.yaml             # Holdings, geographic/sector/currency/ratings exposure

# Settings
backend/app/core/config/settings.py
.env.example
.env.production
```

## Architecture Decision

The FE fundinfo integration consists of:

1. **OAuth2 token manager** — handles client_credentials flow + token caching
2. **FEFundInfoClient** — low-level HTTP client wrapping all 6 APIs
3. **FEFundInfoProvider** — implements `InstrumentDataProvider` + extended methods
4. **Ingestion worker** — periodic sync of fund universe data

```
app/services/providers/
  protocol.py                    (existing — DO NOT MODIFY)
  yahoo_finance_provider.py      (existing — DO NOT MODIFY)
  fefundinfo_client.py           (NEW — low-level API client)
  fefundinfo_provider.py         (NEW — implements InstrumentDataProvider)
```

---

## Implementation Steps

### Step 1: Settings

Add to `backend/app/core/config/settings.py`:

```python
# ── FE fundinfo ────────────────────────────────────────────
feature_fefundinfo_enabled: bool = False
fefundinfo_client_id: str = ""        # OAuth2 client ID
fefundinfo_client_secret: str = ""    # OAuth2 client secret
fefundinfo_subscription_key: str = "" # Fefi-Apim-Subscription-Key header
fefundinfo_data_client_id: str = ""   # clientid query param (Custom Data API)
fefundinfo_token_url: str = "https://auth.fefundinfo.com/connect/token"
```

Add to `.env.example`:

```
# ── FE fundinfo (production fund data provider) ─────────────
FEATURE_FEFUNDINFO_ENABLED=false
FEFUNDINFO_CLIENT_ID=
FEFUNDINFO_CLIENT_SECRET=
FEFUNDINFO_SUBSCRIPTION_KEY=
FEFUNDINFO_DATA_CLIENT_ID=
```

### Step 2: OAuth2 Token Manager + API Client

Create `backend/app/services/providers/fefundinfo_client.py`:

**Class: `FEFundInfoTokenManager`**

```python
class FEFundInfoTokenManager:
    """OAuth2 client_credentials token manager with auto-refresh."""

    def __init__(self, client_id: str, client_secret: str, token_url: str):
        ...

    async def get_token(self) -> str:
        """Return valid access token, refreshing if expired (with 60s margin)."""
        ...
```

- Token URL: `https://auth.fefundinfo.com/connect/token`
- Grant type: `client_credentials`
- Scopes: all scopes from the OpenAPI specs (additional-instruments-read, riskdata-read, discreteperformance-read, calendarperformance-read, cumulativeperformanceandrank-read, chartdata-read, since-launch-read, plus scopes from other APIs)
- Cache token in memory, refresh 60s before expiry
- Use `httpx.AsyncClient` for token requests

**Class: `FEFundInfoClient`**

```python
class FEFundInfoClient:
    """Low-level async client for all 6 FE fundinfo APIs."""

    def __init__(
        self,
        token_manager: FEFundInfoTokenManager,
        subscription_key: str,
        data_client_id: str,
        http_client: httpx.AsyncClient | None = None,
    ):
        ...
```

Base URLs (from OpenAPI specs):
- Custom Data: `https://api.fefundinfo.com/customdata/1.0.0`
- Static: `https://api.fefundinfo.com/funds/Static/1.0.0`
- Dynamic: `https://api.fefundinfo.com/funds/Dynamic/1.0.0`
- Dynamic Data Series: `https://api.fefundinfo.com/funds/DynamicDataSeries/1.0.0`
- Dynamic Performance: `https://api.fefundinfo.com/funds/DynamicPerformance/1.0.0`
- Ratios & Exposures: `https://api.fefundinfo.com/funds/RatiosAndExposures/1.0.0`

**Headers on every request:**
- `Authorization: Bearer {token}`
- `Fefi-Apim-Subscription-Key: {subscription_key}`
- `x-correlation-id: {uuid4}` (for tracing)

**Methods — Custom Data API:**

```python
async def get_additional_instruments(self, isins: list[str]) -> list[dict]: ...
async def get_risk_data(self, isins: list[str], currency: str = "USD") -> list[dict]: ...
async def get_discrete_performance(self, instrument_codes: list[str], currency: str = "USD") -> list[dict]: ...
async def get_calendar_performance(self, instrument_codes: list[str], currency: str = "USD") -> list[dict]: ...
async def get_cumulative_performance(self, instrument_codes: list[str], currency: str = "USD") -> list[dict]: ...
async def get_chart_data(self, driver_isin: str, currency: str = "USD", period: int = 36) -> list[dict]: ...
async def get_since_launch(self, isins: list[str], currency: str = "USD") -> list[dict]: ...
```

**Methods — Static API:**

```python
async def get_fees(self, isins: list[str]) -> list[dict]: ...
async def get_portfolio_managers(self, isins: list[str]) -> list[dict]: ...
```

**Methods — Dynamic API:**

```python
async def get_pricing(self, isins: list[str]) -> list[dict]: ...
async def get_aum(self, isins: list[str]) -> list[dict]: ...
async def get_dividends(self, isins: list[str]) -> list[dict]: ...
async def get_analytics(self, isins: list[str]) -> list[dict]: ...
async def get_ratings(self, isins: list[str]) -> list[dict]: ...
```

**Methods — Dynamic Data Series API:**

```python
async def get_nav_series(
    self, isins: list[str], series_type: str = "BidTr", period: str = "Daily",
    start_date: str | None = None, end_date: str | None = None,
) -> list[dict]: ...

async def get_series_delta(
    self, isins: list[str], series_type: str = "BidTr",
    from_date: str | None = None,
) -> list[dict]: ...
```

**Methods — Dynamic Performance API:**

```python
async def get_cumulative_performance_v2(
    self, isins: list[str], currency: str = "USD", period_end: str = "MonthEnd",
) -> list[dict]: ...

async def get_annualised_performance(
    self, isins: list[str], currency: str = "USD",
) -> list[dict]: ...
```

**Methods — Ratios & Exposures API:**

```python
async def get_holdings_breakdown(self, isins: list[str]) -> list[dict]: ...
async def get_exposures_breakdown(self, isins: list[str]) -> list[dict]: ...
```

**Common patterns for all methods:**
- Max 10 ISINs per request (API limit) — batch internally if more
- Identifier type: `isins` (default), also support `citicodes`
- Parse response: check `IsSuccess`, extract `Result` array
- Rate limiting: 10 req/sec token bucket (adjust based on contract)
- Retry: 3 attempts with exponential backoff for 429/5xx
- Never-raises: return empty list on failure, log warning
- Timeout: 30 seconds per request

### Step 3: FEFundInfoProvider

Create `backend/app/services/providers/fefundinfo_provider.py`:

```python
class FEFundInfoProvider:
    """Implements InstrumentDataProvider + extended methods for FE fundinfo."""

    def __init__(self, client: FEFundInfoClient): ...

    # ── InstrumentDataProvider protocol ────────────────────
    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None:
        """Sync wrapper — calls async client via asyncio.to_thread pattern."""
        ...

    def fetch_batch(self, tickers: list[str]) -> list[RawInstrumentData]:
        """Batch fetch instrument metadata. Tickers are ISINs."""
        ...

    def fetch_batch_history(
        self, tickers: list[str], period: str = "3y"
    ) -> dict[str, pd.DataFrame]:
        """Fetch NAV time series via Dynamic Data Series API."""
        ...

    # ── Extended methods (FE fundinfo specific) ────────────
    async def fetch_risk_profile(self, isin: str, currency: str = "USD") -> dict: ...
    async def fetch_performance_summary(self, isin: str, currency: str = "USD") -> dict: ...
    async def fetch_fees(self, isin: str) -> dict: ...
    async def fetch_exposures(self, isin: str) -> dict: ...
    async def fetch_holdings(self, isin: str) -> list[dict]: ...
    async def fetch_fund_snapshot(self, isin: str, currency: str = "USD") -> dict:
        """Aggregate call: instrument + risk + performance + fees + AUM.
        Used by DD reports and screener for complete fund profile."""
        ...
```

The `fetch_instrument` method maps FE fundinfo fields to `RawInstrumentData`:
- `ticker` = ISIN
- `isin` = ISIN
- `name` = ShareClassName from additional instruments
- `instrument_type` = "fund" (always for FE fundinfo)
- `asset_class` = derived from SectorName
- `geography` = from exposures or country registration
- `currency` = from instrument data
- `source` = "fefundinfo"
- `raw_attributes` = full response dict (fees, AUM, risk, etc.)

### Step 4: Provider Factory

Create or update `backend/app/services/providers/__init__.py`:

```python
def get_instrument_provider() -> InstrumentDataProvider:
    """Factory — returns FEFundInfo in production, Yahoo in dev."""
    if settings.feature_fefundinfo_enabled:
        from app.services.providers.fefundinfo_client import FEFundInfoClient, FEFundInfoTokenManager
        from app.services.providers.fefundinfo_provider import FEFundInfoProvider
        token_mgr = FEFundInfoTokenManager(
            client_id=settings.fefundinfo_client_id,
            client_secret=settings.fefundinfo_client_secret,
            token_url=settings.fefundinfo_token_url,
        )
        client = FEFundInfoClient(
            token_manager=token_mgr,
            subscription_key=settings.fefundinfo_subscription_key,
            data_client_id=settings.fefundinfo_data_client_id,
        )
        return FEFundInfoProvider(client)
    return YahooFinanceProvider()
```

### Step 5: Ingestion Worker

Add to `backend/app/domains/wealth/workers/fefundinfo_ingestion.py`:

```python
async def run_fefundinfo_ingestion(
    db: AsyncSession, actor_id: str, organization_id: UUID
) -> dict:
    """Sync fund universe data from FE fundinfo.

    1. Fetch all tracked ISINs from instruments table
    2. Batch fetch: pricing + AUM + risk + performance for each
    3. Upsert to nav_timeseries, fund_risk_metrics tables
    4. Write snapshots to gold/_global/fefundinfo/ in R2
    """
```

Add worker route in `backend/app/domains/wealth/routes/workers.py`:
```python
@router.post("/run-fefundinfo-ingestion")
```

### Step 6: R2 Folder Structure

Add folder: `gold/_global/fefundinfo/`

Data persisted:
- `gold/_global/fefundinfo/fund_universe.parquet` — latest snapshot of all tracked funds
- `gold/_global/fefundinfo/risk_profiles.parquet` — risk metrics per fund
- `gold/_global/fefundinfo/performance.parquet` — cumulative/discrete performance
- `gold/_global/fefundinfo/exposures.parquet` — geographic/sector/currency breakdowns

### Step 7: Tests

Create `backend/tests/test_fefundinfo_provider.py`:

1. `test_token_manager_caches_token` — second call reuses cached token
2. `test_token_manager_refreshes_expired` — refreshes when near expiry
3. `test_get_risk_data_parses_response` — correct parsing of RiskData schema
4. `test_get_cumulative_performance_parses_response` — correct parsing
5. `test_fetch_instrument_returns_raw_instrument_data` — protocol compliance
6. `test_fetch_batch_chunks_by_10` — batches ISINs in groups of 10
7. `test_fetch_batch_history_returns_dataframes` — NAV series as DataFrame
8. `test_never_raises_on_api_error` — returns None/empty on failure
9. `test_rate_limiting` — respects token bucket
10. `test_provider_factory_returns_correct_type` — feature flag routing

Mock all HTTP calls — do not call real FE fundinfo API in tests.

### Step 8: Verify

```bash
make check  # Must pass: lint + architecture + typecheck + all tests
```

---

## Critical Rules (from CLAUDE.md)

- `async def` for all HTTP calls, wrap sync with `asyncio.to_thread()`
- Never store OAuth2 tokens in database — in-memory only with TTL
- `InstrumentDataProvider` protocol methods are sync (match existing interface)
- Extended async methods are separate (not part of protocol)
- No module-level asyncio primitives — create lazily inside async functions
- Feature flag `feature_fefundinfo_enabled` gates the provider
- Never-raises pattern for all data fetch methods
- All config via settings (no hardcoded URLs beyond defaults)
- Rate limiting via token bucket (same pattern as Yahoo Finance)

## What NOT to Do

- Do not modify `protocol.py` or `yahoo_finance_provider.py`
- Do not add FE fundinfo-specific logic to vertical engines — keep it in the provider
- Do not store raw API responses in PostgreSQL — normalize first
- Do not create a separate pipeline for FE fundinfo data — use existing worker pattern
- Do not hardcode ISINs — they come from the instruments table
- Do not call FE fundinfo from route handlers — only from workers (background sync)
