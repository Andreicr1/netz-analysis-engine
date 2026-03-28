# Auditoria de Endpoints — Wealth Vertical

**Data:** 2026-03-27
**Branch:** `main`
**Vertical:** Wealth

---

## Resumo Executivo

| Metrica | Valor |
|---|---|
| Total de endpoints backend (Wealth) | **129** |
| Conectados ao frontend | **73** (56.6%) |
| Desconectados | **56** (43.4%) |
| Phantom calls (frontend sem backend) | **31** (was 39, -8 legacy route cleanup 2026-03-27) |

### Breakdown por Dominio

| Dominio | Total | Conectados | Desconectados | % Cobertura |
|---|---|---|---|---|
| Analytics | ~16 | 10 | 6 | 63% |
| Screener / Catalog | ~12 | 3 | 9 | 25% |
| Model Portfolios | ~8 | 4 | 4 | 50% |
| DD Reports | ~7 | 3 | 4 | 43% |
| Instruments | ~5 | 3 | 2 | 60% |
| Content Generation | ~5 | 1 | 4 | 20% |
| Portfolios / Rebalancing | ~10 | 8 | 2 | 80% |
| Risk / Regime | ~8 | 7 | 1 | 88% |
| Macro | ~10 | 6 | 4 | 60% |
| Manager Screener | ~11 | 7 | 4 | 64% |
| ESMA Registry | ~5 | 0 | 5 | 0% |
| Allocation | ~6 | 3 | 3 | 50% |
| Universe | ~4 | 3 | 1 | 75% |
| Wealth Documents | ~5 | 3 | 2* | 60% |
| Fact Sheets | ~3 | 1 | 2 | 33% |
| Exposure | ~2 | 1 | 1 | 50% |

> *Wealth document upload endpoints (3) usam presigned-URL flow que o scanner nao rastreia como call direta.

---

## Endpoints Conectados (73)

### Shared (usados por Wealth)

| Endpoint | Componente |
|---|---|
| `DELETE /blended-benchmarks/{benchmark_id}` | BlendedBenchmarkEditor.svelte |
| `GET /funds` | SSR loader |
| `GET /funds/{fund_id}` | SSR loader |

### Wealth Frontend

| Metodo | Endpoint | Pagina/Componente |
|---|---|---|
| `GET` | `/analytics/attribution/{profile}` | Page |
| `GET` | `/analytics/correlation` | SSR loader |
| `GET` | `/analytics/correlation-regime/{profile}` | SSR loader |
| `GET` | `/analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` | Page |
| `GET` | `/analytics/strategy-drift/alerts` | SSR loader, risk-store.svelte.ts |
| `GET` | `/analytics/strategy-drift/{instrument_id}` | Page |
| `GET` | `/content` | SSR loader |
| `GET` | `/dd-reports/funds/{fund_id}` | SSR loader |
| `GET` | `/dd-reports/{report_id}` | SSR loader |
| `GET` | `/fact-sheets/model-portfolios/{portfolio_id}` | SSR loader |
| `GET` | `/instruments` | InstrumentsView.svelte |
| `GET` | `/instruments/{instrument_id}` | InstrumentsView.svelte |
| `GET` | `/macro/regime` | SSR loader |
| `GET` | `/macro/reviews` | SSR loader |
| `GET` | `/macro/scores` | SSR loader |
| `GET` | `/macro/snapshot` | SSR loader |
| `GET` | `/manager-screener/managers/{crd}/brochure/sections` | Page |
| `GET` | `/manager-screener/managers/{crd}/drift` | Page |
| `GET` | `/manager-screener/managers/{crd}/holdings` | Page |
| `GET` | `/manager-screener/managers/{crd}/institutional` | Page |
| `GET` | `/manager-screener/managers/{crd}/nport` | Page |
| `GET` | `/manager-screener/managers/{crd}/profile` | Page |
| `GET` | `/manager-screener/managers/{crd}/universe-status` | Page |
| `GET` | `/model-portfolios` | SSR loader |
| `GET` | `/model-portfolios/{portfolio_id}` | SSR loader |
| `GET` | `/model-portfolios/{portfolio_id}/track-record` | Page, SSR loader |
| `GET` | `/portfolios` | SSR loader |
| `GET` | `/portfolios/{profile}` | SSR loader |
| `GET` | `/portfolios/{profile}/history` | SSR loader |
| `GET` | `/portfolios/{profile}/snapshot` | SSR loader |
| `GET` | `/risk/macro` | SSR loader, risk-store.svelte.ts |
| `GET` | `/risk/regime` | SSR loader, risk-store.svelte.ts |
| `GET` | `/risk/regime/history` | SSR loader, risk-store.svelte.ts |
| `GET` | `/risk/summary` | SSR loader |
| `GET` | `/risk/{profile}/cvar` | SSR loader |
| `GET` | `/risk/{profile}/cvar/history` | SSR loader, risk-store.svelte.ts |
| `GET` | `/screener/results` | SSR loader |
| `GET` | `/screener/runs` | SSR loader |
| `GET` | `/screener/runs/{run_id}` | Page |
| `GET` | `/universe` | UniverseView.svelte |
| `GET` | `/universe/pending` | UniverseView.svelte |
| `GET` | `/wealth/documents` | SSR loader |
| `GET` | `/wealth/documents/{document_id}` | SSR loader |
| `GET` | `/wealth/exposure/metadata` | ExposureView.svelte |
| `PATCH` | `/macro/reviews/{review_id}/approve` | Page |
| `PATCH` | `/macro/reviews/{review_id}/reject` | Page |
| `POST` | `/analytics/backtest` | Page |
| `POST` | `/analytics/optimize` | Page |
| `POST` | `/analytics/optimize/pareto` | Page |
| `POST` | `/analytics/strategy-drift/scan` | Page |
| `POST` | `/content/{content_id}/approve` | Page |
| `POST` | `/dd-reports/{report_id}/approve` | Page |
| `POST` | `/dd-reports/{report_id}/regenerate` | Page |
| `POST` | `/dd-reports/{report_id}/reject` | Page |
| `POST` | `/fact-sheets/model-portfolios/{portfolio_id}` | Page |
| `POST` | `/instruments` | EsmaManagerDrawer.svelte, InstrumentsView.svelte |
| `POST` | `/instruments/import/yahoo` | InstrumentsView.svelte |
| `POST` | `/macro/reviews/generate` | Page |
| `POST` | `/manager-screener/managers/compare` | Page |
| `POST` | `/manager-screener/managers/{crd}/add-to-universe` | ManagerDetailPanel.svelte, Page |
| `POST` | `/model-portfolios` | Page |
| `POST` | `/model-portfolios/{portfolio_id}/backtest` | Page |
| `POST` | `/model-portfolios/{portfolio_id}/construct` | Page |
| `POST` | `/model-portfolios/{portfolio_id}/stress` | Page |
| `POST` | `/portfolios/{profile}/rebalance` | Page, RebalancingTab.svelte |
| `POST` | `/portfolios/{profile}/rebalance/{event_id}/approve` | RebalancingTab.svelte |
| `POST` | `/portfolios/{profile}/rebalance/{event_id}/execute` | RebalancingTab.svelte |
| `POST` | `/screener/run` | Page |
| `POST` | `/universe/funds/{instrument_id}/approve` | UniverseView.svelte |
| `POST` | `/universe/funds/{instrument_id}/reject` | UniverseView.svelte |
| `POST` | `/wealth/documents/ingestion/process-pending` | Page |
| `PUT` | `/allocation/{profile}/strategic` | AllocationView.svelte |
| `PUT` | `/allocation/{profile}/tactical` | AllocationView.svelte |

---

## Endpoints Desconectados (56)

### P1 — Mutativos sem Frontend

#### Wealth — Content Generation (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/content/flash-reports` | Gerar flash reports nao exposto na UI |
| `POST` | `/content/outlooks` | Gerar outlooks nao exposto na UI |
| `POST` | `/content/spotlights` | Gerar spotlights nao exposto na UI |
| `GET` | `/content/{content_id}/download` | Download de conteudo gerado sem link na UI |

> **Nota:** A pagina `/content` mostra lista e aprova, mas a geracao de flash-reports, outlooks e spotlights nao tem botoes — apenas `macro/reviews/generate` esta conectado.

#### Wealth — Model Portfolio Actions (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/model-portfolios/{portfolio_id}/stress-test` | Stress test separado do `/stress` — provavel duplicata ou endpoint legacy |
| `GET` | `/model-portfolios/{portfolio_id}/views` | Listar views BL (Black-Litterman) |
| `POST` | `/model-portfolios/{portfolio_id}/views` | Criar views BL |
| `DELETE` | `/model-portfolios/{portfolio_id}/views/{view_id}` | Deletar view BL |

> **Nota:** Views BL (portfolio_views) foram adicionados no quant upgrade (Sprint 3). Frontend usa `/construct` que aplica views implicitamente, mas CRUD de views individuais nao esta exposto.

#### Wealth — DD Reports Actions (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/dd-reports` | Listar todos DD reports (sem filtro por fund) |
| `POST` | `/dd-reports/funds/{fund_id}` | Disparar geracao de DD report |
| `GET` | `/dd-reports/{report_id}/audit-trail` | Audit trail do report |
| `GET` | `/dd-reports/{report_id}/stream` | SSE stream de progresso |

> **Nota:** Frontend acessa `/dd-reports/funds/{fund_id}` (GET, lista por fund) e `/dd-reports/{report_id}` (GET, detalhe). Mas o POST para **disparar** geracao e o SSE de progresso nao estao conectados. O botao "Generate" no frontend pode estar usando uma chamada que o scanner nao detectou (template literal dinâmica) — verificar `+page.svelte` de DD reports.

#### Wealth — Instruments (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/instruments/import/csv` | Import CSV de instrumentos sem botao na UI |
| `PATCH` | `/instruments/{instrument_id}` | Editar instrumento sem form na UI |

#### Wealth — Allocation Writes (1 endpoint)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/allocation/{profile}/simulate` | Simulacao de alocacao sem botao na UI |

#### Wealth — Other (documentos + exposure) (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/wealth/documents/upload` | Upload direto (sem presigned URL) |
| `POST` | `/wealth/documents/upload-complete` | Completar upload |
| `POST` | `/wealth/documents/upload-url` | Obter presigned URL |
| `GET` | `/wealth/exposure/matrix` | Matriz de exposicao (geo/sector) |

> **Nota:** ExposureView.svelte consome `/wealth/exposure/metadata` mas chama `/wealth/exposure/matrix` via template literal com query params — scanner detectou como phantom call por causa do formato `?dimension=geographic&aggregation={param}`.

### P2 — Reads de Valor sem Frontend

#### Wealth — Screener Detail (9 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/screener/catalog` | Catalogo unificado (3 universos) |
| `GET` | `/screener/catalog/facets` | Facetas do catalogo |
| `GET` | `/screener/facets` | Facetas do screener |
| `POST` | `/screener/import-esma/{isin}` | Import ESMA fund ao screener |
| `POST` | `/screener/import-sec/{ticker}` | Import SEC fund ao screener |
| `GET` | `/screener/results/{instrument_id}` | Resultado individual de screening |
| `GET` | `/screener/search` | Busca textual no screener |
| `GET` | `/screener/securities` | Lista de securities |
| `GET` | `/screener/securities/facets` | Facetas de securities |

> **Nota:** O frontend usa `/screener/results` (lista) e `/screener/runs`, mas o catalogo unificado, search, e detail individual nao estao conectados. Estes endpoints sao a base do Fund Catalog — provavel que `+page.server.ts` do screener use chamadas via template literals que o scanner nao capturou.

#### Wealth — Analytics (6 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/analytics/backtest/{run_id}` | Detalhe de backtest individual |
| `GET` | `/analytics/entity/{entity_id}` | Analytics por entidade |
| `GET` | `/analytics/optimize/pareto/{job_id}/stream` | SSE stream de Pareto optimization |
| `GET` | `/analytics/rolling-correlation` | Rolling correlation matrix |
| `GET` | `/analytics/strategy-drift/{instrument_id}/export` | Export CSV de drift |
| `GET` | `/analytics/strategy-drift/{instrument_id}/history` | Historico de drift |

> **Nota:** Pareto stream (`/pareto/{job_id}/stream`) e consumido via poller generico — o scanner pode nao ter detectado a conexao indireta via `poller.svelte.ts`.

#### Wealth — ESMA Registry (5 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/esma/funds` | Listar fundos ESMA |
| `GET` | `/esma/funds/{isin}` | Detalhe fund ESMA |
| `GET` | `/esma/managers` | Listar managers ESMA |
| `GET` | `/esma/managers/{esma_id}` | Detalhe manager ESMA |
| `GET` | `/esma/managers/{esma_id}/sec-crossref` | Cross-referencia SEC ↔ ESMA |

> **Nota:** ESMA endpoints existem em `_legacy_routes` e foram migrados para `/screener` (catalog unificado). Os endpoints diretos `/esma/*` provavelmente sao consumidos via legacy routes que o scanner detectou como phantom.

#### Wealth — Macro Data (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/macro/bis` | BIS statistics |
| `GET` | `/macro/imf` | IMF WEO forecasts |
| `GET` | `/macro/ofr` | OFR hedge fund data |
| `GET` | `/macro/treasury` | US Treasury data |

> **Nota:** Dados macro granulares (BIS, IMF, OFR, Treasury) nao tem UI dedicada. O dashboard de risk usa `/macro/snapshot` e `/macro/regime` que sao agregados. Considerar tab de "Macro Deep Dive" no risk dashboard.

#### Wealth — Manager Screener (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/manager-screener` | Lista/search de managers (endpoint raiz) |
| `GET` | `/manager-screener/managers/{crd}/brochure` | Brochure completa |
| `GET` | `/manager-screener/managers/{crd}/brochure/key-sections` | Key sections extraidas |
| `GET` | `/manager-screener/managers/{crd}/registered-funds` | Fundos registrados do manager |

> **Nota:** O endpoint raiz `/manager-screener` e consumido via legacy route com query params (`/?{param}`) — scanner detectou como phantom. `/brochure/key-sections` e usado internamente pelo DD report engine.

### P3 — Nice-to-Have

#### Wealth — Asset Universe (1 endpoint)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/universe/funds/{instrument_id}/audit-trail` | Audit trail de aprovacao de fund |

#### Wealth — Fact Sheet Actions (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/fact-sheets/dd-reports/{report_id}/download` | Download PDF do DD report fact sheet |
| `GET` | `/fact-sheets/{fact_sheet_path}/download` | Download PDF de fact sheet |

> **Nota:** Fact sheet download provavelmente e acessado via link direto no browser (window.open) — nao aparece como `.get()` call.

#### Wealth — Portfolio Rebalancing (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/portfolios/{profile}/rebalance` | Listar eventos de rebalancing |
| `GET` | `/portfolios/{profile}/rebalance/{event_id}` | Detalhe de evento |

> **Nota:** RebalancingTab.svelte consome POST (trigger/approve/execute) mas os GETs de listagem/detalhe podem usar pattern diferente.

#### Wealth — Risk SSE (1 endpoint)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/risk/stream` | SSE stream de risk updates |

> **Nota:** SSE streams usam `fetch()` + `ReadableStream` pattern — scanner pode nao detectar conexao via `risk-store.svelte.ts`.

---

## Phantom Calls — Wealth Frontend (39)

### Falsos positivos (URL params parseados como paths)

Estas chamadas sao artefatos do scanner que extrai `searchParams.get('param')` como paths:

| Path | Arquivo | Causa |
|---|---|---|
| `/aum_min` | `screener/+page.server.ts:40` | `url.searchParams.get('aum_min')` |
| `/benchmark_id` | `entity-analytics/+page.server.ts:77` | `url.searchParams.get('benchmark_id')` |
| `/domain` | `documents/+page.server.ts:11` | `url.searchParams.get('domain')` |
| `/entity_id` | `entity-analytics/+page.server.ts:71` | `url.searchParams.get('entity_id')` |
| `/exchange` | `screener/+page.server.ts:60` | `url.searchParams.get('exchange')` |
| `/page` | `screener/+page.server.ts:25` | `url.searchParams.get('page')` |
| `/page_size` | (multiplos) | `url.searchParams.get('page_size')` |
| `/portfolio` | (multiplos) | `url.searchParams.get('portfolio')` |
| `/portfolio_id` | `documents/+page.server.ts:10` | `url.searchParams.get('portfolio_id')` |
| `/profile` | `analytics/+page.server.ts:10` | `url.searchParams.get('profile')` |
| `/q` | `screener/+page.server.ts:30,56` | `url.searchParams.get('q')` |
| `/search` | `esma/+page.server.ts:11` | `url.searchParams.get('search')` |
| `/security_type` | `screener/+page.server.ts:58` | `url.searchParams.get('security_type')` |
| `/sort` | `screener/+page.server.ts:42,62` | `url.searchParams.get('sort')` |
| `/status` | `dd-reports/+page.server.ts:10` | `url.searchParams.get('status')` |
| `/tab` | (multiplos) | `url.searchParams.get('tab')` |
| `/type` | `esma/+page.server.ts:14` | `url.searchParams.get('type')` |
| `/window` | `entity-analytics/+page.server.ts:76` | `url.searchParams.get('window')` |
| `/country` | `esma/+page.server.ts:12` | `url.searchParams.get('country')` |
| `/domicile` | `esma/+page.server.ts:13` | `url.searchParams.get('domicile')` |
| `/__session` | `auth/callback/+page.server.ts:11` | Cookie read |

### Calls reais a investigar

| Metodo | Path | Arquivo | Diagnostico |
|---|---|---|---|
| `POST` | `/content/{param}{param}` | `(app)/content/+page.svelte:55` | Template literal com path dinâmico — provavelmente `/content/{id}/approve` ou `/reject` |
| `GET` | `/wealth/exposure/matrix?dimension=geographic&...` | `ExposureView.svelte:45` | Query params — backend existe, scanner nao matchou |
| `GET` | `/wealth/exposure/matrix?dimension=sector&...` | `ExposureView.svelte:46` | Query params — backend existe, scanner nao matchou |

> **Nota (2026-03-27):** 8 phantom calls originadas de `_legacy_routes/` foram eliminadas com a remoção do diretório `frontends/wealth/src/_legacy_routes/` (66 arquivos, 0 referências externas). Routes legacy: content/reject, inv-dd-reports, esma/funds, esma/managers, manager-screener (3 calls), risk/drift-alerts.

---

## Recomendacoes

### P1 — Critico (Funcionalidade Core Inacessivel)

1. **Content Generation** — 3 endpoints POST (`/content/flash-reports`, `/outlooks`, `/spotlights`) sem botoes na UI. A pagina de content lista e aprova, mas nao dispara geracao. Adicionar botoes "Generate Flash Report", "Generate Outlook", "Generate Spotlight" na pagina `/content`.

2. **Black-Litterman Views CRUD** — 3 endpoints (`GET/POST/DELETE /model-portfolios/{id}/views`) sem UI. O quant upgrade adicionou portfolio_views mas o frontend usa apenas `/construct` implicitamente. Considerar painel de "IC Views" na pagina de model portfolio.

3. **DD Report Trigger + Stream** — `POST /dd-reports/funds/{fund_id}` e `GET /dd-reports/{report_id}/stream` podem estar conectados via template literal dinâmica. Verificar antes de implementar — pode ser falso negativo do scanner.

4. **Instruments PATCH** — Sem form de edicao de instrumento. Apenas criacao (POST) e import (Yahoo) estao conectados.

5. **Allocation Simulate** — `POST /allocation/{profile}/simulate` sem botao. AllocationView tem strategic/tactical PUT mas nao simulate.

### P2 — Importante (Funcionalidade de Valor)

6. **Screener Catalog/Search** — 9 endpoints do catalog unificado (3 universos) nao detectados. Provavelmente conectados via template literals na pagina `/screener` — verificar antes de classificar como gap real.

7. **ESMA Registry** — 5 endpoints diretos `/esma/*` redundantes com catalog unificado. Manter como API interna para workers/DD-report. Nao precisa de UI dedicada.

8. **Macro Deep Dive** — 4 endpoints granulares (BIS, IMF, OFR, Treasury) sem UI. Considerar tab "Macro Sources" no risk dashboard para power users.

9. **Analytics extras** — Backtest detail, entity analytics, Pareto SSE, rolling correlation, drift export/history. Alguns provavelmente conectados via patterns indiretos.

### P3 — Nice-to-Have

10. **Fact Sheet downloads** — Provavelmente acessados via `window.open()`. Baixo risco.

11. **Rebalancing GETs** — Listagem/detalhe de eventos. RebalancingTab usa POSTs mas GETs podem ser carregados inline.

12. **Risk SSE stream** — Consumido via `risk-store.svelte.ts` com `fetch()` + `ReadableStream`. Falso negativo do scanner.

13. **Universe audit-trail** — Funcionalidade de compliance, baixa prioridade.

### Cleanup recomendado

14. ~~**Remover `_legacy_routes/`**~~ — **DONE (2026-03-27).** 66 arquivos removidos. Zero referências externas, zero impacto no build. 8 phantom calls eliminadas do relatório.

---

## Metodologia

### Ferramentas Utilizadas
- Exploracao automatizada de routers FastAPI (AST parsing de `@router.*` + `include_router`)
- Varredura de loaders, pages e componentes SvelteKit (`.get/.post/.put/.patch/.delete` + `fetch(...)`)
- Script: `.claude/skills/endpoint-coverage-auditor/scripts/scan_endpoint_coverage.py`

### Limitacoes
- A resolucao de rotas usa heuristicas AST/regex e pode subcontar construcoes altamente dinamicas
- Template literals com interpolacao complexa (e.g. `` `.../funds/${fundId}` ``) podem gerar falsos negativos
- `url.searchParams.get()` parseado como path gera alto volume de falsos positivos (39 phantom calls, ~21 sao params)
- SSE streams via `fetch()` + `ReadableStream` nao detectados como conexao
- Calls via `poller.svelte.ts` (job polling generico) nao associados ao endpoint de origem
- Componentes que usam `window.open()` para downloads nao rastreados
