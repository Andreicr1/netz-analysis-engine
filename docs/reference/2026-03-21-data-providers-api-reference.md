# Reference: Data Providers — API, Services, Frontend Coverage

> Mapeamento completo de todos os data providers em `backend/data_providers/`, suas APIs externas,
> servicos internos que alimentam, endpoints backend, e status de conexao com o frontend.

---

## Indice

1. [Visao Geral](#1-visao-geral)
2. [BIS — Bank for International Settlements](#2-bis)
3. [IMF — International Monetary Fund](#3-imf)
4. [SEC — Securities and Exchange Commission](#4-sec)
5. [ESMA — European Securities and Markets Authority](#5-esma)
6. [Workers e Endpoints de Trigger](#6-workers)
7. [Manager Screener API](#7-manager-screener-api)
8. [Macro Pipeline (BIS + IMF → Regional Scores)](#8-macro-pipeline)
9. [Cobertura Frontend](#9-cobertura-frontend)
10. [Endpoints sem Consumidor Frontend](#10-endpoints-sem-frontend)
11. [Gaps e Proximos Passos](#11-gaps)

---

## 1. Visao Geral

```
backend/data_providers/
├── bis/
│   ├── __init__.py
│   └── service.py           ← BIS SDMX CSV API (credit gap, DSR, property prices)
├── imf/
│   ├── __init__.py
│   └── service.py           ← IMF DataMapper JSON API (GDP, inflation, fiscal, debt)
├── sec/
│   ├── __init__.py
│   ├── models.py            ← 12 frozen dataclasses (zero app.* imports)
│   ├── shared.py            ← Rate limiting, CIK resolution, sector resolution, thread pool
│   ├── adv_service.py       ← Form ADV (IAPD search, bulk CSV, brochure PDF extraction)
│   ├── thirteenf_service.py ← 13F Holdings (quarterly equity positions)
│   ├── nport_service.py     ← N-PORT Holdings (monthly mutual fund portfolios)
│   ├── institutional_service.py ← 13F Reverse Lookup (institutional ownership)
│   └── seed/                ← Seed data utilities
└── esma/
    ├── __init__.py
    ├── models.py            ← 3 frozen dataclasses
    ├── shared.py            ← Rate limiting, OpenFIGI batch resolver, exchange mapping
    ├── register_service.py  ← ESMA Solr API (UCITS funds + managers)
    ├── ticker_resolver.py   ← ISIN → Yahoo Finance ticker (via OpenFIGI)
    └── seed/                ← ESMA seed pipeline (4 phases)
```

**Isolamento:** Todos os data providers tem zero imports de `app.domains.*`, `vertical_engines.*`, `quant_engine.*`, `ai_engine.*` (enforced by import-linter).

---

## 2. BIS

### 2.1 API Externa

| Campo | Valor |
|-------|-------|
| Base URL | `https://stats.bis.org/api/v1/data` |
| Formato | CSV (SDMX REST) |
| Auth | Nenhuma |
| Rate Limit | Sem limite documentado |
| Frequencia dados | Trimestral |
| Cobertura | 44 paises (ISO-2) |

### 2.2 Datasets

| Dataset | Indicator Name | Descricao | Coluna Pais |
|---------|---------------|-----------|-------------|
| `WS_CREDIT_GAP` | `credit_to_gdp_gap` | Credit-to-GDP gap (pre-computed by BIS) | `BORROWERS_CTY` |
| `WS_DSR` | `debt_service_ratio` | Debt service ratio | `BORROWERS_CTY` |
| `WS_SPP` | `property_prices` | Residential property prices | `REF_AREA` |

### 2.3 Funcoes Publicas

| Funcao | Arquivo | Descricao |
|--------|---------|-----------|
| `fetch_bis_dataset(client, dataset, indicator_name, countries?)` | `bis/service.py:68` | Fetch um dataset BIS para paises especificados |
| `fetch_all_bis_data(countries?)` | `bis/service.py:143` | Fetch todos os 3 datasets, retorna lista flat |
| `_parse_quarter(period_str)` | `bis/service.py:54` | Parse `"2024-Q1"` → `datetime` |

### 2.4 Modelo

```python
@dataclass(frozen=True)
class BisIndicator:
    country_code: str   # ISO-2
    indicator: str      # "credit_to_gdp_gap" | "debt_service_ratio" | "property_prices"
    period: datetime    # UTC, first day of quarter
    value: float
    dataset: str        # "WS_CREDIT_GAP" | "WS_DSR" | "WS_SPP"
```

### 2.5 Cadeia de Consumo

```
BIS CSV API
  └─→ fetch_all_bis_data()
       └─→ BIS Worker (900_014, quarterly)
            └─→ bis_statistics hypertable (1yr chunks, segmentby=country_code)
                 └─→ regional_macro_service.score_credit_cycle()
                      └─→ enrich_region_score() — 7a dimensao do composite
                           └─→ macro_snapshot_builder.build_regional_snapshot()
                                └─→ GET /macro/scores (frontend /macro page)
```

### 2.6 Status Frontend

| Endpoint Backend | Consumido pelo Frontend? | Onde |
|-----------------|------------------------|------|
| `POST /workers/run-bis-ingestion` | **NAO** | Worker admin-only |
| BIS data via `GET /macro/scores` | **SIM** | `frontends/wealth/(team)/macro/` |
| BIS data via `GET /macro/snapshot` | **SIM** | `frontends/wealth/(team)/macro/` |

---

## 3. IMF

### 3.1 API Externa

| Campo | Valor |
|-------|-------|
| Base URL | `https://www.imf.org/external/datamapper/api/v1` |
| Formato | JSON |
| Auth | Nenhuma |
| Rate Limit | Sem limite documentado |
| Frequencia dados | Semestral (abril + outubro) |
| Cobertura | 44 paises (ISO-3 → ISO-2 no DB) |

### 3.2 Indicadores WEO

| Codigo | Label | Descricao |
|--------|-------|-----------|
| `NGDP_RPCH` | `gdp_growth` | Real GDP growth (%) |
| `PCPIPCH` | `inflation` | Inflacao media CPI (%) |
| `GGXCNL_NGDP` | `fiscal_balance` | Resultado fiscal governo geral (% do PIB) |
| `GGXWDG_NGDP` | `govt_debt` | Divida bruta governo geral (% do PIB) |

### 3.3 Funcoes Publicas

| Funcao | Arquivo | Descricao |
|--------|---------|-----------|
| `fetch_imf_indicator(client, indicator_code, countries?)` | `imf/service.py:64` | Fetch um indicador WEO |
| `fetch_all_imf_data(countries?)` | `imf/service.py:134` | Fetch todos os 4 indicadores |

### 3.4 Modelo

```python
@dataclass(frozen=True)
class ImfForecast:
    country_code: str   # ISO-2 (convertido de ISO-3)
    indicator: str      # "NGDP_RPCH" | "PCPIPCH" | "GGXCNL_NGDP" | "GGXWDG_NGDP"
    year: int
    value: float
    edition: str        # "YYYYMM" (e.g. "202604")
```

### 3.5 Mapeamento ISO-3 → ISO-2

44 paises mapeados. Exemplos: `USA→US`, `GBR→GB`, `DEU→DE`, `BRA→BR`, `JPN→JP`, `CHN→CN`.

### 3.6 Cadeia de Consumo

```
IMF JSON API
  └─→ fetch_all_imf_data()
       └─→ IMF Worker (900_015, quarterly)
            └─→ imf_weo_forecasts hypertable (1yr chunks, segmentby=country_code)
                 └─→ regional_macro_service.blend_imf_growth()
                      └─→ enrich_region_score() — blend FRED 70% + IMF 30%
                           └─→ macro_snapshot_builder.build_regional_snapshot()
                                └─→ GET /macro/scores (frontend /macro page)
```

### 3.7 Status Frontend

| Endpoint Backend | Consumido pelo Frontend? | Onde |
|-----------------|------------------------|------|
| `POST /workers/run-imf-ingestion` | **NAO** | Worker admin-only |
| IMF data via `GET /macro/scores` | **SIM** | `frontends/wealth/(team)/macro/` |

---

## 4. SEC

### 4.1 APIs Externas

| API | Base URL | Auth | Rate Limit | Usado por |
|-----|----------|------|------------|-----------|
| EDGAR EFTS | `https://efts.sec.gov/LATEST` | User-Agent | 10 req/s (usamos 8) | CIK resolution |
| EDGAR Filings | `https://www.sec.gov/cgi-bin/browse-edgar` | User-Agent | 10 req/s | 13F, N-PORT filings |
| IAPD Search | SEC IAPD API | Nenhuma | 2 req/s (conservative) | Manager ADV search |
| SEC FOIA | Monthly CSV bulk download | Nenhuma | N/A (download unico) | ADV bulk ingestion |
| ADV Part 2A | SEC EDGAR PDF brochures | User-Agent | 8 req/s | Team extraction, brochure text |

### 4.2 SEC — ADV Service

**Arquivo:** `sec/adv_service.py`
**Classe:** `AdvService(db_session_factory)`

| Metodo | API Externa | Destino DB |
|--------|-------------|------------|
| `search_managers(query, limit=25)` | IAPD `/api/search/firm` | — (search only) |
| `ingest_bulk_adv()` | SEC FOIA monthly CSV (ZIP) | `sec_managers`, `sec_manager_funds` |
| `fetch_manager_team(crd)` | ADV Part 2A PDF | `sec_manager_team` |
| `extract_brochure_sections(crd)` | ADV Part 2A PDF (PyMuPDF) | `sec_manager_brochure_text` |

**18 secoes classificadas do ADV Part 2A:**
`advisory_business`, `fees_compensation`, `performance_fees`, `client_types`, `methods_of_analysis`, `disciplinary_information`, `other_financial_activities`, `code_of_ethics`, `brokerage_practices`, `review_of_accounts`, `client_referrals`, `custody`, `investment_discretion`, `voting_client_securities`, `financial_information`, `investment_philosophy`, `risk_management`, `esg_integration`.

### 4.3 SEC — 13F Holdings Service

**Arquivo:** `sec/thirteenf_service.py`
**Classe:** `ThirteenFService(db_session_factory, rate_check?)`

| Metodo | Descricao | Destino DB |
|--------|-----------|------------|
| `fetch_holdings(cik, quarters=8, force_refresh?, staleness_ttl_days=45)` | Fetch 13F quarterly holdings | `sec_13f_holdings` |
| `compute_diffs(cik, quarter_from, quarter_to)` | Diffs quarter-over-quarter | `sec_13f_diffs` |
| `get_sector_aggregation(cik, report_date)` | Agregacao setorial | — (read-only) |
| `get_concentration_metrics(cik, report_date)` | HHI, top-10, position_count | — (read-only) |
| `enrich_holdings_with_sectors(cik, report_date)` | Backfill sector (SIC → OpenFIGI → heuristic) | `sec_13f_holdings` |

### 4.4 SEC — N-PORT Service

**Arquivo:** `sec/nport_service.py`
**Classe:** `NportService(db_session_factory, rate_check?)`

| Metodo | API | Destino DB |
|--------|-----|------------|
| `fetch_holdings(cik, months=12, force_refresh?, staleness_ttl_days=45)` | EDGAR N-PORT XML (edgartools) | `sec_nport_holdings` |

**Parser:** `_parse_nport_xml_holdings(root, cik, report_date)` — iterative XML, max 20K holdings, chunks de 2000.

### 4.5 SEC — Institutional Service

**Arquivo:** `sec/institutional_service.py`
**Classe:** `InstitutionalService(db_session_factory, rate_check?)`

| Metodo | Descricao | Destino DB |
|--------|-----------|------------|
| `fetch_institutional_allocations(target_cusip)` | 13F reverse lookup — quem segura este CUSIP | `sec_institutional_allocations` |

**Classificacao de filer types:** Endowment, Pension, Foundation, Sovereign, Insurance, Hedge Fund, Mutual Fund.

### 4.6 SEC — Shared Utilities

**Arquivo:** `sec/shared.py`

| Funcao | Descricao |
|--------|-----------|
| `check_edgar_rate()` | Rate limiter 8 req/s (Redis ou local token bucket) |
| `check_iapd_rate()` | Rate limiter 2 req/s |
| `run_in_sec_thread(fn, *args)` | ThreadPoolExecutor (4 workers, "sec-data") |
| `resolve_cik(entity_name, ticker?)` | 3-layer: ticker → fuzzy → EFTS |
| `resolve_sector(cusip, issuer?)` | 3-tier: SIC → OpenFIGI/yfinance → keyword |
| `sanitize_entity_name(name)` | Safe name validation (200 chars max, ASCII-safe) |

### 4.7 SEC — Modelos

12 frozen dataclasses em `sec/models.py`:

| Dataclass | Campos-chave |
|-----------|-------------|
| `CikResolution` | method: "ticker"/"fuzzy"/"efts"/"not_found", confidence: 0.0-1.0 |
| `AdvManager` | crd_number, cik, firm_name, aum_total, fee_types, client_types |
| `AdvFund` | fund_name, fund_id, gross_asset_value, fund_type, investor_count |
| `AdvTeamMember` | person_name, title, certifications[], years_experience |
| `AdvBrochureSection` | section, content, filing_date |
| `ThirteenFHolding` | cik, report_date, cusip, issuer_name, sector, market_value, shares |
| `ThirteenFDiff` | action: "NEW_POSITION"/"EXITED"/"INCREASED"/"DECREASED"/"UNCHANGED" |
| `InstitutionalAllocation` | filer_cik, filer_name, filer_type, target_cusip, market_value |
| `InstitutionalOwnershipResult` | coverage: "found"/"public_securities_no_holders"/"no_public_securities" |
| `CusipTickerResult` | cusip, ticker, figi, is_tradeable |
| `NportHolding` | cik, report_date, cusip, isin, market_value, pct_of_nav |
| `SeriesFetchResult` | data[], warnings[], is_stale |

### 4.8 SEC — Cadeia de Consumo

```
SEC FOIA (monthly CSV)
  └─→ AdvService.ingest_bulk_adv()
       └─→ sec_managers, sec_manager_funds

EDGAR 13F (quarterly XML, via edgartools)
  └─→ ThirteenFService.fetch_holdings()
       └─→ sec_13f_holdings, sec_13f_diffs

ADV Part 2A (PDF brochures, PyMuPDF)
  ├─→ brochure_download worker (Lock 900_019, weekly)
  │    └─→ StorageClient: gold/_global/sec_brochures/{crd}.pdf
  │         └─→ brochure_extract worker (Lock 900_020, on-demand)
  │              ├─→ sec_manager_brochure_text (GIN full-text search)
  │              └─→ sec_manager_team
  └─→ AdvService._download_and_extract_brochure() (lazy, on-demand)
       └─→ StorageClient → legacy local → IAPD fallback

EDGAR N-PORT (monthly XML, via edgartools)
  └─→ NportService.fetch_holdings()
       └─→ sec_nport_holdings hypertable

Migration 0038 (Continuous Aggregates)
  └─→ sec_13f_holdings_agg (setor, HHI, posicoes)
  └─→ sec_13f_drift_agg (churn, turnover)

SEC Refresh Worker (900_016, daily)
  └─→ Refresh continuous aggregates
  └─→ Redis cache: screener:agg:{crd} (24h TTL ±1h jitter)

Manager Screener Routes (Query Builder)
  └─→ Reads: sec_managers + aggs + Redis + instruments_universe
  └─→ 8 REST endpoints → Frontend /manager-screener

Credit EDGAR Engine
  └─→ vertical_engines/credit/edgar/service.py
       └─→ resolve_cik(), check_edgar_rate(), sanitize_entity_name()
       └─→ IC memo entity enrichment (sponsor, borrower, guarantor)
```

---

## 5. ESMA

### 5.1 APIs Externas

| API | Base URL | Auth | Rate Limit |
|-----|----------|------|------------|
| ESMA Register (Solr) | `https://registers.esma.europa.eu/solr/esma_registers_funds_cbdif/select` | Nenhuma | 4 req/s (conservative) |
| OpenFIGI Batch | `https://api.openfigi.com/v3/mapping` | Opcional (API key) | 1 req/s (free) / 4 req/s (key) |

### 5.2 ESMA Register — Campos Solr (verificados 2026-03)

| Campo Solr | Descricao | Mapeado para |
|------------|-----------|-------------|
| `funds_manager_nat_code` | Manager ID | `EsmaManager.esma_id` |
| `funds_manager_lei` | Manager LEI | `EsmaManager.lei` |
| `funds_manager_nat_name` | Company name | `EsmaManager.company_name` |
| `funds_ca_cou_code` | Manager country (ISO-2) | `EsmaManager.country` |
| `funds_status_code_name` | Authorization status | `EsmaManager.authorization_status` |
| `funds_lei` | Fund LEI (unique ID) | `EsmaFund.isin` |
| `funds_national_name` | Fund name | `EsmaFund.fund_name` |
| `funds_domicile_cou_code` | Fund domicile | `EsmaFund.domicile` |
| `funds_legal_framework_name` | Fund type (UCITS) | `EsmaFund.fund_type` |
| `funds_host_country_codes` | Host member states | `EsmaFund.host_member_states` |

### 5.3 Register Service

**Arquivo:** `esma/register_service.py`
**Classe:** `RegisterService(http_client?, page_size=1000)`

| Metodo | Descricao |
|--------|-----------|
| `get_total_count()` | Total UCITS funds (~134K) |
| `iter_ucits_funds(max_pages?)` | AsyncIterator, memory-efficient pagination |
| `fetch_managers_from_funds(funds)` | Deduplica managers de fund docs |

### 5.4 Ticker Resolver

**Arquivo:** `esma/ticker_resolver.py`
**Classe:** `TickerResolver(api_key?, http_client?)`

| Metodo | Descricao |
|--------|-----------|
| `resolve_batch(isins)` | Resolve batch ≤100 ISINs via OpenFIGI |
| `resolve_all(isins, on_batch_complete?)` | Chunked resolution com callback de progresso |

**Exchange Mapping:** 40+ exchanges europeias + US mapeadas para sufixos Yahoo Finance.
Ex: `LN→.L`, `GY→.DE`, `FP→.PA`, `NA→.AS`, `IM→.MI`, `US→""`.

### 5.5 ESMA Modelos

```python
@dataclass(frozen=True)
class EsmaManager:
    esma_id: str
    lei: str | None
    company_name: str
    country: str | None
    authorization_status: str | None
    fund_count: int | None
    sec_crd_number: str | None = None   # Cross-ref com SEC

@dataclass(frozen=True)
class EsmaFund:
    isin: str              # Fund LEI (20 chars)
    fund_name: str
    esma_manager_id: str
    domicile: str | None
    fund_type: str | None
    host_member_states: list[str] = field(default_factory=list)
    yahoo_ticker: str | None = None

@dataclass(frozen=True)
class IsinResolution:
    isin: str
    yahoo_ticker: str | None
    exchange: str | None
    resolved_via: str      # "openfigi" | "unresolved"
    is_tradeable: bool
```

### 5.6 Seed Pipeline (4 fases, resumable)

| Fase | Descricao | Destino DB |
|------|-----------|------------|
| 1 | Popula managers + funds do Solr API | `esma_managers`, `esma_funds` |
| 2 | Resolve ISINs via OpenFIGI | `esma_isin_ticker_map` |
| 3 | Backfill NAV via Yahoo Finance | `nav_timeseries` |
| 4 | Cross-reference SEC ↔ ESMA (fuzzy matching) | `esma_managers.sec_crd_number` |

### 5.7 Status de Integracao

| Componente | Status | Detalhes |
|------------|--------|---------|
| `RegisterService` | **Funcional** | API conecta, e2e validado |
| `TickerResolver` | **Funcional** | OpenFIGI resolve ISINs, e2e validado |
| Worker de ingestion | **NAO EXISTE** | Sem worker para popular esma_managers/esma_funds |
| Endpoint trigger | **NAO EXISTE** | Sem `POST /workers/run-esma-ingestion` |
| Rota backend | **NAO EXISTE** | Sem endpoints REST para consultar dados ESMA |
| Frontend | **NAO EXISTE** | Sem pagina para ESMA managers/funds |

---

## 6. Workers e Endpoints de Trigger

### 6.1 Workers que usam Data Providers

| Worker | Lock ID | Arquivo | Provider | Hypertable | Frequencia |
|--------|---------|---------|----------|------------|------------|
| `sec_refresh` | 900_016 | `workers/sec_refresh.py` | SEC (continuous aggs) | Redis cache | Daily |
| `brochure_download` | 900_019 | `workers/brochure_ingestion.py` | SEC IAPD (ADV Part 2A PDFs) | StorageClient (`gold/_global/sec_brochures/`) | Weekly |
| `brochure_extract` | 900_020 | `workers/brochure_ingestion.py` | StorageClient (PDFs) → PyMuPDF | `sec_manager_brochure_text`, `sec_manager_team` | On-demand |
| `nport_ingestion` | 900_018 | `workers/nport_ingestion.py` | SEC N-PORT (edgartools) | `sec_nport_holdings` | Weekly |
| `bis_ingestion` | 900_014 | `workers/bis_ingestion.py` | BIS SDMX CSV | `bis_statistics` | Quarterly |
| `imf_ingestion` | 900_015 | `workers/imf_ingestion.py` | IMF DataMapper JSON | `imf_weo_forecasts` | Quarterly |

### 6.2 Trigger Endpoints

**Prefix:** `/api/v1/workers` — Auth: `Role.INVESTMENT_TEAM` ou `Role.ADMIN`

| Endpoint | Worker | Lock ID | Status Frontend |
|----------|--------|---------|----------------|
| `POST /run-sec-refresh` | SEC continuous agg refresh | 900_016 | **NAO** |
| `POST /run-brochure-download` | ADV brochure PDF download → StorageClient | 900_019 | **NAO** |
| `POST /run-brochure-extract` | Brochure text extraction (PyMuPDF) → DB | 900_020 | **NAO** |
| `POST /run-nport-ingestion` | N-PORT holdings | 900_018 | **NAO** |
| `POST /run-bis-ingestion` | BIS statistics | 900_014 | **NAO** |
| `POST /run-imf-ingestion` | IMF WEO forecasts | 900_015 | **NAO** |

Todos retornam `202 ACCEPTED` com `WorkerScheduledResponse`. Idempotencia via Redis + advisory locks.

---

## 7. Manager Screener API

**Prefix:** `/api/v1/manager-screener` — Auth: `Role.INVESTMENT_TEAM` ou `Role.ADMIN`

### 7.1 Endpoints

| Endpoint | Metodo | Data Providers usados | Status Frontend |
|----------|--------|----------------------|----------------|
| `/` | GET | Query Builder (sec_managers + aggs + Redis + universe) | **SIM** — lista paginada |
| `/managers/{crd}/profile` | GET | sec_managers + sec_manager_funds + sec_manager_team | **SIM** — tab Profile |
| `/managers/{crd}/holdings` | GET | sec_13f_holdings_agg + sec_13f_holdings | **SIM** — tab Holdings |
| `/managers/{crd}/drift` | GET | sec_13f_drift_agg + sec_13f_diffs | **SIM** — tab Drift |
| `/managers/{crd}/institutional` | GET | sec_institutional_allocations | **SIM** — tab Institutional |
| `/managers/{crd}/universe-status` | GET | instruments_universe (tenant-scoped) | **SIM** — tab Universe |
| `/managers/{crd}/add-to-universe` | POST | instruments_universe | **SIM** — botao "Add" |
| `/managers/compare` | POST | All SEC tables (profile + holdings + drift) | **SIM** — compare modal |

### 7.2 Query Builder

**Arquivo:** `queries/manager_screener_sql.py`

25 parametros de filtro em 5 blocos:
1. **Firma:** aum_min/max, states, countries, compliance_clean, text_search, fee_types
2. **Portfolio:** sectors, hhi_min/max, position_count_min/max, portfolio_value_min
3. **Drift:** style_drift_detected, turnover_min/max, high_activity_quarters_min
4. **Institutional:** has_institutional_holders, holder_types
5. **Universe:** universe_statuses

Sort allowlist: `aum_total`, `firm_name`, `compliance_disclosures`, `last_adv_filed_at`, `state`, `country`.

---

## 8. Macro Pipeline (BIS + IMF → Regional Scores)

### 8.1 Fluxo de dados

```
┌─────────────────────────────────────────────────────────┐
│  INGESTAO (Workers)                                      │
│                                                          │
│  FRED API ──→ macro_ingestion (Lock 43) ──→ macro_data   │
│  BIS API  ──→ bis_ingestion (Lock 900_014) ──→ bis_statistics │
│  IMF API  ──→ imf_ingestion (Lock 900_015) ──→ imf_weo_forecasts │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────┐
│  SCORING (quant_engine/regional_macro_service.py)        │
│                                                          │
│  score_region() ──→ 6 dimensoes FRED                     │
│    └─→ enrich_region_score()                             │
│         ├─→ score_credit_cycle() — 7a dimensao (BIS)     │
│         │    ├─ credit_gap (50%)                          │
│         │    ├─ debt_service (30%)                        │
│         │    └─ property_prices (20%)                     │
│         └─→ blend_imf_growth() — FRED 70% + IMF 30%     │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────┐
│  SNAPSHOT (quant_engine/macro_snapshot_builder.py)        │
│                                                          │
│  build_regional_snapshot()                                │
│    └─→ RegionalMacroResult (7 dimensions, composite)     │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────┐
│  ENDPOINTS (wealth/routes/macro.py)                      │
│                                                          │
│  GET /macro/scores     ──→ Regional composite scores     │
│  GET /macro/snapshot   ──→ Full snapshot + percentiles    │
│  GET /macro/regime     ──→ Global + regional regime      │
│  GET /macro/reviews    ──→ Committee weekly reports       │
│  POST /macro/reviews/generate  ──→ Generate new report   │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────┐
│  FRONTEND (frontends/wealth/(team)/macro/)                │
│                                                          │
│  Macro Intelligence page ──→ Scores, regime, reviews     │
│  Dashboard macro card    ──→ Summary indicators          │
└──────────────────────────────────────────────────────────┘
```

### 8.2 Gap: enrich_region_score nao conectado

`enrich_region_score()` esta definido e testado em `regional_macro_service.py`, mas **nao e chamado pelo macro_ingestion worker** nem por nenhum endpoint. O worker `macro_ingestion.py` importa apenas `build_fetch_configs` e `get_all_series_ids` — nao integra BIS/IMF no scoring. A funcao existe como pure function pronta para integracao.

---

## 9. Cobertura Frontend

### 9.1 Wealth Frontend — Paginas que consomem Data Providers

| Pagina Frontend | Endpoints Consumidos | Data Provider(s) |
|----------------|---------------------|-------------------|
| `/manager-screener` | 8 endpoints screener | SEC (ADV, 13F, N-PORT, Institutional) |
| `/macro` | `/macro/scores`, `/snapshot`, `/regime`, `/reviews` | FRED + BIS + IMF (via scoring) |
| `/dashboard` | macro indicators card | FRED (macro_data) |

### 9.2 Credit Frontend — Paginas que consomem Data Providers

| Pagina Frontend | Endpoints Consumidos | Data Provider(s) |
|----------------|---------------------|-------------------|
| `/dashboard` | `/dashboard/macro-snapshot` | FRED (treasury, BAA spread, yield curve) |
| IC Memo generation | `vertical_engines/credit/edgar/` | SEC (CIK resolution, EDGAR filings) |

---

## 10. Endpoints sem Consumidor Frontend

### 10.1 Worker Triggers (17 endpoints — nenhum no frontend)

Todos os `POST /workers/run-*` sao admin-only, sem UI:

```
POST /workers/run-ingestion
POST /workers/run-risk-calc
POST /workers/run-portfolio-eval
POST /workers/run-macro-ingestion
POST /workers/run-instrument-ingestion
POST /workers/run-benchmark-ingest
POST /workers/run-screening-batch
POST /workers/run-watchlist-check
POST /workers/run-fact-sheet-gen
POST /workers/run-treasury-ingestion
POST /workers/run-ofr-ingestion
POST /workers/run-sec-refresh
POST /workers/run-brochure-download
POST /workers/run-brochure-extract
POST /workers/run-nport-ingestion
POST /workers/run-bis-ingestion
POST /workers/run-imf-ingestion
```

### 10.2 ESMA (zero integracao)

Sem worker, sem endpoints, sem frontend. Apenas os data providers + seed pipeline existem.

### 10.3 SEC N-PORT (parcial)

N-PORT data esta no hypertable `sec_nport_holdings`, mas:
- Sem endpoint REST dedicado para consultar N-PORT holdings diretamente
- Manager Screener nao expoe N-PORT em nenhuma tab
- Worker de ingestion existe (`POST /workers/run-nport-ingestion`)

### 10.4 SEC Brochure Text (parcial)

`sec_manager_brochure_text` tem GIN full-text search index. Workers de download (900_019)
e extract (900_020) implementados com pipeline em duas fases via StorageClient. Gaps restantes:
- Sem endpoint REST para busca full-text em brochures
- Manager Screener Profile tab nao exibe brochure sections

---

## 11. Gaps e Proximos Passos

### 11.1 Integracao Pendente

| Gap | Descricao | Impacto |
|-----|-----------|---------|
| **enrich_region_score nao conectado** | Funcao pura pronta, mas macro_ingestion worker nao chama. BIS/IMF data existe no DB mas nao enriquece os scores regionais. | Scores macro sem 7a dimensao (credit_cycle) e sem blend IMF growth |
| **ESMA sem integracao** | Data providers funcionam (e2e validado), mas sem worker/endpoint/frontend | European fund universe nao populada |
| **N-PORT sem exposure** | Holdings no DB, sem endpoint dedicado | Mutual fund holdings invisiveis no frontend |
| **Brochure text sem busca** | GIN index existe, workers de download/extract implementados (900_019/900_020), sem endpoint REST de busca | Full-text search em ADV brochures nao acessivel via API |
| **Worker triggers sem UI** | 17 endpoints admin-only sem pagina | Requer chamadas manuais via curl/Postman |

### 11.2 Tabelas Global (sem organization_id, sem RLS)

| Tabela | Hypertable | Chunks | Segmentby | Provider |
|--------|-----------|--------|-----------|----------|
| `sec_managers` | Nao | — | — | SEC ADV |
| `sec_manager_funds` | Nao | — | — | SEC ADV |
| `sec_manager_team` | Nao | — | — | SEC ADV |
| `sec_manager_brochure_text` | Nao | — | — | SEC ADV |
| `sec_13f_holdings` | Sim | 1mo | `cik` | SEC 13F |
| `sec_13f_diffs` | Sim | 1mo | `cik` | SEC 13F |
| `sec_13f_holdings_agg` | Cont. Agg | — | — | SEC 13F |
| `sec_13f_drift_agg` | Cont. Agg | — | — | SEC 13F |
| `sec_nport_holdings` | Sim | 3mo | `cik` | SEC N-PORT |
| `sec_institutional_allocations` | Sim | 1mo | `filer_cik` | SEC Institutional |
| `sec_cusip_ticker_map` | Nao | — | — | SEC Shared |
| `esma_managers` | Nao | — | — | ESMA |
| `esma_funds` | Nao | — | — | ESMA |
| `esma_isin_ticker_map` | Nao | — | — | ESMA |
| `bis_statistics` | Sim | 1yr | `country_code` | BIS |
| `imf_weo_forecasts` | Sim | 1yr | `country_code` | IMF |
