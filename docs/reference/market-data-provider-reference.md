# Market Data Provider Reference

> Authoritative reference for market data ingestion and real-time distribution in the Netz Analysis Engine.
> Supersedes: `market-data-provider-audit-massive-poc.md` (Fase 12 audit).
> Last updated: 2026-04-05 (Fase 12.2 -- WebSocket infrastructure + Portfolio Holdings + Live Screener Catalog).

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

| Step | What | Files | Effort | Status |
|------|------|-------|--------|--------|
| 1 | Move `providers.py` into `backend/app/services/providers/tiingo_provider.py` | 1 file | Low | Pending |
| 2 | Adapt `TiingoProvider` to implement existing `InstrumentDataProvider` protocol (add `fetch_instrument`, `fetch_batch`, `fetch_batch_history` wrappers) | 1 file | Low | Pending |
| 3 | Update factory `get_instrument_provider()` to return `TiingoProvider` | `__init__.py` | Low | Pending |
| 4 | Migrate `benchmark_ingest.py` -- replace direct `yf.download()` with provider | 1 file | Medium | Pending |
| 5 | Migrate `sec/shared.py` -- replace `yf.Ticker().info` and `.fast_info` | 1 file | Medium | Pending |
| 6 | Remove `yfinance` from `pyproject.toml` dependencies | 1 file | Low | Pending |
| 7 | WebSocket infrastructure: ConnectionManager + Redis Pub/Sub bridge + WS endpoint | `core/ws/`, `routes/market_data.py` | Medium | **DONE** |
| 8 | Portfolio Holdings REST endpoint (positions + cost basis + pricing) | `routes/market_data.py`, `schemas/market_data.py` | Medium | **DONE** |
| 9 | Screener Catalog REST endpoint (paginated assets + latest prices) | `routes/market_data.py`, `schemas/market_data.py` | Medium | **DONE** |
| 10 | Frontend MarketDataStore (WS client + SSR hydration) | `stores/market-data.svelte.ts` | Medium | **DONE** |
| 11 | Frontend PortfolioAnalyticsStore ($derived NAV, P&L, allocation) | `stores/portfolio-analytics.svelte.ts` | Medium | **DONE** |
| 12 | Frontend Screener live asset grid (WS subscribe/unsubscribe via $effect) | `routes/(app)/screener/+page.svelte` | Medium | **DONE** |
| 13 | Frontend Dashboard integration (analytics store consumption) | `routes/(app)/dashboard/+page.svelte` | Low | **DONE** |

Steps 1-6 migrate the data ingestion layer from YFinance to Tiingo. Steps 7-13 implement the real-time distribution and frontend consumption layer (all complete).

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

## 6. Backend WebSocket Infrastructure (IMPLEMENTED)

### 6.1 Architecture

```
Tiingo WS (IEX)     publish_price_tick()    Redis Pub/Sub       ConnectionManager       Svelte Frontend
wss://api.tiingo  -> backend worker       -> market:prices    -> broadcast_to_subs()  -> WebSocket client
                     (or instrument_ingestion)  channel            per-client ticker      $state priceMap
                                                                   filtering              $derived analytics
```

**Key design:** Workers publish to Redis `market:prices` channel. A single `redis_subscriber()` background task (started in `app.main` lifespan) listens to that channel and forwards ticks to all authenticated WebSocket clients via `ConnectionManager.broadcast_to_subscribers()`. Each client connection tracks its own subscribed ticker set — only matching ticks are forwarded.

### 6.2 File Layout

| File | Purpose |
|------|---------|
| `backend/app/core/ws/__init__.py` | Package marker |
| `backend/app/core/ws/manager.py` | `ConnectionManager` + `redis_subscriber()` + `publish_price_tick()` |
| `backend/app/core/ws/auth.py` | `authenticate_ws()` — JWT via `?token=` query param |
| `backend/app/domains/wealth/routes/market_data.py` | WS endpoint + REST endpoints (dashboard, holdings, screener) |
| `backend/app/domains/wealth/schemas/market_data.py` | `PriceTick`, `Position`, `PortfolioHoldingsResponse`, `ScreenerAsset`, `ScreenerAssetPage`, `DashboardSnapshot` |

### 6.3 WebSocket Endpoint

```
WS  /api/v1/market-data/live/ws?token=<jwt>
```

**Protocol (client → server):**

| Action | Payload | Server Response |
|--------|---------|-----------------|
| `subscribe` | `{"action": "subscribe", "tickers": ["SPY", "QQQ"]}` | `{"type": "subscribed", "data": {"tickers": ["QQQ", "SPY"]}}` |
| `unsubscribe` | `{"action": "unsubscribe", "tickers": ["SPY"]}` | `{"type": "subscribed", "data": {"tickers": ["QQQ"]}}` |
| `ping` | `{"action": "ping"}` | `{"type": "pong"}` |

**Protocol (server → client):**

| Type | When | Shape |
|------|------|-------|
| `price` | Redis tick matches subscribed ticker | `{"type": "price", "data": PriceTick}` |
| `subscribed` | After subscribe/unsubscribe | `{"type": "subscribed", "data": {"tickers": [...]}}` |
| `pong` | Response to ping + 15s heartbeat | `{"type": "pong"}` |
| `error` | Invalid JSON, unknown action | `{"type": "error", "data": {"message": "..."}}` |

**Close codes:** `1008` = auth failure (missing/invalid/expired JWT). `1000` = normal close.

**Auth:** JWT query param validated by `authenticate_ws()` — reuses same `_verify_clerk_jwt` logic as REST. Dev bypass: `dev-token-change-me`.

### 6.4 ConnectionManager

```python
class ConnectionManager:
    _connections: dict[int, ClientConnection]  # keyed by id(ws)

    async def accept(ws, actor) -> ClientConnection
    def disconnect(ws) -> None
    def update_subscriptions(ws, tickers: set[str]) -> None
    async def broadcast_to_subscribers(message: dict) -> None  # filters by ticker
    async def send_personal(ws, data: dict) -> None
```

- **One instance per app** (`app.state.ws_manager`), created in `main.py` lifespan.
- **Stale connection cleanup:** `broadcast_to_subscribers()` catches `send_json` exceptions and auto-removes dead connections.
- **No module-level asyncio primitives** — all state is instance-level.

### 6.5 Redis Pub/Sub Bridge

```python
async def redis_subscriber(manager: ConnectionManager) -> None
```

- Background `asyncio.Task` started in lifespan, cancelled on shutdown.
- Subscribes to `market:prices` channel.
- Auto-reconnects with exponential backoff (1s → 30s cap).
- Workers publish ticks via `publish_price_tick(tick_dict)`.

### 6.6 REST Endpoints (IMPLEMENTED)

| Endpoint | Response Schema | Purpose |
|----------|-----------------|---------|
| `GET /market-data/dashboard-snapshot` | `DashboardSnapshot` | SSR seed for dashboard — holdings + latest prices from `nav_timeseries` |
| `GET /market-data/portfolio/{id}/holdings` | `PortfolioHoldingsResponse` | Detailed positions with cost basis, quantity, previous close for P&L |
| `GET /market-data/screener/catalog` | `ScreenerAssetPage` | Paginated asset catalog with latest prices for live screener grid |

**Portfolio Holdings** (`GET /market-data/portfolio/{id}/holdings`):
- `{id}` accepts UUID or profile name (growth, moderate, conservative).
- Resolves model portfolio → `fund_selection_schema` → instruments + `nav_timeseries` join.
- Returns `Position[]` with: `weight`, `quantity` (notional = weight * portfolio_nav / price), `avg_cost` (previous close proxy), `last_price`, `previous_close`.
- Empty fallback if no model portfolio exists (200, empty `holdings[]`).

**Screener Catalog** (`GET /market-data/screener/catalog`):
- Reads from `mv_unified_funds` materialized view + `nav_timeseries` for latest pricing.
- Params: `page`, `page_size`, `q` (name/ticker search), `asset_class`, `region`.
- Returns `ScreenerAsset[]` with: static metadata + `last_price`, `change`, `change_pct`.
- Frontend uses this as SSR seed, then subscribes to visible tickers via WebSocket.

### 6.7 Schema Reference

```python
class Position(BaseModel):
    instrument_id: str; ticker: str; name: str
    asset_class: str; currency: str
    weight: Decimal          # 0.0-1.0
    quantity: Decimal         # notional units
    avg_cost: Decimal         # cost basis per unit
    last_price: Decimal       # latest NAV/price
    previous_close: Decimal   # previous day close
    price_date: str | None
    aum_usd: Decimal | None

class PortfolioHoldingsResponse(BaseModel):
    portfolio_id: str; profile: str
    holdings: list[Position]
    cash_balance: Decimal
    portfolio_nav: Decimal
    as_of: str

class ScreenerAsset(BaseModel):
    external_id: str; ticker: str | None; name: str
    asset_class: str; region: str; fund_type: str
    strategy_label: str | None; currency: str | None
    aum: Decimal | None; expense_ratio_pct: Decimal | None
    inception_date: str | None
    last_price: Decimal | None; change: Decimal | None; change_pct: Decimal | None

class ScreenerAssetPage(BaseModel):
    items: list[ScreenerAsset]; total: int; page: int; page_size: int; has_next: bool
```

---

## 7. Frontend Real-Time Architecture (IMPLEMENTED)

### 7.1 Store Architecture

```
+layout.svelte (app shell)
  ├── createMarketDataStore()    → context "netz:marketDataStore"
  ├── createPortfolioAnalytics() → context "netz:portfolioAnalytics"
  └── createRiskStore()          → context "netz:riskStore"
```

All stores are created once at layout level and persist across navigations. No localStorage — in-memory only.

### 7.2 MarketDataStore (`market-data.svelte.ts`)

**Reactive state (Svelte 5 `$state`):**
- `status: WsStatus` — "connecting" | "connected" | "reconnecting" | "disconnected" | "error"
- `priceMap: Record<string, PriceTick>` — ticker → latest tick (live or SSR)
- `holdings: HoldingSummary[]` — from dashboard snapshot
- `totalAum`, `totalReturnPct`, `asOf` — portfolio summary
- `subscribedTickers: string[]` — current server-confirmed subscriptions

**Public API:**
- `start()` / `stop()` — lifecycle control (called by layout `onMount`)
- `subscribe(tickers)` / `unsubscribe(tickers)` — dynamic ticker management
- `seedFromSSR(snapshot: DashboardSnapshot)` — hydrate from server-rendered data

**Resilience:**
- Heartbeat monitoring (45s timeout → reconnect)
- Exponential backoff reconnection (1s → 30s cap, max 5 retries)
- Monotonic version counter (prevents stale data overwrites)
- Auth failure (close code 1008) → error state, no reconnect

### 7.3 PortfolioAnalyticsStore (`portfolio-analytics.svelte.ts`)

**Derived state (Svelte 5 `$derived`):** All recomputation is automatic as `priceMap` or `holdings` change.

```
MarketDataStore.priceMap ──→ $derived.by positions[]
                                  │   (fuse live tick + SSR holding)
                                  │   positionValue = weight * portfolioNAV
                                  │   intradayPnl = positionValue * changePct
                                  │
                                  ├── $derived totalNav (sum position values)
                                  ├── $derived totalPnl (sum intraday P&L)
                                  ├── $derived totalPnlPct (weighted %)
                                  ├── $derived allocation[] (grouped by asset_class)
                                  ├── $derived gainers[] (sorted by P&L desc)
                                  └── $derived losers[] (sorted by P&L asc)
```

**Price source precedence:** Live WS tick → SSR holding price → 0 (never stale).

**Portfolio NAV formula:**
```
weightedReturn = Σ (weight_i × changePct_i)
navNow = inceptionNAV × (1 + weightedReturn)
positionValue_i = weight_i × navNow
intradayPnl_i = positionValue_i × changePct_i
```

### 7.4 Screener WS Subscription Lifecycle

The screener uses Svelte 5 `$effect` to manage WebSocket subscriptions based on the currently visible page of assets:

```svelte
// Extract tickers from current page (reactive)
let visibleTickers = $derived(
  data.assets.items.map(a => a.ticker).filter(Boolean)
);

// Subscribe/unsubscribe lifecycle
$effect(() => {
  const tickers = visibleTickers;
  if (tickers.length === 0 || activeView !== "assets") return;
  marketStore.subscribe(tickers);
  return () => {
    marketStore.unsubscribe(tickers);  // cleanup on paginate/filter/leave
  };
});
```

**Bandwidth optimization:** Only tickers visible on the current page are subscribed. Pagination, filtering, search, or navigation triggers cleanup → unsubscribe → new subscribe cycle. No leaked subscriptions.

**Live fusion:** SSR provides initial `last_price`, `change`, `change_pct`. As WS ticks arrive, `$derived liveAssets` merges them:

```svelte
let liveAssets = $derived.by(() => {
  return data.assets.items.map(asset => {
    const tick = asset.ticker ? marketStore.priceMap[asset.ticker] : undefined;
    return {
      ...asset,
      last_price: tick?.price ?? asset.last_price,
      change: tick?.change ?? asset.change,
      change_pct: tick?.change_pct ?? asset.change_pct,
    };
  });
});
```

### 7.5 Dashboard Integration

The dashboard consumes both `MarketDataStore` and `PortfolioAnalyticsStore`:

| Component | Data Source | Live Updates |
|-----------|------------|--------------|
| Total AUM card | `analytics.totalNav` → `marketStore.totalAum` → risk snapshots (fallback chain) | Yes — recomputes on each tick |
| Return indicator | `analytics.totalPnlPct` with absolute P&L in parens | Yes |
| Holdings cards (top 5) | `marketStore.holdings[0:5]` | Yes — price, change, change_pct tick |
| Portfolio Overview table | `analytics.positions[]` → `marketStore.holdings[]` (fallback) | Yes — live P&L per row |
| Watchlist | `marketStore.holdings` filtered by gainers/losers | Yes |

### 7.6 Mutual Funds in Dashboard

Mutual fund prices update **once daily** (after market close, ~00:00 EST via REST). The Dashboard shows the latest EOD NAV from `nav_timeseries` for MF holdings, and only streams real-time updates for equity/ETF holdings. The frontend handles mixed update frequencies gracefully — MF rows show SSR data until the next daily refresh, while equity/ETF rows tick live.

### 7.7 Components That Consume Live Data

| Component | File | Store | Update Trigger |
|-----------|------|-------|----------------|
| Dashboard (AUM, Holdings, Overview, Watchlist) | `routes/(app)/dashboard/+page.svelte` | `marketStore` + `analytics` | WS price tick |
| Screener Asset Grid | `routes/(app)/screener/+page.svelte` | `marketStore.priceMap` | WS price tick (page-scoped) |
| Screener Manager Grid | `components/screener/CatalogTableV2.svelte` | None (static SSR) | Page navigation only |

### 7.8 Test Coverage

| Test File | Cases | Coverage |
|-----------|-------|----------|
| `tests/test_market_data_ws.py` | 10 | WS auth, subscribe/unsubscribe, ping/pong, ConnectionManager broadcast, stale cleanup, dashboard REST |
| `tests/test_portfolio_screener_rest.py` | 10 | Portfolio holdings (auth, shape, empty fallback, position fields), Screener catalog (auth, shape, pagination, search, asset fields, region filter) |

---

## 8. Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TIINGO_API_KEY` | Yes | -- | API key from tiingo.com/account/api/token |

No feature flags needed -- Tiingo is the only provider. The key is already in `.env.dev`.

---

## 9. Rate Limits & Pricing

### 9.1 Free Tier (Current)

| Limit | Value |
|-------|-------|
| REST requests | ~50 unique symbols per hour |
| REST historical depth | 30+ years |
| WebSocket symbols | ~30 concurrent |
| Coverage | 82,468 securities (37k stocks + 45k ETFs/MFs) |
| Update frequency | EOD at 17:30 ET (equities/ETFs), 00:00 ET (MFs) |

### 9.2 Paid Tier (Prod Target)

| Plan | Price | REST | WebSocket | Note |
|------|-------|------|-----------|------|
| Power | ~$10/mo | 500 sym/hr | 100 symbols | Sufficient for <50 tenants |
| Commercial | ~$30/mo | 5000 sym/hr | Unlimited | Scale target |

### 9.3 Cost Comparison

| Solution | Monthly Cost | Coverage |
|----------|-------------|----------|
| **Tiingo (selected)** | $0-30 | Equities + ETFs + MFs + WS |
| Alpaca + Tiingo | $99-129 | Redundant -- Alpaca adds nothing |
| Bloomberg | ~$2,000 | Overkill |
| Refinitiv/LSEG | ~$1,000 | Overkill |
| YFinance | $0 | Unreliable, no SLA, no WS |

---

## 10. Decision Log

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
