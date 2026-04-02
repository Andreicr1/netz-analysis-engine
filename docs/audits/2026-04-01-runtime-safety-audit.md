# Runtime Safety Audit — 2026-04-01

Varredura completa dos 5 padrões de erro encontrados em produção após deploy dos sprints A–H.

---

## 1. Unsafe `.toFixed()` / `.toLocaleString()` calls

**12 ocorrências UNSAFE encontradas** (de ~80 total). Todas as demais têm guards adequados.

| File | Line | Expression | Guard? | Status |
|------|------|-----------|--------|--------|
| `lib/components/analytics/entity/MonteCarloPanel.svelte` | 105 | `mc.n_simulations.toLocaleString()` | none | **UNSAFE** — P1 |
| `lib/components/model-portfolio/ConstructionAdvisor.svelte` | 305 | `c.correlation_with_portfolio.toFixed(2)` | none | **UNSAFE** — P0 |
| `lib/components/screener/CatalogFilterSidebar.svelte` | 179 | `count.toLocaleString()` | none | **UNSAFE** — P0 |
| `lib/components/screener/CatalogFilterSidebar.svelte` | 196 | `item.count.toLocaleString()` | none | **UNSAFE** — P0 |
| `lib/components/screener/CatalogFilterSidebar.svelte` | 214 | `item.count.toLocaleString()` | none | **UNSAFE** — P0 |
| `lib/components/screener/CatalogFilterSidebar.svelte` | 232 | `item.count.toLocaleString()` | none | **UNSAFE** — P0 |
| `lib/components/screener/SecuritiesFilterSidebar.svelte` | 63 | `item.count.toLocaleString()` | none | **UNSAFE** — P0 |
| `lib/components/screener/SecuritiesFilterSidebar.svelte` | 75 | `item.count.toLocaleString()` | none | **UNSAFE** — P0 |
| `routes/(app)/model-portfolios/[portfolioId]/+page.svelte` | 569 | `optimizationMeta.sharpe_ratio.toFixed(3)` | none | **UNSAFE** — P0 |
| `routes/(app)/risk/+page.svelte` | 212 | `alert.dtw_score.toFixed(2)` | none | **UNSAFE** — P0 |
| `routes/(app)/screener/+page.svelte` | 358 | `item.count.toLocaleString()` | none | **UNSAFE** — P0 |
| `routes/(app)/screener/+page.svelte` | 367 | `item.count.toLocaleString()` | none | **UNSAFE** — P0 |

**Fix sugerido:** `value?.toLocaleString() ?? "—"` ou `value != null ? value.toFixed(N) : "—"`

---

## 2. Nullable property access without guard

**0 ocorrências UNSAFE.** Todos os campos nullable auditados têm guards adequados.

O frontend usa consistentemente 3 mecanismos de proteção:
- `{#if field != null}` blocks
- Ternários `field != null ? ... : "—"`
- Formatters que tratam null internamente (`riskValue()`, `fmtPct()`, `formatPercent()`, `formatAUM()`)

| Field | Files checked | Status |
|-------|--------------|--------|
| `confidence_score` | dd-reports (3 pages) | SAFE — `{#if !== null}` + `Number().toFixed()` |
| `screening_score` | CatalogDetailPanel, InstrumentDetailPanel | SAFE — `{#if != null}` |
| `expense_ratio_pct` | CatalogDetailPanel, CatalogTable, FundDetailsTab, screener/[cik] | SAFE — `{#if}` + ternários |
| `avg_annual_return_1y/10y` | CatalogDetailPanel, CatalogTable, screener/[cik] | SAFE — `{#if}` + ternários |
| `aum` / `total_assets` | CatalogDetailPanel, screener/[cik] | SAFE — `{#if}` + `formatAUM()` |
| `cvar_95_3m` / `sharpe_1y` / `return_1y` / `volatility_1y` | universe/+page, ConstructionAdvisor | SAFE — formatters `riskValue()`/`ratioValue()` |
| `equity_pct` / `fixed_income_pct` / `cash_pct` | screener/[cik] | SAFE — `{#if != null}` |
| `market_value` / `shares` / `weight` | screener/[cik], model-portfolios | SAFE — ternários + required types |

---

## 3. str↔datetime mismatches

**5 mismatches encontrados em 3 vertical engines.** Todos têm conversão defensiva nos route handlers — sem crashes em produção, mas o root cause (domain model tipado como `str`) persiste.

| Domain Model File | Field | Domain Type | Schema File | Schema Type | Conversão no Route? | Status |
|---|---|---|---|---|---|---|
| `vertical_engines/wealth/attribution/models.py` | `start_date` | `str` (ISO date) | `schemas/attribution.py` | `date` | SIM | **MISMATCH** — P2 |
| `vertical_engines/wealth/attribution/models.py` | `end_date` | `str` (ISO date) | `schemas/attribution.py` | `date` | SIM | **MISMATCH** — P2 |
| `vertical_engines/wealth/correlation/models.py` | `computed_at` | `str` | `schemas/correlation_regime.py` | `datetime` | SIM (l.205) | **MISMATCH** — P2 |
| `vertical_engines/wealth/monitoring/strategy_drift_models.py` | `detected_at` | `str` (ISO) | `schemas/strategy_drift.py` | `datetime` | SIM (l.227) | **MISMATCH** — P2 |
| `vertical_engines/wealth/monitoring/strategy_drift_models.py` | `scan_timestamp` | `str` | `schemas/strategy_drift.py` | `datetime` | SIM (l.238) | **MISMATCH** — P2 |

**Fix sugerido:** Mudar domain models para usar `datetime`/`date` nativos em vez de `str`, eliminando conversões defensivas nos routes.

---

## 4. CRD/CIK confusion points

**1 confusion point principal** — corrigido no commit `1197244`. 1 issue de documentação pendente.

| File | Line | Pattern | ID Used | Expected | Status |
|------|------|---------|---------|----------|--------|
| `routes/sec_analysis.py` | 7 | Route doc: `GET /sec/managers/{cik}` | CIK (no nome) | CIK ou CRD | **DOC DESATUALIZADA** — P2 |
| `routes/sec_analysis.py` | 126 | `.where(SecManager.cik == cik)` | CIK | CIK | CORRECT |
| `routes/sec_analysis.py` | 130 | `.where(SecManager.crd_number == cik)` (fallback) | CRD | CIK | **FIXED** (1197244) |
| `routes/sec_analysis.py` | 329 | `SecManager.cik.in_(ciks)` compare | CIK | CIK | CORRECT |
| `routes/sec_analysis.py` | 484-532 | `get_manager_funds({crd_number})` | CRD | CRD | CORRECT |
| `routes/manager_screener.py` | 235-298 | `get_profile({crd})`, `get_holdings({crd})` | CRD | CRD | CORRECT |
| `queries/catalog_sql.py` | 408 | `crd_number.label("manager_id")` (registered) | CRD | CRD | CORRECT |
| `queries/catalog_sql.py` | 777 | `crd_number.label("manager_id")` (private) | CRD | CRD | CORRECT |
| `frontends/.../CatalogTable.svelte` | 310 | `onOpenManager(mg.manager_id)` → passes CRD | CRD | CRD | CORRECT |
| `frontends/.../screener/+page.svelte` | 261 | `` api.get(`/sec/managers/${managerId}`) `` | CRD | CIK | **FIXED** (fallback no backend) |

**Fix sugerido:** Renomear path param de `{cik}` para `{cik_or_crd}` e atualizar docstring.

---

## 5. Feature flag 404s

**10 endpoints protegidos por feature flags**, todos retornando 404 quando desabilitados. **1 gap no stream endpoint.**

| Route Path | Method | Feature Flag | Default | HTTP Status | File | Line |
|---|---|---|---|---|---|---|
| `/api/v1/content/outlooks` | POST | `feature_wealth_content` | **False** | 404 | content.py | 71 |
| `/api/v1/content/flash-reports` | POST | `feature_wealth_content` | **False** | 404 | content.py | 121 |
| `/api/v1/content/spotlights` | POST | `feature_wealth_content` | **False** | 404 | content.py | 172 |
| `/api/v1/content` | GET | `feature_wealth_content` | **False** | 404 | content.py | 241 |
| `/api/v1/content/{content_id}` | GET | `feature_wealth_content` | **False** | 404 | content.py | 263 |
| `/api/v1/content/{content_id}/approve` | POST | `feature_wealth_content` | **False** | 404 | content.py | 291 |
| `/api/v1/content/{content_id}/download` | GET | `feature_wealth_content` | **False** | 404 | content.py | 349 |
| `/api/v1/content/{content_id}/stream/{job_id}` | GET | **NENHUM** | — | — | content.py | 403 |
| `/api/v1/fact-sheets/model-portfolios/{portfolio_id}` | POST | `feature_wealth_fact_sheets` | **True** | 404 | fact_sheets.py | 52 |
| `/api/v1/fact-sheets/model-portfolios/{portfolio_id}` | GET | `feature_wealth_fact_sheets` | **True** | 404 | fact_sheets.py | 125 |
| `/api/v1/fact-sheets/{path}/download` | GET | `feature_wealth_fact_sheets` | **True** | 404 | fact_sheets.py | 171 |

**Issues:**
1. **404 semanticamente incorreto** — deveria ser **501 Not Implemented** (feature existe mas está desabilitada)
2. **Stream endpoint sem guard** — `/content/{id}/stream/{job_id}` (l.403) NÃO chama `_require_feature()`, permitindo streaming mesmo com feature desabilitada
3. **Defaults inconsistentes** — `feature_wealth_content` = False (desabilitada), `feature_wealth_fact_sheets` = True (habilitada)

**Fix sugerido:** Mudar `_require_feature()` para retornar 501 + adicionar guard no stream endpoint.

---

## Totais

| Categoria | Total | UNSAFE/MISMATCH | Prioridade |
|-----------|-------|-----------------|------------|
| 1. `.toFixed()` / `.toLocaleString()` sem guard | 80+ | **12 UNSAFE** | P0 (10), P1 (2) |
| 2. Nullable property access | 38+ | **0 UNSAFE** | — |
| 3. str↔datetime mismatch | 5 | **5 MISMATCH** (com conversão) | P2 |
| 4. CRD/CIK confusion | 10 | **1 DOC** (fix aplicado) | P2 |
| 5. Feature flag 404s | 11 | **1 GAP** + 10 wrong status | P1 (gap), P2 (status) |

**Grand total: 12 P0 + 3 P1 + 8 P2 = 23 findings**
