# Prompt: Endpoint Coverage Audit — Wealth Vertical (2026-04-01)

## Contexto

Este prompt produz uma auditoria de cobertura frontend↔backend para o vertical Wealth do Netz Analysis Engine.

**Problema:** O backend do vertical Wealth cresceu significativamente desde o último audit
(2026-03-23). Novos route files foram adicionados (`long_form_reports.py`, `monthly_report.py`,
`rebalancing.py`, `attribution.py`, `portfolio_views.py`, `sec_funds.py`, `sec_analysis.py`,
`entity_analytics.py`) e os existentes (`screener.py`, `model_portfolios.py`, `macro.py`)
receberam muitos endpoints novos. A cobertura real atual é desconhecida.

**Frontend wealth:** `D:\Projetos\netz-analysis-engine\frontends\wealth\src`
**Backend wealth routes:** `D:\Projetos\netz-analysis-engine\backend\app\domains\wealth\routes`

**Padrão de chamada API no frontend:**
```typescript
// Em +page.server.ts (SSR):
const api = createServerApiClient(token);
api.get<T>("/caminho")
api.post<T>("/caminho", body)

// Em +page.svelte ou componentes (client-side):
api.get<T>("/caminho")          // via apiClient singleton
api.post<T>("/caminho", body)
```
O prefixo base `/api/v1` é adicionado pelo cliente — os paths nos arquivos
frontend NÃO incluem `/api/v1`.

---

## Tarefa

Realizar uma auditoria completa de cobertura de endpoints do vertical Wealth, produzindo:

1. Lista de todos os endpoints backend (método, path completo, arquivo)
2. Lista de todos os endpoints frontend (método, path normalizado, arquivo)
3. Tabela cruzada com status: `CONNECTED`, `DISCONNECTED`, `INFRA`
4. Resumo executivo com contagens e % cobertura
5. Recomendações priorizadas P1/P2/P3 agrupadas por feature area

---

## Fase 1 — Extrair endpoints do backend

### 1.1 Identificar prefixes dos routers

Leia em ordem até encontrar:
```
D:\Projetos\netz-analysis-engine\backend\app\domains\wealth\router.py
D:\Projetos\netz-analysis-engine\backend\app\main.py
D:\Projetos\netz-analysis-engine\backend\app\api\v1\router.py
```

Busque `include_router(` para mapear `{router_module} → prefix`.

Como fallback, leia o topo de cada arquivo de route — `APIRouter(prefix=...)` revela o prefix.

### 1.2 Extrair rotas de cada arquivo

Leia cada arquivo em `D:\Projetos\netz-analysis-engine\backend\app\domains\wealth\routes\`
e extraia todas as ocorrências de `@router.(get|post|put|patch|delete)("...")`.

Lista completa:
```
allocation.py, analytics.py, attribution.py, blended_benchmark.py,
content.py, correlation_regime.py, dd_reports.py, documents.py,
entity_analytics.py, exposure.py, fact_sheets.py, funds.py,
instruments.py, long_form_reports.py, macro.py, manager_screener.py,
model_portfolios.py, monthly_report.py, portfolios.py, portfolio_views.py,
rebalancing.py, risk.py, screener.py, search.py, sec_analysis.py,
sec_funds.py, strategy_drift.py, universe.py, workers.py
```

Construa path completo: `{prefix_do_router}{path_da_rota}`.

**IMPORTANTE:** Todos os endpoints de `workers.py` são INFRA — não requerem UI.

---

## Fase 2 — Extrair chamadas API do frontend

### 2.1 Arquivos a escanear

**Server loaders (SSR):**
- `frontends\wealth\src\routes\(app)\**\+page.server.ts`
- `frontends\wealth\src\routes\(app)\**\+layout.server.ts`

**Client-side:**
- `frontends\wealth\src\routes\(app)\**\+page.svelte`
- `frontends\wealth\src\lib\components\**\*.svelte`
- `frontends\wealth\src\lib\stores\*.svelte.ts`
- `frontends\wealth\src\lib\stores\*.ts`

Use `start_search` com pattern `api\.(get|post|put|patch|delete)\(` em cada diretório.
Se a busca não retornar resultados, tente pattern alternativo `\.get\(|\.post\(|\.put\(|\.patch\(|\.delete\(`.

### 2.2 Normalização de paths

- Template strings: `` `/funds/${fundId}/nav` `` → `/funds/{fund_id}/nav`
- Path params variáveis → `{param_name}` sem o `$` e sem backticks
- Query strings: ignorar no matching (`?limit=20` etc.)

### 2.3 Output desta fase

Tabela: `Method | Normalized Path | File`

---

## Fase 3 — Cross-reference

Para cada endpoint backend, determine:

| Status | Critério |
|--------|---------|
| `CONNECTED` | Existe chamada frontend com método + path correspondente |
| `INFRA` | Em `workers.py` ou endpoint de infraestrutura interna |
| `DISCONNECTED` | Não encontrado no frontend |

**Regras de matching:**
- Case-insensitive
- `/funds/{fund_id}` ↔ `` `/funds/${fundId}` `` ↔ `/funds/:id` → equivalentes
- Endpoint CONNECTED via SSR conta como conectado
- Em dúvida → reportar como `UNCERTAIN` em seção separada

**Classificação INFRA automática (não contar como gap):**
- Todo endpoint de `workers.py`
- `POST /internal/workers/dispatch`
- `GET /health`, `GET /api/v1`

---

## Fase 4 — Output do relatório

### 4.1 Resumo executivo (no topo do arquivo)

```
Data: 2026-04-01
Total endpoints backend wealth (excl. infra/workers): N
Conectados: X (Y%)
Desconectados: Z (W%)
Infra/workers (excluídos): K
Phantom calls (frontend → backend inexistente): M
```

### 4.2 Tabela CONNECTED

`| Method | Path | Backend File | Frontend File(s) |`

### 4.3 Tabela DISCONNECTED — agrupada com prioridade

**P1** = Ação mutativa sem UI (trigger de relatório, aprovação, ação que cria/altera dados)
**P2** = Funcionalidade de valor que desbloqueia capacidade implementada (analytics avançados, downloads, SSE streams)
**P3** = Nice-to-have / residual (exports secundários, audit trails, metadata)

Formato por grupo:
```
### {Feature Area} — P{1|2|3}

| Method | Path | Backend File | Impacto |
```

Feature areas esperadas (não limitadas a estas):
- Model Portfolios (construction-advice, activate, overlap, views, stress-test, long-form, monthly)
- DD Reports (trigger POST, stream GET, audit-trail GET)
- Fact Sheets (generate POST, download GET)
- Content (download GET)
- Entity Analytics (entity/{id}, active-share, monte-carlo, peer-group, risk-budget, factor-analysis)
- Screener Catalog (catalog, catalog/facets, catalog/{id}/detail)
- Screener Securities (securities, securities/facets)
- SEC Funds (holdings, style-history, holdings-history, peer-analysis, reverse-holdings, prospectus)
- Macro (reviews/{id}/download)
- Risk (summary, stream SSE)
- Instruments (PATCH /{id}, PATCH /{id}/org)
- Blended Benchmarks (GET blocks, GET profile, POST profile, DELETE benchmark)
- Allocation (POST simulate)
- Analytics advanced (rolling-correlation, risk-budget, factor-analysis, pareto stream)
- Strategy Drift (history, export)
- Universe (audit-trail)

### 4.4 Phantom calls

Chamadas frontend sem endpoint backend correspondente (404 em produção):
`| Method | Path | Frontend File | Nota |`

### 4.5 Top 10 por valor de negócio

Os 10 endpoints desconectados mais impactantes com:
- Complexidade de wiring: `Low` (loader SSR simples) / `Medium` (componente + ação) / `High` (SSE/stream/novo componente)
- Impacto em 1 linha

---

## Fase 5 — Salvar

Salve o relatório completo em:
```
D:\Projetos\netz-analysis-engine\docs\audit\endpoint-coverage-audit-2026-04-01.md
```

---

## Regras críticas

- **Não modificar nenhum arquivo de código** (backend ou frontend)
- Não criar endpoints, páginas ou componentes novos
- Não sugerir implementações — apenas auditar e documentar
- Se arquivo não existir, reportar o gap e continuar

---

## Definition of Done

- [ ] Todos os 29 arquivos de route do backend wealth escaneados
- [ ] Prefix de cada router identificado
- [ ] Todos os `+page.server.ts` e `+page.svelte` em `routes/(app)/**` escaneados
- [ ] Todos os componentes em `lib/components/**/*.svelte` escaneados
- [ ] Todos os stores em `lib/stores/` escaneados
- [ ] Tabela DISCONNECTED agrupada por feature area com prioridade
- [ ] Phantom calls identificados
- [ ] Arquivo salvo em `docs/audit/endpoint-coverage-audit-2026-04-01.md`
- [ ] Resumo executivo com % de cobertura

---

## Referência

Audit anterior (2026-03-23) em:
`D:\Projetos\netz-analysis-engine\docs\audit\endpoint_coverage_audit.md`

Reportou 93 endpoints wealth, 62 conectados (67%). Desde então ~25-30 endpoints novos
foram adicionados ao backend (long_form, monthly_report, model_portfolios expanded,
sec_funds, entity_analytics, screener catalog/securities). A cobertura em % provavelmente
caiu apesar do progresso em Macro e Content.
