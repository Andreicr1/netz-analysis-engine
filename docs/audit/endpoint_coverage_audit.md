# Auditoria de Endpoints — Netz Analysis Engine

**Data:** 2026-03-17
**Branch:** `feat/admin-frontend`
**Verticals:** Credit, Wealth, Admin

---

## Resumo Executivo

| Metrica | Valor |
|---|---|
| Total de endpoints backend | **186** |
| Conectados ao frontend | **83** (44.6%) |
| Desconectados | **95** (51.1%) |
| Internos/Infra | **4** (2.2%) |
| Phantom calls (frontend sem backend) | **2** (1.1%) |

### Breakdown por Vertical

| Vertical | Total | Conectados | Desconectados | % Cobertura |
|---|---|---|---|---|
| Admin | 28 | 16 | 12 | 57% |
| Credit | 80 | 40 | 40 | 50% |
| Wealth | 74 | 27 | 47 | 36% |
| Shared/Core | 4 | 0 | 0 | N/A (infra) |

---

## Endpoints Internos/Infra

| Endpoint | Proposito |
|---|---|
| `GET /health` | Health check |
| `GET /api/health` | Health check (alternate) |
| `GET /api/v1` | API root/version info |
| `POST /api/v1/test/sse/{job_id}/emit` | Dev-only SSE test emitter |

---

## Endpoints Conectados

### Shared (Credit + Wealth)

| Endpoint | Credit | Wealth | Admin |
|---|---|---|---|
| `GET /branding` | layout | layout | - |
| `GET /funds` | funds list | funds/dd-reports list | - |
| `GET /funds/{fund_id}` | fund layout | fund detail | - |
| `GET /jobs/{job_id}/stream` (SSE) | ingestion + IC memo | - | - |

### Admin Frontend (16 endpoints conectados)

| Metodo | Endpoint | Componente |
|---|---|---|
| `GET` | `/admin/health/services` | Health page (SSR + refresh) |
| `GET` | `/admin/health/workers` | Health page (SSR) |
| `GET` | `/admin/health/pipelines` | Health page (SSR + refresh) |
| `GET` | `/admin/health/workers/logs` | WorkerLogFeed SSE stream |
| `GET` | `/admin/tenants/` | Tenants list page |
| `GET` | `/admin/tenants/{org_id}` | Tenant detail layout |
| `GET` | `/admin/configs/` | Config list page |
| `GET` | `/admin/configs/{vertical}/{config_type}` | ConfigEditor |
| `GET` | `/admin/configs/{vertical}/{config_type}/diff` | ConfigDiffViewer |
| `POST` | `/admin/configs/validate` | ConfigEditor |
| `GET` | `/admin/prompts/{vertical}` | Prompts list page |
| `GET` | `/admin/prompts/{vertical}/{name}` | PromptEditor |
| `PUT` | `/admin/prompts/{vertical}/{name}` | PromptEditor (save) |
| `DELETE` | `/admin/prompts/{vertical}/{name}` | PromptEditor (revert) |
| `POST` | `/admin/prompts/{vertical}/{name}/preview` | PromptEditor |
| `POST` | `/admin/prompts/{vertical}/{name}/validate` | PromptEditor |

### Credit Frontend (40 endpoints conectados)

| Metodo | Endpoint | Pagina/Componente |
|---|---|---|
| `GET` | `/funds/{fund_id}/deals` | Pipeline list |
| `GET` | `/funds/{fund_id}/deals/{deal_id}` | Deal detail |
| `GET` | `/funds/{fund_id}/deals/{deal_id}/stage-timeline` | Deal detail |
| `POST` | `/funds/{fund_id}/deals/{deal_id}/ic-memo` | ICMemoViewer (generate) |
| `GET` | `/funds/{fund_id}/deals/{deal_id}/ic-memo` | Deal detail |
| `GET` | `/funds/{fund_id}/deals/{deal_id}/ic-memo/voting-status` | Deal detail |
| `GET` | `/funds/{fund_id}/alerts` | Portfolio |
| `GET` | `/funds/{fund_id}/obligations` | Portfolio |
| `GET` | `/funds/{fund_id}/portfolio/actions` | Portfolio |
| `POST` | `/documents/upload-url` | Document upload (step 1) |
| `POST` | `/documents/upload-complete` | Document upload (step 3) |
| `GET` | `/documents` | Document list |
| `GET` | `/funds/{fund_id}/document-reviews` | Reviews list |
| `GET` | `/funds/{fund_id}/document-reviews/pending` | Reviews pending |
| `GET` | `/funds/{fund_id}/document-reviews/summary` | Reviews summary |
| `GET` | `/funds/{fund_id}/document-reviews/{review_id}` | Review detail |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/decide` | Review decision |
| `GET` | `/funds/{fund_id}/document-reviews/{review_id}/checklist` | Review checklist |
| `GET` | `/dashboard/portfolio-summary` | Dashboard |
| `GET` | `/dashboard/pipeline-summary` | Dashboard |
| `GET` | `/dashboard/macro-snapshot` | Dashboard |
| `GET` | `/dashboard/compliance-alerts` | Dashboard |
| `GET` | `/dashboard/pipeline-analytics` | Dashboard |
| `GET` | `/dashboard/task-inbox` | Dashboard |
| `POST` | `/funds/{fund_id}/report-packs` | Reporting (create pack) |
| `POST` | `/funds/{fund_id}/reports/nav/snapshots` | Reporting (create NAV) |
| `GET` | `/funds/{fund_id}/reports/nav/snapshots` | Reporting |
| `GET` | `/funds/{fund_id}/reports/monthly-pack/list` | Reporting |
| `GET` | `/funds/{fund_id}/reports/investor-statements` | Reporting |
| `POST` | `/funds/{fund_id}/reports/evidence-pack` | Reporting (JSON export) |
| `POST` | `/funds/{fund_id}/reports/evidence-pack/pdf` | Reporting (PDF export) |
| `GET` | `/funds/{fund_id}/investor/documents` | Investor portal |
| `GET` | `/funds/{fund_id}/investor/report-packs` | Investor portal |
| `GET` | `/funds/{fund_id}/investor/statements` | Investor portal |
| `POST` | `/ai/answer` | Fund Copilot |

### Wealth Frontend (27 endpoints conectados)

| Metodo | Endpoint | Pagina/Componente |
|---|---|---|
| `GET` | `/portfolios` | Dashboard |
| `GET` | `/risk/{profile}/cvar` | Dashboard + Risk (3x per profile) |
| `GET` | `/risk/{profile}/cvar/history` | Risk (3x per profile) |
| `GET` | `/risk/regime` | Dashboard + Risk |
| `GET` | `/risk/regime/history` | Risk |
| `GET` | `/risk/macro` | Dashboard + Risk |
| `GET` | `/macro/scores` | Macro Intelligence |
| `GET` | `/macro/snapshot` | Macro Intelligence |
| `GET` | `/macro/regime` | Macro Intelligence |
| `GET` | `/macro/reviews` | Macro Intelligence |
| `POST` | `/screener/run` | Screener (client-side batch) |
| `GET` | `/screener/runs` | Funds + Screener |
| `GET` | `/screener/results` | Screener |
| `GET` | `/wealth/exposure/matrix` | Exposure (2x: geo + sector) |
| `GET` | `/wealth/exposure/metadata` | Exposure |
| `GET` | `/allocation/{profile}/strategic` | Allocation |
| `GET` | `/allocation/{profile}/tactical` | Allocation |
| `GET` | `/allocation/{profile}/effective` | Allocation |
| `GET` | `/analytics/correlation` | Analytics |
| `GET` | `/analytics/correlation-regime/{profile}` | Analytics |
| `GET` | `/analytics/strategy-drift/alerts` | Risk |
| `GET` | `/content` | Content + Investor (docs/reports) |
| `GET` | `/dd-reports/funds/{fund_id}` | DD Reports |
| `GET` | `/dd-reports/{report_id}/stream` (SSE) | FundDetailPanel |
| `GET` | `/fact-sheets/model-portfolios/{portfolio_id}` | Investor fact-sheets |
| `GET` | `/model-portfolios` | Dashboard + Model Portfolios + Investor |
| `GET` | `/model-portfolios/{id}` | Model Portfolio detail |
| `GET` | `/model-portfolios/{id}/track-record` | Model Portfolio detail + Investor |

---

## Endpoints Desconectados

### PRIORIDADE CRITICA — Write Operations sem Frontend

Endpoints com verbos destrutivos/mutativos que nao possuem nenhuma interface no frontend. Representam funcionalidade implementada no backend sem forma de uso pelo usuario.

#### Admin — Tenant Management (5 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/admin/tenants/` | **Criar tenant** — sem form no admin |
| `PATCH` | `/admin/tenants/{org_id}` | **Editar tenant** — sem form no admin |
| `POST` | `/admin/tenants/{org_id}/seed` | **Seed tenant** — sem botao no admin |
| `POST` | `/admin/tenants/{org_id}/assets` | **Upload logo/asset** — sem upload no admin |
| `DELETE` | `/admin/tenants/{org_id}/assets/{asset_type}` | **Deletar asset** — sem botao no admin |

#### Admin — Config Management (3 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `PUT` | `/admin/configs/{vertical}/{config_type}` | **Salvar config override** — ConfigEditor le e valida mas NAO salva |
| `DELETE` | `/admin/configs/{vertical}/{config_type}` | **Deletar config override** — sem botao |
| `PUT` | `/admin/configs/defaults/{vertical}/{config_type}` | **Atualizar default** — sem interface |

#### Credit — Deal Lifecycle (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/funds/{fund_id}/deals` | **Criar deal** — pipeline so lista, nao cria |
| `PATCH` | `/funds/{fund_id}/deals/{deal_id}/decision` | **Decidir deal** — sem botao approve/reject |
| `PATCH` | `/funds/{fund_id}/deals/{deal_id}/ic-memo/conditions` | **Resolver condicao IC** — sem checkbox |
| `POST` | `/funds/{fund_id}/deals/{deal_id}/convert` | **Converter deal→asset** — sem botao |

#### Credit — Portfolio Management (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/funds/{fund_id}/assets` | **Criar asset** — sem form |
| `POST` | `/funds/{fund_id}/assets/{asset_id}/obligations` | **Criar obligation** — sem form |
| `PATCH` | `/funds/{fund_id}/obligations/{obligation_id}` | **Atualizar obligation** — sem form |
| `PATCH` | `/funds/{fund_id}/portfolio/actions/{action_id}` | **Atualizar action** — sem botao |

#### Credit — Document Workflow (10 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/documents/upload` | Upload alternativo (nao-SAS) — sem interface |
| `GET` | `/documents/root-folders` | Listar root folders — sem navegacao |
| `GET` | `/documents/{document_id}` | Detalhe de documento — sem pagina |
| `GET` | `/documents/{document_id}/versions` | Versoes de documento — sem interface |
| `POST` | `/documents/root-folders` | Criar root folder — sem form |
| `POST` | `/documents/ingestion/process-pending` | Processar pendentes — sem botao |
| `POST` | `/funds/{fund_id}/evidence/upload-request` | Upload evidence — sem form |
| `PATCH` | `/funds/{fund_id}/evidence/{evidence_id}/complete` | Marcar evidence — sem interface |
| `GET` | `/funds/{fund_id}/auditor/evidence` | Auditor view — sem pagina |
| `POST` | `/funds/{fund_id}/document-reviews` | Submeter para review — sem botao |

#### Credit — Document Review Actions (5 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/assign` | Atribuir reviewer — sem interface |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/finalize` | Finalizar review — sem botao |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/resubmit` | Resubmeter — sem botao |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/ai-analyze` | Trigger AI analysis — sem botao |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/checklist/{item_id}/check` | Marcar checklist — sem checkbox interativo |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/checklist/{item_id}/uncheck` | Desmarcar checklist — sem checkbox interativo |

#### Credit — Dashboard FRED/Macro (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/dashboard/macro-history` | Historico macro — sem pagina |
| `GET` | `/dashboard/macro-fred-series` | FRED series — sem pagina |
| `GET` | `/dashboard/fred-search` | Busca FRED — sem interface |
| `GET` | `/dashboard/macro-fred-multi` | Multi-series FRED — sem interface |

#### Credit — Report Pack Actions (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/funds/{fund_id}/report-packs/{pack_id}/generate` | Gerar pack — sem botao |
| `POST` | `/funds/{fund_id}/report-packs/{pack_id}/publish` | Publicar pack — sem botao |

#### Credit — AI Module (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/ai/query` | Query alternativo — sem interface |
| `GET` | `/ai/activity` | AI activity log — sem pagina |
| `GET` | `/ai/history` | Query history — sem pagina |
| `POST` | `/ai/retrieve` | Document retrieval — sem interface |

#### Wealth — Portfolio Rebalancing (6 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/portfolios/{profile}` | Profile detail — sem pagina dedicada |
| `GET` | `/portfolios/{profile}/snapshot` | Portfolio snapshot — sem interface |
| `GET` | `/portfolios/{profile}/history` | Portfolio history — sem interface |
| `POST` | `/portfolios/{profile}/rebalance` | Trigger rebalance — sem botao |
| `POST` | `/portfolios/{profile}/rebalance/{event_id}/approve` | Aprovar rebalance — sem botao |
| `POST` | `/portfolios/{profile}/rebalance/{event_id}/execute` | Executar rebalance — sem botao |
| `GET` | `/portfolios/{profile}/rebalance/{event_id}` | Rebalance event detail — sem pagina |

#### Wealth — Macro Committee (3 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/macro/reviews/generate` | Gerar relatorio comite — sem botao |
| `PATCH` | `/macro/reviews/{review_id}/approve` | CIO approve — sem botao |
| `PATCH` | `/macro/reviews/{review_id}/reject` | CIO reject — sem botao |

#### Wealth — Screener Detail (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/screener/runs/{run_id}` | Run detail — sem pagina |
| `GET` | `/screener/results/{instrument_id}` | Instrument screening history — sem interface |

#### Wealth — Allocation Writes (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `PUT` | `/allocation/{profile}/strategic` | IC update strategic — sem form |
| `PUT` | `/allocation/{profile}/tactical` | Update tactical — sem form |

#### Wealth — Analytics (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/analytics/backtest` | Run backtest — sem interface |
| `GET` | `/analytics/backtest/{run_id}` | Backtest results — sem pagina |
| `POST` | `/analytics/optimize` | Portfolio optimization — sem interface |
| `POST` | `/analytics/optimize/pareto` | Multi-objective optimization — sem interface |

#### Wealth — Analytics Drill-Down (3 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` | Pair correlation — sem interface |
| `POST` | `/analytics/strategy-drift/scan` | Trigger drift scan — sem botao |
| `GET` | `/analytics/strategy-drift/{instrument_id}` | Instrument drift — sem interface |

#### Wealth — Attribution (1 endpoint)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/analytics/attribution/funds/{fund_id}/period` | Performance attribution — sem pagina |

#### Wealth — Content Generation (5 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/content/outlooks` | Generate Investment Outlook — sem botao |
| `POST` | `/content/flash-reports` | Generate Flash Report — sem botao |
| `POST` | `/content/spotlights` | Generate Manager Spotlight — sem botao |
| `POST` | `/content/{content_id}/approve` | Approve content — sem botao |
| `GET` | `/content/{content_id}/download` | Download content PDF — sem link |

#### Wealth — DD Reports Actions (3 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/dd-reports/funds/{fund_id}` | Generate DD Report — sem botao |
| `GET` | `/dd-reports/{report_id}` | DD Report full detail — sem pagina |
| `POST` | `/dd-reports/{report_id}/regenerate` | Regenerate chapters — sem botao |

#### Wealth — Fact Sheet Actions (3 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/fact-sheets/model-portfolios/{portfolio_id}` | Generate fact-sheet — sem botao |
| `GET` | `/fact-sheets/{path}/download` | Download fact-sheet PDF — sem link |
| `GET` | `/fact-sheets/dd-reports/{report_id}/download` | Download DD as PDF — sem link |

#### Wealth — Model Portfolio Actions (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/model-portfolios` | Create model portfolio — sem form |
| `POST` | `/model-portfolios/validate` | Validate portfolio — sem interface |
| `GET` | `/model-portfolios/{id}/backtest` | Portfolio backtest — sem interface |
| `POST` | `/model-portfolios/{id}/allocate` | Allocate portfolio — sem interface |
| `POST` | `/model-portfolios/{id}/rebalance` | Rebalance portfolio — sem interface |

#### Wealth — Instruments (5 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/instruments` | List instruments — sem pagina |
| `GET` | `/instruments/{instrument_id}` | Instrument detail — sem pagina |
| `POST` | `/instruments` | Create instrument — sem form |
| `POST` | `/instruments/bulk-sync` | Bulk sync — sem interface |
| `POST` | `/instruments/search-external` | External search — sem interface |

#### Wealth — Fund Detail (3 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/funds/{fund_id}/stats` | Fund stats — nao chamado por nenhum frontend |
| `GET` | `/funds/{fund_id}/performance` | Fund performance — nao chamado |
| `GET` | `/funds/{fund_id}/holdings` | Fund holdings — nao chamado |

#### Wealth — Risk SSE (1 endpoint)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/risk/stream` | Live risk alerts SSE — nao conectado |

#### Admin — Other (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/admin/configs/invalid` | List invalid configs — sem pagina |
| `GET` | `/assets/tenant/{org_slug}/{asset_type}` | Serve tenant asset — possivelmente usado indiretamente por `<img>` tags |

#### Admin — Prompt Versioning (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/admin/prompts/{vertical}/{name}/versions` | Prompt version history — sem interface |
| `POST` | `/admin/prompts/{vertical}/{name}/revert/{version}` | Revert to version — sem interface |

---

## Phantom Calls (Frontend sem Backend)

Chamadas no frontend que nao correspondem a nenhum endpoint conhecido no backend:

| Frontend | Metodo | Path | Arquivo |
|---|---|---|---|
| Wealth | `GET` | `/funds/{fundId}/risk` | `funds/[fundId]/+page.server.ts:12` |
| Wealth | `GET` | `/funds/{fundId}/nav` | `funds/[fundId]/+page.server.ts:13` |

> Estas chamadas provavelmente retornam 404 ou sao tratadas por `Promise.allSettled` com fallback silencioso. Verificar se sao endpoints planejados ou residuos de refatoracao.

---

## Recomendacoes

### P1 — Critico (Funcionalidade Core Inacessivel)

1. **Admin: ConfigEditor nao salva** — O editor de configuracao carrega e valida mas falta o `PUT` para persistir. Adicionar botao "Save" que chame `PUT /admin/configs/{vertical}/{config_type}`.

2. **Admin: Tenant CRUD incompleto** — Apenas list/detail implementados. Faltam: create, edit, seed, asset upload/delete. Completar o CRUD do tenant management.

3. **Credit: Deal lifecycle sem acoes** — Pipeline lista deals mas nao permite criar, aprovar/rejeitar, resolver condicoes IC, ou converter. Estes sao os workflows core do Private Credit.

4. **Credit: Document review parcialmente interativo** — Review detail mostra dados e permite decidir (approve/reject) mas falta: assign reviewer, finalize, resubmit, AI analyze, checklist toggle. O workflow de review esta incompleto.

5. **Wealth: Content generation sem triggers** — O backend suporta geracao de Investment Outlooks, Flash Reports e Manager Spotlights, mas a pagina de Content so lista — nao permite gerar, aprovar ou baixar.

6. **Wealth: DD Report generation sem trigger** — A pagina lista reports mas nao permite gerar novos. O botao "Generate" precisa chamar `POST /dd-reports/funds/{fund_id}`.

### P2 — Importante (Funcionalidade de Valor)

7. **Wealth: Rebalancing workflow completo desconectado** — 7 endpoints de rebalance portfolio sem interface. Este e um workflow critico para wealth management.

8. **Wealth: Macro Committee actions** — Generate, approve/reject macro reviews nao expostos. CIO precisa de interface para aprovar relatorios do comite macro.

9. **Wealth: Backtest + Optimization engine** — 4 endpoints de analytics avancado sem interface. Representa capacidade analitica significativa nao exposta.

10. **Credit: FRED/Macro explorer** — 4 endpoints de exploracao macro (history, series, search, multi) sem pagina dedicada. Considerar adicionar tab "Macro Explorer" ao dashboard.

11. **Credit: Portfolio asset/obligation CRUD** — Backend suporta criar assets e obligations mas frontend so lista.

12. **Wealth: Instrument management** — 5 endpoints sem pagina. Instruments sao referenciados por screener e portfolios mas nao gerenciados diretamente.

13. **Wealth: Allocation write operations** — Frontend mostra strategic/tactical/effective alocacoes mas nao permite editar (PUT).

### P3 — Nice-to-Have

14. **Admin: Prompt versioning** — Backend suporta version history e revert mas PromptEditor nao expoe historico.

15. **Credit: Document detail/versions** — Backend serve documento individual e versoes mas frontend so tem lista.

16. **Credit: Auditor evidence view** — Endpoint de auditor nao exposto em nenhuma interface.

17. **Wealth: Pair correlation drill-down** — Correlation-regime por par de instrumentos disponivel mas sem interface.

18. **Wealth: Risk SSE stream** — Backend emite alertas de risco em tempo real via SSE mas frontend nao consome.

19. **Phantom calls cleanup** — Remover ou implementar `/funds/{fundId}/risk` e `/funds/{fundId}/nav` no wealth frontend.

---

## Metodologia

### Ferramentas Utilizadas
- Exploracao automatizada de routers FastAPI (backend)
- Varredura de `+page.server.ts`, `+page.svelte`, e componentes Svelte (frontends)
- Rastreamento de `createServerApiClient` e `createClientApiClient` calls
- Verificacao cruzada de prefixos de router em `main.py`

### Limitacoes
- Workers e Universe endpoints nao foram individualmente enumerados (estimativa: ~10 endpoints adicionais, todos desconectados)
- Endpoints de dataroom, schedules, e fund_investments foram parcialmente cobertos
- Contagem exata pode variar +/- 5 endpoints devido a routers menores nao explorados
- O endpoint `GET /assets/tenant/{org_slug}/{asset_type}` pode ser usado indiretamente por tags `<img>` no frontend sem chamada programatica explicita
