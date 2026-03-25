# Screener & US Fund Analysis — Index Reference

> Inventário completo de índices, queries habilitadas, respostas da API e oportunidades de implementação no frontend.
> Atualizado: 2026-03-24 | Migrations: 0023–0047

---

## Sumário

| Tabela | Índices | Rows estimados | Páginas que usam |
|--------|---------|----------------|------------------|
| `sec_managers` | 10 | 951K | Screener (Funds tab), US Fund Analysis |
| `sec_manager_funds` | 2 | ~50K | US Fund Analysis (strategy breakdown) |
| `sec_13f_holdings` | 2 + hypertable | 991K | US Fund Analysis (Holdings, Drift, Reverse) |
| `sec_13f_diffs` | 2 + hypertable | computed | US Fund Analysis (Holdings delta) |
| `sec_nport_holdings` | 2 + hypertable | ~15K+ | Futuro: N-PORT enrichment |
| `esma_funds` | 5 | 10.4K | Screener (Funds tab — UCITS) |
| `esma_managers` | 2 | 658 | Screener (join com esma_funds) |
| `instruments_global` | 8 | ~270 (crescendo) | Screener (Equities, ETF, Fixed Income tabs) |
| **Total** | **33** | | |

---

## 1. `sec_managers` — 10 Índices

### 1.1 `idx_sec_managers_cik`
- **Migration:** 0023
- **Tipo:** btree partial (`WHERE cik IS NOT NULL`)
- **Query habilitada:** `WHERE cik = :cik` (lookup direto)
- **Endpoint:** `GET /sec/managers/{cik}` — Manager Detail
- **Retorno:** `SecManagerDetail` (crd_number, cik, firm_name, registration_status, aum_total, state, country, website, sic, sic_description, latest_quarter, holdings_count, total_portfolio_value)
- **Status frontend:** Implementado — panel de detalhe no US Fund Analysis

### 1.2 `idx_sec_managers_aum`
- **Migration:** 0038
- **Tipo:** btree (`aum_total DESC`)
- **Query habilitada:** `ORDER BY aum_total DESC` (sort geral)
- **Endpoint:** `GET /sec/managers/search?sort_by=aum_total&sort_dir=desc`
- **Retorno:** `SecManagerSearchPage` (managers[], total_count, page, page_size, has_next)
- **Status frontend:** Implementado — coluna AUM sortable na ManagerTable

### 1.3 `idx_sec_managers_compliance_aum`
- **Migration:** 0038
- **Tipo:** btree composite (`compliance_disclosures, aum_total DESC`)
- **Query habilitada:** `WHERE compliance_disclosures = :val ORDER BY aum_total DESC`
- **Endpoint:** Nenhum dedicado
- **Oportunidade frontend:** Filtro "Compliance Flags" no US Fund Analysis sidebar — mostrar advisers com disclosure flags, ordered por AUM

### 1.4 `idx_sec_managers_investment`
- **Migration:** 0046
- **Tipo:** btree partial (`aum_total DESC WHERE registration_status = 'investment'`)
- **Query habilitada:** `WHERE registration_status = 'investment' ORDER BY aum_total DESC`
- **Endpoint:** `GET /screener/search?tab=fund&fund_type=mutual_fund`
- **Retorno:** `InstrumentSearchItem` com source="sec", structure="SEC"
- **Status frontend:** Implementado — Screener Funds tab mostra investment companies

### 1.5 `idx_sec_managers_name_trgm`
- **Migration:** 0046
- **Tipo:** GIN trigram (`firm_name gin_trgm_ops`)
- **Extensão:** `pg_trgm`
- **Query habilitada:** `WHERE firm_name ILIKE '%query%'` ou `firm_name % 'query'` (fuzzy)
- **Endpoint:** `GET /sec/managers/search?q=blackrock` e `GET /screener/search?q=blackrock`
- **Retorno:** Managers com nome similar ao query (tolerância a typos)
- **Status frontend:** Implementado — search box em ambas as páginas
- **Oportunidade frontend:** Habilitar fuzzy search com `%` operator (similarity) ao invés de `ILIKE` — mostraria sugestões "Did you mean?" quando a query retorna 0 resultados

### 1.6 `idx_sec_managers_reg_status`
- **Migration:** 0046
- **Tipo:** btree (`registration_status`)
- **Query habilitada:** `WHERE registration_status = :status`
- **Endpoint:** `GET /sec/managers/search?entity_type=Registered`
- **Retorno:** Managers filtrados por status (Registered, Exempt Reporting, Not Registered)
- **Status frontend:** Implementado — dropdown "Entity Type" no US Fund Analysis sidebar

### 1.7 `idx_sec_managers_registered_aum`
- **Migration:** 0047
- **Tipo:** btree partial (`aum_total DESC WHERE registration_status = 'Registered'`)
- **Query habilitada:** `WHERE registration_status = 'Registered' ORDER BY aum_total DESC`
- **Endpoint:** `GET /sec/managers/search?entity_type=Registered&sort_by=aum_total`
- **Retorno:** Top advisers registrados por AUM (16K rows no partial index vs 951K full scan)
- **Status frontend:** Implementado — Overview tab com entity_type=Registered
- **Oportunidade frontend:** "Top 50 Advisers by AUM" widget/card na landing do US Fund Analysis — ranking pré-computado com partial index, resposta instantânea

### 1.8 `idx_sec_managers_client_types_gin`
- **Migration:** 0047
- **Tipo:** GIN jsonb_path_ops partial (`client_types WHERE client_types IS NOT NULL`)
- **Query habilitada:** `WHERE client_types @> '{"sic": "6726"}'` (JSONB containment)
- **Endpoint:** Nenhum dedicado (índice preparatório)
- **Oportunidade frontend:** Filtro "Strategy / SIC Code" no US Fund Analysis sidebar — dropdown com SIC codes comuns (6726=Investment Offices, 6282=Investment Advice, 6211=Security Brokers). Habilita drill-down por tipo de negócio do adviser

### 1.9 `idx_sec_managers_last_adv_filed`
- **Migration:** 0047
- **Tipo:** btree partial (`last_adv_filed_at DESC WHERE last_adv_filed_at IS NOT NULL`)
- **Query habilitada:** `ORDER BY last_adv_filed_at DESC` e `WHERE last_adv_filed_at >= :date`
- **Endpoint:** Nenhum dedicado (campo não retornado nos schemas atuais)
- **Oportunidade frontend:**
  1. Coluna "Last Filing" na ManagerTable — mostra quando o adviser atualizou o ADV pela última vez
  2. Filtro "Filing Recency" — "Filed in last 30/90/180 days" dropdown
  3. Badge "Stale" para advisers sem filing há >12 meses (sinal de risco)

### 1.10 `idx_sec_managers_status_aum`
- **Migration:** 0047
- **Tipo:** btree composite (`registration_status, aum_total DESC NULLS LAST`)
- **Query habilitada:** `WHERE registration_status = :status ORDER BY aum_total DESC` (covering)
- **Endpoint:** `GET /sec/managers/search?entity_type=Registered&sort_by=aum_total`
- **Retorno:** Query plan usa index-only scan (ambos campos no índice)
- **Status frontend:** Implementado implicitamente — combo de entity_type + sort por AUM

---

## 2. `sec_manager_funds` — 2 Índices

### 2.1 `idx_sec_manager_funds_type`
- **Migration:** 0047
- **Tipo:** btree partial (`fund_type WHERE fund_type IS NOT NULL`)
- **Query habilitada:** `WHERE fund_type = :type` ou `GROUP BY fund_type`
- **Endpoint:** Nenhum dedicado
- **Oportunidade frontend:** Strategy breakdown card no manager detail panel — pie/donut chart com distribuição de fund_type (Hedge Fund, PE, VC, Real Estate, etc.) por adviser

### 2.2 `idx_sec_manager_funds_crd_type`
- **Migration:** 0047
- **Tipo:** btree composite (`crd_number, fund_type`)
- **Query habilitada:** `WHERE crd_number = :crd GROUP BY fund_type` (index-only scan)
- **Endpoint:** Nenhum dedicado
- **Oportunidade frontend:**
  1. "Fund Structure" tab/section no manager detail — lista de fundos agrupados por tipo
  2. Enrichment no Peer Compare — comparar não só holdings 13F mas também estrutura de fundos (Adviser A: 60% PE + 40% VC vs Adviser B: 100% HF)

---

## 3. `sec_13f_holdings` — 2 Índices + Hypertable

### 3.1 `idx_sec_13f_holdings_cik_report_date`
- **Migration:** 0023
- **Tipo:** btree composite (`cik, report_date`)
- **Hypertable:** 3-month chunks, compressed after 6 months (segmentby: cik)
- **Query habilitada:** `WHERE cik = :cik AND report_date = :date` (chunk-pruned)
- **Endpoint:** `GET /sec/managers/{cik}/holdings?quarter=2025-12-31`
- **Retorno:** `SecHoldingsPage` (holdings[], available_quarters[], total_count, total_value)
- **Status frontend:** Implementado — HoldingsTable com quarter selector

### 3.2 `idx_sec_13f_holdings_cusip_report_date`
- **Migration:** 0023
- **Tipo:** btree covering (`cusip, report_date` INCLUDE `cik, shares, market_value`)
- **Query habilitada:** `WHERE cusip = :cusip AND report_date = :date` (index-only scan)
- **Endpoint:** `GET /sec/holdings/reverse?cusip=037833100`
- **Retorno:** `SecReverseLookup` (holders[], total_holders)
- **Status frontend:** Implementado — ReverseLookup tab
- **Oportunidade frontend:** "Who Else Holds This?" link em cada row da HoldingsTable — click no CUSIP abre reverse lookup inline (sem trocar de tab)

### 3.3 Continuous Aggregates (0038)
- `sec_13f_holdings_agg` — materialized view com `idx_sec_13f_holdings_agg_cik_quarter`
- `sec_13f_drift_agg` — materialized view com `idx_sec_13f_drift_agg_cik_quarter`
- **Query habilitada:** Aggregações pré-computadas por (cik, quarter)
- **Endpoint:** `GET /sec/managers/{cik}/style-drift` (usa aggregates para performance)
- **Status frontend:** Implementado — StyleDriftChart (ECharts stacked bar)

---

## 4. `sec_13f_diffs` — 2 Índices + Hypertable

### 4.1 `idx_sec_13f_diffs_cik_quarter_to`
- **Migration:** 0023
- **Tipo:** btree composite (`cik, quarter_to`)
- **Query habilitada:** `WHERE cik = :cik AND quarter_to = :date`
- **Endpoint:** `GET /sec/managers/{cik}/holdings` (left-join para delta_action)
- **Retorno:** delta_shares, delta_value, delta_action (NEW_POSITION, INCREASED, DECREASED, EXITED)
- **Status frontend:** Implementado — badges coloridos na HoldingsTable

### 4.2 `idx_sec_13f_diffs_cusip_quarter_to`
- **Migration:** 0023
- **Tipo:** btree composite (`cusip, quarter_to`)
- **Query habilitada:** `WHERE cusip = :cusip AND quarter_to = :date`
- **Endpoint:** Nenhum dedicado (disponível para enrichment)
- **Oportunidade frontend:** "Position History" mini-chart no reverse lookup — sparkline mostrando evolução do número de holders de um CUSIP ao longo dos trimestres

---

## 5. `sec_nport_holdings` — 2 Índices + Hypertable

### 5.1 `idx_sec_nport_holdings_cik_date`
- **Migration:** 0040
- **Tipo:** btree composite (`cik, report_date DESC`)
- **Hypertable:** 3-month chunks (segmentby: cik)
- **Query habilitada:** `WHERE cik = :cik ORDER BY report_date DESC`
- **Endpoint:** Nenhum dedicado (worker-side ingestion only)
- **Oportunidade frontend:** "Full Portfolio" view no manager detail — N-PORT filings mostram posições completas (não só 13F equity), incluindo bonds, derivatives, repo agreements

### 5.2 `idx_sec_nport_holdings_cusip_date`
- **Migration:** 0040
- **Tipo:** btree composite (`cusip, report_date DESC`)
- **Query habilitada:** `WHERE cusip = :cusip ORDER BY report_date DESC`
- **Endpoint:** Nenhum dedicado
- **Oportunidade frontend:** Enrichment do Reverse Lookup — combinar 13F holders + N-PORT holders para visão completa de quem detém um security

---

## 6. `esma_funds` — 5 Índices

### 6.1 `idx_esma_funds_manager_id`
- **Migration:** 0039
- **Tipo:** btree (`esma_manager_id`)
- **Query habilitada:** `WHERE esma_manager_id = :id` (FK lookup)
- **Endpoint:** `GET /screener/search?tab=fund` (OUTERJOIN com EsmaManager)
- **Status frontend:** Implementado — coluna "Manager" na Screener Funds tab

### 6.2 `idx_esma_funds_yahoo_ticker`
- **Migration:** 0039
- **Tipo:** btree partial (`yahoo_ticker WHERE yahoo_ticker IS NOT NULL`)
- **Query habilitada:** `WHERE yahoo_ticker = :ticker`
- **Endpoint:** Usado internamente para ISIN→Ticker resolution
- **Status frontend:** Indireto — ticker aparece no InstrumentSearchItem

### 6.3 `idx_esma_funds_domicile`
- **Migration:** 0046
- **Tipo:** btree (`domicile`)
- **Query habilitada:** `WHERE domicile = :domicile`
- **Endpoint:** `GET /screener/search?tab=fund&domicile=LU`
- **Retorno:** UCITS funds filtrados por país de domicílio
- **Status frontend:** Implementado — dropdown "Geography" mapeia para domicile no ESMA query
- **Oportunidade frontend:** Faceted count badges no filtro — "Luxembourg (3,200)" ao lado de cada opção

### 6.4 `idx_esma_funds_fund_type`
- **Migration:** 0046
- **Tipo:** btree (`fund_type`)
- **Query habilitada:** `WHERE fund_type = :type`
- **Endpoint:** `GET /screener/facets` (facet count por fund_type)
- **Status frontend:** Implementado — facet counts na sidebar

### 6.5 `idx_esma_funds_domicile_type`
- **Migration:** 0046
- **Tipo:** btree composite (`domicile, fund_type`)
- **Query habilitada:** `WHERE domicile = :dom AND fund_type = :type` (index-only scan)
- **Endpoint:** `GET /screener/search?tab=fund&domicile=IE&fund_type=ucits`
- **Status frontend:** Implementado — combo de filtros Funds tab

---

## 7. `esma_managers` — 2 Índices

### 7.1 `idx_esma_managers_country`
- **Migration:** 0046
- **Tipo:** btree (`country`)
- **Query habilitada:** `WHERE country = :country`
- **Endpoint:** `GET /screener/search` (join filter)
- **Status frontend:** Indireto — filtragem por geography inclui country do manager

### 7.2 `idx_esma_managers_name_trgm`
- **Migration:** 0046
- **Tipo:** GIN trigram (`company_name gin_trgm_ops`)
- **Query habilitada:** `WHERE company_name ILIKE '%query%'` (fuzzy match)
- **Endpoint:** `GET /screener/search?tab=fund&manager=amundi`
- **Retorno:** Funds cujo manager name matcha o query
- **Status frontend:** Implementado — filtro "Investment Manager" na Funds tab

---

## 8. `instruments_global` — 8 Índices

### 8.1 `ix_instruments_global_instrument_type`
- **Migration:** 0045
- **Tipo:** btree (`instrument_type`)
- **Query habilitada:** `WHERE instrument_type = :type`
- **Endpoint:** `GET /screener/search?tab=equity` (routes para `instrument_type='equity'`)
- **Status frontend:** Implementado — tab routing (Equity/ETF/Bond tabs)

### 8.2 `ix_instruments_global_asset_class`
- **Migration:** 0045
- **Tipo:** btree (`asset_class`)
- **Query habilitada:** `WHERE asset_class = :class`
- **Endpoint:** `GET /screener/search?asset_class=fixed_income`
- **Status frontend:** Implementado — dropdown "Asset Class" nos tabs ETF e Fixed Income

### 8.3 `ix_instruments_global_geography`
- **Migration:** 0045
- **Tipo:** btree (`geography`)
- **Query habilitada:** `WHERE geography = :geo`
- **Endpoint:** `GET /screener/search?geography=us`
- **Status frontend:** Implementado — filtro Geography (atualmente 100% "us")
- **Oportunidade frontend:** Quando seed expandir para mercados internacionais, geography filter terá valores significativos

### 8.4 `ix_instruments_global_isin`
- **Migration:** 0045
- **Tipo:** btree partial (`isin WHERE isin IS NOT NULL`)
- **Query habilitada:** `WHERE isin = :isin` (exact match)
- **Endpoint:** `GET /screener/search?q=US0378331005` (search por ISIN)
- **Status frontend:** Implementado — search box aceita ISIN

### 8.5 `idx_instruments_global_exchange`
- **Migration:** 0047
- **Tipo:** btree partial (`exchange WHERE exchange IS NOT NULL`)
- **Query habilitada:** `WHERE exchange = :exchange`
- **Endpoint:** Nenhum dedicado (campo retornado no InstrumentSearchItem)
- **Retorno:** `exchange` field → mapeado para SOURCE badges (NMS→NASDAQ, NYQ→NYSE, PCX→ARCA)
- **Status frontend:** Parcial — badge SOURCE exibido mas sem filtro
- **Oportunidade frontend:**
  1. Filtro "Exchange" dropdown na Equities tab (NASDAQ, NYSE, ARCA, OTC)
  2. Click no badge SOURCE para filtrar por exchange
  3. Exchange breakdown chart no overview do screener

### 8.6 `idx_instruments_global_market_cap`
- **Migration:** 0047
- **Tipo:** btree partial (`market_cap DESC WHERE market_cap IS NOT NULL`)
- **Query habilitada:** `WHERE market_cap >= :min ORDER BY market_cap DESC`
- **Endpoint:** `GET /screener/search?tab=equity&market_cap_min=10000000000`
- **Retorno:** Equities filtradas por market cap mínimo
- **Status frontend:** Implementado — dropdown "Market Cap" (Small < $2B / Mid $2-10B / Large $10-200B / Mega > $200B)
- **Oportunidade frontend:** Sortable column header na Equities tab — click "Market Cap" ordena ASC/DESC

### 8.7 `idx_instruments_global_attributes_gin`
- **Migration:** 0047
- **Tipo:** GIN jsonb_path_ops (`attributes`)
- **Query habilitada:** `WHERE attributes @> '{"fund_family": "Vanguard"}'` e extrações `attributes->>'expense_ratio'`
- **Endpoint:** `GET /screener/search?tab=etf&expense_ratio_max=0.5&fund_family=Vanguard`
- **Retorno:** ETFs/Bonds filtrados por atributos JSONB
- **Status frontend:** Implementado — filtros "Fund Family", "Expense Ratio max", "YTM min" nos tabs ETF e Fixed Income
- **Oportunidade frontend:**
  1. Filtro "Issuer" na Fixed Income tab (extraído de attributes)
  2. "Compare ETFs" — selecionar 2-3 ETFs e comparar expense_ratio, AUM, yield side-by-side
  3. Faceted counts dinâmicos por fund_family (Vanguard: 12, iShares: 8, SPDR: 5)

### 8.8 `idx_instruments_global_type_cap`
- **Migration:** 0047
- **Tipo:** btree composite (`instrument_type, market_cap DESC NULLS LAST`)
- **Query habilitada:** `WHERE instrument_type = 'equity' ORDER BY market_cap DESC` (index-only scan)
- **Endpoint:** `GET /screener/search?tab=equity` com sort implícito por market_cap
- **Status frontend:** Parcial — tab routing usa instrument_type, market_cap exibido mas sort é por name
- **Oportunidade frontend:** Default sort da Equities tab por market_cap DESC (maiores primeiro) — UX mais natural para institutional users

---

## Oportunidades de Implementação — Consolidado

### Alta Prioridade (dados e índices prontos, só precisa de frontend + endpoint)

| # | Feature | Índice(s) | Endpoint necessário | Componente frontend |
|---|---------|-----------|--------------------|--------------------|
| 1 | Coluna "Last Filing" na ManagerTable | `idx_sec_managers_last_adv_filed` | Adicionar `last_adv_filed_at` ao schema `SecManagerItem` | Nova coluna na ManagerTable + badge "Stale" (>12m) |
| 2 | Strategy/SIC filter no US Fund Analysis | `idx_sec_managers_client_types_gin` | Novo param `sic` em `GET /sec/managers/search` | Dropdown "Strategy" no FilterSidebar |
| 3 | Fund Structure por manager | `idx_sec_manager_funds_crd_type` | Novo endpoint `GET /sec/managers/{crd}/funds` | Donut chart no manager detail panel |
| 4 | Default sort Equities por market_cap | `idx_instruments_global_type_cap` | Param `sort_by=market_cap` já suportado | Mudar default sort na Equities tab |
| 5 | Exchange filter na Equities tab | `idx_instruments_global_exchange` | Param `exchange` no `GET /screener/search` | Dropdown "Exchange" no ScreenerFilters |
| 6 | Sortable columns no Screener | Todos os btree DESC | Param `sort_by` + `sort_dir` no `/screener/search` | Click-to-sort headers no InstrumentTable |

### Média Prioridade (precisa de novo endpoint + frontend)

| # | Feature | Índice(s) | Endpoint necessário | Componente frontend |
|---|---------|-----------|--------------------|--------------------|
| 7 | Compliance flags filter | `idx_sec_managers_compliance_aum` | Param `has_disclosures` em `/sec/managers/search` | Toggle "Show Flagged" no FilterSidebar |
| 8 | CUSIP click → Reverse Lookup inline | `idx_sec_13f_holdings_cusip_report_date` | Endpoint já existe (`/sec/holdings/reverse`) | Popover/tooltip no CUSIP cell da HoldingsTable |
| 9 | N-PORT Full Portfolio view | `idx_sec_nport_holdings_cik_date` | Novo endpoint `GET /sec/managers/{cik}/nport` | Nova tab "Full Portfolio" no US Fund Analysis |
| 10 | ETF Compare side-by-side | `idx_instruments_global_attributes_gin` | Novo endpoint `GET /screener/compare?tickers=...` | Compare modal/drawer com tabela de atributos |
| 11 | Faceted counts com badges | `idx_esma_funds_domicile`, `idx_esma_funds_fund_type` | Facets já retornados por `/screener/facets` | Counts ao lado de cada opção no ScreenerFilters |

### Baixa Prioridade (enrichment futuro)

| # | Feature | Índice(s) | Endpoint necessário | Componente frontend |
|---|---------|-----------|--------------------|--------------------|
| 12 | "Did you mean?" fuzzy suggestions | `idx_sec_managers_name_trgm` | Endpoint similarity search (`%` operator) | Autocomplete dropdown no search box |
| 13 | Position History sparkline | `idx_sec_13f_diffs_cusip_quarter_to` | Novo endpoint time-series por CUSIP | Sparkline inline na ReverseLookup table |
| 14 | N-PORT + 13F combined reverse | `idx_sec_nport_holdings_cusip_date` | Merge de dois queries (13F + N-PORT) | Badge "13F + N-PORT" na reverse lookup |
| 15 | Top 50 Advisers widget | `idx_sec_managers_registered_aum` | Partial index retorna top instantaneamente | Card/widget na landing do US Fund Analysis |
| 16 | Peer Compare fund structure | `idx_sec_manager_funds_crd_type` | Extend `/sec/managers/compare` com fund breakdown | Nova seção no PeerCompare component |

---

## Queries SQL — Exemplos por Índice

### sec_managers: Registered advisers sorted by AUM
```sql
-- Uses: idx_sec_managers_registered_aum (partial index, ~16K rows)
SELECT crd_number, firm_name, aum_total, state, last_adv_filed_at
FROM sec_managers
WHERE registration_status = 'Registered'
ORDER BY aum_total DESC NULLS LAST
LIMIT 25 OFFSET 0;
```

### sec_managers: Strategy filter via SIC
```sql
-- Uses: idx_sec_managers_client_types_gin
SELECT crd_number, firm_name, aum_total, client_types->>'sic' as sic
FROM sec_managers
WHERE client_types @> '{"sic": "6726"}'
  AND registration_status = 'Registered'
ORDER BY aum_total DESC;
```

### sec_manager_funds: Strategy breakdown per manager
```sql
-- Uses: idx_sec_manager_funds_crd_type (index-only scan)
SELECT fund_type, COUNT(*) as fund_count
FROM sec_manager_funds
WHERE crd_number = '12345'
GROUP BY fund_type
ORDER BY fund_count DESC;
```

### instruments_global: Equities by market cap
```sql
-- Uses: idx_instruments_global_type_cap (covering index)
SELECT ticker, name, market_cap, sector, exchange
FROM instruments_global
WHERE instrument_type = 'equity'
  AND market_cap >= 10000000000
ORDER BY market_cap DESC NULLS LAST
LIMIT 50;
```

### instruments_global: ETF by expense ratio
```sql
-- Uses: idx_instruments_global_attributes_gin
SELECT ticker, name, attributes->>'totalAssets' as aum,
       attributes->>'annualReportExpenseRatio' as expense_ratio
FROM instruments_global
WHERE instrument_type = 'etf'
  AND (attributes->>'annualReportExpenseRatio')::float <= 0.005
ORDER BY (attributes->>'totalAssets')::bigint DESC NULLS LAST;
```

### instruments_global: Exchange filter
```sql
-- Uses: idx_instruments_global_exchange (partial)
SELECT ticker, name, exchange, market_cap
FROM instruments_global
WHERE exchange = 'NMS'
  AND instrument_type = 'equity'
ORDER BY market_cap DESC NULLS LAST;
```

### sec_13f_holdings: Reverse lookup
```sql
-- Uses: idx_sec_13f_holdings_cusip_report_date (covering index)
SELECT h.cik, m.firm_name, h.shares, h.market_value, h.report_date
FROM sec_13f_holdings h
JOIN sec_managers m ON m.cik = h.cik
WHERE h.cusip = '037833100'
  AND h.report_date = '2025-12-31'
ORDER BY h.market_value DESC
LIMIT 50;
```

---

## Mapa: Índice → Endpoint → Frontend Component

```
idx_sec_managers_cik ─────────────► GET /sec/managers/{cik} ──────► ManagerDetailPanel
idx_sec_managers_aum ─────────────► GET /sec/managers/search ─────► ManagerTable (sort)
idx_sec_managers_investment ──────► GET /screener/search?tab=fund ► InstrumentTable (Funds)
idx_sec_managers_name_trgm ───────► GET /sec/managers/search?q= ──► Search box (fuzzy)
idx_sec_managers_reg_status ──────► GET /sec/managers/search ─────► FilterSidebar (Entity Type)
idx_sec_managers_registered_aum ──► GET /sec/managers/search ─────► ManagerTable (Registered)
idx_sec_managers_client_types_gin ► [PENDING endpoint] ───────────► [PENDING] Strategy filter
idx_sec_managers_last_adv_filed ──► [PENDING schema field] ───────► [PENDING] Last Filing column
idx_sec_managers_status_aum ──────► GET /sec/managers/search ─────► Combined filter+sort
idx_sec_managers_compliance_aum ──► [PENDING endpoint] ───────────► [PENDING] Compliance filter

idx_sec_manager_funds_type ───────► [PENDING endpoint] ───────────► [PENDING] Strategy breakdown
idx_sec_manager_funds_crd_type ───► [PENDING endpoint] ───────────► [PENDING] Fund structure chart

idx_sec_13f_holdings_cik_date ────► GET /sec/managers/{cik}/hold. ► HoldingsTable
idx_sec_13f_holdings_cusip_date ──► GET /sec/holdings/reverse ────► ReverseLookup tab
idx_sec_13f_diffs_cik_quarter ────► GET /sec/managers/{cik}/hold. ► Delta badges
idx_sec_13f_diffs_cusip_quarter ──► [PENDING endpoint] ───────────► [PENDING] Position sparkline

idx_sec_nport_holdings_cik_date ──► [PENDING endpoint] ───────────► [PENDING] Full Portfolio tab
idx_sec_nport_holdings_cusip_date ► [PENDING endpoint] ───────────► [PENDING] Combined reverse

idx_esma_funds_manager_id ────────► GET /screener/search?tab=fund ► InstrumentTable (Manager col)
idx_esma_funds_yahoo_ticker ──────► Internal resolution ──────────► Ticker display
idx_esma_funds_domicile ──────────► GET /screener/search?domicile ► ScreenerFilters (Geography)
idx_esma_funds_fund_type ─────────► GET /screener/facets ─────────► Facet counts
idx_esma_funds_domicile_type ─────► GET /screener/search (combo) ─► Combined filter

idx_esma_managers_country ────────► GET /screener/search (join) ──► Geography filter
idx_esma_managers_name_trgm ──────► GET /screener/search?manager= ► Manager filter (fuzzy)

ix_instruments_global_type ───────► GET /screener/search?tab= ────► Tab routing
ix_instruments_global_asset_class ► GET /screener/search?asset= ──► Asset class dropdown
ix_instruments_global_geography ──► GET /screener/search?geo= ────► Geography filter
ix_instruments_global_isin ───────► GET /screener/search?q=ISIN ──► Search box
idx_instruments_global_exchange ──► [PENDING filter param] ───────► [PENDING] Exchange filter
idx_instruments_global_market_cap ► GET /screener/search?cap_min= ► Market Cap dropdown
idx_instruments_global_attrs_gin ─► GET /screener/search?expense= ► ETF/Bond attribute filters
idx_instruments_global_type_cap ──► GET /screener/search?tab=eq ──► [PENDING] Default sort
```

**Legenda:** `►` = implementado | `[PENDING]` = oportunidade identificada

---

## Continuous Aggregates (TimescaleDB)

| View | Índice | Refresh | Usado por |
|------|--------|---------|-----------|
| `sec_13f_holdings_agg` | `idx_sec_13f_holdings_agg_cik_quarter` | Auto (on insert) | Style Drift chart |
| `sec_13f_drift_agg` | `idx_sec_13f_drift_agg_cik_quarter` | Auto (on insert) | Drift signal computation |

---

## Caching Strategy

| Endpoint | TTL | Scope | Key Pattern |
|----------|-----|-------|-------------|
| `GET /screener/search` | 60s | org-scoped | `screener:search:{hash}` |
| `GET /screener/facets` | 300s | org-scoped | `screener:facets:{hash}` |
| `GET /screener/results` | 60s | org-scoped | `screener:results:{hash}` |
| `GET /sec/managers/search` | 300s | global | `sec:search:{hash}` |
| `GET /sec/managers/{cik}/holdings` | 300s | global | `sec:holdings:{hash}` |
| `GET /sec/managers/{cik}/style-drift` | 300s | global | `sec:drift:{hash}` |
| `GET /sec/holdings/reverse` | 300s | global | `sec:reverse:{hash}` |
| `GET /sec/managers/compare` | 300s | global | `sec:compare:{hash}` |

> SEC endpoints usam `global_key=True` (sem RLS) — cache compartilhado entre tenants.
> Screener endpoints são org-scoped — cache isolado por organization_id.
