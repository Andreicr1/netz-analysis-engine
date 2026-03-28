# Verificacao de Gaps — Resultado

**Data:** 2026-03-27
**Base:** `docs/audit/endpoint_coverage_audit.md` (56 endpoints desconectados)

---

## Resumo

| Check | Endpoint(s) | Status | Evidencia |
|---|---|---|---|
| CHECK-01 | `POST /dd-reports/funds/{fund_id}` | FALSO NEGATIVO | `dd-reports/[fundId]/+page.svelte:29` — `api.post(\`/dd-reports/funds/${fundId}\`, {})` |
| CHECK-01 | `GET /dd-reports/{report_id}/stream` | FALSO NEGATIVO | `dd-reports/[fundId]/[reportId]/+page.svelte:101` — `createSSEStream({ url: \`/dd-reports/${reportId}/stream\` })` |
| CHECK-02 | `GET /screener/catalog` | FALSO NEGATIVO | `screener/+page.server.ts:46` — `api.get("/screener/catalog", catalogParams)` |
| CHECK-02 | `GET /screener/catalog/facets` | FALSO NEGATIVO | `screener/+page.server.ts:47` — `api.get("/screener/catalog/facets", catalogParams)` |
| CHECK-02 | `GET /screener/facets` | GAP REAL | Nao encontrado — superseded por `/catalog/facets` e `/securities/facets` |
| CHECK-02 | `GET /screener/results/{instrument_id}` | FALSO NEGATIVO | `lib/components/screener/FundDetailPanel.svelte:32` — `api.get(\`/screener/results/${instrumentId}\`)` |
| CHECK-02 | `GET /screener/search` | FALSO NEGATIVO | `lib/components/screener/InstrumentTable.svelte:86` — `api.get("/screener/search", params)` |
| CHECK-02 | `GET /screener/securities` | FALSO NEGATIVO | `screener/+page.server.ts:66` — `api.get("/screener/securities", secParams)` |
| CHECK-02 | `GET /screener/securities/facets` | FALSO NEGATIVO | `screener/+page.server.ts:67` — `api.get("/screener/securities/facets", ...)` |
| CHECK-02 | `POST /screener/import-esma/{isin}` | FALSO NEGATIVO | `screener/+page.svelte:116`, `CatalogDetailPanel.svelte:61` — `api.post(\`/screener/import-esma/${item.isin}\`, {})` |
| CHECK-02 | `POST /screener/import-sec/{ticker}` | FALSO NEGATIVO | `screener/+page.svelte:119`, `CatalogDetailPanel.svelte:64` — `api.post(\`/screener/import-sec/${item.ticker}\`, {})` |
| CHECK-03 | `GET /portfolios/{profile}/rebalance` | FALSO NEGATIVO | `lib/components/RebalancingTab.svelte:165` — `api.get(\`/portfolios/${profile}/rebalance\`)` |
| CHECK-03 | `GET /portfolios/{profile}/rebalance/{event_id}` | FALSO NEGATIVO | `lib/components/RebalancingTab.svelte:253` — `api.get(\`/portfolios/${profile}/rebalance/${eventId}\`)` |
| CHECK-04 | `GET /risk/stream` | FALSO NEGATIVO | `lib/stores/risk-store.svelte.ts:197` — `createSSEStream` com `${apiBase}/risk/stream` |
| CHECK-05 | `GET /analytics/optimize/pareto/{job_id}/stream` | FALSO NEGATIVO | `analytics/+page.svelte:234` — `fetch(\`${apiBase}/analytics/optimize/pareto/${jobId}/stream\`)` com ReadableStream |
| CHECK-06 | `GET /manager-screener` | GAP REAL | Chamado apenas em `_legacy_routes/` — rota ativa usa `/sec/managers/search` |
| CHECK-07 | `POST /content/flash-reports` | FALSO NEGATIVO | `content/+page.svelte:55,148` — `api.post(\`/content/${endpoint}\`, {})` com `endpoint="flash-reports"` |
| CHECK-07 | `POST /content/outlooks` | FALSO NEGATIVO | `content/+page.svelte:55,145` — `generateContent("outlooks")` |
| CHECK-07 | `POST /content/spotlights` | FALSO NEGATIVO | `content/+page.svelte:55,77` — `generateContent("spotlights", { instrument_id })` |
| CHECK-07 | `GET /content/{content_id}/download` | FALSO NEGATIVO | `content/+page.svelte:113` — `fetch(\`${apiBase}/content/${item.id}/download\`)` |
| CHECK-08 | `GET /model-portfolios/{id}/views` | GAP REAL | Nenhuma chamada no frontend |
| CHECK-08 | `POST /model-portfolios/{id}/views` | GAP REAL | Nenhuma chamada no frontend |
| CHECK-08 | `DELETE /model-portfolios/{id}/views/{view_id}` | GAP REAL | Nenhuma chamada no frontend |
| CHECK-09 | `POST /allocation/{profile}/simulate` | FALSO NEGATIVO | `lib/components/AllocationView.svelte:280` — `api.post(\`/allocation/${activeProfile}/simulate\`, { weights, rationale })` |
| CHECK-10 | `GET /wealth/exposure/matrix?dimension=geographic` | FALSO NEGATIVO | `exposure/+page.server.ts:10` e `ExposureView.svelte:45` |
| CHECK-10 | `GET /wealth/exposure/matrix?dimension=sector` | FALSO NEGATIVO | `exposure/+page.server.ts:11` e `ExposureView.svelte:46` |
| CHECK-11 | `GET /fact-sheets/dd-reports/{id}/download` | FALSO NEGATIVO | `dd-reports/[fundId]/[reportId]/+page.svelte:135` — `fetch(\`/api/v1/fact-sheets/dd-reports/${reportId}/download\`)` |
| CHECK-11 | `GET /fact-sheets/{path}/download` | FALSO NEGATIVO | `model-portfolios/[portfolioId]/+page.svelte:118` — `api.getBlob(\`/fact-sheets/${encodeURIComponent(path)}/download\`)` |

---

## Falsos Negativos Confirmados (23 endpoints)

Endpoints que existem no frontend mas o scanner nao detectou. Causa raiz por categoria:

### Template Literals (14)

O scanner nao resolve interpolacao de template literals (`${variable}`).

| Endpoint | Arquivo | Linha |
|---|---|---|
| `POST /dd-reports/funds/{fund_id}` | `dd-reports/[fundId]/+page.svelte` | 29 |
| `GET /screener/results/{instrument_id}` | `lib/components/screener/FundDetailPanel.svelte` | 32 |
| `POST /screener/import-esma/{isin}` | `screener/+page.svelte` + `CatalogDetailPanel.svelte` | 116, 61 |
| `POST /screener/import-sec/{ticker}` | `screener/+page.svelte` + `CatalogDetailPanel.svelte` | 119, 64 |
| `GET /portfolios/{profile}/rebalance` | `lib/components/RebalancingTab.svelte` | 165 |
| `GET /portfolios/{profile}/rebalance/{event_id}` | `lib/components/RebalancingTab.svelte` | 253 |
| `POST /allocation/{profile}/simulate` | `lib/components/AllocationView.svelte` | 280 |
| `GET /fact-sheets/dd-reports/{id}/download` | `dd-reports/[fundId]/[reportId]/+page.svelte` | 135 |
| `GET /fact-sheets/{path}/download` | `model-portfolios/[portfolioId]/+page.svelte` | 118 |

### Parametro Dinamico em Path Generico (4)

A funcao `generateContent(endpoint)` monta o path dinamicamente — scanner nao associa string param ao endpoint final.

| Endpoint | Arquivo | Linha |
|---|---|---|
| `POST /content/flash-reports` | `content/+page.svelte` | 55, 148 |
| `POST /content/outlooks` | `content/+page.svelte` | 55, 145 |
| `POST /content/spotlights` | `content/+page.svelte` | 55, 77 |
| `GET /content/{content_id}/download` | `content/+page.svelte` | 113 |

### SSE via createSSEStream / fetch+ReadableStream (3)

Scanner nao reconhece `createSSEStream()` ou `fetch()` + `getReader()` como conexao a endpoint.

| Endpoint | Arquivo | Linha |
|---|---|---|
| `GET /dd-reports/{report_id}/stream` | `dd-reports/[fundId]/[reportId]/+page.svelte` | 101 |
| `GET /risk/stream` | `lib/stores/risk-store.svelte.ts` | 197 |
| `GET /analytics/optimize/pareto/{job_id}/stream` | `analytics/+page.svelte` | 234 |

### Query Params nao Resolvidos (2)

Scanner nao faz match quando query params sao passados como objeto separado em `api.get()`.

| Endpoint | Arquivo | Linha |
|---|---|---|
| `GET /wealth/exposure/matrix?dimension=geographic` | `exposure/+page.server.ts` + `ExposureView.svelte` | 10, 45 |
| `GET /wealth/exposure/matrix?dimension=sector` | `exposure/+page.server.ts` + `ExposureView.svelte` | 11, 46 |

---

## Gaps Reais Confirmados (5 endpoints)

### 1. `GET /screener/facets`

- **Diagnostico:** Endpoint generico superseded por variantes especificas `/screener/catalog/facets` e `/screener/securities/facets`.
- **Acao sugerida:** Deprecar endpoint ou manter como alias interno. Sem necessidade de UI.

### 2. `GET /manager-screener` (endpoint raiz)

- **Diagnostico:** Chamado apenas em `_legacy_routes/(team)/manager-screener/+page.server.ts:22`. Rota ativa (`(app)/screener/`) usa `/sec/managers/search` em vez de `/manager-screener`.
- **Componentes orfaos:** `ManagerDetailPanel.svelte`, `ManagerHierarchyTable.svelte`, `HoldingsTab.svelte`, `DocsTab.svelte`, `DriftTab.svelte`, `PeerComparisonView.svelte` — exportados mas nao importados na rota ativa.
- **Acao sugerida:** Migrar funcionalidades unicas do manager-screener (brochure, drift, holdings drill-down) para componentes ativos do `/screener`, ou deprecar `/manager-screener` e consolidar em `/sec/managers/search`.

### 3. `GET /model-portfolios/{portfolio_id}/views`

- **Diagnostico:** Backend implementado em `routes/portfolio_views.py:100-126`. Nenhuma UI para listar views BL.
- **Acao sugerida:** Adicionar painel "IC Views" na pagina de model portfolio (`[portfolioId]/+page.svelte`).

### 4. `POST /model-portfolios/{portfolio_id}/views`

- **Diagnostico:** Backend implementado em `routes/portfolio_views.py:58-97`. Nenhuma UI para criar views BL.
- **Acao sugerida:** Adicionar formulario de criacao de view (asset, return expectation, confidence) no painel "IC Views".

### 5. `DELETE /model-portfolios/{portfolio_id}/views/{view_id}`

- **Diagnostico:** Backend implementado em `routes/portfolio_views.py:129-157`. Nenhuma UI para deletar views BL.
- **Acao sugerida:** Adicionar botao delete por view no painel "IC Views".

---

## Inconclusivos

Nenhum. Todos os 28 endpoints verificados tiveram resultado definitivo.

---

## Impacto na Contagem do Audit Original

| Metrica | Audit Original | Pos-Verificacao |
|---|---|---|
| Total desconectados | 56 | **56 - 23 = 33** (minimo, apenas os 11 checks) |
| Falsos negativos confirmados | — | **23** |
| Gaps reais confirmados | — | **5** (dos 28 verificados) |
| Restantes nao verificados | — | **28** (fora do escopo deste check) |

> **Nota:** Os 28 endpoints restantes nao verificados incluem: macro granulares (BIS/IMF/OFR/Treasury), ESMA registry diretos, analytics extras (backtest detail, entity, rolling-correlation, drift export/history), instruments PATCH/CSV, documents upload flow, model-portfolio stress-test legacy, e universe audit-trail. Estes requerem verificacao separada.

---

## Recomendacoes para o Scanner

1. **Resolver template literals:** Extrair patterns `${variable}` como wildcards e fazer match contra backend routes.
2. **Reconhecer `createSSEStream()`:** Tratar como equivalente a `fetch()` para SSE endpoints.
3. **Reconhecer `fetch()` + `getReader()`:** Detectar ReadableStream consumption como conexao SSE.
4. **Resolver chamadas indiretas:** Quando uma funcao recebe o endpoint como parametro (ex: `generateContent("flash-reports")`), rastrear os call sites para resolver o valor.
5. **Tratar `api.get(path, params)` com params objeto:** Reconhecer que query params passados como segundo argumento expandem o path com `?key=value`.
