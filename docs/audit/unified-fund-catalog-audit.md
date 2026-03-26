# Unified Fund Catalog & Disclosure Matrix — Audit

**Date:** 2026-03-26
**Scope:** Backend (SQLAlchemy models, migrations, Pydantic schemas, routes) + Frontend (Svelte routes, TS types, components)
**Goal:** Validate current state against the Target architecture for a polymorphic Unified Fund Catalog with Disclosure Matrix for the Wealth Screener "Single Pane of Glass".

---

## 1. Backend — Current State

### 1.1 Global Tables (no RLS, shared across tenants)

| Braço | Tabela | PK | Status | Migração | Campos-chave |
|-------|--------|----|--------|----------|-------------|
| **Private US** | `sec_manager_funds` | `id` (UUID) | ✅ Exists | `0028` | `crd_number` FK, `fund_name`, `fund_id`, `gross_asset_value`, `fund_type`, `is_fund_of_funds`, `investor_count` |
| **Private US** | `sec_managers` | `crd_number` | ✅ Exists | `0028` | `cik`, `firm_name`, `aum_total`, `aum_discretionary`, fund counts (hedge/pe/vc/re/securitized/liquidity/other), `total_private_fund_assets`, `fee_types` JSONB, `client_types` JSONB |
| **Registered US** | `sec_registered_funds` | `cik` | ✅ Exists | `0054` | `crd_number` FK nullable, `fund_name`, `fund_type` (mutual_fund\|etf\|closed_end\|interval_fund), `ticker`, `isin`, `series_id`, `class_id`, `total_assets`, `total_shareholder_accounts`, `inception_date`, `last_nport_date`, `aum_below_threshold` |
| **Registered US** | `sec_nport_holdings` | (cik, report_date, cusip) | ✅ Hypertable 3mo | `0040` | `isin`, `issuer_name`, `asset_class`, `sector`, `market_value`, `quantity`, `pct_of_nav`, `is_restricted`, `fair_value_level` |
| **Registered US** | `sec_fund_style_snapshots` | (cik, report_date) | ✅ Exists | `0054` | `style_label`, `growth_tilt`, `sector_weights` JSONB, `equity_pct`, `fixed_income_pct`, `cash_pct`, `confidence` |
| **Registered US** | `sec_13f_holdings` | (cik, report_date, cusip) | ✅ Hypertable 3mo | — | `shares`, `market_value`, `discretion`, voting columns |
| **Registered US** | `sec_13f_diffs` | (cik, quarter_to, cusip, quarter_from) | ✅ Hypertable 3mo | — | `shares_delta`, `value_delta`, `action` |
| **EU UCITS** | `esma_funds` | `isin` | ✅ Exists | `0039` | `fund_name`, `esma_manager_id` FK, `domicile`, `fund_type`, `host_member_states` ARRAY, `yahoo_ticker`, `ticker_resolved_at` |
| **EU UCITS** | `esma_managers` | `esma_id` | ✅ Exists | `0039` | `lei`, `company_name`, `country`, `authorization_status`, `fund_count`, `sec_crd_number` crossref |
| **EU UCITS** | `esma_isin_ticker_map` | `isin` | ✅ Exists | `0039`/`0043` | `fund_lei`, `yahoo_ticker`, `exchange`, `resolved_via`, `is_tradeable` |
| **Linking** | `sec_entity_links` | `id` (int) | ✅ Exists | `0052` | `manager_crd` FK, `related_cik`, `relationship` (parent_13f\|subsidiary\|managed_fund), `confidence` |
| **Linking** | `sec_cusip_ticker_map` | `cusip` | ✅ Exists | — | `ticker`, `issuer_name`, `exchange`, `security_type`, `figi`, `composite_figi` |

### 1.2 Tenant-Scoped Tables (RLS-protected)

| Tabela | PK | Relevância para Screener |
|--------|----|-------------------------|
| `instruments_universe` | `instrument_id` (UUID) | Polimórfica (fund\|bond\|equity). Fundos importados do catálogo global entram aqui. `attributes` JSONB, `approval_status`, `block_id` FK. |
| `nav_timeseries` | (instrument_id, nav_date) | NAV diário pós-import. Fonte: YFinance via `instrument_ingestion` worker. |
| `fund_risk_metrics` | (instrument_id, calc_date) | Métricas pré-computadas: CVaR, Sharpe, Sortino, momentum (RSI, Bollinger, blended_momentum_score), DTW drift. |
| `screening_runs` | `run_id` (UUID) | Batch runs com `config_hash` SHA-256 para dedup. |
| `screening_results` | `id` (UUID) | PASS/FAIL/WATCHLIST por instrumento, `layer_results` JSONB com criterion/expected/actual/passed. |

### 1.3 Pydantic Schemas — Current

| Arquivo | Schemas | Gap |
|---------|---------|-----|
| `schemas/sec_funds.py` | `RegisteredFundSummary`, `PrivateFundSummary`, `FundDetailResponse`, `FundDataAvailabilitySchema`, `NportHoldingItem`, `StyleSnapshotItem` | Schemas individuais por universo — sem polimorfismo |
| `schemas/esma.py` | `EsmaManagerItem`, `EsmaFundItem`, `EsmaFundDetail`, `EsmaSecCrossRef` | Idem — separado dos SEC schemas |
| `schemas/screening.py` | `ScreeningRunRead`, `ScreeningResultRead`, `ScreeningRunRequest` | Ligado ao `instruments_universe` (tenant), não ao catálogo global |
| **MISSING** | `UnifiedFundItem`, `DisclosureMatrix` | **Não existe** — precisa ser criado |

### 1.4 Routes — Current

| Arquivo | Endpoints | Escopo |
|---------|-----------|--------|
| `routes/screener.py` | `POST /screener/run`, `GET /screener/search`, `GET /screener/facets`, `GET /screener/results`, `POST /screener/import-esma/{isin}` | Tenant-scoped (`instruments_universe`). Não consulta catálogo global. |
| `routes/sec_funds.py` | `GET /sec/managers/{crd}/registered-funds`, `GET /sec/managers/{crd}/private-funds`, `GET /sec/funds/{cik}`, `GET /sec/funds/{cik}/holdings`, `GET /sec/funds/{cik}/style-history` | Global tables. DB-only. Sem paginação unificada. |
| `routes/esma.py` | `GET /esma/managers`, `GET /esma/funds`, `GET /esma/funds/{isin}`, `GET /esma/funds/search`, `GET /esma/sec-crossref` | Global tables. DB-only. Separado do SEC. |
| **MISSING** | `GET /screener/catalog`, `GET /screener/catalog/facets` | **Não existe** — endpoint unificador dos 3 universos |

### 1.5 Screener Vertical Engine

| Arquivo | Conteúdo | Status |
|---------|----------|--------|
| `vertical_engines/wealth/screener/service.py` | `ScreenerService` — 3-layer deterministic screener (eliminatory → mandate fit → quant). Config via parameter. | ✅ OK — opera sobre `instruments_universe` pós-import |
| `vertical_engines/wealth/screener/layer_evaluator.py` | Per-layer criterion evaluation | ✅ OK |
| `vertical_engines/wealth/screener/quant_metrics.py` | Composite score from pre-computed `fund_risk_metrics` | ✅ OK |

---

## 2. Frontend — Current State

### 2.1 Routes

| Rota | Arquivo | Função | Limitação |
|------|---------|--------|-----------|
| `/screener` | `routes/(app)/screener/+page.svelte` | Busca em `instruments_universe` com 4 tabs (Fund/Equity/Bond/ETF). Infinite scroll. Detail panel. CSV export. | **Só vê fundos já importados pelo tenant.** Catálogo global (SEC/ESMA) não aparece diretamente. |
| `/us-fund-analysis` | `routes/(app)/us-fund-analysis/+page.svelte` | Análise SEC: 5 tabs (Overview, Holdings, Style Drift, Reverse Lookup, Peer Compare). Manager-centric. | **Separado do screener.** Só SEC, sem ESMA. Não tem screening integrado. Manager-centric, não fund-centric. |

### 2.2 Components — Reusáveis

| Componente | Localização | Reutilizável? |
|------------|-------------|---------------|
| `ScreenerFilters.svelte` | `lib/components/screener/` | ✅ Evoluir com novos filtros (universe, region) |
| `InstrumentTable.svelte` | `lib/components/screener/` | ✅ Adaptar colunas para `UnifiedFundItem` |
| `InstrumentDetailPanel.svelte` | `lib/components/screener/` | ✅ Evoluir com seções condicionais via `disclosure` |
| `HoldingsTable.svelte` | `us-fund-analysis/components/` | ⚠️ Mover para shared — renderizar se `disclosure.has_holdings` |
| `StyleDriftChart.svelte` | `us-fund-analysis/components/` | ⚠️ Mover para shared — renderizar se `disclosure.has_style_analysis` |
| `PeerCompare.svelte` | `us-fund-analysis/components/` | ⚠️ Mover para shared — renderizar se `disclosure.has_peer_analysis` |
| `ReverseLookup.svelte` | `us-fund-analysis/components/` | ⚠️ Mover para shared |
| `ManagerTable.svelte` | `us-fund-analysis/components/` | ⚠️ Absorver como tab "Managers" no screener |
| `TopAdvisersWidget.svelte` | `us-fund-analysis/components/` | ⚠️ Mover para shared |

### 2.3 TypeScript Types

| Arquivo | Types | Gap |
|---------|-------|-----|
| `types/screening.ts` | `InstrumentSearchItem`, `ScreenerFacets`, `ScreenerTab` | `InstrumentSearchItem` já tem `source: "internal"\|"esma"\|"sec"` — bom ponto de partida |
| `types/sec-analysis.ts` | `SecManagerItem`, `SecHoldingItem`, `SecStyleDrift`, `SecReverseLookup`, `SecManagerFundBreakdown` | Tipos SEC isolados |
| `types/sec-funds.ts` | `RegisteredFundSummary`, `PrivateFundSummary`, `FundDetailResponse`, `FundDataAvailabilitySchema` | Tipos registered/private isolados |
| **MISSING** | `UnifiedFundItem`, `DisclosureMatrix`, `UnifiedCatalogPage`, `CatalogFacets` | **Não existe** |

### 2.4 API Client

- `lib/api/client.ts` re-exports de `@netz/ui/utils`
- Base URL: `VITE_API_BASE_URL ?? "http://localhost:8000/api/v1"`
- Funções: `createServerApiClient(token)`, `createClientApiClient(getToken)`

---

## 3. Gap Analysis — Summary

| Item | Status | Ação necessária |
|------|--------|----------------|
| `sec_registered_funds` table | ✅ Exists (mig 0054) | Nenhuma |
| `esma_funds` table | ✅ Exists (mig 0039) | Nenhuma |
| `sec_manager_funds` table | ✅ Exists | Nenhuma |
| `sec_entity_links` (CRD↔CIK) | ✅ Exists (mig 0052) | Nenhuma |
| `UnifiedFundItem` Pydantic schema | ❌ Missing | **Criar** em `schemas/catalog.py` |
| `DisclosureMatrix` Pydantic schema | ❌ Missing | **Criar** em `schemas/catalog.py` |
| `GET /screener/catalog` endpoint | ❌ Missing | **Criar** — UNION ALL dos 3 universos + pagination |
| `GET /screener/catalog/facets` endpoint | ❌ Missing | **Criar** — contagens agrupadas |
| Materialized View `mv_unified_fund_catalog` | ❌ Missing | **Avaliar** — criar se p95 > 200ms |
| `UnifiedFundItem` TypeScript type | ❌ Missing | **Criar** em `types/catalog.ts` |
| `DisclosureMatrix` TypeScript type | ❌ Missing | **Criar** em `types/catalog.ts` |
| Screener "Funds" tab consuming catalog | ❌ Missing | **Criar** — nova tab com filtros universe/region |
| `/us-fund-analysis` → screener merge | ❌ Not started | **Absorver** como tab "Managers" |
| Shared components (Holdings, StyleDrift, etc.) | ⚠️ Isolated | **Mover** de `us-fund-analysis/components/` para `lib/components/screener/` |
| Detail Panel disclosure-conditional | ⚠️ Partial | **Evoluir** `InstrumentDetailPanel` com seções condicionais |

---

## 4. Proposed Architecture

### 4.1 Endpoint: `GET /api/v1/wealth/screener/catalog`

```
GET /screener/catalog?
  q=blackrock&
  region=us|eu|all&
  fund_universe=private|registered|ucits|all&
  fund_type=hedge_fund|pe|vc|mutual_fund|etf|ucits&
  aum_min=1000000&
  has_nav=true&
  page=1&
  page_size=50&
  sort=aum_desc
```

**Implementation — 3 subqueries with UNION ALL:**

```sql
-- CTE 1: Registered US (mutual, ETF)
SELECT
  'registered_us' AS universe,
  rf.cik AS external_id,
  rf.fund_name AS name,
  rf.ticker,
  rf.isin,
  'US' AS region,
  rf.fund_type,
  rf.total_assets AS aum,
  'USD' AS currency,
  rf.domicile,
  sm.firm_name AS manager_name,
  sm.crd_number AS manager_id,
  rf.inception_date,
  -- disclosure booleans
  true AS has_holdings,
  true AS has_nav,
  true AS has_quant_metrics,
  false AS has_private_data
FROM sec_registered_funds rf
LEFT JOIN sec_managers sm ON rf.crd_number = sm.crd_number

UNION ALL

-- CTE 2: Private US (hedge, PE, VC)
SELECT
  'private_us' AS universe,
  smf.id::text AS external_id,
  smf.fund_name AS name,
  NULL AS ticker,
  NULL AS isin,
  'US' AS region,
  smf.fund_type,
  smf.gross_asset_value AS aum,
  'USD' AS currency,
  'US' AS domicile,
  sm.firm_name AS manager_name,
  sm.crd_number AS manager_id,
  NULL AS inception_date,
  -- disclosure booleans
  false AS has_holdings,
  false AS has_nav,
  false AS has_quant_metrics,
  true AS has_private_data
FROM sec_manager_funds smf
JOIN sec_managers sm ON smf.crd_number = sm.crd_number

UNION ALL

-- CTE 3: EU UCITS (ticker resolvido only)
SELECT
  'ucits_eu' AS universe,
  ef.isin AS external_id,
  ef.fund_name AS name,
  ef.yahoo_ticker AS ticker,
  ef.isin,
  'EU' AS region,
  ef.fund_type,
  NULL AS aum,
  NULL AS currency,
  ef.domicile,
  em.company_name AS manager_name,
  em.esma_id AS manager_id,
  NULL AS inception_date,
  -- disclosure booleans
  false AS has_holdings,
  (ef.yahoo_ticker IS NOT NULL) AS has_nav,
  (ef.yahoo_ticker IS NOT NULL) AS has_quant_metrics,
  false AS has_private_data
FROM esma_funds ef
JOIN esma_managers em ON ef.esma_manager_id = em.esma_id
WHERE ef.yahoo_ticker IS NOT NULL
```

**Performance:** ~50k registered + ~50k private + ~30k UCITS (com ticker). UNION ALL com WHERE push-down e LIMIT/OFFSET via subquery wrapping. Se p95 > 200ms: criar **Materialized View** `mv_unified_fund_catalog` com refresh a cada 6h (dados não mudam intra-dia).

### 4.2 Pydantic Schema: `UnifiedFundItem`

```python
class DisclosureMatrix(BaseModel):
    """What data is available for this fund based on its universe/source."""
    has_holdings: bool          # N-PORT for registered, N/A for private/UCITS
    has_nav_history: bool       # YFinance ticker required
    has_quant_metrics: bool     # Requires NAV history
    has_private_fund_data: bool # Schedule D (GAV, investor_count)
    has_style_analysis: bool    # N-PORT style snapshots
    has_13f_overlay: bool       # 13F holdings via entity link
    has_peer_analysis: bool     # Requires ≥3 peers in same fund_type
    holdings_source: Literal["nport", "13f", None]
    nav_source: Literal["yfinance", None]
    aum_source: Literal["nport", "schedule_d", "yfinance", None]


class UnifiedFundItem(BaseModel):
    """Polymorphic fund item for the unified screener catalog."""
    # Identity
    external_id: str            # cik | fund UUID | isin
    universe: Literal["registered_us", "private_us", "ucits_eu"]
    name: str
    ticker: str | None = None
    isin: str | None = None

    # Classification
    region: Literal["US", "EU"]
    fund_type: str              # hedge_fund, pe, vc, mutual_fund, etf, ucits, ...
    domicile: str | None = None
    currency: str | None = None

    # Manager
    manager_name: str | None = None
    manager_id: str | None = None  # crd_number | esma_id

    # Metrics (nullable — frontend checks disclosure)
    aum: Decimal | None = None
    inception_date: date | None = None
    total_shareholder_accounts: int | None = None  # registered only
    investor_count: int | None = None              # private only

    # Screening (if imported to tenant universe)
    instrument_id: str | None = None   # UUID if imported
    screening_status: Literal["PASS", "FAIL", "WATCHLIST"] | None = None
    screening_score: Decimal | None = None
    approval_status: str | None = None

    # Disclosure matrix — drives UI rendering
    disclosure: DisclosureMatrix
```

### 4.3 TypeScript Interface (Frontend)

```typescript
interface DisclosureMatrix {
  has_holdings: boolean;
  has_nav_history: boolean;
  has_quant_metrics: boolean;
  has_private_fund_data: boolean;
  has_style_analysis: boolean;
  has_13f_overlay: boolean;
  has_peer_analysis: boolean;
  holdings_source: "nport" | "13f" | null;
  nav_source: "yfinance" | null;
  aum_source: "nport" | "schedule_d" | "yfinance" | null;
}

interface UnifiedFundItem {
  external_id: string;
  universe: "registered_us" | "private_us" | "ucits_eu";
  name: string;
  ticker: string | null;
  isin: string | null;

  region: "US" | "EU";
  fund_type: string;
  domicile: string | null;
  currency: string | null;

  manager_name: string | null;
  manager_id: string | null;

  aum: number | null;
  inception_date: string | null;
  total_shareholder_accounts: number | null;
  investor_count: number | null;

  instrument_id: string | null;
  screening_status: "PASS" | "FAIL" | "WATCHLIST" | null;
  screening_score: number | null;
  approval_status: string | null;

  disclosure: DisclosureMatrix;
}

interface UnifiedCatalogPage {
  items: UnifiedFundItem[];
  total: number;
  page: number;
  page_size: number;
  facets: CatalogFacets;
}

interface CatalogFacets {
  universes: FacetItem[];
  regions: FacetItem[];
  fund_types: FacetItem[];
  domiciles: FacetItem[];
  currencies: FacetItem[];
}
```

**Svelte usage (disclosure-driven rendering):**

```svelte
{#if item.disclosure.has_holdings}
  <HoldingsTab cik={item.external_id} />
{:else}
  <Badge variant="muted">No Disclosure</Badge>
{/if}

{#if item.disclosure.has_nav_history}
  <NavChart ticker={item.ticker} />
{:else}
  <Badge variant="muted">NAV N/A</Badge>
{/if}
```

### 4.4 Frontend Merge Plan

#### From 2 routes → 1 unified `/screener`

| Current | Destination |
|---------|-------------|
| `/screener/+page.svelte` | **Evolves** — adds "Funds" tab consuming `/catalog` and "Managers" tab |
| `/us-fund-analysis/+page.svelte` | **Absorbed** — becomes "Managers" tab inside unified screener |
| `HoldingsTable`, `StyleDriftChart`, `PeerCompare`, `ReverseLookup` | **Move** to `lib/components/screener/` — render conditionally via `disclosure` |

#### New tab structure

```
/screener?tab=funds        → UnifiedFundItem[] (3 universes via /catalog)
/screener?tab=managers     → SecManagerItem[] (absorbs /us-fund-analysis)
/screener?tab=equities     → InstrumentSearchItem[] (keeps current)
/screener?tab=bonds        → InstrumentSearchItem[] (keeps current)
```

#### Funds tab filters

```
Universe:  [All] [US Registered] [US Private] [EU UCITS]
Region:    [All] [US] [EU]
Fund Type: [Mutual Fund] [ETF] [Hedge Fund] [PE] [VC] [UCITS] [Closed-End]
AUM Min:   [________]
Has NAV:   [Yes] [No] [All]
Manager:   [________] (autocomplete)
```

#### Detail Panel — conditional sections via disclosure

| Section | Condition |
|---------|-----------|
| NAV Chart | `disclosure.has_nav_history` |
| Holdings Table | `disclosure.has_holdings` |
| Style Analysis | `disclosure.has_style_analysis` |
| Quant Metrics (CVaR, Sharpe) | `disclosure.has_quant_metrics` |
| Private Fund Data (GAV, investors) | `disclosure.has_private_fund_data` |
| 13F Overlay | `disclosure.has_13f_overlay` |
| Peer Compare | `disclosure.has_peer_analysis` |

Sections not available render `<Badge variant="outline">No Disclosure</Badge>`.

---

## 5. Execution Plan

| Phase | Scope | Deliverables |
|-------|-------|-------------|
| **1 — Backend schemas + endpoint** | `UnifiedFundItem` + `DisclosureMatrix` Pydantic schemas. `GET /screener/catalog` with UNION ALL + pagination. `GET /screener/catalog/facets`. | `schemas/catalog.py`, query builder, route additions to `screener.py` |
| **2 — Performance gate** | Benchmark p95. If > 200ms: create `mv_unified_fund_catalog` Materialized View + migration + refresh cron (6h). Trigram indexes on `name`. | Migration, worker task |
| **3 — Frontend merge** | Add "Funds" tab to screener consuming `/catalog`. Move `us-fund-analysis` components to shared. Add "Managers" tab. Remove `/us-fund-analysis` route. | Svelte refactor |
| **4 — Detail panel evolution** | Evolve `InstrumentDetailPanel` for disclosure-conditional rendering. Integrate HoldingsTable, StyleDrift, PeerCompare as conditional sections. | Component evolution |
| **5 — Cleanup** | Deprecate individual routes (`/sec/managers/{crd}/registered-funds`, `/esma/funds`). Redirect `/us-fund-analysis` → `/screener?tab=managers`. | Housekeeping |

---

## 6. Disclosure Matrix Rules

| Universe | Holdings | NAV History | AUM Source | Quant Metrics | Style Analysis | 13F Overlay | Private Data |
|----------|----------|-------------|------------|---------------|----------------|-------------|-------------|
| **US Registered** (mutual/ETF) | ✅ N-PORT | ✅ YFinance | N-PORT `total_assets` | ✅ Yes | ✅ N-PORT style snapshots | ✅ via `sec_entity_links` | ❌ |
| **US Private** (hedge/PE/VC) | ❌ N/A | ❌ N/A | Schedule D `gross_asset_value` | ❌ N/A (or proxy via 13F) | ❌ | Possible via `sec_entity_links` | ✅ GAV, investor_count |
| **EU UCITS** (with ticker) | ❌ N/A | ✅ YFinance | ❌ (or YFinance AUM) | ✅ High-level (requires NAV) | ❌ | ❌ | ❌ |
| **EU UCITS** (no ticker) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**Note:** EU UCITS without resolved `yahoo_ticker` are excluded from the catalog (WHERE filter in UNION ALL). They provide no actionable data for the screener.
