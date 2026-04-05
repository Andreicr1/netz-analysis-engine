# Market Data Provider Reference

> Authoritative reference for market data ingestion in the Netz Analysis Engine.
> Supersedes: `market-data-provider-audit-massive-poc.md` (Fase 12 audit).
> Last updated: 2026-04-05 (Fase 12.1 -- Tiingo implementation complete).

---

## 1. Architecture Decision

### 1.1 Provider Selection

After evaluating 5 providers (YFinance, Massive, Alpaca, Twelve Data, FMP), the engine uses **Tiingo as the single market data provider** for both dev and prod.

| Provider | Equities | ETFs | Mutual Funds | Bonds | WebSocket | Free Tier | Verdict |
|----------|----------|------|--------------|-------|-----------|-----------|---------|
| **Tiingo** | 37k stocks | 45k ETFs+MFs | **SIM** | Via EOD | **SIM** (IEX) | 50 sym/hr | **SELECTED** |
| Alpaca | 5k+ | SIM | NAO | Treasuries | SIM (SIP) | 200 req/min | Rejected -- no MFs |
| Massive | 32k+ | SIM | NAO | NAO | SIM (25ms) | Unknown | Rejected -- no MFs |
| Twelve Data | SIM | SIM | So plano Pro ($229/mo) | SIM | SIM | 800/dia, sem MFs | Rejected -- MFs pagas |
| YFinance | SIM | SIM (~95%) | Parcial (<20%) | NAO | NAO | Unlimited | Retired |

**Why Tiingo alone:** Covers all 6 instrument universes (registered_us, etf, bdc, money_market, private_us, ucits_eu) with a single API key, single auth pattern, and single response format. No composite routing needed.

### 1.2 Why Not YFinance (Even as Fallback)

- yfinance has a confirmed global mutable state bug (#2557) requiring serialized `.info` calls with sleep
- Scrapes Yahoo Finance HTML -- no SLA, breaks without notice
- Mutual fund coverage is <20% by ticker
- No WebSocket / real-time capability
- Thread-safety workarounds (token bucket, dedicated ThreadPoolExecutor) add complexity

Tiingo's free tier (50 symbols/hour) exceeds dev needs, and the paid tier (~$10-30/mo) is cheaper than the engineering cost of maintaining yfinance workarounds.

---

## 2. Implementation

### 2.1 File Location

```
providers.py                          <-- Standalone module (root)
```

Future integration path: move to `backend/app/services/providers/tiingo_provider.py` and wire into the existing `InstrumentDataProvider` protocol when replacing yfinance in workers.

### 2.2 Data Models

```python
class MarketDataPoint(BaseModel):
    """Standardized EOD OHLCV point -- provider-agnostic."""
    date: date
    open: float        # adjOpen when available (split/div adjusted)
    high: float        # adjHigh
    low: float         # adjLow
    close: float       # adjClose
    volume: int        # adjVolume

class LiveQuote(BaseModel):
    """Real-time quote from WebSocket stream."""
    ticker: str
    price: float       # last trade price
    size: int          # trade size (shares)
    timestamp: str     # ISO-8601 with nanosecond precision
    source: str        # "iex" | "crypto"
```

### 2.3 TiingoProvider API

```python
class TiingoProvider:
    def __init__(self, api_key: str | None = None) -> None
    # REST
    async def get_historical_data(ticker, start_date, end_date) -> list[MarketDataPoint]
    async def get_latest_price(ticker) -> float | None
    # WebSocket
    async def subscribe(tickers, callback) -> None
    async def unsubscribe(tickers) -> None
    async def disconnect() -> None
```

### 2.4 Factory

```python
from providers import get_market_data_provider

provider = get_market_data_provider()  # reads TIINGO_API_KEY from env
```

---

## 3. REST API -- EOD Daily Prices

### 3.1 Endpoint

```
GET https://api.tiingo.com/tiingo/daily/{ticker}/prices
    ?startDate=YYYY-MM-DD
    &endDate=YYYY-MM-DD
```

**Auth header:** `Authorization: Token {TIINGO_API_KEY}`

### 3.2 Tiingo Response Format

```json
[
  {
    "date": "2026-04-02T00:00:00+00:00",
    "open": 254.10, "high": 258.30, "low": 253.80, "close": 255.92,
    "volume": 45231500,
    "adjOpen": 254.10, "adjHigh": 258.30, "adjLow": 253.80, "adjClose": 255.92,
    "adjVolume": 45231500,
    "divCash": 0.0, "splitFactor": 1.0
  }
]
```

### 3.3 Parsing Logic

The `_parse_eod()` function prefers adjusted fields (`adjClose`, `adjOpen`, etc.) for equities/ETFs where splits and dividends affect historical prices. Falls back to raw fields for mutual funds (which have no adjustments -- NAV is already the canonical price).

```python
close = float(row.get("adjClose") or row["close"])
```

### 3.4 Asset Class Coverage (Tested)

| Ticker | Type | Bars (30d) | Last Close | Status |
|--------|------|------------|------------|--------|
| AAPL | equity | 20 | $255.92 | OK |
| SPY | etf | 20 | $655.83 | OK |
| OAKMX | mutual_fund | 20 | $167.51 | OK |
| VFINX | mutual_fund | 20 | $607.66 | OK |

### 3.5 Error Handling

| HTTP Status | Behavior |
|-------------|----------|
| 200 | Parse and return `list[MarketDataPoint]` |
| 404 | Log info, return `[]` (ticker not found) |
| 429 | Log warning, return `[]` (rate limited) |
| Other 4xx/5xx | Log warning, return `[]` |
| Network error | Log warning, return `[]` |

All errors are **silent and resilient** -- callers receive empty lists, never exceptions. This matches the existing yfinance worker pattern where failed tickers are skipped and retried next cycle.

---

## 4. WebSocket API -- Real-Time IEX Stream

### 4.1 Connection

```
wss://api.tiingo.com/iex
```

Auth is sent in the subscription message (not headers):

```json
{
  "eventName": "subscribe",
  "authorization": "TIINGO_API_KEY",
  "eventData": {
    "thresholdLevel": 5,
    "tickers": ["AAPL", "SPY"]
  }
}
```

`thresholdLevel: 5` = trade-level updates (most granular). Levels 0-4 provide increasingly aggregated data to reduce bandwidth.

### 4.2 Message Types

| messageType | Meaning | Action |
|-------------|---------|--------|
| `"I"` | Connection info | Logged |
| `"H"` | Heartbeat | Ignored (keeps connection alive) |
| `"A"` | Trade/quote update | Parsed into `LiveQuote` |

### 4.3 Trade Message Format

```json
{
  "messageType": "A",
  "data": ["T", "2026-04-05T14:30:00.123456+00:00", 1712345678123456789, "AAPL", 100, 255.92]
}
```

| Index | Field | Type | Description |
|-------|-------|------|-------------|
| 0 | update_type | str | `"T"` = trade, `"Q"` = quote |
| 1 | timestamp | str | ISO-8601 with nanoseconds |
| 2 | timestamp_ns | int | Unix nanoseconds |
| 3 | ticker | str | Symbol |
| 4 | size | int | Trade size (shares) |
| 5 | price | float | Trade price |

Only `"T"` (trade) messages are forwarded to the callback. Quote messages (`"Q"`) are dropped.

### 4.4 Auto-Reconnect

The WebSocket runs in a background `asyncio.Task` with exponential backoff:

```
Disconnect -> wait 1s -> reconnect
Disconnect -> wait 2s -> reconnect
Disconnect -> wait 4s -> reconnect
...
Disconnect -> wait 30s -> reconnect (capped)
Success    -> reset to 1s
```

### 4.5 Lifecycle

```python
provider = TiingoProvider()

# Subscribe -- starts background WS task
await provider.subscribe(["AAPL", "SPY"], on_quote_callback)

# Add more tickers to existing connection
await provider.subscribe(["MSFT"], on_quote_callback)

# Remove tickers
await provider.unsubscribe(["MSFT"])

# Shutdown -- closes WS, cancels background task
await provider.disconnect()
```

### 4.6 Limitations

| Constraint | Value |
|------------|-------|
| Market hours only | IEX trades stream Mon-Fri 9:30-16:00 ET |
| Mutual fund NAV | **Not available via WS** -- MF NAV updates once daily at 00:00 EST via REST only |
| Free tier symbols | ~30 concurrent WS symbols (plan-dependent) |
| Latency | IEX exchange only (~2.5% of US volume), not full SIP |

---

## 5. Integration with Existing Backend

### 5.1 Current State (YFinance)

The existing backend uses `InstrumentDataProvider` protocol in `backend/app/services/providers/protocol.py` with `YahooFinanceProvider` as the default implementation. The protocol defines:

```python
class InstrumentDataProvider(Protocol):
    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None
    def fetch_batch(self, tickers: list[str]) -> list[RawInstrumentData]
    def fetch_batch_history(self, tickers: list[str], period: str) -> dict[str, pd.DataFrame]
```

### 5.2 Migration Path

| Step | What | Files | Effort |
|------|------|-------|--------|
| 1 | Move `providers.py` into `backend/app/services/providers/tiingo_provider.py` | 1 file | Low |
| 2 | Adapt `TiingoProvider` to implement existing `InstrumentDataProvider` protocol (add `fetch_instrument`, `fetch_batch`, `fetch_batch_history` wrappers) | 1 file | Low |
| 3 | Update factory `get_instrument_provider()` to return `TiingoProvider` | `__init__.py` | Low |
| 4 | Migrate `benchmark_ingest.py` -- replace direct `yf.download()` with provider | 1 file | Medium |
| 5 | Migrate `sec/shared.py` -- replace `yf.Ticker().info` and `.fast_info` | 1 file | Medium |
| 6 | Remove `yfinance` from `pyproject.toml` dependencies | 1 file | Low |
| 7 | Add WebSocket bridge route for frontend live quotes | New route | Medium |

Steps 1-3 enable the switch. Steps 4-5 eliminate direct yfinance coupling. Step 6 removes the dependency. Step 7 enables the Dashboard live feed.

### 5.3 Points of Direct YFinance Coupling (to migrate)

| File | Current Usage | Migration |
|------|--------------|-----------|
| `benchmark_ingest.py` | `yf.download()` directly | Use `provider.get_historical_data()` per ticker, or add batch method |
| `backfill_nav.py` | `yf.download()` directly | Use provider factory |
| `populate_seed.py` | `yf.download()` directly | Use provider factory |
| `sec/shared.py` | `yf.Ticker().info` for sector | Use `provider.get_latest_price()` + separate metadata source |
| `sec/shared.py` | `yf.Ticker().fast_info` for price | Use `provider.get_latest_price()` |
| `instrument_ingestion.py` | Via `get_instrument_provider()` | Already abstracted -- just swap factory |
| `instruments.py` route | Via `get_instrument_provider()` | Already abstracted -- just swap factory |

---

## 6. Frontend Integration (WebSocket -> SSE)

### 6.1 Architecture

```
Tiingo WS (IEX)          FastAPI Backend              Svelte Frontend
wss://api.tiingo.com  ->  TiingoProvider.subscribe()  ->  SSE endpoint
                          on_quote callback                /api/live-quotes
                          Redis pub/sub bridge             fetch() + ReadableStream
                                                          (not EventSource -- auth)
```

### 6.2 Dashboard Components That Consume Live Data

| Component | Data | Update Frequency |
|-----------|------|------------------|
| Portfolio Holdings cards | Last price, change, change% | Real-time (per trade) |
| Portfolio Overview table | Last Price, Change columns | Real-time (per trade) |
| Watchlist panel | Price, change% | Real-time (per trade) |
| Total AUM | Sum of holdings * price | Derived (recalc on price update) |

### 6.3 Mutual Funds in Dashboard

Mutual fund prices update **once daily** (after market close, ~00:00 EST via REST). The Dashboard should show the latest EOD NAV from `nav_timeseries` for MF holdings, and only stream real-time updates for equity/ETF holdings. The frontend must handle mixed update frequencies gracefully.

---

## 7. Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TIINGO_API_KEY` | Yes | -- | API key from tiingo.com/account/api/token |

No feature flags needed -- Tiingo is the only provider. The key is already in `.env.dev`.

---

## 8. Rate Limits & Pricing

### 8.1 Free Tier (Current)

| Limit | Value |
|-------|-------|
| REST requests | ~50 unique symbols per hour |
| REST historical depth | 30+ years |
| WebSocket symbols | ~30 concurrent |
| Coverage | 82,468 securities (37k stocks + 45k ETFs/MFs) |
| Update frequency | EOD at 17:30 ET (equities/ETFs), 00:00 ET (MFs) |

### 8.2 Paid Tier (Prod Target)

| Plan | Price | REST | WebSocket | Note |
|------|-------|------|-----------|------|
| Power | ~$10/mo | 500 sym/hr | 100 symbols | Sufficient for <50 tenants |
| Commercial | ~$30/mo | 5000 sym/hr | Unlimited | Scale target |

### 8.3 Cost Comparison

| Solution | Monthly Cost | Coverage |
|----------|-------------|----------|
| **Tiingo (selected)** | $0-30 | Equities + ETFs + MFs + WS |
| Alpaca + Tiingo | $99-129 | Redundant -- Alpaca adds nothing |
| Bloomberg | ~$2,000 | Overkill |
| Refinitiv/LSEG | ~$1,000 | Overkill |
| YFinance | $0 | Unreliable, no SLA, no WS |

---

## 9. Decision Log

### Why not CompositeProvider (multi-provider routing)?

Originally proposed Alpaca (equities/ETFs) + Tiingo (mutual funds) + YFinance (dev). Analysis showed Tiingo alone covers all asset classes, making the composite pattern unnecessary complexity. One provider = one auth, one rate limit, one error pattern, one response format.

### Why Tiingo over Alpaca for equities?

Both cover equities equally. But Alpaca cannot serve mutual fund NAV, forcing a second provider. Tiingo serves everything, eliminating the routing layer. If SIP-quality real-time data becomes critical (Tiingo only has IEX, ~2.5% volume), Alpaca can be added later as a WebSocket-only supplement.

### Why not keep YFinance as dev fallback?

Tiingo's free tier already works for dev (50 sym/hr is more than enough for local testing). Keeping yfinance means maintaining thread-safety workarounds, a second response parser, and a dependency with no SLA. Clean cut.

### When would we add a second provider?

1. **Full SIP real-time** -- Alpaca's $99/mo plan provides 100% market volume SIP feed. Add when live ticker accuracy matters.
2. **EU fund NAV** -- FEFundInfo (toggle already exists: `FEATURE_FEFUNDINFO_ENABLED`) for UCITS daily NAV if Tiingo's coverage gaps emerge for European funds.
3. **Fixed income analytics** -- Bloomberg/Refinitiv if institutional bond pricing becomes a product requirement.
