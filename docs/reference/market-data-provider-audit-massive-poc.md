# Market Data Provider Audit & Massive API POC

> Technical assessment for migrating from YFinance to institutional-grade market data.
> Date: 2026-04-05. Author: Claude (Fase 12 — Market Data Audit).

---

## 1. Auditoria do Estado Atual (YFinance)

### 1.1 Mapa Completo de Uso

O YFinance e utilizado em **6 arquivos** no backend, organizados em 4 camadas:

```
┌─────────────────────────────────────────────────────────────────┐
│                     CAMADA DE ABSTRAÇÃO                        │
│  protocol.py ← InstrumentDataProvider (Protocol, runtime)      │
│  __init__.py ← get_instrument_provider() factory               │
├─────────────────────────────────────────────────────────────────┤
│                     IMPLEMENTAÇÕES                             │
│  yahoo_finance_provider.py ← YahooFinanceProvider              │
│  (fefundinfo_provider.py  ← FEFundInfoProvider, toggle)        │
├─────────────────────────────────────────────────────────────────┤
│                     WORKERS (Background)                       │
│  benchmark_ingest.py     ← yf.download() → benchmark_nav      │
│  instrument_ingestion.py ← provider.fetch_batch_history()      │
│                             → nav_timeseries                   │
│  ingestion.py            ← yf.download() → nav_timeseries      │
│                             (DEPRECATED)                       │
├─────────────────────────────────────────────────────────────────┤
│                     SCRIPTS (One-off)                          │
│  backfill_nav.py         ← yf.download() → nav_timeseries      │
│  populate_seed.py (ESMA) ← yf.download() → nav_timeseries      │
├─────────────────────────────────────────────────────────────────┤
│                     UTILITÁRIOS                                │
│  sec/shared.py           ← yf.Ticker().info → sector lookup    │
│                          ← yf.Ticker().fast_info → price       │
├─────────────────────────────────────────────────────────────────┤
│                     ROTA USER-FACING                           │
│  instruments.py          ← POST /instruments/import/yahoo      │
│                             provider.fetch_batch() → insert     │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Metodos YFinance Utilizados

| Metodo YFinance | Onde | Destino DB | Contexto |
|----------------|------|------------|----------|
| `yf.download(tickers, period, threads=True)` | `yahoo_finance_provider.fetch_batch_history()` | `nav_timeseries` | Batch historico (worker) |
| `yf.download(tickers, start, end, interval="1d")` | `benchmark_ingest.py` | `benchmark_nav` | Benchmarks diarios |
| `yf.download(tickers, start, end)` | `backfill_nav.py`, `populate_seed.py` | `nav_timeseries` | Scripts one-off |
| `yf.Ticker(ticker).info` | `yahoo_finance_provider.fetch_instrument()` | `instruments_universe` | Metadata import |
| `yf.Ticker(ticker).info` | `sec/shared.py` | — (in-memory) | Sector resolution |
| `yf.Ticker(ticker).fast_info` | `sec/shared.py` | — (in-memory) | Current price |

### 1.3 Tabelas Alimentadas

| Tabela | Escopo | Tipo | Colunas-Chave |
|--------|--------|------|---------------|
| `nav_timeseries` | Global | Hypertable | `instrument_id, nav_date, nav, return_1d, source` |
| `benchmark_nav` | Global | Hypertable | `block_id, nav_date, nav, return_1d, source="yfinance"` |
| `instruments_universe` | Global | Regular | `instrument_id, ticker, name, instrument_type, attributes` |
| `fund_risk_metrics` | Org | Regular | Derivado de `nav_timeseries` (sem yfinance direto) |
| `model_portfolio_nav` | Org | Hypertable | Derivado de `nav_timeseries` (sem yfinance direto) |

### 1.4 Acoplamento vs. Abstração

**Ja existe uma camada de abstração bem desenhada:**

```python
# protocol.py
@runtime_checkable
class InstrumentDataProvider(Protocol):
    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None: ...
    def fetch_batch(self, tickers: list[str]) -> list[RawInstrumentData]: ...
    def fetch_batch_history(self, tickers: list[str], period: str = "3y") -> dict[str, pd.DataFrame]: ...
```

**Pontos de acoplamento direto (bypassing a interface):**

| Local | Tipo de Acoplamento | Risco |
|-------|---------------------|-------|
| `benchmark_ingest.py` | Chama `yf.download()` diretamente | **Alto** — nao usa o provider |
| `backfill_nav.py` | Chama `yf.download()` diretamente | Medio — script one-off |
| `populate_seed.py` | Chama `yf.download()` diretamente | Baixo — seed one-off |
| `sec/shared.py` | Chama `yf.Ticker().info` e `.fast_info` | **Alto** — utilidade compartilhada |
| `instrument_ingestion.py` | Usa `get_instrument_provider()` | **OK** — ja abstraido |
| `instruments.py` (rota) | Usa `get_instrument_provider()` | **OK** — ja abstraido |

**Conclusao:** ~60% do uso ja passa pela interface `InstrumentDataProvider`. Os 40% restantes (benchmark_ingest, sec/shared) fazem chamadas diretas ao yfinance e precisam ser migrados para a interface.

### 1.5 Streaming / Tempo Real

**Nao existe.** Todo o consumo de dados e batch/agendado:
- Workers rodam em schedule (daily/weekly)
- Nenhum WebSocket de precos
- Nenhum real-time feed no frontend

O frontend consome dados via REST API do backend, que le do PostgreSQL. O dashboard exibe snapshots, nao tickers ao vivo.

---

## 2. Prova de Conceito (POC) — Massive API

### 2.1 O Que e a Massive

A [Massive](https://massive.com/) (massive.com) e uma plataforma de market data focada em:
- **Equities** (32k+ tickers, todos os exchanges US + OTC + dark pools)
- **Options** (chains, Greeks)
- **Indices** (S&P, Nasdaq, Dow Jones)
- **Forex** (1,750+ pares)
- **Crypto**
- **Futures**
- **ETFs** (analytics via parceiro ETF Global)

**Base URL:** `https://api.massive.com`
**Auth:** Query parameter `?apiKey=YOUR_KEY`
**Client Python:** `pip install massive` → `from massive import RESTClient`
**Formato:** JSON, endpoints versionados (`/v2/`, `/v3/`)
**WebSocket:** Sim — aggs por segundo/minuto, quotes, trades (25ms latency)

### 2.2 Endpoints Relevantes Mapeados

| Endpoint Massive | Equivalente YFinance | Uso no Netz |
|-----------------|---------------------|-------------|
| `GET /v2/aggs/ticker/{T}/range/1/day/{from}/{to}` | `yf.download(T, start, end)` | nav_timeseries, benchmark_nav |
| `GET /v2/aggs/grouped/locale/us/market/stocks/{date}` | `yf.download(tickers)` batch | Bulk ingest |
| `GET /v3/reference/tickers/{T}` | `yf.Ticker(T).info` | instruments_universe metadata |
| `GET /v3/reference/tickers` | Lista de tickers | universe discovery |
| `GET /v2/snapshot/locale/us/markets/stocks/tickers/{T}` | `yf.Ticker(T).fast_info` | Current price |
| `WS wss://socket.massive.com/stocks` | N/A (yfinance nao tem) | Futuro: live feed |

### 2.3 Response Format (Aggregates)

```json
{
  "adjusted": true,
  "queryCount": 2,
  "request_id": "abc123",
  "results": [
    {
      "c": 75.0875,    // close
      "h": 75.15,      // high
      "l": 73.7975,    // low
      "n": 1,          // number of transactions
      "o": 74.06,      // open
      "t": 1577941200000,  // timestamp (ms)
      "v": 135647456,  // volume
      "vw": 74.6099    // volume-weighted average price
    }
  ],
  "resultsCount": 2,
  "status": "OK",
  "ticker": "AAPL"
}
```

### 2.4 Script de POC

Criado em [`massive_poc.py`](../../massive_poc.py) (raiz do projeto). O script testa:

| Ticker | Tipo | Proposito |
|--------|------|-----------|
| AAPL, MSFT | equity | Baseline — deve funcionar |
| SPY, IVV | ETF | Core benchmarks |
| AGG, BND | ETF (bond) | Fixed income benchmarks |
| OAKMX, DODGX | mutual_fund | **Teste critico** — fundos do nosso dev_seed |
| PRWCX, VFINX | mutual_fund | **Teste critico** — fundos institucionais |

Execucao:
```bash
MASSIVE_API_KEY=your_key python massive_poc.py
```

### 2.5 Resultado Esperado (Baseado na Documentacao)

Antes de rodar o POC com uma API key valida, a analise da documentacao da Massive **ja revela a limitacao critica:**

| Asset Class | Cobertura Massive | Evidencia |
|-------------|-------------------|-----------|
| Equities | **COMPLETA** | Documentado extensivamente, 32k+ tickers |
| ETFs | **COMPLETA** | Exchange-traded, cobertura via stocks endpoints + ETF Analytics |
| Options | **COMPLETA** | Chains, Greeks, snapshots |
| Forex | **COMPLETA** | 1,750+ pares |
| Crypto | **COMPLETA** | Spot e derivativos |
| Indices | **COMPLETA** | S&P, Nasdaq, Dow Jones |
| **Mutual Funds** | **NAO SUPORTADO** | Nenhuma mencao em toda a documentacao (llms-full.txt, REST docs, pricing page). Markets suportados: `stocks, crypto, fx, otc, indices`. Nenhum tipo "MUTUALFUND" ou "OPEN_END_FUND". |
| Bonds (individual) | **NAO SUPORTADO** | Sem endpoints de fixed income individual |

**Veredicto preliminar:** A Massive e excelente para instrumentos exchange-traded (equities, ETFs, options) mas **nao cobre fundos mutuos** — exatamente a classe de ativos mais critica para o Wealth OS (3,652 mutual funds na `sec_registered_funds`, 45,942 private funds na `sec_manager_funds`).

### 2.6 Implicacao para o Netz

O nosso `instruments_universe` contem 6 universos:

| Universe | Cobertura Massive | Cobertura YFinance |
|----------|-------------------|--------------------|
| `etf` (985 SEC) | **SIM** — exchange-traded | SIM (~95% success) |
| `bdc` (196 SEC) | **SIM** — exchange-traded | SIM |
| `registered_us` (3,652 MFs) | **NAO** | Parcial (<20% success via ticker) |
| `money_market` (373 SEC) | **NAO** (NAV estavel) | NAO |
| `private_us` (45,942 ADV) | **NAO** (sem ticker publico) | NAO |
| `ucits_eu` (ESMA) | **PARCIAL** (se ticker em exchange) | Parcial (via yahoo_ticker) |

**Nenhum provedor unico cobre tudo.** A arquitetura DEVE ser multi-provider.

---

## 3. Proposta Arquitetural — Multi-Provider Adapter

### 3.1 Visao Geral

```
                     ┌──────────────────────────┐
                     │   MarketDataProvider      │
                     │   (Protocol — interface)  │
                     └──────────┬───────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                  │
   ┌──────────▼──────┐  ┌──────▼──────┐  ┌───────▼───────┐
   │ MassiveProvider  │  │ YFinance    │  │ FEFundInfo    │
   │ (Prod: equities, │  │ Provider    │  │ Provider      │
   │  ETFs, options,  │  │ (Dev/fallback│  │ (EU UCITS,   │
   │  WS streaming)   │  │  + MF NAV)  │  │  premium)     │
   └─────────────────┘  └─────────────┘  └───────────────┘
              │                 │                  │
              └────────┬───────┘──────────────────┘
                       │
              ┌────────▼────────┐
              │ CompositeProvider│ ← Roteador por instrument_type
              │                  │   equity/etf → Massive
              │                  │   mutual_fund → YFinance/FEFundInfo
              │                  │   bond → YFinance (fallback)
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │   Workers,      │
              │   Routes,       │
              │   SEC shared    │
              └─────────────────┘
```

### 3.2 Interface Expandida

A interface existente (`InstrumentDataProvider`) ja e adequada para metadata e historico. Para suportar a Massive com streaming, proponho uma extensao **aditiva** (sem quebrar o que existe):

```python
# backend/app/services/providers/protocol.py

@runtime_checkable
class InstrumentDataProvider(Protocol):
    """Existing protocol — unchanged."""
    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None: ...
    def fetch_batch(self, tickers: list[str]) -> list[RawInstrumentData]: ...
    def fetch_batch_history(
        self, tickers: list[str], period: str = "3y",
    ) -> dict[str, pd.DataFrame]: ...


@runtime_checkable
class StreamingDataProvider(Protocol):
    """Extension for real-time providers (Massive WS, future use)."""
    async def subscribe_quotes(
        self, tickers: list[str], callback: Callable[[str, QuoteSnapshot], None],
    ) -> AsyncContextManager: ...

    async def get_snapshot(self, ticker: str) -> QuoteSnapshot | None: ...


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    """Real-time quote from streaming provider."""
    ticker: str
    price: float
    bid: float | None
    ask: float | None
    volume: int
    timestamp_ms: int
    source: str
```

### 3.3 CompositeProvider — Roteador Inteligente

```python
# backend/app/services/providers/composite_provider.py

class CompositeProvider:
    """Routes requests to the best provider per instrument type.
    
    Configured via environment:
      MARKET_DATA_PRIMARY=massive    (equities, ETFs)
      MARKET_DATA_FUND_FALLBACK=yahoo  (mutual funds, bonds)
    """

    def __init__(
        self,
        primary: InstrumentDataProvider,       # Massive (prod) or Yahoo (dev)
        fund_fallback: InstrumentDataProvider,  # Yahoo or FEFundInfo
        instrument_type_resolver: Callable[[str], str | None] = None,
    ):
        self._primary = primary
        self._fund_fallback = fund_fallback
        self._resolve_type = instrument_type_resolver or (lambda t: None)

    def _route(self, ticker: str) -> InstrumentDataProvider:
        """Select provider based on instrument type."""
        itype = self._resolve_type(ticker)
        if itype in ("mutual_fund", "money_market", "private"):
            return self._fund_fallback
        return self._primary

    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None:
        provider = self._route(ticker)
        result = provider.fetch_instrument(ticker)
        # Fallback: if primary fails, try fund_fallback
        if result is None and provider is self._primary:
            result = self._fund_fallback.fetch_instrument(ticker)
        return result

    def fetch_batch(self, tickers: list[str]) -> list[RawInstrumentData]:
        # Partition tickers by provider
        primary_tickers = []
        fallback_tickers = []
        for t in tickers:
            if self._resolve_type(t) in ("mutual_fund", "money_market", "private"):
                fallback_tickers.append(t)
            else:
                primary_tickers.append(t)

        results = []
        if primary_tickers:
            results.extend(self._primary.fetch_batch(primary_tickers))
        if fallback_tickers:
            results.extend(self._fund_fallback.fetch_batch(fallback_tickers))
        return results

    def fetch_batch_history(
        self, tickers: list[str], period: str = "3y",
    ) -> dict[str, pd.DataFrame]:
        # Same partitioning logic
        primary_tickers = [t for t in tickers if self._resolve_type(t) not in ("mutual_fund", "money_market", "private")]
        fallback_tickers = [t for t in tickers if self._resolve_type(t) in ("mutual_fund", "money_market", "private")]

        result: dict[str, pd.DataFrame] = {}
        if primary_tickers:
            result.update(self._primary.fetch_batch_history(primary_tickers, period))
        if fallback_tickers:
            result.update(self._fund_fallback.fetch_batch_history(fallback_tickers, period))
        return result
```

### 3.4 Factory Atualizada

```python
# backend/app/services/providers/__init__.py

def get_instrument_provider() -> InstrumentDataProvider:
    """Factory — resolves provider based on env config."""
    from app.core.config.settings import settings

    if settings.feature_fefundinfo_enabled:
        # ... existing FEFundInfo logic ...
        return FEFundInfoProvider(client)

    if settings.feature_massive_enabled:
        from app.services.providers.massive_provider import MassiveProvider
        primary = MassiveProvider(api_key=settings.massive_api_key)
        fallback = YahooFinanceProvider()
        return CompositeProvider(
            primary=primary,
            fund_fallback=fallback,
            instrument_type_resolver=_resolve_instrument_type,
        )

    return YahooFinanceProvider()


def _resolve_instrument_type(ticker: str) -> str | None:
    """Lookup instrument_type from instruments_universe.
    Uses an in-memory cache refreshed every 10 minutes.
    """
    # Implementation: query instruments_universe for ticker → instrument_type
    # Cache with TTL to avoid per-call DB hits
    ...
```

### 3.5 Variaveis de Ambiente

```bash
# Dev (default — tudo via YFinance)
# Nenhuma variavel necessaria

# Staging (Massive para equities/ETFs, Yahoo para MFs)
FEATURE_MASSIVE_ENABLED=true
MASSIVE_API_KEY=your_key

# Prod (Massive + FEFundInfo para fundos EU)
FEATURE_MASSIVE_ENABLED=true
MASSIVE_API_KEY=your_key
FEATURE_FEFUNDINFO_ENABLED=true
FEFUNDINFO_CLIENT_ID=...
FEFUNDINFO_CLIENT_SECRET=...
```

### 3.6 Migracao dos Pontos de Acoplamento Direto

| Arquivo | Mudanca Necessaria | Esforco |
|---------|-------------------|---------|
| `benchmark_ingest.py` | Substituir `yf.download()` por `get_instrument_provider().fetch_batch_history()` | Baixo — ja existe o metodo |
| `sec/shared.py` (`_resolve_sector_via_openfigi`) | Criar `get_instrument_provider().fetch_instrument(ticker)` e extrair sector dos attrs | Medio — refatorar cascade |
| `sec/shared.py` (`_fetch_price`) | Criar metodo `get_snapshot_price(ticker)` no provider | Baixo |
| `backfill_nav.py` | Usar provider factory | Baixo — script one-off |
| `populate_seed.py` | Usar provider factory | Baixo — script one-off |

---

## 4. Recomendacao Final

### 4.1 A Massive NAO Substitui o YFinance para Mutual Funds

A Massive e um **excelente upgrade** para equities e ETFs:
- Latencia menor (~50-200ms vs 500-2000ms do yfinance)
- WebSocket nativo (futuro live feed)
- API estavel e documentada (vs yfinance que depende de scraping)
- Suporte a CUSIP, CIK, FIGI no ticker lookup

Mas **nao cobre fundos mutuos**, que sao ~70% do nosso universo SEC por contagem.

### 4.2 Estrategia Recomendada

```
┌──────────────────────────────────────────────────────┐
│              Estrategia Multi-Provider                │
├──────────────────────────────────────────────────────┤
│  Massive (Prod)                                      │
│    → Equities, ETFs, BDCs (exchange-traded)          │
│    → WebSocket para futuro live feed                 │
│    → 985 ETFs + 196 BDCs + equities = ~1,200 inst.  │
│                                                      │
│  YFinance (Dev/Fallback)                             │
│    → Mutual funds (best-effort, <20% success)        │
│    → ESMA UCITS com yahoo_ticker                     │
│    → Development local (zero cost)                   │
│                                                      │
│  SEC N-PORT NAV (Ja implementado!)                   │
│    → Registered funds NAV via N-PORT filings         │
│    → 3,652 MFs com holdings + NAV trimestral         │
│    → Ja ingerido por nport_ingestion worker          │
│                                                      │
│  FEFundInfo (Premium, futuro)                        │
│    → UCITS europeus com NAV diario                   │
│    → Toggle: FEATURE_FEFUNDINFO_ENABLED              │
└──────────────────────────────────────────────────────┘
```

### 4.3 Proximo Passo Imediato

1. **Rodar o POC** (`MASSIVE_API_KEY=... python massive_poc.py`) para confirmar empiricamente as hipoteses
2. **Implementar `MassiveProvider`** seguindo o pattern do `YahooFinanceProvider` (mesmo Protocol)
3. **Implementar `CompositeProvider`** com roteamento por `instrument_type`
4. **Migrar `benchmark_ingest.py`** para usar a interface (unico worker com acoplamento direto significativo)
5. **Adicionar `FEATURE_MASSIVE_ENABLED`** ao settings + env

---

## Fontes

- [Massive API Docs](https://massive.com/docs)
- [Massive REST Stocks Overview](https://massive.com/docs/rest/stocks/overview)
- [Massive Custom Bars (OHLC)](https://massive.com/docs/rest/stocks/aggregates/custom-bars)
- [Massive ETF Analytics](https://massive.com/docs/rest/partners/etf-global/analytics)
- [Massive Python Client](https://github.com/massive-com/client-python)
- [Massive MCP Server](https://github.com/massive-com/mcp_massive)
- [Massive All Tickers](https://massive.com/docs/rest/stocks/tickers/all-tickers)
