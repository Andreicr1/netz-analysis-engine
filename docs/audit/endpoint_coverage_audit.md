# Auditoria de Endpoints — netz-analysis-engine

**Data:** 2026-03-18
**Branch:** `main`
**Verticals:** Credit, Wealth, Admin

---

## Resumo Executivo

| Metrica | Valor |
|---|---|
| Total de endpoints backend | **290** |
| Conectados ao frontend | **115** (39.7%) |
| Desconectados | **171** (59.0%) |
| Internos/Infra | **4** (1.4%) |
| Phantom calls (frontend sem backend) | **53** (27.9%) |

### Breakdown por Vertical

| Vertical | Total | Conectados | Desconectados | % Cobertura |
|---|---|---|---|---|
| Admin | 29 | 15 | 14 | 52% |
| Credit | 92 | 48 | 44 | 52% |
| Wealth | 72 | 50 | 22 | 69% |
| Shared/Core | 97 | 2 | 0 | N/A (infra) |

---

## Endpoints Internos/Infra

| Endpoint | Proposito |
|---|---|
| `GET /api/health` | Health check (alternate) |
| `GET /api/v1` | API root/version info |
| `POST /api/v1/test/sse/{job_id}/emit` | Dev-only SSE test emitter |
| `GET /health` | Health check |


---

## Endpoints Conectados

### Shared (Credit + Wealth)

| Endpoint | Credit | Wealth | Admin |
|---|---|---|---|
| `GET /funds` | - | SSR loader | - |
| `GET /funds/{fund_id}` | - | SSR loader | - |

### Admin Frontend (15 endpoints conectados)

| Metodo | Endpoint | Componente |
|---|---|---|
| `DELETE` | `/admin/prompts/{vertical}/{name}` | PromptEditor.svelte |
| `DELETE` | `/admin/tenants/{org_id}/assets/{asset_type}` | Page |
| `GET` | `/admin/configs` | SSR loader |
| `GET` | `/admin/configs/invalid` | SSR loader |
| `GET` | `/admin/configs/{vertical}/{config_type}/diff` | ConfigDiffViewer.svelte |
| `GET` | `/admin/health/pipelines` | Page, SSR loader |
| `GET` | `/admin/health/services` | Page, SSR loader |
| `GET` | `/admin/health/workers` | SSR loader |
| `GET` | `/admin/prompts/{vertical}` | SSR loader |
| `GET` | `/admin/tenants` | SSR loader |
| `GET` | `/admin/tenants/{org_id}` | +layout.server.ts |
| `PATCH` | `/admin/tenants/{org_id}` | Page |
| `POST` | `/admin/prompts/{vertical}/{name}/revert/{version}` | PromptEditor.svelte |
| `POST` | `/admin/tenants/{org_id}/seed` | Page |
| `PUT` | `/admin/configs/defaults/{vertical}/{config_type}` | ConfigEditor.svelte |

### Credit Frontend (48 endpoints conectados)

| Metodo | Endpoint | Pagina/Componente |
|---|---|---|
| `GET` | `/dashboard/compliance-alerts` | SSR loader |
| `GET` | `/dashboard/macro-snapshot` | SSR loader |
| `GET` | `/dashboard/pipeline-analytics` | SSR loader |
| `GET` | `/dashboard/pipeline-summary` | SSR loader |
| `GET` | `/dashboard/portfolio-summary` | SSR loader |
| `GET` | `/dashboard/task-inbox` | SSR loader |
| `GET` | `/documents` | SSR loader |
| `GET` | `/documents/root-folders` | SSR loader |
| `GET` | `/documents/{doc_id}` | SSR loader |
| `GET` | `/documents/{document_id}` | SSR loader |
| `GET` | `/documents/{document_id}/versions` | SSR loader |
| `GET` | `/funds/{fund_id}/alerts` | SSR loader |
| `GET` | `/funds/{fund_id}/auditor/evidence` | SSR loader |
| `GET` | `/funds/{fund_id}/deals` | SSR loader |
| `GET` | `/funds/{fund_id}/deals/{deal_id}/ic-memo` | SSR loader |
| `GET` | `/funds/{fund_id}/deals/{deal_id}/ic-memo/voting-status` | SSR loader |
| `GET` | `/funds/{fund_id}/deals/{deal_id}/stage-timeline` | SSR loader |
| `GET` | `/funds/{fund_id}/document-reviews` | SSR loader |
| `GET` | `/funds/{fund_id}/document-reviews/pending` | SSR loader |
| `GET` | `/funds/{fund_id}/document-reviews/summary` | SSR loader |
| `GET` | `/funds/{fund_id}/document-reviews/{review_id}` | SSR loader |
| `GET` | `/funds/{fund_id}/document-reviews/{review_id}/checklist` | SSR loader |
| `GET` | `/funds/{fund_id}/investor/report-packs` | SSR loader |
| `GET` | `/funds/{fund_id}/obligations` | SSR loader |
| `GET` | `/funds/{fund_id}/portfolio/actions` | SSR loader |
| `GET` | `/funds/{fund_id}/reports/investor-statements` | SSR loader |
| `GET` | `/funds/{fund_id}/reports/monthly-pack/list` | SSR loader |
| `GET` | `/funds/{fund_id}/reports/nav/snapshots` | SSR loader |
| `PATCH` | `/funds/{fund_id}/deals/{deal_id}/decision` | Page |
| `PATCH` | `/funds/{fund_id}/deals/{deal_id}/ic-memo/conditions` | Page |
| `PATCH` | `/funds/{fund_id}/evidence/{evidence_id}/complete` | Page |
| `PATCH` | `/funds/{fund_id}/obligations/{obligation_id}` | Page |
| `PATCH` | `/funds/{fund_id}/portfolio/actions/{action_id}` | Page |
| `POST` | `/documents/root-folders` | Page |
| `POST` | `/funds/{fund_id}/assets` | Page |
| `POST` | `/funds/{fund_id}/assets/{asset_id}/obligations` | Page |
| `POST` | `/funds/{fund_id}/deals/{deal_id}/convert` | Page |
| `POST` | `/funds/{fund_id}/document-reviews` | Page |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/ai-analyze` | Page |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/assign` | Page |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/decide` | Page |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/finalize` | Page |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/resubmit` | Page |
| `POST` | `/funds/{fund_id}/evidence/upload-request` | Page |
| `POST` | `/funds/{fund_id}/report-packs` | Page |
| `POST` | `/funds/{fund_id}/report-packs/{pack_id}/generate` | Page |
| `POST` | `/funds/{fund_id}/report-packs/{pack_id}/publish` | Page |
| `POST` | `/funds/{fund_id}/reports/nav/snapshots` | Page |


### Wealth Frontend (50 endpoints conectados)

| Metodo | Endpoint | Pagina/Componente |
|---|---|---|
| `GET` | `/allocation/{profile}/effective` | SSR loader |
| `GET` | `/allocation/{profile}/strategic` | SSR loader |
| `GET` | `/allocation/{profile}/tactical` | SSR loader |
| `GET` | `/analytics/correlation` | SSR loader |
| `GET` | `/analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` | Page |
| `GET` | `/analytics/strategy-drift/alerts` | risk-store.svelte.ts |
| `GET` | `/analytics/strategy-drift/{instrument_id}` | Page |
| `GET` | `/content` | SSR loader |
| `GET` | `/dd-reports/funds/{fund_id}` | SSR loader |
| `GET` | `/dd-reports/{report_id}` | SSR loader |
| `GET` | `/fact-sheets/model-portfolios/{portfolio_id}` | SSR loader |
| `GET` | `/instruments` | SSR loader |
| `GET` | `/instruments/{instrument_id}` | Page |
| `GET` | `/macro/regime` | SSR loader |
| `GET` | `/macro/reviews` | SSR loader |
| `GET` | `/macro/scores` | SSR loader |
| `GET` | `/macro/snapshot` | SSR loader |
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
| `GET` | `/risk/{profile}/cvar` | SSR loader, risk-store.svelte.ts |
| `GET` | `/risk/{profile}/cvar/history` | SSR loader, risk-store.svelte.ts |
| `GET` | `/screener/results` | SSR loader |
| `GET` | `/screener/runs` | SSR loader |
| `GET` | `/screener/runs/{run_id}` | Page |
| `GET` | `/wealth/exposure/metadata` | SSR loader |
| `PATCH` | `/macro/reviews/{review_id}/approve` | Page |
| `PATCH` | `/macro/reviews/{review_id}/reject` | Page |
| `POST` | `/analytics/backtest` | Page |
| `POST` | `/analytics/optimize` | Page |
| `POST` | `/analytics/optimize/pareto` | Page |
| `POST` | `/analytics/strategy-drift/scan` | Page |
| `POST` | `/content/{content_id}/approve` | Page |
| `POST` | `/dd-reports/{report_id}/regenerate` | Page |
| `POST` | `/fact-sheets/model-portfolios/{portfolio_id}` | Page |
| `POST` | `/instruments` | Page |
| `POST` | `/macro/reviews/generate` | Page |
| `POST` | `/model-portfolios` | Page |
| `POST` | `/portfolios/{profile}/rebalance` | Page |
| `POST` | `/portfolios/{profile}/rebalance/{event_id}/approve` | Page |
| `POST` | `/portfolios/{profile}/rebalance/{event_id}/execute` | Page |
| `PUT` | `/allocation/{profile}/strategic` | Page |
| `PUT` | `/allocation/{profile}/tactical` | Page |


---

## Endpoints Desconectados

### PRIORIDADE CRITICA — Write Operations sem Frontend

#### Shared/Core (91 endpoints)
> NOTA: A maioria destes são rotas do módulo transitional credit/modules/ai/ (pipeline, deep-review, extraction).
> Não implementar frontend contra estes — são paths legados ou de uso interno/admin.
> Ver docs/audit/backend-system-map-v2.md seção 5.2 para classificação definitiva.

| Metodo | Endpoint |
|---|---|
| `GET` | `/activity` |
| `GET` | `/alerts/daily` |
| `POST` | `/answer` |
| `GET` | `/api/data-room/file-link` |
| `GET` | `/api/data-room/list` |
| `GET` | `/api/data-room/pipeline/file-link` |
| `GET` | `/api/data-room/pipeline/list` |
| `GET` | `/api/data-room/tree` |
| `POST` | `/api/data-room/upload` |
| `GET` | `/api/dataroom/browse` |
| `POST` | `/api/dataroom/documents` |
| `POST` | `/api/dataroom/documents/{document_id}/ingest` |
| `GET` | `/api/dataroom/search` |
| `GET` | `/api/v1/jobs/{job_id}/stream` |
| `GET` | `/branding` |
| `GET` | `/history` |
| `GET` | `/linker/links` |
| `GET` | `/linker/obligations/status` |
| `POST` | `/linker/run` |
| `GET` | `/managers/profile` |
| `GET` | `/obligations/register` |
| `GET` | `/pipeline/alerts` |
| `GET` | `/pipeline/deals` |
| `POST` | `/pipeline/deals` |
| `POST` | `/pipeline/deals/qualification/run` |
| `POST` | `/pipeline/deals/reset-all-stuck` |
| `GET` | `/pipeline/deals/{deal_id}` |
| `POST` | `/pipeline/deals/{deal_id}/approve` |
| `POST` | `/pipeline/deals/{deal_id}/bootstrap` |
| `PATCH` | `/pipeline/deals/{deal_id}/context` |
| `GET` | `/pipeline/deals/{deal_id}/critical-gaps` |
| `POST` | `/pipeline/deals/{deal_id}/decisions` |
| `GET` | `/pipeline/deals/{deal_id}/deep-review-status` |
| `POST` | `/pipeline/deals/{deal_id}/deep-review-v4` |
| `POST` | `/pipeline/deals/{deal_id}/documents` |
| `GET` | `/pipeline/deals/{deal_id}/events` |
| `GET` | `/pipeline/deals/{deal_id}/evidence-governance` |
| `GET` | `/pipeline/deals/{deal_id}/evidence-pack` |
| `GET` | `/pipeline/deals/{deal_id}/im-draft` |
| `GET` | `/pipeline/deals/{deal_id}/im-pdf` |
| `GET` | `/pipeline/deals/{deal_id}/im-pdf/download` |
| `POST` | `/pipeline/deals/{deal_id}/im-pdf/rebuild` |
| `GET` | `/pipeline/deals/{deal_id}/memo-chapters` |
| `GET` | `/pipeline/deals/{deal_id}/memo-chapters/versions` |
| `POST` | `/pipeline/deals/{deal_id}/memo-chapters/{chapter_number}/regenerate` |
| `GET` | `/pipeline/deals/{deal_id}/pipeline-memo-pdf` |
| `POST` | `/pipeline/deals/{deal_id}/reanalyze` |
| `POST` | `/pipeline/deals/{deal_id}/reset-status` |
| `PATCH` | `/pipeline/deals/{deal_id}/stage` |
| `GET` | `/pipeline/deals/{deal_id}/underwriting-artifact` |
| `GET` | `/pipeline/deals/{deal_id}/underwriting-artifact/history` |
| `POST` | `/pipeline/deep-review-v4` |
| `POST` | `/pipeline/deep-review/evaluate` |
| `POST` | `/pipeline/deep-review/validate-sample` |
| `GET` | `/pipeline/extract/jobs` |
| `POST` | `/pipeline/extract/run` |
| `GET` | `/pipeline/extract/sources` |
| `GET` | `/pipeline/extract/status/{job_id}` |
| `POST` | `/pipeline/fact-sheet/generate` |
| `GET` | `/pipeline/fact-sheet/pdf` |
| `POST` | `/pipeline/ingest` |
| `POST` | `/pipeline/ingest/full` |
| `GET` | `/pipeline/ingest/jobs/latest` |
| `GET` | `/pipeline/ingest/jobs/{job_id}` |
| `POST` | `/pipeline/marketing-presentation/generate` |
| `GET` | `/pipeline/marketing-presentation/pdf` |
| `GET` | `/portfolio/alerts` |
| `POST` | `/portfolio/deep-review` |
| `POST` | `/portfolio/ingest` |
| `GET` | `/portfolio/investments` |
| `GET` | `/portfolio/investments/{investment_id}` |


#### Credit — Other (25 endpoints)

| Metodo | Endpoint |
|---|---|
| `DELETE` | `/admin/configs/{vertical}/{config_type}` |
| `GET` | `/admin/configs/{vertical}/{config_type}` |
| `PUT` | `/admin/configs/{vertical}/{config_type}` |

#### Admin — Config Management (4 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `DELETE` | `/admin/configs/{vertical}/{config_type}` | sem botao de delete no ConfigEditor |
| `GET` | `/admin/configs/{vertical}/{config_type}` | sem leitura individual de config |
| `PUT` | `/admin/configs/{vertical}/{config_type}` | ConfigEditor valida mas nao salva override |
| `GET` | `/admin/configs/{vertical}/{config_type}/diff` | ConfigDiffViewer existe mas diff nao exibido |

#### Admin — Prompt Versioning (5 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/admin/prompts/{vertical}/{name}` | sem leitura individual de prompt |
| `PUT` | `/admin/prompts/{vertical}/{name}` | PromptEditor nao salva |
| `POST` | `/admin/prompts/{vertical}/{name}/preview` | sem preview no editor |
| `POST` | `/admin/prompts/{vertical}/{name}/validate` | sem validacao no editor |
| `GET` | `/admin/prompts/{vertical}/{name}/versions` | sem historico de versoes |

#### Admin — Tenant Management (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/admin/tenants` | sem form de criacao de tenant |
| `POST` | `/admin/tenants/{org_id}/assets` | sem upload de asset de branding |

#### Admin — Other (3 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `GET` | `/admin/audit` | sem pagina de audit trail no admin |
| `GET` | `/admin/health/workers/logs` | sem log feed em tempo real |
| `GET` | `/assets/tenant/{org_slug}/{asset_type}` | serve assets de branding mas sem consumer explicito |

#### Credit — Deal Lifecycle (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/funds/{fund_id}/deals` | sem form de criacao de deal |
| `POST` | `/funds/{fund_id}/deals/{deal_id}/ic-memo` | sem trigger de geracao de IC memo |

#### Credit — Document Review Actions (2 endpoints)

| Metodo | Endpoint | Impacto |
|---|---|---|
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/checklist/{item_id}/check` | checklist nao interativo |
| `POST` | `/funds/{fund_id}/document-reviews/{review_id}/checklist/{item_id}/uncheck` | checklist nao interativo |

#### Credit — Dashboard FRED/Macro (4 endpoints)

| Metodo | Endpoint |
|---|---|
| `GET` | `/dashboard/fred-search` |
| `GET` | `/dashboard/macro-fred-multi` |
| `GET` | `/dashboard/macro-fred-series` |
| `GET` | `/dashboard/macro-history` |

#### Credit — Portfolio Management (2 endpoints)

| Metodo | Endpoint |
|---|---|
| `GET` | `/funds/{fund_id}/assets/{asset_id}/fund-investment` |
| `POST` | `/funds/{fund_id}/assets/{asset_id}/fund-investment` |

#### Wealth — Content Generation (4 endpoints)

| Metodo | Endpoint |
|---|---|
| `POST` | `/content/flash-reports` |
| `POST` | `/content/outlooks` |
| `POST` | `/content/spotlights` |
| `GET` | `/content/{content_id}/download` |

#### Wealth — DD Reports Actions (2 endpoints)

| Metodo | Endpoint |
|---|---|
| `POST` | `/dd-reports/funds/{fund_id}` |
| `GET` | `/dd-reports/{report_id}/stream` |

#### Wealth — Model Portfolio Actions (3 endpoints)

| Metodo | Endpoint |
|---|---|
| `POST` | `/model-portfolios/{portfolio_id}/backtest` |
| `POST` | `/model-portfolios/{portfolio_id}/construct` |
| `POST` | `/model-portfolios/{portfolio_id}/stress` |

#### Wealth — Screener Detail (2 endpoints)

| Metodo | Endpoint |
|---|---|
| `GET` | `/screener/results/{instrument_id}` |
| `POST` | `/screener/run` |

#### Wealth — Instruments (2 endpoints)

| Metodo | Endpoint |
|---|---|
| `POST` | `/instruments/import/csv` |
| `POST` | `/instruments/import/yahoo` |

#### Wealth — Analytics (2 endpoints)

| Metodo | Endpoint |
|---|---|
| `GET` | `/analytics/backtest/{run_id}` |
| `GET` | `/analytics/correlation-regime/{profile}` |

#### Wealth — Attribution (1 endpoint)

| Metodo | Endpoint |
|---|---|
| `GET` | `/analytics/attribution/{profile}` |

#### Wealth — Fact Sheet Actions (2 endpoints)

| Metodo | Endpoint |
|---|---|
| `GET` | `/fact-sheets/dd-reports/{report_id}/download` |
| `GET` | `/fact-sheets/{fact_sheet_path}/download` |

#### Wealth — Portfolio Rebalancing (2 endpoints)

| Metodo | Endpoint |
|---|---|
| `GET` | `/portfolios/{profile}/rebalance` |
| `GET` | `/portfolios/{profile}/rebalance/{event_id}` |

#### Wealth — Risk SSE (1 endpoint)

| Metodo | Endpoint |
|---|---|
| `GET` | `/risk/stream` |

#### Wealth — Other (1 endpoint)

| Metodo | Endpoint |
|---|---|
| `GET` | `/wealth/exposure/matrix` |


---

## Phantom Calls (Frontend sem Backend)

### IMPORTANTE — Classificação dos 53 phantom calls

A maioria dos phantom calls é FALSO POSITIVO de metodologia:
- **36 Shared/Core**: quase todos são fixtures de testes (`/a`, `/b`, `/items`, etc. em `api-client.test.ts`)
  e constantes de auth (`/__session`, `/authorization`, `/x-dev-actor` em `auth.ts`). NÃO são chamadas de produção.
- **8 Credit**: vários são erros de interpolação de variável — o scanner capturou o nome da variável
  como path (`/domain`, `/page`, `/stage`, `/fund_id`, `/root_folder`). São bugs reais de código mas
  não endpoints inexistentes no backend.

### Phantom calls REAIS que requerem correção

| Frontend | Metodo | Path | Arquivo | Problema |
|---|---|---|---|---|
| Admin | `PUT` | `/admin/configs/{param}/{param}?org_id={param}` | `ConfigEditor.svelte:74` | URL com query param errado — deve ser path param |
| Admin | `DELETE` | `/admin/configs/{param}/{param}?org_id={param}` | `ConfigEditor.svelte:103` | Mesmo problema — `?org_id=` deve ser parte do path |
| Admin | `GET` | `/admin/configs/{param}` | `branding/+page.server.ts:8` | Endpoint errado para contexto de branding |
| Admin | `GET` | `/error` | `auth/sign-in/+page.svelte:7` | Rota de erro inexistente no backend |
| Credit | `POST` | `/funds/{param}/document-reviews/{param}/checklist/{param}/{param}` | `[reviewId]/+page.svelte:122` | Path malformado — falta `/check` ou `/uncheck` no final |
| Wealth | `GET` | `/analytics/attribution/funds/{param}/period` | `analytics/+page.svelte:323` | Path errado — endpoint real é `/analytics/attribution/{profile}` |
| Wealth | `POST` | `/api/screener/run` | `screener/+page.svelte:142` | Prefixo `/api/` incorreto — endpoint real é `/screener/run` |
| Wealth | `GET` | `/wealth/analytics/correlation-regime/{param}` | `analytics/+page.server.ts:13` | Prefixo `/wealth/` incorreto — endpoint real é `/analytics/correlation-regime/{profile}` |
| Wealth | `GET` | `/wealth/exposure/matrix?dimension=geographic&aggregation={param}` | `exposure/+page.server.ts:12` | Prefixo `/wealth/` incorreto — endpoint real é `/wealth/exposure/matrix` (verificar) |

### Phantom calls que são BUGS de variável não interpolada (Credit)

| Arquivo | Path capturado | Problema |
|---|---|---|
| `documents/+page.server.ts:9` | `/page` | Variável não interpolada |
| `documents/+page.server.ts:10` | `/root_folder` | Variável não interpolada |
| `documents/+page.server.ts:11` | `/domain` | Variável não interpolada |
| `documents/auditor/+page.server.ts:9` | `/page` | Variável não interpolada |
| `pipeline/+page.server.ts:9` | `/page` | Variável não interpolada |
| `pipeline/+page.server.ts:10` | `/stage` | Variável não interpolada |
| `investor/documents/+page.server.ts:9` | `/fund_id` | Variável não interpolada |
| `investor/report-packs/+page.server.ts:10` | `/fund_id` | Variável não interpolada |
| `investor/statements/+page.server.ts:9` | `/fund_id` | Variável não interpolada |
| `portfolio/+page.server.ts:11` | `/funds/{param}/assets` | Path de assets não existe — endpoint é via portfolio |
| `[dealId]/+page.server.ts:13` | `/funds/{param}/deals/{param}` | Provavelmente correto mas verificar se DealDetail está sendo usado |

### Phantom calls de testes e utilitários (ignorar para cobertura)

Todos os calls em `packages/ui/src/lib/utils/__tests__/api-client.test.ts` são fixtures de teste.
Calls em `auth.ts` (`/__session`, `/authorization`, `/x-dev-actor`) são rotas Clerk/auth internas.
`/netz-theme` em `theme.ts` e `/tab` em `PageTabs.svelte` são rotas de UI interna.
`/jobs/{param}` em `poller.svelte.ts` é um exemplo genérico no utilitário de polling.

---

## Metodologia

- Exploração automatizada de routers FastAPI (backend)
- Varredura de loaders, pages e componentes SvelteKit/Svelte (frontend)
- Rastreamento de chamadas `.get/.post/.put/.patch/.delete` e `fetch(...)`
- Verificação de prefixes e `include_router(...)` em arquivos Python
- A resolução de rotas usa heurísticas AST/regex — construções altamente dinâmicas podem subcontar
- Componentes associados são inferidos por arquivos consumidores, não por telemetria runtime
