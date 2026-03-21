# SEC Data Providers — Guia Completo de Implementação e Integração

> **Data:** 2026-03-21 (atualizado)
> **Status:** Implementação completa (Phases 1-8 DONE + Phase 10 hypertable + 0028 sec_institutional hypertable + 0033 CUSIP ticker map)
> **Migrações DB:** `0023_sec_data_providers_tables`, `0024_sec_13f_sector`, `0025_sec_13f_hypertable`, `0028_sec_inst_hypertable`, `0033_sec_cusip_ticker_map`
> **Testes:** 249 testes unitários (SEC-related)

---

## Sumário

1. [Visão Geral da Arquitetura](#1-visão-geral-da-arquitetura)
2. [Infraestrutura Compartilhada (shared.py)](#2-infraestrutura-compartilhada)
3. [Modelos de Dados (models.py)](#3-modelos-de-dados)
4. [ADV Service — Gestores de Investimento](#4-adv-service)
5. [13F Service — Holdings Institucionais](#5-13f-service)
6. [Institutional Service — Reverse Lookup](#6-institutional-service)
7. [Schema do Banco de Dados](#7-schema-do-banco-de-dados) (hypertables, materialized views, indexes)
8. [Wiring — Como Conectar ao FastAPI](#8-wiring-fastapi)
9. [API Routes — Endpoints Recomendados](#9-api-routes)
10. [Integração Frontend — Performance e Componentes](#10-integração-frontend)
11. [Workers e Ingestão de Dados](#11-workers-e-ingestão)
12. [Padrões de Erro e Resiliência](#12-padrões-de-erro)
13. [Limites e Restrições de Rate](#13-rate-limits)
14. [Referência Rápida de Campos](#14-referência-rápida)
15. [CUSIP → Ticker Mapping (Phase 6)](#15-cusip-ticker-mapping)
16. [Seed Population Script](#16-seed-population-script)

---

## 1. Visão Geral da Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Lifespan                       │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │AdvService│  │ThirteenFSvc  │  │InstitutionalSvc   │  │
│  │(IAPD+CSV)│  │(edgartools)  │  │(EFTS+reverse 13F) │  │
│  └────┬─────┘  └──────┬───────┘  └─────────┬─────────┘  │
│       │               │                     │            │
│       │    ┌──────────────────────┐         │            │
│       └────┤   shared.py          ├─────────┘            │
│            │  • resolve_cik()     │                      │
│            │  • rate limiters     │                      │
│            │  • sanitize_name()   │                      │
│            │  • SEC thread pool   │                      │
│            └──────────┬───────────┘                      │
│                       │                                  │
│            ┌──────────▼───────────┐                      │
│            │   models.py          │                      │
│            │  11 frozen dataclass │                      │
│            └──────────────────────┘                      │
└──────────────────────┬──────────────────────────────────┘
                       │
           ┌───────────▼──────────────┐
           │   PostgreSQL + TimescaleDB    │
           │   • sec_managers              │
           │   • sec_manager_funds         │
           │   • sec_manager_team          │
           │   • sec_13f_holdings ⏱        │  ⏱ = hypertable
           │   • sec_13f_diffs ⏱           │
           │   • sec_inst_allocations ⏱    │
           │   • sec_cusip_ticker_map      │  lookup table
           │   ── Materialized Views ──    │
           │   • sec_13f_latest_quarter    │  continuous aggregate
           │   • sec_13f_manager_sector_   │  plain (refresh manual)
           │     latest                    │
           └───────────────────────────────┘
```

### Princípios Fundamentais

| Princípio | Implementação |
|---|---|
| **Tabelas globais** | Sem `organization_id`, sem RLS — dados SEC são públicos e compartilhados entre tenants |
| **TimescaleDB hypertables** | `sec_13f_holdings`, `sec_13f_diffs` e `sec_institutional_allocations` são hypertables com chunks trimestrais. Queries DEVEM incluir filtro de data para chunk pruning |
| **Never-raises** | Todos os métodos públicos capturam exceções e retornam `[]`, `None`, ou defaults seguros |
| **Thread pool dedicado** | `_sec_executor` (4 workers) via `run_in_sec_thread()` — edgartools é sync + blocking |
| **Rate limiting coordenado** | Redis sliding window (prod) + token bucket local (dev/fallback) |
| **Zero duplicação** | `InstitutionalService` delega para `ThirteenFService` para parsing de 13F |
| **Frozen dataclasses** | Todos os DTOs são `@dataclass(frozen=True)` — imutáveis, thread-safe |

---

## 2. Infraestrutura Compartilhada

**Arquivo:** `backend/data_providers/sec/shared.py`

### 2.1 CIK Resolution — `resolve_cik()`

Resolve nome de entidade para CIK (Central Index Key) da SEC, zero-padded a 10 dígitos.

```python
from data_providers.sec.shared import resolve_cik

result = resolve_cik("Ares Capital Corporation", ticker="ARCC")
# CikResolution(cik='0001287750', company_name='Ares Capital Corporation',
#               method='ticker', confidence=1.0)
```

**Cascata de 3 tiers:**

| Tier | Método | Confiança | Fonte | Latência |
|------|--------|-----------|-------|----------|
| 1 | `Company(ticker)` | 1.0 (determinístico) | edgartools | ~200ms |
| 2 | `find(name)` + rapidfuzz ≥0.85 | `fuzz.ratio/100` | edgartools | ~500ms |
| 3 | EFTS full-text search | 0.7 (fixo) | `efts.sec.gov` HTTP | ~800ms |

**Retorno:** `CikResolution(cik, company_name, method, confidence)`
- `method` ∈ `{"ticker", "fuzzy", "efts", "not_found"}`
- `cik` é `None` quando `method == "not_found"`
- CIK sempre zero-padded: `"0001287750"` (10 dígitos)

### 2.2 Sanitização — `sanitize_entity_name()`

```python
from data_providers.sec.shared import sanitize_entity_name

sanitize_entity_name("Ares Capital")         # → "Ares Capital"
sanitize_entity_name("")                      # → None
sanitize_entity_name("x" * 201)              # → None (max 200 chars)
sanitize_entity_name('name"OR 1=1')          # → None (falha allowlist)
sanitize_entity_name("O'Brien & Sons, Inc.") # → "O'Brien & Sons, Inc."
```

**Allowlist de caracteres:** `^[a-zA-Z0-9\s.,'\-&()]+$`
- Previne injection em queries EFTS
- Remove control chars (`\x00-\x1f`, `\x7f`)
- Rejeita nomes >200 caracteres

### 2.3 Rate Limiters

| Limiter | Rate | Chave Redis | Uso |
|---------|------|-------------|-----|
| `check_edgar_rate()` | 8 req/s | `edgar:rate:{timestamp}` | EDGAR API, EFTS |
| `check_iapd_rate()` | 2 req/s | `iapd:rate:{timestamp}` | IAPD search API |

**Fallback sem Redis:** Token bucket local a `rate/4` req/s. Log WARNING uma vez por prefixo.

### 2.4 Thread Pool — `run_in_sec_thread()`

```python
from data_providers.sec.shared import run_in_sec_thread

# Executa função sync no thread pool dedicado da SEC
result = await run_in_sec_thread(sync_function, arg1, arg2)
```

- `ThreadPoolExecutor(max_workers=4, thread_name_prefix="sec-data")`
- Obtém event loop em call-time (evita "attached to different loop")
- Usado por todos os 3 services para operações edgartools/httpx

### 2.5 CUSIP → Ticker Resolution — `resolve_cusip_to_ticker_batch()`

Resolve até 100 CUSIPs para tickers via OpenFIGI batch API. Persistido na tabela `sec_cusip_ticker_map`.

```python
import httpx
from data_providers.sec.shared import resolve_cusip_to_ticker_batch

async with httpx.AsyncClient() as client:
    results = await resolve_cusip_to_ticker_batch(
        ["594918104", "037833100", "16411Q101"],  # MSFT, AAPL, Cheniere
        http_client=client,
        api_key=None,  # opcional — sem key: 25 req/min, com key: 250 req/min
    )
    for r in results:
        print(f"{r.cusip} → {r.ticker} ({r.exchange}) tradeable={r.is_tradeable}")
```

| Aspecto | Detalhe |
|---------|---------|
| **API** | `api.openfigi.com/v3/mapping` (batch, POST) |
| **Batch size** | Máximo 100 CUSIPs por request |
| **Rate limit (free)** | 25 req/min (sleep 2.4s entre batches) |
| **Rate limit (com key)** | 250 req/min (sleep 0.25s entre batches) |
| **Retorno** | `list[CusipTickerResult]` — mesmo tamanho e ordem que input |
| **Erro** | Retorna todos como `resolved_via='unresolved'` |

### 2.6 Price Lookup — `get_current_price_for_cusip()`

Resolve CUSIP → ticker (via `sec_cusip_ticker_map`) → preço atual (via YFinance).

```python
from data_providers.sec.shared import get_current_price_for_cusip

price = await get_current_price_for_cusip(
    "16411Q101",  # Cheniere Energy Partners
    db_session_factory=db_factory,
)
# price = 52.34 (float) ou None se não tradável
```

| Aspecto | Detalhe |
|---------|---------|
| **Fonte** | `sec_cusip_ticker_map` (DB) → YFinance (`fast_info`) |
| **Requisito** | CUSIP deve estar na tabela com `is_tradeable = true` |
| **Thread** | `asyncio.to_thread()` (YFinance é sync) |
| **Erro** | Retorna `None` |

### 2.7 Normalization Helpers

```python
from data_providers.sec.shared import _normalize_light, _normalize_heavy

_normalize_light("ARES CAPITAL Corp.")  # → "ares capital corp"
_normalize_heavy("Ares Capital Inc")    # → "ares capital"
# _normalize_heavy NÃO remove Fund/Capital/Partners (diferenciadores significativos)
```

---

## 3. Modelos de Dados

**Arquivo:** `backend/data_providers/sec/models.py`

Todos os modelos são `@dataclass(frozen=True)` — imutáveis, sem imports de `app.*`.

### 3.1 CikResolution

```python
@dataclass(frozen=True)
class CikResolution:
    cik: str | None           # "0001287750" ou None
    company_name: str | None  # Nome oficial na SEC
    method: str               # "ticker" | "fuzzy" | "efts" | "not_found"
    confidence: float         # 0.0 a 1.0
```

### 3.2 AdvManager (Form ADV)

```python
@dataclass(frozen=True)
class AdvManager:
    crd_number: str                    # PK — SEC CRD identifier
    cik: str | None                    # CIK se disponível
    firm_name: str                     # Nome da firma
    sec_number: str | None             # e.g. "801-12345"
    registration_status: str | None    # "ACTIVE" | "INACTIVE"
    aum_total: int | None              # AUM total em USD
    aum_discretionary: int | None      # AUM discricionário
    aum_non_discretionary: int | None  # AUM não-discricionário
    total_accounts: int | None         # Número de contas
    fee_types: dict | None             # JSONB — tipos de taxa
    client_types: dict | None          # JSONB — tipos de cliente
    state: str | None                  # Estado (e.g. "CA")
    country: str | None                # País (e.g. "US")
    website: str | None                # URL do site
    compliance_disclosures: int | None # Número de disclosures
    last_adv_filed_at: str | None      # ISO date do último ADV
    data_fetched_at: str | None        # ISO datetime da coleta
```

### 3.3 AdvFund (Schedule D)

```python
@dataclass(frozen=True)
class AdvFund:
    crd_number: str              # FK para SecManager
    fund_name: str               # Nome do fundo
    fund_id: str | None          # ID SEC do fundo
    gross_asset_value: int | None # GAV em USD
    fund_type: str | None        # Tipo do fundo
    is_fund_of_funds: bool | None
    investor_count: int | None   # Número de investidores
```

### 3.4 AdvTeamMember (Part 2A)

```python
@dataclass(frozen=True)
class AdvTeamMember:
    crd_number: str                  # FK para SecManager
    person_name: str                 # Nome completo
    title: str | None                # Cargo
    role: str | None                 # Função
    education: dict | None           # JSONB — formação
    certifications: list[str]        # ["CFA", "CAIA"]
    years_experience: int | None
    bio_summary: str | None          # Resumo biográfico
```

> **⚠️ Stub M1:** `fetch_manager_team()` retorna `[]`. Implementação real requer OCR de Part 2A PDF via Mistral (escopo M2).

### 3.5 ThirteenFHolding

```python
@dataclass(frozen=True)
class ThirteenFHolding:
    cik: str                    # CIK do filer (10 dígitos)
    report_date: str            # ISO date do trimestre (e.g. "2025-12-31")
    filing_date: str            # Data de envio à SEC
    accession_number: str       # Identificador único do filing
    cusip: str                  # CUSIP do título
    issuer_name: str            # Nome do emissor
    asset_class: str | None     # "COM", "CALL", "PUT", etc.
    sector: str | None          # GICS sector (via SIC/yfinance/heuristic)
    shares: int | None          # Quantidade de ações/cotas
    market_value: int | None    # Valor de mercado em USD (×1000 JÁ APLICADO)
    discretion: str | None      # "SOLE", "SHARED", "DEFINED"
    voting_sole: int | None     # Votos — controle exclusivo
    voting_shared: int | None   # Votos — compartilhado
    voting_none: int | None     # Votos — nenhum
```

> **⚠️ Importante:** `market_value` já está em USD. O edgartools reporta em milhares (campo `Value`); o service multiplica ×1000 na ingestão.
>
> **`sector`** é resolvido via `enrich_holdings_with_sectors()` após ingestão: 3-tier (SIC mapping → OpenFIGI/yfinance → keyword heuristic). Pode ser `None` se nenhum tier resolver.

### 3.6 ThirteenFDiff

```python
@dataclass(frozen=True)
class ThirteenFDiff:
    cik: str
    cusip: str
    issuer_name: str
    quarter_from: str          # ISO date (e.g. "2025-09-30")
    quarter_to: str            # ISO date (e.g. "2025-12-31")
    shares_before: int | None
    shares_after: int | None
    shares_delta: int | None   # = after - before
    value_before: int | None   # USD
    value_after: int | None    # USD
    action: str                # "NEW_POSITION" | "INCREASED" | "DECREASED" | "EXITED" | "UNCHANGED"
    weight_before: float | None # 0.0–1.0 (% do portfólio)
    weight_after: float | None
```

### 3.7 InstitutionalAllocation

```python
@dataclass(frozen=True)
class InstitutionalAllocation:
    filer_cik: str             # CIK do investidor institucional
    filer_name: str            # Nome do investidor
    filer_type: str | None     # "pension" | "endowment" | "foundation" | "sovereign" | "insurance"
    report_date: str           # ISO date
    target_cusip: str          # CUSIP do ativo alvo
    target_issuer: str         # Nome do emissor alvo
    market_value: int | None   # USD
    shares: int | None
```

### 3.8 CusipTickerResult

```python
@dataclass(frozen=True)
class CusipTickerResult:
    cusip: str                   # CUSIP de 9 dígitos
    ticker: str | None           # Ticker de mercado (e.g. "AAPL")
    issuer_name: str | None      # Nome do emissor (via OpenFIGI)
    exchange: str | None         # Código da exchange (e.g. "US", "UW")
    security_type: str | None    # Tipo (e.g. "Common Stock", "ETF")
    figi: str | None             # OpenFIGI global identifier
    composite_figi: str | None   # OpenFIGI composite (preferido p/ YFinance)
    resolved_via: str            # "openfigi" | "unresolved"
    is_tradeable: bool           # true se ticker + exchange principal
```

> **Exchanges tradáveis:** `US` (NYSE), `UN` (NYSE ARCA), `UW` (NASDAQ), `UA` (NYSE American), `UR` (NYSE MKT), `UT` (OTC). Tickers nessas exchanges são compatíveis com YFinance.

### 3.9 Enums e Wrappers

```python
class CoverageType(str, Enum):
    FOUND = "found"
    PUBLIC_SECURITIES_NO_HOLDERS = "public_securities_no_holders"
    NO_PUBLIC_SECURITIES = "no_public_securities"

@dataclass(frozen=True)
class InstitutionalOwnershipResult:
    manager_cik: str
    coverage: CoverageType
    investors: list[InstitutionalAllocation] = []
    note: str | None = None

@dataclass(frozen=True)
class SeriesFetchResult:
    data: list[Any] = []
    warnings: list[str] = []
    is_stale: bool = False
    data_fetched_at: str | None = None
```

---

## 4. ADV Service

**Arquivo:** `backend/data_providers/sec/adv_service.py`
**Classe:** `AdvService(db_session_factory)`

### 4.1 `search_managers(query, *, limit=25) → list[AdvManager]`

Busca gestores na API IAPD da SEC por nome.

| Aspecto | Detalhe |
|---------|---------|
| **Fonte** | `api.adviserinfo.sec.gov/search/firm` |
| **Rate limit** | 2 req/s (IAPD) |
| **Dados retornados** | Identificação básica: CRD, nome, status, SEC number, estado/país |
| **Dados NÃO retornados** | AUM, fees, fundos — requer `ingest_bulk_adv()` |
| **Thread** | `run_in_sec_thread()` |
| **Erro** | Retorna `[]` |

```python
managers = await adv_service.search_managers("Ares Management", limit=10)
for m in managers:
    print(f"{m.crd_number}: {m.firm_name} ({m.registration_status})")
```

### 4.2 `ingest_bulk_adv(csv_path=None) → int`

Ingere dados detalhados do Form ADV via CSV mensal da SEC FOIA.

| Aspecto | Detalhe |
|---------|---------|
| **Fonte** | CSV mensal de `sec.gov/foia-services` ou arquivo local |
| **Colunas CSV** | `CRD Number`, `Primary Business Name`, `Q5F2A` (AUM disc), `Q5F2B` (AUM non-disc), `Q5F2C` (AUM total), etc. |
| **Upsert** | `ON CONFLICT (crd_number) DO UPDATE` — chunks de 2000 |
| **ZIP** | Extrai CSV automaticamente de arquivos `.zip` |
| **Retorno** | Número de managers upserted |
| **Erro** | Retorna `0` |

```python
# Download automático do FOIA mais recente
count = await adv_service.ingest_bulk_adv()

# Ou de arquivo local
count = await adv_service.ingest_bulk_adv("/data/ia032026.csv")
count = await adv_service.ingest_bulk_adv("/data/ia032026.zip")
```

### 4.3 `fetch_manager(crd_number, *, force_refresh=False, staleness_ttl_days=7) → AdvManager | None`

Lê manager do banco de dados. **Não faz chamada de API** — dados populados pelo `ingest_bulk_adv()`.

| Aspecto | Detalhe |
|---------|---------|
| **Fonte** | DB (`sec_managers`) |
| **Validação** | CRD deve ser `^\d{1,10}$` |
| **Retorno** | `AdvManager` ou `None` se não encontrado |
| **Padrão** | Stale-but-serve (dados do último bulk ingest) |

```python
manager = await adv_service.fetch_manager("158307")
if manager:
    print(f"AUM: ${manager.aum_total:,}")
    print(f"Estado: {manager.state}")
```

### 4.4 `fetch_manager_funds(crd_number) → list[AdvFund]`

Retorna fundos Schedule D do manager.

```python
funds = await adv_service.fetch_manager_funds("158307")
for f in funds:
    print(f"  {f.fund_name}: GAV ${f.gross_asset_value:,}")
```

### 4.5 `fetch_manager_team(crd_number) → list[AdvTeamMember]`

> **Stub M1** — retorna `[]`. Requer OCR de Part 2A PDF (escopo M2).

---

## 5. 13F Service

**Arquivo:** `backend/data_providers/sec/thirteenf_service.py`
**Classe:** `ThirteenFService(db_session_factory, rate_check=None)`

### 5.1 `fetch_holdings(cik, *, quarters=8, force_refresh=False, staleness_ttl_days=45) → list[ThirteenFHolding]`

Busca posições trimestrais de um filer 13F.

| Aspecto | Detalhe |
|---------|---------|
| **Fonte** | DB cache → edgartools (`Company(cik).get_filings(form="13F-HR")`) |
| **Cache** | Primeiro verifica DB; se stale (>45 dias), refetch do EDGAR |
| **force_refresh** | Ignora cache, sempre busca do EDGAR |
| **quarters** | Número de trimestres para buscar (default 8 = 2 anos) |
| **Value ×1000** | Aplica multiplicação na ingestão |
| **Dedup** | `seen_periods` previne duplicação de amendments |
| **Cap** | 15.000 holdings por filing (Vanguard tem 24K+) |
| **Upsert** | `ON CONFLICT (cik, report_date, cusip) DO UPDATE` — chunks de 2000 |
| **Thread** | Parsing em `run_in_sec_thread()` |

```python
holdings = await thirteenf_service.fetch_holdings(
    "0001287750",  # Ares Capital
    quarters=4,
    force_refresh=True,
)
for h in holdings:
    print(f"{h.cusip} {h.issuer_name}: {h.shares} shares, ${h.market_value:,}")
```

### 5.2 `compute_diffs(cik, quarter_from, quarter_to) → list[ThirteenFDiff]`

Computa diferenças trimestre-a-trimestre.

| Aspecto | Detalhe |
|---------|---------|
| **Fonte** | DB (holdings dos dois trimestres) |
| **Ações** | `NEW_POSITION`, `INCREASED`, `DECREASED`, `EXITED`, `UNCHANGED` |
| **Pesos** | `weight_before/after` = `value / total_portfolio_value` |
| **Transação** | Separada do upsert de holdings |
| **Upsert** | `ON CONFLICT (cik, cusip, quarter_from, quarter_to) DO UPDATE` |

```python
from datetime import date

diffs = await thirteenf_service.compute_diffs(
    "0001287750",
    quarter_from=date(2025, 9, 30),
    quarter_to=date(2025, 12, 31),
)
for d in diffs:
    if d.action != "UNCHANGED":
        print(f"{d.action}: {d.issuer_name} Δ{d.shares_delta:+,} shares "
              f"(weight {d.weight_before:.1%} → {d.weight_after:.1%})")
```

### 5.3 `get_sector_aggregation(cik, report_date) → dict[str, float]`

Agrega holdings por **industry sector** (GICS), retorna pesos. Exclui CALL/PUT (derivativos distorcem composição setorial). Holdings sem sector resolvido aparecem como `"Unknown"`.

```python
sectors = await thirteenf_service.get_sector_aggregation(
    "0001287750", date(2025, 12, 31),
)
# {"Technology": 0.35, "Real Estate": 0.25, "Financials": 0.20, "Unknown": 0.20}
```

### 5.5 `enrich_holdings_with_sectors(cik, report_date) → int`

Backfill de sector para holdings sem `sector`. Resolução 3-tier: SIC mapping → OpenFIGI/yfinance → keyword heuristic. Retorna contagem de CUSIPs enriquecidos. Chamado automaticamente após `fetch_holdings()`.

```python
enriched = await thirteenf_service.enrich_holdings_with_sectors(
    "0001287750", date(2025, 12, 31),
)
# enriched = 42  (42 CUSIPs tiveram sector resolvido)
```

### 5.4 `get_concentration_metrics(cik, report_date) → dict[str, float]`

Métricas de concentração do portfólio.

```python
metrics = await thirteenf_service.get_concentration_metrics(
    "0001287750", date(2025, 12, 31),
)
# {
#   "hhi": 0.0234,              # Herfindahl-Hirschman Index (0-1)
#   "top_10_concentration": 0.45,# Peso acumulado das 10 maiores posições
#   "position_count": 187.0     # Total de posições
# }
```

**Interpretação do HHI:**

| HHI | Concentração | Interpretação |
|-----|-------------|---------------|
| < 0.01 | Muito baixa | Altamente diversificado (>100 posições iguais) |
| 0.01–0.15 | Baixa | Portfólio diversificado |
| 0.15–0.25 | Moderada | Concentrado |
| > 0.25 | Alta | Muito concentrado |

---

## 6. Institutional Service

**Arquivo:** `backend/data_providers/sec/institutional_service.py`
**Classe:** `InstitutionalService(thirteenf_service, db_session_factory)`

### 6.1 `discover_institutional_filers(*, filer_types=None, limit=100) → list[dict]`

Descobre filers institucionais via busca EFTS.

| Aspecto | Detalhe |
|---------|---------|
| **Fonte** | EFTS (`efts.sec.gov/LATEST/search-index`) |
| **Keywords padrão** | `"endowment"`, `"pension"`, `"foundation"`, `"sovereign"`, `"insurance"` |
| **Classificação** | Regex em nome do filer → `filer_type` |
| **Dedup** | Por CIK (evita duplicatas nos resultados EFTS) |
| **Rate limit** | 8 req/s (EDGAR) |

```python
filers = await institutional_service.discover_institutional_filers(
    filer_types=["pension", "endowment"],
    limit=50,
)
for f in filers:
    print(f"{f['cik']}: {f['filer_name']} ({f['filer_type']})")
```

**Retorno:** `list[{"cik": str, "filer_name": str, "filer_type": str}]`

**Classificação de `filer_type`:**

| Pattern (regex, case-insensitive) | Tipo |
|---|---|
| `\bendowment\b` | `"endowment"` |
| `\bpension\b \| \bretirement\b` | `"pension"` |
| `\bfoundation\b` | `"foundation"` |
| `\bsovereign\b \| \binvestment authority\b` | `"sovereign"` |
| `\binsurance\b \| \bassurance\b \| \blife\b` | `"insurance"` |
| Nenhum match | `"unknown"` |
| Múltiplos matches | Primeiro match + log WARNING |

### 6.2 `fetch_allocations(filer_cik, filer_name, filer_type, *, quarters=4, force_refresh=False) → list[InstitutionalAllocation]`

Busca holdings de um filer e persiste como allocations.

| Aspecto | Detalhe |
|---------|---------|
| **Delegação** | `ThirteenFService.fetch_holdings()` — zero duplicação |
| **Mapping** | `ThirteenFHolding` → `InstitutionalAllocation` com contexto do filer |
| **Upsert** | `ON CONFLICT (filer_cik, report_date, target_cusip) DO UPDATE` |

```python
allocations = await institutional_service.fetch_allocations(
    filer_cik="0001234567",
    filer_name="State Pension Fund",
    filer_type="pension",
    quarters=4,
)
```

### 6.3 `find_investors_in_manager(manager_cik) → InstitutionalOwnershipResult`

**Reverse lookup:** quais instituições detêm títulos deste gestor?

| Aspecto | Detalhe |
|---------|---------|
| **3-way coverage** | Detecta o motivo exato quando não há resultados |
| **Feeder→Master** | Heurística best-effort para estruturas offshore |
| **Validação CIK** | `^\d{1,10}$` |

```python
result = await institutional_service.find_investors_in_manager("0001287750")

match result.coverage:
    case CoverageType.FOUND:
        print(f"Encontrados {len(result.investors)} investidores institucionais")
        for inv in result.investors:
            print(f"  {inv.filer_name} ({inv.filer_type}): "
                  f"${inv.market_value:,} em {inv.target_issuer}")

    case CoverageType.PUBLIC_SECURITIES_NO_HOLDERS:
        print("Manager tem títulos públicos, mas sem holders institucionais")

    case CoverageType.NO_PUBLIC_SECURITIES:
        print("Manager não tem filings 13F (private credit puro)")
        print(f"Nota: {result.note}")
```

**Fluxo de Decisão:**

```
find_investors_in_manager(manager_cik)
│
├─ _get_manager_cusips(cik) → CUSIPs no DB?
│   │
│   ├─ SIM (tem CUSIPs) ──────────────────────────────────────┐
│   │                                                          │
│   │   _query_institutional_holders(cusips)                   │
│   │   │                                                      │
│   │   ├─ Encontrou holders → FOUND + investors              │
│   │   └─ Nenhum holder   → PUBLIC_SECURITIES_NO_HOLDERS     │
│   │
│   └─ NÃO (sem CUSIPs) ─────────────────────────────────────┐
│                                                              │
│       _try_feeder_master_lookthrough(cik)                    │
│       │                                                      │
│       ├─ Nome tem keywords feeder? (offshore, cayman, ltd)  │
│       │   │                                                  │
│       │   ├─ SIM → strip suffixes → resolve_cik(base_name) │
│       │   │   │                                              │
│       │   │   ├─ Master encontrado + tem holders → FOUND    │
│       │   │   ├─ Master encontrado + sem holders → NO_HOLD. │
│       │   │   └─ Master não encontrado → fallthrough        │
│       │   │                                                  │
│       │   └─ NÃO → fallthrough                              │
│       │                                                      │
│       └─ Erro/fallthrough → NO_PUBLIC_SECURITIES            │
```

---

## 7. Schema do Banco de Dados

### 7.1 Tabelas e Índices

| Tabela | Tipo | PK | Índices |
|--------|------|----|---------|
| `sec_managers` | regular | `crd_number` | `idx_sec_managers_cik` (partial, WHERE cik IS NOT NULL) |
| `sec_manager_funds` | regular | `id` (UUID) | FK cascade + UNIQUE `(crd_number, fund_name)` |
| `sec_manager_team` | regular | `id` (UUID) | FK cascade + UNIQUE `(crd_number, person_name)` |
| `sec_13f_holdings` | **hypertable** | `(report_date, cik, cusip)` | `(cik, report_date DESC)`, covering `(cusip, report_date DESC) INCLUDE (cik, shares, market_value)`, `(cik, report_date DESC, sector)` |
| `sec_13f_diffs` | **hypertable** | `(quarter_to, cik, cusip, quarter_from)` | `(cik, quarter_to DESC)`, `(cusip, quarter_to DESC)` |
| `sec_institutional_allocations` | **hypertable** | `(report_date, filer_cik, target_cusip)` | covering `(target_cusip, report_date DESC) INCLUDE (...)`, `(filer_cik, report_date DESC)` |
| `sec_cusip_ticker_map` | regular (lookup) | `cusip` | `idx_cusip_ticker_map_ticker` (partial, WHERE ticker IS NOT NULL), `idx_cusip_ticker_map_unresolved` (partial, WHERE resolved_via = 'unresolved') |

> **Sem coluna `id` (UUID)** em `sec_13f_holdings`, `sec_13f_diffs` e `sec_institutional_allocations` — hypertables exigem a partition key em todos os unique constraints. PK composta é a natural key.

### 7.2 TimescaleDB Hypertables (Migrations 0025 + 0028)

Todas as três tabelas de séries temporais SEC convertidas para hypertables com chunks trimestrais para suportar profundidade histórica completa (EDGAR desde 1999, 100+ trimestres, centenas de milhões de linhas).

#### sec_13f_holdings

```sql
-- Particionado por report_date, chunks de 3 meses
SELECT create_hypertable('sec_13f_holdings', 'report_date',
    chunk_time_interval => INTERVAL '3 months');

-- Compressão: segmentby=cik (queries são por manager)
ALTER TABLE sec_13f_holdings SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'report_date DESC',
    timescaledb.compress_segmentby = 'cik'
);

-- Auto-compress chunks >6 meses
SELECT add_compression_policy('sec_13f_holdings', INTERVAL '6 months');
```

#### sec_13f_diffs

```sql
-- Particionado por quarter_to
SELECT create_hypertable('sec_13f_diffs', 'quarter_to',
    chunk_time_interval => INTERVAL '3 months');

ALTER TABLE sec_13f_diffs SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'quarter_to DESC',
    timescaledb.compress_segmentby = 'cik'
);

SELECT add_compression_policy('sec_13f_diffs', INTERVAL '6 months');
```

#### sec_institutional_allocations (Migration 0028)

```sql
-- Particionado por report_date, chunks de 3 meses
SELECT create_hypertable('sec_institutional_allocations', 'report_date',
    chunk_time_interval => INTERVAL '3 months');

-- Compressão: segmentby=filer_cik (queries são por filer)
ALTER TABLE sec_institutional_allocations SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'report_date DESC',
    timescaledb.compress_segmentby = 'filer_cik'
);

-- Auto-compress chunks >6 meses
SELECT add_compression_policy('sec_institutional_allocations', INTERVAL '6 months');
```

> **ORM:** `SecInstitutionalAllocation` não tem mais `id` (UUID) nem `IdMixin`. PK composta `(report_date, filer_cik, target_cusip)`.

#### Regras de Query para Hypertables

| Regra | Motivo |
|-------|--------|
| **SEMPRE** incluir `WHERE report_date >= X` (holdings, allocations) ou `WHERE quarter_to >= X` (diffs) | Chunk pruning — sem filtro de data, scan é full table |
| Preferir `cik + report_date` (holdings) ou `filer_cik + report_date` (allocations) como predicado | Alinha com compress_segmentby + compress_orderby |
| Nunca `SELECT *` sem bound temporal | Chunks comprimidos requerem descompressão — I/O proporcional |

### 7.3 Materialized Views

#### sec_13f_latest_quarter (continuous aggregate)

Agregação por manager por trimestre — usada pelo Manager Screener para evitar scan direto de `sec_13f_holdings`.

```sql
CREATE MATERIALIZED VIEW sec_13f_latest_quarter
WITH (timescaledb.continuous) AS
SELECT
    cik,
    time_bucket('3 months', report_date) AS quarter,
    SUM(market_value) FILTER (WHERE asset_class = 'COM') AS total_equity_value,
    COUNT(DISTINCT cusip) FILTER (WHERE asset_class = 'COM') AS position_count
FROM sec_13f_holdings
GROUP BY cik, time_bucket('3 months', report_date)
WITH NO DATA;

-- Refresh diário, cobrindo últimos 6 meses
SELECT add_continuous_aggregate_policy('sec_13f_latest_quarter',
    start_offset => INTERVAL '6 months',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day');
```

#### sec_13f_manager_sector_latest (plain materialized view)

Top sector por manager (snapshot mais recente). **Refresh manual** após cada batch de ingestão 13F.

```sql
CREATE MATERIALIZED VIEW sec_13f_manager_sector_latest AS
SELECT DISTINCT ON (cik)
    cik, report_date, sector, sector_value, sector_weight
FROM (
    SELECT cik, report_date, sector,
        SUM(market_value) AS sector_value,
        SUM(market_value)::float /
            NULLIF(SUM(SUM(market_value)) OVER (PARTITION BY cik, report_date), 0)
            AS sector_weight
    FROM sec_13f_holdings
    WHERE asset_class = 'COM' AND sector IS NOT NULL
    GROUP BY cik, report_date, sector
) agg
ORDER BY cik, report_date DESC, sector_value DESC;

CREATE UNIQUE INDEX ON sec_13f_manager_sector_latest (cik);
```

**Manager Screener:** Use `sec_13f_latest_quarter` e `sec_13f_manager_sector_latest` para list view — nunca scan `sec_13f_holdings` diretamente para paginação do screener.

### 7.4 Covering Indexes (Performance)

**`idx_sec_13f_holdings_cusip_report_date`** — Otimizado para queries de portfolio overlap:
```sql
CREATE INDEX idx_sec_13f_holdings_cusip_report_date
ON sec_13f_holdings (cusip, report_date DESC)
INCLUDE (cik, shares, market_value)
```

**`idx_sec_inst_alloc_target_report`** — Otimizado para reverse lookup (hypertable):
```sql
CREATE INDEX idx_sec_inst_alloc_target_report
ON sec_institutional_allocations (target_cusip, report_date DESC)
INCLUDE (filer_cik, filer_name, filer_type, market_value, shares)
```

### 7.5 Check Constraint

```sql
ALTER TABLE sec_13f_diffs
ADD CONSTRAINT chk_sec_13f_diffs_action
CHECK (action IN ('NEW_POSITION', 'INCREASED', 'DECREASED', 'EXITED', 'UNCHANGED'))
```

### 7.6 Queries de Verificação

Após migrations 0025 + 0028, confirmar hypertables funcionando:

```sql
-- Confirmar hypertables
SELECT * FROM timescaledb_information.hypertables
WHERE hypertable_name IN ('sec_13f_holdings', 'sec_13f_diffs', 'sec_institutional_allocations');

-- Confirmar chunks criados
SELECT * FROM timescaledb_information.chunks
WHERE hypertable_name = 'sec_13f_holdings'
ORDER BY range_start DESC;

-- Confirmar compression policy
SELECT * FROM timescaledb_information.jobs
WHERE application_name LIKE '%Compression%';

-- Confirmar chunk pruning ativo (deve mostrar "Chunks excluded")
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM sec_13f_holdings
WHERE cik = '0001393818' AND report_date >= '2024-01-01';
```

---

## 8. Wiring — Como Conectar ao FastAPI

### 8.1 Lifespan Setup

```python
# backend/app/core/lifespan.py (adicionar)

from data_providers.sec.adv_service import AdvService
from data_providers.sec.thirteenf_service import ThirteenFService
from data_providers.sec.institutional_service import InstitutionalService

@asynccontextmanager
async def lifespan(app: FastAPI):
    # db_session_factory já existe no lifespan atual
    db_session_factory = get_async_session_factory()

    # Instanciar ONCE (singleton)
    adv_service = AdvService(db_session_factory=db_session_factory)
    thirteenf_service = ThirteenFService(db_session_factory=db_session_factory)
    institutional_service = InstitutionalService(
        thirteenf_service=thirteenf_service,
        db_session_factory=db_session_factory,
    )

    # Registrar no app.state
    app.state.adv_service = adv_service
    app.state.thirteenf_service = thirteenf_service
    app.state.institutional_service = institutional_service

    yield
```

### 8.2 Dependency Injection

```python
# backend/app/core/deps.py (adicionar)

from fastapi import Depends, Request

def get_adv_service(request: Request) -> AdvService:
    return request.app.state.adv_service

def get_thirteenf_service(request: Request) -> ThirteenFService:
    return request.app.state.thirteenf_service

def get_institutional_service(request: Request) -> InstitutionalService:
    return request.app.state.institutional_service
```

---

## 9. API Routes — Endpoints Recomendados

### 9.1 Estrutura de Routes

```
/api/v1/sec/
├── managers/
│   ├── GET  /search?q={query}&limit={25}     → search_managers
│   ├── GET  /{crd_number}                     → fetch_manager
│   └── GET  /{crd_number}/funds               → fetch_manager_funds
│
├── thirteenf/
│   ├── GET  /{cik}/holdings?quarters={8}      → fetch_holdings
│   ├── GET  /{cik}/diffs?from={date}&to={date}→ compute_diffs
│   ├── GET  /{cik}/sectors?date={date}        → get_sector_aggregation
│   └── GET  /{cik}/concentration?date={date}  → get_concentration_metrics
│
├── institutional/
│   ├── GET  /filers?types={...}&limit={100}   → discover_institutional_filers
│   ├── POST /{filer_cik}/allocations          → fetch_allocations
│   └── GET  /investors/{manager_cik}          → find_investors_in_manager
│
└── admin/
    └── POST /ingest/adv                       → ingest_bulk_adv (worker-only)
```

### 9.2 Schemas Pydantic Recomendados

```python
# backend/data_providers/sec/schemas.py (criar)

from pydantic import BaseModel, Field

class ManagerSearchResponse(BaseModel):
    crd_number: str
    firm_name: str
    registration_status: str | None
    state: str | None
    country: str | None

class ManagerDetailResponse(BaseModel):
    crd_number: str
    cik: str | None
    firm_name: str
    sec_number: str | None
    registration_status: str | None
    aum_total: int | None
    aum_discretionary: int | None
    aum_non_discretionary: int | None
    total_accounts: int | None
    state: str | None
    country: str | None
    website: str | None
    compliance_disclosures: int | None
    last_adv_filed_at: str | None

class HoldingResponse(BaseModel):
    cusip: str
    issuer_name: str
    asset_class: str | None
    sector: str | None
    shares: int | None
    market_value: int | None
    report_date: str
    weight: float | None = None  # calculado no route

class DiffResponse(BaseModel):
    cusip: str
    issuer_name: str
    action: str
    shares_before: int | None
    shares_after: int | None
    shares_delta: int | None
    value_before: int | None
    value_after: int | None
    weight_before: float | None
    weight_after: float | None

class ConcentrationResponse(BaseModel):
    hhi: float
    top_10_concentration: float
    position_count: int

class InstitutionalInvestorResponse(BaseModel):
    filer_cik: str
    filer_name: str
    filer_type: str | None
    report_date: str
    target_cusip: str
    target_issuer: str
    market_value: int | None
    shares: int | None

class InstitutionalOwnershipResponse(BaseModel):
    manager_cik: str
    coverage: str  # "found" | "public_securities_no_holders" | "no_public_securities"
    investors: list[InstitutionalInvestorResponse]
    note: str | None
```

### 9.3 Exemplo de Route Implementado

```python
# backend/data_providers/sec/routes.py (criar)

from fastapi import APIRouter, Depends, Query
from datetime import date

router = APIRouter(prefix="/api/v1/sec", tags=["SEC Data"])

@router.get("/managers/search", response_model=list[ManagerSearchResponse])
async def search_managers(
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(25, ge=1, le=100),
    adv: AdvService = Depends(get_adv_service),
):
    results = await adv.search_managers(q, limit=limit)
    return [ManagerSearchResponse.model_validate(r.__dict__) for r in results]

@router.get("/managers/{crd_number}", response_model=ManagerDetailResponse | None)
async def get_manager(
    crd_number: str,
    adv: AdvService = Depends(get_adv_service),
):
    return await adv.fetch_manager(crd_number)

@router.get("/thirteenf/{cik}/holdings", response_model=list[HoldingResponse])
async def get_holdings(
    cik: str,
    quarters: int = Query(8, ge=1, le=20),
    force_refresh: bool = Query(False),
    svc: ThirteenFService = Depends(get_thirteenf_service),
):
    holdings = await svc.fetch_holdings(cik, quarters=quarters, force_refresh=force_refresh)
    total_value = sum(h.market_value or 0 for h in holdings) or 1
    return [
        HoldingResponse(
            **{k: v for k, v in h.__dict__.items() if k in HoldingResponse.model_fields},
            weight=round((h.market_value or 0) / total_value, 6),
        )
        for h in holdings
    ]

@router.get("/institutional/investors/{manager_cik}", response_model=InstitutionalOwnershipResponse)
async def find_investors(
    manager_cik: str,
    svc: InstitutionalService = Depends(get_institutional_service),
):
    result = await svc.find_investors_in_manager(manager_cik)
    return InstitutionalOwnershipResponse(
        manager_cik=result.manager_cik,
        coverage=result.coverage.value,
        investors=[InstitutionalInvestorResponse(**i.__dict__) for i in result.investors],
        note=result.note,
    )
```

---

## 10. Integração Frontend — Performance e Componentes

### 10.1 Estratégia de Performance

#### Prioridade 1: Latência Zero para Dados Locais

| Endpoint | Fonte real | Latência esperada | Estratégia |
|----------|-----------|-------------------|------------|
| `GET /managers/{crd}` | DB only | <50ms | Render imediato |
| `GET /managers/{crd}/funds` | DB only | <50ms | Render imediato |
| `GET /thirteenf/{cik}/sectors` | DB only | <100ms | Render imediato |
| `GET /thirteenf/{cik}/concentration` | DB only | <100ms | Render imediato |
| `GET /managers/search?q=` | IAPD API | 200-500ms | Debounce 300ms |
| `GET /thirteenf/{cik}/holdings` | DB cache ou EDGAR | 50ms–5s | Stale-while-revalidate |
| `GET /institutional/investors/{cik}` | DB + possível EFTS | 100ms–3s | Loading skeleton |

#### Prioridade 2: Padrões de Fetch

```typescript
// frontends/credit/src/lib/api/sec.ts

import { formatCurrency, formatNumber, formatPercent } from '@netz/ui';

const SEC_API = '/api/v1/sec';

// 1. Busca com debounce — autocomplete de gestores
export async function searchManagers(query: string, limit = 25): Promise<ManagerSearch[]> {
  const resp = await fetch(`${SEC_API}/managers/search?q=${encodeURIComponent(query)}&limit=${limit}`, {
    headers: authHeaders(),
  });
  return resp.json();
}

// 2. Detalhe de gestor — cache agressivo (dados mudam mensalmente)
export async function fetchManager(crd: string): Promise<ManagerDetail | null> {
  const resp = await fetch(`${SEC_API}/managers/${crd}`, { headers: authHeaders() });
  if (resp.status === 404) return null;
  return resp.json();
}

// 3. Holdings — pode ser lento na primeira chamada (EDGAR fetch)
export async function fetchHoldings(cik: string, quarters = 8): Promise<Holding[]> {
  const resp = await fetch(
    `${SEC_API}/thirteenf/${cik}/holdings?quarters=${quarters}`,
    { headers: authHeaders() },
  );
  return resp.json();
}

// 4. Institutional ownership — loading state importante
export async function findInvestors(managerCik: string): Promise<OwnershipResult> {
  const resp = await fetch(
    `${SEC_API}/institutional/investors/${managerCik}`,
    { headers: authHeaders() },
  );
  return resp.json();
}
```

### 10.2 Componentes SvelteKit Recomendados

#### A. Manager Search — Autocomplete com Debounce

```svelte
<!-- ManagerSearch.svelte -->
<script lang="ts">
  import { searchManagers } from '$lib/api/sec';

  let query = $state('');
  let results = $state<ManagerSearch[]>([]);
  let loading = $state(false);
  let debounceTimer: ReturnType<typeof setTimeout>;

  function handleInput() {
    clearTimeout(debounceTimer);
    if (query.length < 2) { results = []; return; }

    loading = true;
    debounceTimer = setTimeout(async () => {
      results = await searchManagers(query);
      loading = false;
    }, 300); // 300ms debounce — equilíbrio UX/rate-limit
  }
</script>

<input
  type="search"
  bind:value={query}
  oninput={handleInput}
  placeholder="Search SEC managers..."
/>

{#if loading}
  <Skeleton lines={3} />
{:else}
  {#each results as m}
    <a href="/sec/managers/{m.crd_number}">
      <strong>{m.firm_name}</strong>
      <span class="badge">{m.registration_status}</span>
      <span class="text-muted">{m.state}, {m.country}</span>
    </a>
  {/each}
{/if}
```

#### B. Holdings Table — Sortable + Virtual Scroll

```svelte
<!-- HoldingsTable.svelte -->
<script lang="ts">
  import { formatCurrency, formatNumber, formatPercent } from '@netz/ui';
  import type { Holding } from '$lib/api/sec';

  interface Props {
    holdings: Holding[];
  }

  let { holdings }: Props = $props();

  // Agrupar por report_date para tabs trimestrais
  let quarters = $derived(
    [...new Set(holdings.map(h => h.report_date))].sort().reverse()
  );
  let selectedQuarter = $state(quarters[0] ?? '');
  let filtered = $derived(
    holdings
      .filter(h => h.report_date === selectedQuarter)
      .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))
  );

  let sortKey = $state<keyof Holding>('market_value');
  let sortDir = $state<'asc' | 'desc'>('desc');
</script>

<!-- Quarter selector tabs -->
<div class="tabs">
  {#each quarters.slice(0, 4) as q}
    <button
      class:active={q === selectedQuarter}
      onclick={() => selectedQuarter = q}
    >
      Q{Math.ceil(new Date(q).getMonth() / 3)} {new Date(q).getFullYear()}
    </button>
  {/each}
</div>

<!-- Holdings table -->
<table>
  <thead>
    <tr>
      <th>CUSIP</th>
      <th>Issuer</th>
      <th>Class</th>
      <th class="numeric">Shares</th>
      <th class="numeric">Market Value</th>
      <th class="numeric">Weight</th>
    </tr>
  </thead>
  <tbody>
    {#each filtered as h}
      <tr>
        <td class="mono">{h.cusip}</td>
        <td>{h.issuer_name}</td>
        <td><span class="badge">{h.asset_class ?? '—'}</span></td>
        <td class="numeric">{formatNumber(h.shares)}</td>
        <td class="numeric">{formatCurrency(h.market_value, 'USD', 0)}</td>
        <td class="numeric">{formatPercent(h.weight, 2)}</td>
      </tr>
    {/each}
  </tbody>
</table>

<div class="summary">
  {formatNumber(filtered.length)} positions · Total {formatCurrency(
    filtered.reduce((s, h) => s + (h.market_value ?? 0), 0), 'USD', 0
  )}
</div>
```

#### C. Portfolio Diffs — Activity Feed

```svelte
<!-- PortfolioDiffs.svelte -->
<script lang="ts">
  import { formatCurrency, formatNumber, formatPercent } from '@netz/ui';
  import type { DiffResponse } from '$lib/api/sec';

  interface Props {
    diffs: DiffResponse[];
  }
  let { diffs }: Props = $props();

  // Separar por tipo de ação
  let newPositions = $derived(diffs.filter(d => d.action === 'NEW_POSITION'));
  let exits = $derived(diffs.filter(d => d.action === 'EXITED'));
  let increases = $derived(diffs.filter(d => d.action === 'INCREASED'));
  let decreases = $derived(diffs.filter(d => d.action === 'DECREASED'));

  const actionColors: Record<string, string> = {
    NEW_POSITION: 'text-green-600',
    INCREASED: 'text-green-500',
    DECREASED: 'text-amber-500',
    EXITED: 'text-red-500',
    UNCHANGED: 'text-gray-400',
  };

  const actionLabels: Record<string, string> = {
    NEW_POSITION: 'New',
    INCREASED: '▲ Increased',
    DECREASED: '▼ Decreased',
    EXITED: '✕ Exited',
    UNCHANGED: '— Unchanged',
  };
</script>

{#each diffs.filter(d => d.action !== 'UNCHANGED') as d}
  <div class="diff-row">
    <span class={actionColors[d.action]}>{actionLabels[d.action]}</span>
    <span class="issuer">{d.issuer_name}</span>
    <span class="delta">
      {#if d.shares_delta}
        {formatNumber(d.shares_delta, { signDisplay: 'always' })} shares
      {/if}
    </span>
    <span class="weight">
      {formatPercent(d.weight_before)} → {formatPercent(d.weight_after)}
    </span>
  </div>
{/each}
```

#### D. Concentration Dashboard — Chart Components

```svelte
<!-- ConcentrationDashboard.svelte -->
<script lang="ts">
  import { formatPercent } from '@netz/ui';
  // Use LayerChart (já no stack) para visualizações
  import { Chart, Pie, Tooltip, Bar } from 'layerchart';

  interface Props {
    sectors: Record<string, number>;
    concentration: { hhi: number; top_10_concentration: number; position_count: number };
  }
  let { sectors, concentration }: Props = $props();

  // HHI interpretação
  let hhiLabel = $derived(
    concentration.hhi > 0.25 ? 'Very Concentrated' :
    concentration.hhi > 0.15 ? 'Concentrated' :
    concentration.hhi > 0.01 ? 'Diversified' :
    'Highly Diversified'
  );
</script>

<div class="grid grid-cols-3 gap-4">
  <!-- KPI Cards -->
  <div class="card">
    <div class="label">HHI Index</div>
    <div class="value">{concentration.hhi.toFixed(4)}</div>
    <div class="sublabel">{hhiLabel}</div>
  </div>
  <div class="card">
    <div class="label">Top 10 Weight</div>
    <div class="value">{formatPercent(concentration.top_10_concentration)}</div>
  </div>
  <div class="card">
    <div class="label">Positions</div>
    <div class="value">{concentration.position_count}</div>
  </div>
</div>

<!-- Sector Allocation Pie/Bar -->
<Chart data={Object.entries(sectors).map(([name, weight]) => ({ name, weight }))}>
  <!-- LayerChart pie ou bar chart -->
</Chart>
```

#### E. Institutional Ownership — Coverage-Aware Component

```svelte
<!-- InstitutionalOwnership.svelte -->
<script lang="ts">
  import { formatCurrency } from '@netz/ui';
  import { findInvestors } from '$lib/api/sec';

  interface Props {
    managerCik: string;
  }
  let { managerCik }: Props = $props();

  let result = $state<OwnershipResult | null>(null);
  let loading = $state(true);

  $effect(() => {
    loading = true;
    findInvestors(managerCik).then(r => {
      result = r;
      loading = false;
    });
  });
</script>

{#if loading}
  <Skeleton lines={5} />
{:else if result}
  {#if result.coverage === 'found'}
    <h3>{result.investors.length} Institutional Holders</h3>
    <table>
      <thead>
        <tr>
          <th>Investor</th>
          <th>Type</th>
          <th>Security</th>
          <th class="numeric">Value</th>
          <th class="numeric">Shares</th>
          <th>Report Date</th>
        </tr>
      </thead>
      <tbody>
        {#each result.investors as inv}
          <tr>
            <td>{inv.filer_name}</td>
            <td><span class="badge badge-{inv.filer_type}">{inv.filer_type}</span></td>
            <td>{inv.target_issuer} ({inv.target_cusip})</td>
            <td class="numeric">{formatCurrency(inv.market_value, 'USD', 0)}</td>
            <td class="numeric">{inv.shares?.toLocaleString()}</td>
            <td>{inv.report_date}</td>
          </tr>
        {/each}
      </tbody>
    </table>

  {:else if result.coverage === 'public_securities_no_holders'}
    <div class="info-banner">
      Manager has public securities registered with SEC but no institutional
      13F filers currently hold them.
    </div>

  {:else}
    <div class="info-banner muted">
      No 13F filings found. This manager likely operates via direct private
      credit deals, offshore feeder structures without a US master fund,
      or is below the $100M AUM threshold for 13F filing.
    </div>
  {/if}

  {#if result.note}
    <p class="note text-sm text-muted">{result.note}</p>
  {/if}
{/if}
```

### 10.3 Recomendações de Performance

| Técnica | Onde aplicar | Impacto |
|---------|-------------|---------|
| **Debounce 300ms** | `searchManagers` autocomplete | Reduz calls IAPD de 10/s → 3/s |
| **Stale-while-revalidate** | `fetchHoldings`, `fetchManager` | Render imediato do cache, refresh em background |
| **Skeleton loading** | `findInvestors`, `fetchHoldings` (first load) | Perceived performance |
| **Quarter tabs (lazy)** | Holdings table | Renderiza apenas 1 trimestre por vez |
| **Virtual scroll** | Holdings table (>500 rows) | Vanguard tem 15K+ holdings |
| **formatters de @netz/ui** | Todos os números/datas | Consistência + i18n |
| **`load()` no +page.server.ts** | Manager detail, Holdings page | SSR com streaming |
| **Parallel fetch** | Manager detail page | `Promise.all([fetchManager, fetchFunds, fetchHoldings])` |
| **Error boundaries** | Cada componente SEC | Isolamento — falha em holdings não quebra concentração |

### 10.4 SvelteKit Load Pattern

```typescript
// frontends/credit/src/routes/(team)/sec/managers/[crd]/+page.server.ts

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch }) => {
  const crd = params.crd;

  // Parallel fetch — 3 chamadas simultâneas
  const [manager, funds] = await Promise.all([
    fetch(`/api/v1/sec/managers/${crd}`).then(r => r.ok ? r.json() : null),
    fetch(`/api/v1/sec/managers/${crd}/funds`).then(r => r.json()),
  ]);

  return { manager, funds };
};
```

```typescript
// frontends/credit/src/routes/(team)/sec/thirteenf/[cik]/+page.server.ts
//
// IMPORTANTE: Usar +page.server.ts (NÃO +page.ts) porque:
// 1. Endpoints SEC requerem auth headers (Clerk JWT ou X-DEV-ACTOR)
// 2. +page.ts roda no browser em client-side navigation — o fetch()
//    do SvelteKit injeta cookies automaticamente no SSR, mas em CSR
//    headers customizados (X-DEV-ACTOR) não são propagados
// 3. +page.server.ts SEMPRE roda no server, garantindo auth context

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch }) => {
  const cik = params.cik;

  // Parallel fetch — todos resolvem no server com auth headers
  const [sectors, concentration, holdings] = await Promise.all([
    fetch(`/api/v1/sec/thirteenf/${cik}/sectors?date=2025-12-31`)
      .then(r => r.json()),
    fetch(`/api/v1/sec/thirteenf/${cik}/concentration?date=2025-12-31`)
      .then(r => r.json()),
    fetch(`/api/v1/sec/thirteenf/${cik}/holdings?quarters=4`)
      .then(r => r.json()),
  ]);

  return { sectors, concentration, holdings };

  // ALTERNATIVA com streaming (se holdings for consistentemente lento):
  // return {
  //   sectors,
  //   concentration,
  //   streamed: { holdings },  // resolve via {#await} no template
  // };
};
```

---

## 11. Workers e Ingestão de Dados

### 11.1 Worker de Ingestão Mensal (ADV)

```python
# Executar mensalmente via cron ou BackgroundTasks
async def adv_monthly_ingest():
    """Download e ingest do Form ADV bulk CSV."""
    adv_service = AdvService(db_session_factory=get_session_factory())

    # Download automático + upsert (pode levar 5-10min para ~15K managers)
    count = await adv_service.ingest_bulk_adv()
    logger.info("adv_monthly_ingest_complete", managers=count)
```

### 11.2 Worker de 13F Trimestral

```python
# Executar após cada deadline trimestral de 13F (45 dias após quarter-end)
async def thirteenf_quarterly_refresh(ciks: list[str]):
    """Refresh 13F holdings para lista de CIKs monitorados."""
    svc = ThirteenFService(db_session_factory=get_session_factory())

    for cik in ciks:
        await svc.fetch_holdings(cik, quarters=4, force_refresh=True)
        # Compute diffs automaticamente
        today = date.today()
        q_end = _quarter_end(today)
        q_prev = _quarter_end(q_end - timedelta(days=100))
        await svc.compute_diffs(cik, q_prev, q_end)

    # Refresh materialized view após batch completo
    # (continuous aggregate sec_13f_latest_quarter é atualizado automaticamente)
    async with get_session_factory()() as session:
        await session.execute(text(
            "REFRESH MATERIALIZED VIEW CONCURRENTLY sec_13f_manager_sector_latest"
        ))
        await session.commit()
```

### 11.3 Worker de Discovery Institucional

```python
# Executar semanalmente ou sob demanda
async def institutional_discovery():
    """Descobre e ingere dados de filers institucionais."""
    db_factory = get_session_factory()
    thirteenf = ThirteenFService(db_session_factory=db_factory)
    svc = InstitutionalService(thirteenf_service=thirteenf, db_session_factory=db_factory)

    filers = await svc.discover_institutional_filers(limit=200)

    for filer in filers:
        await svc.fetch_allocations(
            filer_cik=filer["cik"],
            filer_name=filer["filer_name"],
            filer_type=filer["filer_type"],
            quarters=2,
        )
```

### 11.4 Cadência Recomendada

| Worker | Frequência | Janela | Dados |
|--------|-----------|--------|-------|
| ADV Bulk Ingest | Mensal (1º sábado) | ~10min | ~15K managers |
| 13F Holdings Refresh | Trimestral (45 dias pós quarter-end) | ~30min para 100 CIKs | Holdings + diffs + refresh materialized view |
| Institutional Discovery | Semanal | ~15min | Filers + allocations |
| CIK Resolution | On-demand (via deal ingestion) | <5s por entidade | CIK lookup |
| `sec_13f_latest_quarter` | Automático (policy diário) | — | Continuous aggregate (TimescaleDB gerencia) |
| `sec_13f_manager_sector_latest` | Manual (pós 13F batch) | ~1min | `REFRESH MATERIALIZED VIEW CONCURRENTLY` |
| CUSIP Ticker Mapping | Mensal (pós 13F ingest) ou on-demand | ~5min (12K CUSIPs, free tier) | `sec_cusip_ticker_map` via OpenFIGI batch |

---

## 12. Padrões de Erro e Resiliência

### Never-Raises Contract

Todos os métodos públicos dos 3 services seguem o padrão:

```python
async def method(self, ...) -> ReturnType:
    try:
        # business logic
        return result
    except Exception as exc:
        logger.error("method_failed", error=str(exc))
        return safe_default  # [], None, 0, empty InstitutionalOwnershipResult
```

**Implicação para o frontend:** Nunca receberá 500 desses endpoints — sempre receberá uma resposta válida (possivelmente vazia).

### Erro de CIK Inválido

```python
# Todos os services validam CIK/CRD no início
if not _validate_cik(cik):   # ^\d{1,10}$
    return []                 # ou safe default
```

**Implicação para o route:** Validar CIK/CRD no Pydantic schema ou path parameter.

### Staleness e Cache

| Service | Cache | TTL | Fallback |
|---------|-------|-----|----------|
| `fetch_manager` | DB (bulk ingest) | ∞ (sempre stale-but-serve) | `None` |
| `fetch_holdings` | DB → EDGAR refresh | 45 dias | Cache antigo |
| `find_investors` | DB (institutional_allocations) | Depende do discovery worker | Empty result |

---

## 13. Rate Limits

### SEC Rate Limits

| API | Rate | Enforced by |
|-----|------|------------|
| EDGAR (efts.sec.gov, edgartools) | 8 req/s (conservador, SEC permite 10) | `check_edgar_rate()` |
| IAPD (api.adviserinfo.sec.gov) | 2 req/s (API não documentada) | `check_iapd_rate()` |
| OpenFIGI (api.openfigi.com) | 25 req/min (free) ou 250 req/min (com key) | `asyncio.sleep()` entre batches |

### Recomendação para Frontend

- **Autocomplete:** Debounce 300ms mínimo (evita burst)
- **Holdings refresh:** Botão com cooldown de 30s (evita re-fetch acidental)
- **Bulk operations:** Usar workers, nunca endpoint síncrono
- **Rate limit response:** Se SEC retornar 429, o service loga e retorna `[]` — o frontend deve exibir "try again later"

---

## 14. Referência Rápida de Campos

### ADV Manager — Campos Disponíveis

| Campo | Tipo | Fonte | Disponível via |
|-------|------|-------|---------------|
| `crd_number` | string | IAPD + CSV | search, fetch |
| `cik` | string? | CSV cross-reference | fetch |
| `firm_name` | string | IAPD + CSV | search, fetch |
| `sec_number` | string? | IAPD + CSV | search, fetch |
| `registration_status` | string? | IAPD + CSV | search, fetch |
| `aum_total` | int? (USD) | CSV only | fetch |
| `aum_discretionary` | int? (USD) | CSV only | fetch |
| `aum_non_discretionary` | int? (USD) | CSV only | fetch |
| `total_accounts` | int? | CSV only | fetch |
| `fee_types` | JSONB? | CSV only | fetch |
| `client_types` | JSONB? | CSV only | fetch |
| `state` | string? | IAPD + CSV | search, fetch |
| `country` | string? | IAPD + CSV | search, fetch |
| `website` | string? | CSV only | fetch |
| `compliance_disclosures` | int? | CSV only | fetch |
| `last_adv_filed_at` | date? | CSV only | fetch |

### 13F Holdings — Campos Disponíveis

| Campo | Tipo | PK | Descrição |
|-------|------|----|-----------|
| `report_date` | date | PK1 | Quarter-end (e.g. 2025-12-31) — partition key do hypertable |
| `cik` | string | PK2 | CIK do filer (10 dígitos) |
| `cusip` | string | PK3 | CUSIP do título (9 chars) |
| `filing_date` | date | | Data do envio à SEC |
| `accession_number` | string | | ID único do filing |
| `issuer_name` | string | | Nome do emissor |
| `asset_class` | string? | | COM, CALL, PUT, etc. |
| `sector` | string? | | GICS sector (Technology, Financials, etc.) — via `enrich_holdings_with_sectors()` |
| `shares` | bigint? | | Quantidade |
| `market_value` | bigint? | | USD (já multiplicado ×1000) |
| `discretion` | string? | | SOLE, SHARED, DEFINED |
| `voting_sole` | bigint? | | Votos exclusivos |
| `voting_shared` | bigint? | | Votos compartilhados |
| `voting_none` | bigint? | | Sem direito a voto |

> **Nota:** Sem coluna `id` (UUID) — hypertable exige partition key na PK. Natural key `(report_date, cik, cusip)` é suficiente.

### 13F Diffs — Ações Possíveis

| Action | Significado | shares_delta |
|--------|-----------|--------------|
| `NEW_POSITION` | Posição nova (não existia no trimestre anterior) | = shares_after |
| `INCREASED` | Aumentou posição | > 0 |
| `DECREASED` | Reduziu posição | < 0 |
| `EXITED` | Saiu completamente | = -shares_before |
| `UNCHANGED` | Mesma quantidade de ações | 0 |

### Institutional Allocation — Coverage Types

| Coverage | Significado | Ação recomendada no frontend |
|----------|-----------|------------------------------|
| `found` | Investidores institucionais encontrados | Exibir tabela de holders |
| `public_securities_no_holders` | Manager tem CUSIPs mas ninguém reporta deter | Info banner "sem holders" |
| `no_public_securities` | Manager não tem filings 13F | Info banner explicando motivo (private credit, offshore, <$100M) |

---

## 15. CUSIP → Ticker Mapping (Phase 6)

### 15.1 Visão Geral

A tabela `sec_cusip_ticker_map` (migration `0033`) mapeia CUSIPs de posições 13F para tickers de mercado via OpenFIGI batch API. Isso habilita:

- **Price lookups em tempo real** via YFinance para qualquer posição 13F
- **Performance attribution** com preços reais entre filings
- **"Since last filing" return** — estimativa de retorno por posição
- **Integração frontend** — Manager Analytics com preços ao vivo

### 15.2 Schema

```sql
CREATE TABLE sec_cusip_ticker_map (
    cusip TEXT PRIMARY KEY,
    ticker TEXT,
    issuer_name TEXT,
    exchange TEXT,
    security_type TEXT,       -- CS, ETF, ADR, REIT, etc.
    figi TEXT,                -- OpenFIGI global identifier
    composite_figi TEXT,      -- OpenFIGI composite (preferido p/ YFinance)
    resolved_via TEXT NOT NULL,  -- openfigi | unresolved
    is_tradeable BOOLEAN NOT NULL DEFAULT false,
    last_verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Partial indexes
CREATE INDEX idx_cusip_ticker_map_ticker
    ON sec_cusip_ticker_map (ticker) WHERE ticker IS NOT NULL;
CREATE INDEX idx_cusip_ticker_map_unresolved
    ON sec_cusip_ticker_map (resolved_via) WHERE resolved_via = 'unresolved';
```

**Tipo:** Tabela regular (lookup/referência) — **NÃO** é hypertable.
**Escopo:** Global (sem `organization_id`, sem RLS) — consistente com todas as tabelas `sec_*`.

### 15.3 ORM Model

```python
class SecCusipTickerMap(Base):
    __tablename__ = "sec_cusip_ticker_map"

    cusip: Mapped[str] = mapped_column(Text, primary_key=True)
    ticker: Mapped[str | None] = mapped_column(Text)
    issuer_name: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(Text)
    security_type: Mapped[str | None] = mapped_column(Text)
    figi: Mapped[str | None] = mapped_column(Text)
    composite_figi: Mapped[str | None] = mapped_column(Text)
    resolved_via: Mapped[str] = mapped_column(Text, nullable=False)
    is_tradeable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_verified_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
```

### 15.4 Queries Úteis

```sql
-- Estatísticas de resolução
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN is_tradeable THEN 1 ELSE 0 END) as tradeable,
    SUM(CASE WHEN resolved_via = 'unresolved' THEN 1 ELSE 0 END) as unresolved
FROM sec_cusip_ticker_map;

-- Top exchanges
SELECT exchange, COUNT(*) as count
FROM sec_cusip_ticker_map
WHERE ticker IS NOT NULL
GROUP BY exchange
ORDER BY count DESC;

-- Buscar ticker por CUSIP
SELECT ticker, issuer_name, exchange, is_tradeable
FROM sec_cusip_ticker_map
WHERE cusip = '594918104';  -- MSFT

-- Reverse: todos os CUSIPs para um ticker
SELECT cusip, issuer_name, security_type
FROM sec_cusip_ticker_map
WHERE ticker = 'AAPL';

-- CUSIPs não resolvidos (candidatos a retry)
SELECT cusip FROM sec_cusip_ticker_map
WHERE resolved_via = 'unresolved';
```

---

## 16. Seed Population Script

### 16.1 Visão Geral

Script one-time para popular as tabelas `sec_*` com um universo curado de 60 gestores de investimento. Resumível via checkpoint. Localizado em `backend/data_providers/sec/seed/`.

**Arquivos:**
- `manager_seed_list.py` — Lista curada de 60 managers (equity, FI, alternatives, hedge funds, institucionais)
- `populate_seed.py` — Script de 6 fases com CLI completo

### 16.2 Fases

| Fase | Descrição | Fonte | Destino |
|------|-----------|-------|---------|
| 1 | ADV bulk CSV ingest | SEC FOIA download | `sec_managers` |
| 2 | 13F holdings (2 passes: recente + histórico) | EDGAR via edgartools | `sec_13f_holdings` |
| 3 | Diffs computation | DB (holdings) | `sec_13f_diffs` |
| 4 | Sector enrichment | SIC/OpenFIGI/yfinance/keyword | `sec_13f_holdings.sector` |
| 5 | Institutional allocations | EDGAR (endowments/pensions) | `sec_institutional_allocations` |
| 6 | CUSIP → Ticker mapping | OpenFIGI batch API | `sec_cusip_ticker_map` |

### 16.3 CLI

```bash
# Full pipeline (todas as 6 fases)
python -m data_providers.sec.seed.populate_seed

# Resume de checkpoint
python -m data_providers.sec.seed.populate_seed --resume

# Dry run (resolve CIKs, print plan, sem DB writes)
python -m data_providers.sec.seed.populate_seed --dry-run

# Apenas ADV
python -m data_providers.sec.seed.populate_seed --only-adv

# Apenas holdings
python -m data_providers.sec.seed.populate_seed --only-holdings

# Apenas ticker mapping (Phase 6)
python -m data_providers.sec.seed.populate_seed --only-ticker-map

# Ticker mapping com API key (10x mais rápido)
python -m data_providers.sec.seed.populate_seed --only-ticker-map --openfigi-key YOUR_KEY

# Retry CUSIPs não resolvidos
python -m data_providers.sec.seed.populate_seed --only-ticker-map --retry-unresolved

# Um manager específico
python -m data_providers.sec.seed.populate_seed --manager BX

# Apenas últimos 8 trimestres (screener usável rápido)
python -m data_providers.sec.seed.populate_seed --recent-only
```

### 16.4 Checkpoint

Arquivo `.sec_seed_checkpoint.json` na raiz do backend. Tracks:
- `completed`: set de `{cik}:recent` e `{cik}:full` keys
- `failed`: dict de `{cik: error_message}`

Limpo automaticamente se `--resume` não for passado.

### 16.5 Universo de Managers

60 gestores pré-pesquisados cobrindo:

| Categoria | Quantidade | Exemplos |
|-----------|-----------|----------|
| Traditional Asset Managers | 20 | BlackRock, Vanguard, Fidelity, T. Rowe Price |
| Fixed Income Specialists | 6 | PIMCO, DoubleLine, Loomis Sayles |
| Alternatives / Private Credit / BDCs | 15 | Blackstone, Ares, KKR, Apollo, Oaktree |
| Hedge Funds (>$100M) | 10 | Bridgewater, Renaissance, Citadel, Two Sigma |
| Institutional Investors | 10 | Harvard, Yale, CalPERS, Norges Bank |

---

## 17. Itens Abertos e Limitações Conhecidas

### 17.0 TimescaleDB Hypertables — Concluído (Phase 10 + Migration 0028)

Todas as três tabelas de séries temporais SEC convertidas para hypertables:

| Tabela | Migration | Partition col | Chunks | Compress after | segmentby |
|--------|-----------|---------------|--------|----------------|-----------|
| `sec_13f_holdings` | 0025 | `report_date` | 3 meses | 6 meses | `cik` |
| `sec_13f_diffs` | 0025 | `quarter_to` | 3 meses | 6 meses | `cik` |
| `sec_institutional_allocations` | 0028 | `report_date` | 3 meses | 6 meses | `filer_cik` |

Impactos:
- **ORM:** `Sec13fHolding`, `Sec13fDiff` e `SecInstitutionalAllocation` não têm mais `id` (UUID). PK composta na natural key.
- **Queries:** Todas as queries devem incluir filtro de `report_date` / `quarter_to` para chunk pruning.
- **Compressão:** Chunks >6 meses são comprimidos automaticamente.
- **Screener:** Usar `sec_13f_latest_quarter` (continuous aggregate) e `sec_13f_manager_sector_latest` (mat view) para list view.

### 17.1 `fetch_manager_team()` — Stub M1

**Status:** Retorna `[]` com log `INFO` level (`adv_fetch_team_stub`).

**Impacto no Wealth DD Report:** O `evidence_pack` do DD Report pode tentar popular o campo de team bios via `fetch_manager_team()`. Receberá lista vazia. O log `INFO` garante visibilidade no concordance logging do pipeline — não é silencioso.

**Ação necessária (M2):** Implementar OCR de Part 2A PDF via Mistral:
1. Download do brochure de `reports.adviserinfo.sec.gov/crd/{crd}/brochure`
2. OCR via Mistral API (pipeline existente)
3. Extração estruturada (nome, cargo, educação, certificações)
4. Persist em `sec_manager_team`

**Workaround frontend:** Se o componente de team bios receber lista vazia, exibir placeholder "Team information not yet available — requires Part 2A brochure processing" em vez de esconder a seção silenciosamente.

### 17.2 Tone Normalizer — Paired Logging `first_pass → tone`

**Status do logging existente:**

O tone normalizer já emite logs pareados em dois níveis:

| Log Event | Módulo | Dados |
|---|---|---|
| `deep_review.v4.tone_normalizer.start` | `deep_review/service.py` | `deal_id`, `chapters` count, `signal` |
| `deep_review.v4.memo_to_tone_handoff` | `deep_review/service.py` | `deal_id`, `chapters`, `total_chars`, `chapter_chars` (dict por capítulo), `signal` |
| `tone_normalizer.chapter_diff` (pass_num=1) | `memo/tone.py` | `deal_id`, `chapter_id`, `input_len`, `output_len`, `skipped` |
| `tone_normalizer.chapter_diff` (pass_num=2) | `memo/tone.py` | `deal_id`, `chapter_id`, `input_len`, `output_len` |
| `deep_review.v4.tone_normalizer.db_updated` | `deep_review/service.py` | `deal_id`, `chapters` count |
| `deep_review.v4.tone_normalizer.signal_escalated` | `deep_review/service.py` | `deal_id`, `signal_from`, `signal_to`, `rationale` |

**Resolvido (2026-03-21):** Log `deep_review.v4.memo_to_tone_handoff` adicionado em ambos os call sites de `deep_review/service.py`, logo antes da chamada a `_run_tone_normalizer()`. Registra `total_chars`, `chapter_chars` (por capítulo), e `signal` — fecha o gap de observabilidade entre a saída do memo generator e a entrada do tone normalizer.

### 17.3 Notas de Autenticação para Frontend

**Contexto:** O sistema usa Clerk JWT v2 para autenticação. Em dev, o header `X-DEV-ACTOR` bypassa auth.

**Regra para SvelteKit load functions:**
- **`+page.server.ts`** (recomendado para SEC endpoints): O `fetch()` do SvelteKit injeta cookies automaticamente no server. Auth headers são propagados corretamente.
- **`+page.ts`**: Roda no browser em client-side navigation. O `fetch()` do SvelteKit propaga cookies no SSR, mas em CSR (client-side routing) headers customizados como `X-DEV-ACTOR` NÃO são automaticamente incluídos.
- **Componentes client-side** (autocomplete, refresh buttons): Devem usar o wrapper `authHeaders()` de `$lib/api/sec.ts` que inclui o token Clerk via `getToken()`.

**Consequência:** Todos os endpoints SEC que requerem autenticação devem ser chamados via `+page.server.ts` para load functions, ou via wrapper com `authHeaders()` para fetches client-side.
