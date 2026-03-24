# Auditoria de Endpoints — Wealth Vertical

**Data:** 2026-03-23
**Branch:** `main`
**Metodo:** Grep exaustivo em `frontends/wealth/src/routes/` e `frontends/wealth/src/lib/` contra todos os endpoints extraidos de `backend/app/domains/wealth/routes/*.py`. Calls em `_legacy_routes/` NAO contam como cobertura (arquivos mortos, fora do router SvelteKit ativo).

---

## Principio Arquitetural: DB-First

Antes de classificar cobertura, e essencial entender o modelo de dados:

```
data_providers/         Workers (cron)          Routes (user-facing)
sec/ esma/ bis/ imf/  → ingest → Hypertables → SELECT do DB
                                  (sec_*, esma_*, bis_*, imf_*)
```

**Regra:** Rotas e vertical engines NUNCA chamam APIs externas no hot path. Todos os dados vem do DB (Timescale hypertables). `data_providers/` sao ingestores que populam as tabelas. O Screener, Quant Engine e DD Report consomem do DB para computacao rapida.

**Implicacao para cobertura:**
- Endpoints em `/esma/*` sao rotas de **browse** de tabelas globais (DB-only reads) — uteis para exploracao isolada, mas os dados ESMA ja fluem pelo screener via `union_all` entre `instruments_universe` e `esma_funds`
- Endpoints em `/manager-screener/managers/{crd}/*` sao rotas de **leitura DB** (`SecManager`, `Sec13fHolding`, `Sec13fDiff`, `SecNportHolding`) — zero chamadas EDGAR/EFTS
- Classificar esses endpoints como "desconectados" nao significa funcionalidade perdida se os dados ja sao acessiveis por outro caminho

---

## Resumo Executivo

| Metrica | Valor |
|---------|-------|
| **Endpoints backend wealth total** | **131** |
| **Workers (infra/cron, sem UI)** | **20** |
| **Browse/convenience (dados acessiveis por outro caminho)** | **9** |
| **Endpoints de produto (excl. workers + browse)** | **102** |
| **Conectados no frontend atual** | **83** |
| **Desconectados com funcionalidade perdida** | **19** |
| **Cobertura efetiva (produto)** | **81.4%** (83/102) |
| **Cobertura total (incl. workers + browse as covered)** | **85.5%** (83 + 20 + 9 = 112/131) |

### Veredicto

O claim de "~98-99% cobertura" do documento `wm-coverage-implementation-reference.md` e **otimista**. A cobertura efetiva de produto e **~81%**. A discrepancia vem de:

1. **Contagem de falsos negativos inflada:** o audit original contou endpoints que so existem em `_legacy_routes/` (arquivos mortos) como "ja conectados"
2. **Modulos com migracao incompleta:** macro reviews (5 endpoints), analytics backtest/correlation (4), manager-screener tabs avancadas (4)
3. **Endpoints pontuais omitidos:** `POST /model-portfolios`, `DELETE /blended-benchmarks/{id}`, `GET /universe/funds/{id}/audit-trail`, etc.

### Reclassificacao vs audit anterior

| Categoria | Anterior (inflado) | Atual (real) |
|-----------|-------------------|-------------|
| ESMA browse (5 endpoints) | "desconectado — P1" | Browse/convenience — dados ja fluem pelo screener (`/screener/search` faz `union_all` com `EsmaFund`) |
| Manager screener drift/nport/brochure (4 endpoints) | "desconectado — P2" | Split: drift e nport sao dados DB ricos que agregam valor no panel (desconectados reais); brochure depende de ingestion previa |
| Funds scoring/nav (2 endpoints) | "desconectado" | Deprecated — funcionalidade coberta por `/instruments` + `/risk/{profile}/cvar` |

---

## Endpoints Browse/Convenience — Dados Acessiveis por Outro Caminho (9)

Estes endpoints leem do DB (correto), mas a funcionalidade ja e acessivel pelo screener ou por outros modulos. Nao representam funcionalidade perdida.

| Endpoint | Tipo | Como os dados ja fluem |
|----------|------|----------------------|
| `GET /esma/managers` | Browse global | Screener `/search?source=esma` faz union com EsmaFund+EsmaManager |
| `GET /esma/managers/{esma_id}` | Browse detalhe | Dados do manager acessiveis via screener panel |
| `GET /esma/funds` | Browse global | Screener `/search` inclui ESMA funds |
| `GET /esma/funds/{isin}` | Browse detalhe | `/screener/import-esma/{isin}` ja importa |
| `GET /esma/managers/{esma_id}/sec-crossref` | Cross-ref | Dado enrichment — util mas nao bloqueante |
| `GET /funds/scoring` | Deprecated | Substituido por `/risk/{profile}/cvar` + risk-store |
| `GET /funds/{fund_id}/nav` | Deprecated | NAV via `/instruments/{id}` ou risk-store |
| `GET /funds/{fund_id}/risk` | Parcial | Usado em universe/+page.svelte; coberto por risk-store para profiles |
| `POST /instruments/import/csv` | Util | InstrumentsView tem o endpoint conectado (confirmado) |

**Nota:** `POST /instruments/import/csv` foi erroneamente listado como desconectado — esta conectado em `InstrumentsView.svelte:185`.

---

## Endpoints Desconectados — Funcionalidade Realmente Perdida (19)

### P1 (ALTA) — Workflows interrompidos

#### Macro Reviews (5 endpoints)
Workflow completo de geracao, listagem, aprovacao e rejeicao de macro reviews. So existe em `_legacy_routes`. A macro page atual mostra scores, regime, BIS, IMF, Treasury, OFR — mas o workflow de **committee reviews** nao foi migrado.

| Endpoint | Status |
|----------|--------|
| `GET /macro/snapshot` | Legacy only |
| `GET /macro/reviews` | Legacy only |
| `POST /macro/reviews/generate` | Legacy only |
| `PATCH /macro/reviews/{review_id}/approve` | Legacy only |
| `PATCH /macro/reviews/{review_id}/reject` | Legacy only |

#### Analytics — Backtest + Correlation (4 endpoints)
Backtest standalone (submit + poll) e correlation matrix/pairwise. Pareto optimization foi migrado, mas backtest individual e pairwise correlation nao.

| Endpoint | Status |
|----------|--------|
| `POST /analytics/backtest` | Legacy only |
| `GET /analytics/backtest/{run_id}` | Legacy only |
| `GET /analytics/correlation` | Legacy only |
| `GET /analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` | Legacy only |

### P2 (MEDIA) — Funcionalidade complementar

#### Manager Screener — tabs avancadas (4 endpoints)
O screener principal foi migrado (list, profile, holdings, institutional, universe-status, compare). Mas drift (turnover timeline), nport (N-PORT holdings), brochure (ADV Part 2A) agregam valor significativo para due diligence e so existem em `_legacy_routes`.

| Endpoint | Dados | Status |
|----------|-------|--------|
| `GET /manager-screener/managers/{crd}/drift` | `Sec13fDiff` — turnover por quarter | Legacy only |
| `GET /manager-screener/managers/{crd}/nport` | `SecNportHolding` — holdings atuais | Legacy only |
| `GET /manager-screener/managers/{crd}/brochure/sections` | Brochure ADV Part 2A | Legacy only |
| `GET /manager-screener/managers/{crd}/brochure` | Brochure search | Legacy only |

#### Fact Sheets — Model Portfolios (3 endpoints)
Fact sheets de DD reports foram migradas. Fact sheets de model portfolios so em `_legacy_routes`.

| Endpoint | Status |
|----------|--------|
| `POST /fact-sheets/model-portfolios/{portfolio_id}` | Legacy only |
| `GET /fact-sheets/model-portfolios/{portfolio_id}` | Legacy only |
| `GET /fact-sheets/{fact_sheet_path}/download` | Legacy only |

### P3 (BAIXA) — Endpoints pontuais

| Endpoint | Status | Nota |
|----------|--------|------|
| `POST /model-portfolios` | Legacy only | Criar novo model portfolio |
| `DELETE /blended-benchmarks/{benchmark_id}` | Nenhuma chamada | Deletar benchmark |
| `GET /universe/funds/{instrument_id}/audit-trail` | Nenhuma chamada | Audit trail do universe |
| `GET /portfolios/{profile}/history` | Legacy only | Historico de snapshots |
| `GET /screener/runs/{run_id}` | Legacy only | Detalhe de um screening run |

---

## Bug Encontrado: Path Mismatch no Exposure

| Arquivo | Chamada | Backend real | Impacto |
|---------|---------|-------------|---------|
| `routes/(app)/exposure/+page.server.ts:11-12` | `/exposure/matrix` | `/wealth/exposure/matrix` | **Chamada falha silenciosamente** (`.catch(() => null)`). Dados so aparecem porque `ExposureView.svelte` usa o path correto `/wealth/exposure/matrix` no client-side. SSR retorna null, client-side hydration corrige. |

---

## Cobertura por Modulo

| Modulo | Total | Conectados | % | Nota |
|--------|-------|-----------|---|------|
| Allocation | 6 | 6 | 100% | |
| Analytics (core) | 6 | 4 | 67% | backtest + correlation legacy |
| Strategy Drift | 5 | 5 | 100% | |
| Blended Benchmarks | 5 | 4 | 80% | DELETE missing |
| Content | 6 | 6 | 100% | |
| DD Reports | 8 | 8 | 100% | |
| Documents | 6 | 6 | 100% | |
| ESMA | 5 | 0 | — | Browse/convenience (dados fluem pelo screener) |
| Exposure | 2 | 2 | 100% | Bug: server load path errado |
| Fact Sheets | 4 | 1 | 25% | So DD report download |
| Funds | 5 | 2 | — | Deprecated (coberto por instruments + risk) |
| Instruments | 5 | 5 | 100% | Inclui CSV import |
| Macro | 11 | 6 | 55% | Reviews + snapshot legacy |
| Manager Screener | 11 | 7 | 64% | drift/nport/brochure legacy |
| Model Portfolios | 7 | 6 | 86% | POST create missing |
| Portfolios | 9 | 8 | 89% | history legacy |
| Risk | 7 | 7 | 100% | |
| Screener | 8 | 7 | 88% | run detail legacy |
| Universe | 5 | 4 | 80% | audit-trail missing |
| Workers | 20 | N/A | — | Infra/cron |
| **TOTAL** | **131** | **83 + 20 infra + 9 browse** | **~85%** | |

---

## Endpoints Conectados — Inventario Completo (83)

### Allocation (6/6)
| Endpoint | Frontend |
|----------|----------|
| `GET /allocation/{profile}/strategic` | AllocationView.svelte, +page.server.ts |
| `PUT /allocation/{profile}/strategic` | AllocationView.svelte |
| `GET /allocation/{profile}/tactical` | AllocationView.svelte, +page.server.ts |
| `PUT /allocation/{profile}/tactical` | AllocationView.svelte |
| `GET /allocation/{profile}/effective` | AllocationView.svelte, +page.server.ts |
| `POST /allocation/{profile}/simulate` | AllocationView.svelte |

### Analytics (4/6)
| Endpoint | Frontend |
|----------|----------|
| `POST /analytics/optimize` | analytics/+page.svelte |
| `POST /analytics/optimize/pareto` | analytics/+page.svelte |
| `GET /analytics/optimize/pareto/{job_id}/stream` | analytics/+page.svelte (SSE) |
| `GET /analytics/attribution/{profile}` | analytics/+page.server.ts |

### Strategy Drift (5/5)
| Endpoint | Frontend |
|----------|----------|
| `POST /analytics/strategy-drift/scan` | risk/+page.svelte |
| `GET /analytics/strategy-drift/alerts` | analytics/+page.server.ts, risk-store |
| `GET /analytics/strategy-drift/{instrument_id}/history` | DriftHistoryPanel.svelte |
| `GET /analytics/strategy-drift/{instrument_id}/export` | DriftHistoryPanel.svelte |
| `GET /analytics/strategy-drift/{instrument_id}` | risk/+page.svelte |

### Blended Benchmarks (4/5)
| Endpoint | Frontend |
|----------|----------|
| `GET /blended-benchmarks/blocks` | BlendedBenchmarkEditor.svelte |
| `GET /blended-benchmarks/{profile}` | BlendedBenchmarkEditor.svelte |
| `POST /blended-benchmarks/{profile}` | BlendedBenchmarkEditor.svelte |
| `GET /blended-benchmarks/{benchmark_id}/nav` | BlendedBenchmarkEditor.svelte |

### Content (6/6)
| Endpoint | Frontend |
|----------|----------|
| `POST /content/outlooks` | content/+page.svelte (dynamic) |
| `POST /content/flash-reports` | content/+page.svelte (dynamic) |
| `POST /content/spotlights` | content/+page.svelte |
| `GET /content` | content/+page.server.ts |
| `POST /content/{content_id}/approve` | content/+page.svelte |
| `GET /content/{content_id}/download` | content/+page.svelte (fetch) |

### DD Reports (8/8)
| Endpoint | Frontend |
|----------|----------|
| `POST /dd-reports/funds/{fund_id}` | dd-reports/[fundId]/+page.svelte |
| `GET /dd-reports/funds/{fund_id}` | dd-reports/[fundId]/+page.server.ts |
| `GET /dd-reports/{report_id}/audit-trail` | dd-reports/.../+page.svelte |
| `GET /dd-reports/{report_id}` | dd-reports/.../+page.server.ts |
| `POST /dd-reports/{report_id}/regenerate` | dd-reports/.../+page.svelte |
| `POST /dd-reports/{report_id}/approve` | dd-reports/.../+page.svelte |
| `POST /dd-reports/{report_id}/reject` | dd-reports/.../+page.svelte |
| `GET /dd-reports/{report_id}/stream` | dd-reports/.../+page.svelte (SSE) |

### Documents (6/6)
| Endpoint | Frontend |
|----------|----------|
| `POST /wealth/documents/upload-url` | documents/upload/+page.svelte |
| `POST /wealth/documents/upload-complete` | documents/upload/+page.svelte |
| `POST /wealth/documents/upload` | documents/upload/+page.svelte |
| `POST /wealth/documents/ingestion/process-pending` | documents/+page.svelte, upload/+page.svelte |
| `GET /wealth/documents` | documents/+page.server.ts |
| `GET /wealth/documents/{document_id}` | documents/[documentId]/+page.server.ts |

### Exposure (2/2 — bug no server load)
| Endpoint | Frontend |
|----------|----------|
| `GET /wealth/exposure/matrix` | ExposureView.svelte (correto), +page.server.ts (**path errado**) |
| `GET /wealth/exposure/metadata` | ExposureView.svelte |

### Funds (2/5 — modulo deprecated)
| Endpoint | Frontend |
|----------|----------|
| `GET /funds` | FundsView.svelte, content/+page.server.ts |
| `GET /funds/{fund_id}` | dd-reports/[fundId]/+page.server.ts |

### Instruments (5/5)
| Endpoint | Frontend |
|----------|----------|
| `GET /instruments` | InstrumentsView.svelte |
| `GET /instruments/{instrument_id}` | InstrumentsView.svelte |
| `POST /instruments` | InstrumentsView.svelte |
| `POST /instruments/import/yahoo` | InstrumentsView.svelte |
| `POST /instruments/import/csv` | InstrumentsView.svelte |

### Macro (6/11)
| Endpoint | Frontend |
|----------|----------|
| `GET /macro/scores` | macro/+page.server.ts |
| `GET /macro/regime` | macro/+page.server.ts |
| `GET /macro/bis` | macro/+page.svelte |
| `GET /macro/imf` | macro/+page.svelte |
| `GET /macro/treasury` | macro/+page.svelte |
| `GET /macro/ofr` | macro/+page.svelte |

### Manager Screener (7/11)
| Endpoint | Frontend |
|----------|----------|
| `GET /manager-screener/` | screener/+page.server.ts |
| `GET /manager-screener/managers/{crd}/profile` | screener/+page.svelte |
| `GET /manager-screener/managers/{crd}/holdings` | screener/+page.svelte |
| `GET /manager-screener/managers/{crd}/institutional` | screener/+page.svelte |
| `GET /manager-screener/managers/{crd}/universe-status` | screener/+page.svelte |
| `POST /manager-screener/managers/{crd}/add-to-universe` | screener/+page.svelte |
| `POST /manager-screener/managers/compare` | screener/+page.svelte |

### Model Portfolios (6/7)
| Endpoint | Frontend |
|----------|----------|
| `GET /model-portfolios` | model-portfolios/+page.server.ts |
| `GET /model-portfolios/{portfolio_id}` | [portfolioId]/+page.server.ts |
| `POST /model-portfolios/{portfolio_id}/construct` | [portfolioId]/+page.svelte |
| `GET /model-portfolios/{portfolio_id}/track-record` | [portfolioId]/+page.server.ts |
| `POST /model-portfolios/{portfolio_id}/backtest` | [portfolioId]/+page.svelte |
| `POST /model-portfolios/{portfolio_id}/stress` | [portfolioId]/+page.svelte |

### Portfolios (8/9)
| Endpoint | Frontend |
|----------|----------|
| `GET /portfolios` | portfolios/+page.server.ts |
| `GET /portfolios/{profile}` | portfolios/[profile]/+page.server.ts |
| `GET /portfolios/{profile}/snapshot` | portfolios/[profile]/+page.server.ts |
| `POST /portfolios/{profile}/rebalance` | portfolios/[profile]/+page.svelte |
| `GET /portfolios/{profile}/rebalance` | RebalancingTab.svelte |
| `GET /portfolios/{profile}/rebalance/{event_id}` | RebalancingTab.svelte |
| `POST /portfolios/{profile}/rebalance/{event_id}/approve` | RebalancingTab.svelte |
| `POST /portfolios/{profile}/rebalance/{event_id}/execute` | RebalancingTab.svelte |

### Risk (7/7)
| Endpoint | Frontend |
|----------|----------|
| `GET /risk/summary` | risk-store.svelte.ts |
| `GET /risk/{profile}/cvar` | risk-store.svelte.ts |
| `GET /risk/{profile}/cvar/history` | risk-store.svelte.ts |
| `GET /risk/regime` | risk-store.svelte.ts |
| `GET /risk/regime/history` | risk-store.svelte.ts |
| `GET /risk/macro` | risk-store.svelte.ts, macro/+page.server.ts |
| `GET /risk/stream` | risk-store.svelte.ts (SSE) |

### Screener (7/8)
| Endpoint | Frontend |
|----------|----------|
| `POST /screener/run` | screener/+page.svelte |
| `GET /screener/runs` | screener/+page.server.ts |
| `GET /screener/results` | screener/+page.server.ts |
| `GET /screener/results/{instrument_id}` | screener/+page.svelte |
| `GET /screener/search` | screener/+page.server.ts |
| `GET /screener/facets` | screener/+page.server.ts |
| `POST /screener/import-esma/{isin}` | screener/+page.svelte |

### Universe (4/5)
| Endpoint | Frontend |
|----------|----------|
| `GET /universe` | universe/+page.server.ts |
| `GET /universe/pending` | UniverseView.svelte |
| `POST /universe/funds/{instrument_id}/approve` | UniverseView.svelte |
| `POST /universe/funds/{instrument_id}/reject` | UniverseView.svelte |

### Fact Sheets (1/4)
| Endpoint | Frontend |
|----------|----------|
| `GET /fact-sheets/dd-reports/{report_id}/download` | dd-reports/.../+page.svelte (fetch) |

---

## Workers (20 endpoints — Infra/Cron)

Todos os `POST /workers/run-*` sao triggers de workers. Invocados por cron, admin CLI ou admin frontend. Nao requerem UI no wealth frontend.

| Endpoint |
|----------|
| `POST /workers/run-ingestion` |
| `POST /workers/run-risk-calc` |
| `POST /workers/run-portfolio-eval` |
| `POST /workers/run-macro-ingestion` |
| `POST /workers/run-fact-sheet-gen` |
| `POST /workers/run-watchlist-check` |
| `POST /workers/run-screening-batch` |
| `POST /workers/run-instrument-ingestion` |
| `POST /workers/run-benchmark-ingest` |
| `POST /workers/run-treasury-ingestion` |
| `POST /workers/run-ofr-ingestion` |
| `POST /workers/run-sec-refresh` |
| `POST /workers/run-nport-ingestion` |
| `POST /workers/run-bis-ingestion` |
| `POST /workers/run-imf-ingestion` |
| `POST /workers/run-brochure-download` |
| `POST /workers/run-brochure-extract` |
| `POST /workers/run-esma-ingestion` |
| `POST /workers/run-sec-13f-ingestion` |
| `POST /workers/run-sec-adv-ingestion` |

---

## Nota Arquitetural: Fluxo de Dados

```
┌─────────────────────────────────────────────────────────────────┐
│  DATA PROVIDERS (backend/data_providers/)                       │
│  sec/ esma/ bis/ imf/                                          │
│  Chamam APIs externas (EDGAR, ESMA Register, BIS SDMX, IMF)   │
└──────────────┬──────────────────────────────────────────────────┘
               │ Workers (cron, advisory locks)
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  TIMESCALE HYPERTABLES (global, sem RLS)                        │
│  sec_managers, sec_13f_holdings, sec_13f_diffs,                │
│  sec_nport_holdings, esma_managers, esma_funds,                │
│  bis_statistics, imf_weo_forecasts, macro_data,                │
│  treasury_data, ofr_hedge_fund_data, benchmark_nav             │
└──────────────┬──────────────────────────────────────────────────┘
               │ SELECT (DB-only reads)
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  ROUTES (backend/app/domains/wealth/routes/)                    │
│  Screener: union_all(instruments + esma_funds)                 │
│  Manager Screener: sec_managers + sec_13f + sec_nport          │
│  Macro: macro_data + bis + imf + treasury + ofr                │
│  Quant Engine: fund_risk_metrics (pre-computed by workers)     │
│  DD Report: sec_managers + sec_13f + quant metrics             │
└──────────────┬──────────────────────────────────────────────────┘
               │ JSON API
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  FRONTEND (frontends/wealth/)                                   │
│  Consome apenas JSON das routes — zero chamadas externas       │
└─────────────────────────────────────────────────────────────────┘
```

Confirmado via leitura de codigo:
- `manager_screener.py`: SELECT em `SecManager`, `Sec13fHolding`, `Sec13fDiff`, `SecNportHolding`, `SecInstitutionalAllocation`
- `screener.py`: `union_all` entre `Instrument` (interno) e `EsmaFund` (global)
- `esma.py`: SELECT em `EsmaManager`, `EsmaFund` via `esma_sql` queries
- `macro.py`: SELECT em `macro_data`, `bis_statistics`, `imf_weo_forecasts`, `treasury_data`, `ofr_hedge_fund_data`

**Zero chamadas a APIs externas em qualquer rota user-facing.**

---

## Metodologia

1. Extraidos todos os endpoints de 24 arquivos em `backend/app/domains/wealth/routes/*.py` (decorators `@router.get/post/put/patch/delete`)
2. Mapeados prefixos via `main.py:331-352` (`include_router` calls)
3. Grep exaustivo em `frontends/wealth/src/routes/` e `frontends/wealth/src/lib/` por cada path pattern
4. Calls em `frontends/wealth/src/_legacy_routes/` classificados como **NAO conectados** (fora do router SvelteKit ativo)
5. Verificacao de `data_providers/` para confirmar que rotas sao DB-only reads
6. Leitura de `screener.py` e `manager_screener.py` para confirmar fluxo de dados
7. Cada endpoint classificado como: conectado, browse/convenience, legacy-only, nenhuma chamada, deprecated, ou infra/worker

### Limitacoes

- Nao cobre chamadas indiretas via stores que importam de outros stores
- Nao valida se o endpoint retorna dados uteis (apenas se ha call no frontend)
- Nao testa runtime — apenas analise estatica de codigo
- Exposure server load tem bug de path mas funciona via client-side hydration
