# Netz Analysis Engine — Deploy & Validation Checklist

**Railway Pro + Timescale Cloud**

---

## Fase 0 — Pré-Deploy (Local)

### 0.1 Import Linter

```bash
lint-imports
```

Confirmar zero violações. Especialmente:

- `long_form_report/` não importa de `dd_report/`
- `quant_engine/` não importa de `app/domains/`
- Verticais não importam entre si
- Nenhum consumer de NAV importa `NavTimeseries` ou `ModelPortfolioNav` diretamente — apenas via `nav_reader`

### 0.2 Suite completa

```bash
make check
```

Esperado: **2858 passed, 0 failed** (com DB local). Sem DB: 2858 - 56 failures de `asyncpg.InvalidPasswordError` — aceitável.

### 0.3 Migrations pendentes

```bash
alembic current
alembic heads
# Devem coincidir
alembic upgrade head  # se divergirem
```

> ⚠️ Migration crítica: `0055_model_portfolio_nav.py` usa autocommit — verificar que não está dentro de transaction block.

---

## Fase 1 — Variáveis de Ambiente no Railway

| Variável | Descrição |
|----------|-----------|
| `DATABASE_URL` | Timescale Cloud — pooler (porta 6543) |
| `DIRECT_DATABASE_URL` | Timescale Cloud — direct (porta 5432, para Alembic) |
| `REDIS_URL` | Upstash |
| `CLERK_SECRET_KEY` | Clerk auth |
| `CLERK_PUBLISHABLE_KEY` | Clerk auth |
| `OPENAI_API_KEY` | LLM + embeddings |
| `MISTRAL_API_KEY` | OCR |
| `R2_ACCOUNT_ID` | Cloudflare R2 |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 |
| `R2_BUCKET_NAME` | Cloudflare R2 |
| `FRED_API_KEY` | FRED API (`macro_ingestion` worker) |
| `EDGAR_IDENTITY` | SEC EDGAR user-agent (e.g. `"Company Name email@example.com"`) |
| `ENVIRONMENT` | `production` |

> ⚠️ Alembic usa `DIRECT_DATABASE_URL` (porta 5432). `create_hypertable()` não funciona via PgBouncer.

---

## Fase 2 — Startup do Backend

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 2.1 Health check

```bash
GET /health
# Esperado: {"status": "ok", "db": "ok", "redis": "ok"}

GET /api/health
# Mesmo — dual mount para Cloudflare gateway compat
```

### 2.2 Routers das sprints presentes

```bash
GET /api/v1/openapi.json
```

Confirmar:

- `GET /api/v1/analytics/entity/{entity_id}` — Sprint 4
- `POST /api/v1/wealth/rebalancing/proposals/{id}/apply` — Sprint 5
- `POST /api/v1/wealth/reporting/model-portfolios/{id}/long-form-report` — Sprint 6
- `GET /api/v1/wealth/reporting/model-portfolios/{id}/long-form-report/stream/{job_id}` — Sprint 6

### 2.3 Semaphore do LongFormReport

O endpoint de long-form-report tem `asyncio.Semaphore(2)` — máximo 2 gerações simultâneas. Terceira requisição deve retornar **429 Too Many Requests**. Verificar na sequência do smoke test.

---

## Fase 3 — Migrations no Timescale Cloud

```bash
alembic upgrade head  # via DIRECT_DATABASE_URL
```

### 3.1 Hypertables

```sql
SELECT hypertable_name, num_dimensions, compression_enabled
FROM timescaledb_information.hypertables
ORDER BY hypertable_name;
```

Esperado na lista:

| Hypertable | Escopo | Chunk |
|------------|--------|-------|
| `macro_data` | global | 1 mês |
| `benchmark_nav` | global | 1 mês |
| `nav_timeseries` | tenant-scoped | — |
| `fund_risk_metrics` | tenant-scoped | — |
| `model_portfolio_nav` | tenant-scoped | 1 mês, compress 3 meses (nova — Sprint 3) |
| `sec_nport_holdings` | global | 3 meses |
| `sec_13f_holdings` | global | 3 meses |

### 3.2 Compressão da `model_portfolio_nav`

> ⚠️ **NOTA PG18:** PostgreSQL 18 + TimescaleDB não permite columnstore compression em hypertables com RLS ativo. RLS é mandatório (multi-tenant) — compressão foi desabilitada na migration 0055. Limitação conhecida do PG18, não é bug. Hypertable funciona normalmente sem compressão.

```sql
-- Verificar que a hypertable existe (compressão N/A é esperado)
SELECT hypertable_name, num_dimensions
FROM timescaledb_information.hypertables
WHERE hypertable_name = 'model_portfolio_nav';
-- Esperado: 1 row
```

### 3.3 RLS ativo nas tabelas corretas

```sql
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
```

| RLS = true | RLS = false |
|------------|-------------|
| `model_portfolio_nav` | `macro_data` |
| `nav_timeseries` | `benchmark_nav` |
| `fund_risk_metrics` | `sec_nport_holdings` |
| `macro_reviews` | `sec_13f_holdings` |
| `strategic_allocations` | `allocation_blocks` |
| `model_portfolios` | |
| `portfolio_snapshots` | |

### 3.4 pgvector

```sql
SELECT * FROM pg_extension WHERE extname = 'vector';
```

---

## Fase 4 — Seed de Dados (Workers Globais)

**Scheduling automático:** Workers rodam automaticamente via Railway Cron Jobs configurados em `railway.toml`. Para o seed inicial, disparar manualmente via endpoints HTTP (requer role ADMIN ou INVESTMENT_TEAM):

```bash
# 1. Macro (FRED ~65 séries — base de tudo)
POST /api/v1/workers/run-macro-ingestion
# Aguardar (~2-5 min)

# 2. Treasury
POST /api/v1/workers/run-treasury-ingestion

# 3. Benchmark NAV (SPY, AGG, VNQ e demais tickers dos blocos)
POST /api/v1/workers/run-benchmark-ingest

# 4. OFR
POST /api/v1/workers/run-ofr-ingestion

# 5. SEC 13F — ATENÇÃO: rate-limited pelo EDGAR API (180 managers, ~7-10 min)
#    Requer EDGAR_IDENTITY configurado (ex: "Netz Analysis Engine contact@netz.com")
#    para reduzir throttling. Worker é trimestral — NÃO é bloqueador para o
#    Go/No-Go do deploy inicial. Rodar off-peak após os demais workers.
POST /api/v1/workers/run-sec-13f-ingestion

# 6. SEC N-PORT (crítico para overlap scanner — Fase 5.5)
POST /api/v1/workers/run-nport-ingestion

# 7. Portfolio NAV Synthesizer (após benchmark + portfolio_eval)
POST /api/v1/workers/run-portfolio-nav-synthesizer
```

Alternativa via CLI (dentro do container Railway):

```bash
python -m app.workers.cli macro_ingestion
python -m app.workers.cli treasury_ingestion
python -m app.workers.cli benchmark_ingest
```

### 4.1 Verificar dados

```sql
-- Macro: esperar ~65 séries × histórico
SELECT series_id, COUNT(*), MIN(date), MAX(date)
FROM macro_data
GROUP BY series_id
ORDER BY series_id;

-- Benchmark: confirmar SPY e tickers dos blocos
SELECT ticker, COUNT(*), MAX(date)
FROM benchmark_nav
GROUP BY ticker ORDER BY ticker;

-- N-PORT: confirmar holdings disponíveis
SELECT COUNT(*), COUNT(DISTINCT cik), MAX(report_date)
FROM sec_nport_holdings;
```

### 4.2 Verificar série FRED crítica para regime

```sql
-- VIX — essencial para classify_regime_multi_signal()
SELECT series_id, MAX(date), value
FROM macro_data
WHERE series_id = 'VIXCLS'
ORDER BY date DESC LIMIT 1;

-- CPI YoY — threshold 4.0% para INFLATION
SELECT series_id, MAX(date), value
FROM macro_data
WHERE series_id = 'CPIAUCSL'
ORDER BY date DESC LIMIT 1;

-- HY Spread US — threshold 550/800 bps para regional
SELECT series_id, MAX(date), value
FROM macro_data
WHERE series_id = 'BAMLH0A0HYM2'
ORDER BY date DESC LIMIT 1;
```

> ⚠️ Sem esses dados, `classify_regime_multi_signal()` retorna `RISK_ON` por default (fallback seguro, mas não representativo).

---

## Fase 5 — Smoke Test E2E (Ciclo Completo)

Tenant de teste com `Authorization: Bearer {clerk_jwt}`.

### 5.1 Ponte 1 — Macro → StrategicAllocation

```bash
# Gerar MacroReview
POST /api/v1/wealth/macro/reviews/generate
# Salvar {review_id}

# Verificar regime no report_json
GET /api/v1/wealth/macro/reviews/{review_id}
```

Inspecionar `report_json.regime`:

- `global`: um de `CRISIS` | `RISK_OFF` | `INFLATION` | `RISK_ON`
- `regional`: objeto com `US`, `EUROPE`, `ASIA`, `EM`
- `composition_reasons`: deve ter decision explicando a composição
- `has_material_changes`: boolean

```bash
# Aprovar — dispara AllocationProposalEngine
PATCH /api/v1/wealth/macro/reviews/{review_id}/approve
body: { "decision_rationale": "Smoke test E2E" }
```

```bash
# Verificar StrategicAllocation para os 3 perfis
GET /api/v1/wealth/allocation/strategic?profile=conservative
GET /api/v1/wealth/allocation/strategic?profile=moderate
GET /api/v1/wealth/allocation/strategic?profile=growth
```

Checar invariantes (ref: Section 1.6):

- `actor_source = "macro_proposal"` em todos os blocos
- `effective_from = today`
- Alocações anteriores com `effective_to = today` (time-versioning)
- Soma dos pesos: `Σ target_weight ≈ 1.0` (tolerância 1e-4)
- Blocos FI e cash não devem ter tilt regional — apenas equity
- Todos os pesos dentro de `[min_weight, max_weight]`

```bash
# Verificar regime CRISIS reduz equity mecanicamente
# Se regime = CRISIS, equity_tilt = -0.50 — confirmar queda vs target neutro
# Se regime = RISK_ON, equity_tilt = +0.30 — confirmar aumento vs target neutro
```

### 5.2 Ponte 2 — CLARABEL → ModelPortfolio

```bash
# Pré-requisito: instrumentos aprovados no universo com NAV disponível
GET /api/v1/wealth/universe
# Confirmar ≥ 3 instrumentos aprovados com NAV (mínimo 120 obs para CLARABEL)
```

```bash
# Construir portfólio
POST /api/v1/wealth/model-portfolios/{portfolio_id}/construct
```

```bash
# Verificar snapshot Dia 0
GET /api/v1/wealth/model-portfolios/{portfolio_id}/snapshots/latest
```

Checar campos do snapshot (ref: Section 2.4 e 2.9):

- `solver_status`: um de `optimal` | `optimal:cvar_constrained` | `optimal:min_variance_fallback` | `optimal:cvar_violated`
- `cvar_current < cvar_limit` (se status ≠ `cvar_violated`)
- `cvar_utilized_pct > 0`
- `trigger_source = "construct"`
- `consecutive_breach_days = 0`

Verificar `fund_selection_schema` (ref: Section 2.8):

```json
{
  "optimization": {
    "solver": "CLARABEL",
    "status": "optimal",
    "cvar_within_limit": true,
    "expected_return": "> 0",
    "sharpe_ratio": "> 0"
  }
}
```

Verificar covariância PSD (indiretamente — se CLARABEL retornou `optimal`, a matriz PSD passou):

```bash
# Se status = "solver_failed", investigar — pode ser eigenvalue negativo não corrigido
```

### 5.3 Ponte 3 — NAV Sintético

```bash
# Rodar synthesizer
POST /api/v1/workers/run-portfolio_nav_synthesizer
```

```bash
# Verificar série NAV
GET /api/v1/wealth/model-portfolios/{portfolio_id}/nav
```

Checar (ref: Section 3.2):

- Primeiro registro: `nav = 1000.0`, `daily_return = null` (Day-0 anchor)
- Demais: nav calculado via produto cruzado ponderado
- Série contínua (gaps apenas em feriados)
- Incrementalidade: segunda execução não duplica registros (`ON CONFLICT DO UPDATE`)
- Se fundos tinham < 5 anos de NAV: série limitada ao disponível (max 1260 dias)

Verificar duck typing (ref: Section 3.3):

```sql
-- ModelPortfolioNav usa daily_return (não return_1d)
SELECT column_name FROM information_schema.columns
WHERE table_name = 'model_portfolio_nav';
-- Deve ter: portfolio_id, nav_date, nav, daily_return, organization_id
```

### 5.4 Sprint 4 — Polimorfismo Analytics

```bash
# Fundo externo
GET /api/v1/analytics/entity/{instrument_id}?window=1Y

# Portfólio modelo
GET /api/v1/analytics/entity/{portfolio_id}?window=1Y
```

Verificar shape idêntico dos dois JSONs (ref: Section 3.7):

```json
{
  "risk_stats": { "sharpe", "sortino", "calmar", "max_dd", "var_95", "skewness", "alpha", "beta", "tracking_error", "information_ratio" },
  "drawdown": { "series[]", "max_dd", "current_dd", "worst_periods[]" },
  "capture_ratios": { "up_capture", "down_capture", "up_number_ratio", "down_number_ratio", "benchmark_source" },
  "rolling_returns": { "1M[]", "3M[]", "6M[]", "1Y[]" },
  "distribution": { "histogram[]", "skewness", "kurtosis", "var_95", "cvar_95" }
}
```

Verificar `benchmark_source` (ref: Section 3.6):

- Se passou `?benchmark_id=`: `"param"`
- Se não passou e bloco tem ticker: `"block"`
- Se fallback: `"spy_fallback"`

### 5.5 Sprint 5 — Monitoring e Rebalancing

```bash
# Overlap scan
POST /api/v1/wealth/monitoring/overlap-scan?portfolio_id={portfolio_id}
```

Verificar `OverlapResult` (ref: Section 4.3):

- `cusip_exposures[]` — sorted desc por exposição
- `sector_exposures[]` — sorted desc por exposição GICS
- `breaches[]` — apenas CUSIPs > 5% (default `limit_pct`)
- `total_holdings`: total de posições explodidas

Verificar fronteira de dados (ref: Section 4.4):

- Holdings vêm de `sec_nport_holdings` — tabela global, sem RLS
- `sec_cik` resolvido via `Instrument.attributes` JSONB (tenant-scoped com RLS)
- Se fundo não tem `sec_cik` em attributes: excluído da explosão silenciosamente

```bash
# Pegar proposta de rebalanceamento em status pending
GET /api/v1/wealth/rebalancing/proposals?portfolio_id={portfolio_id}

# Aplicar
POST /api/v1/wealth/rebalancing/proposals/{proposal_id}/apply
```

Verificar:

- Novo `PortfolioSnapshot` com `trigger_source = "rebalance_apply"` e `rebalanced_at` preenchido
- Registro em `model_portfolio_nav` com `daily_return = 0.0` (breakpoint para o worker)
- Proposta marcada como `applied` com audit trail

```bash
# Idempotência — segunda chamada deve retornar 409
POST /api/v1/wealth/rebalancing/proposals/{proposal_id}/apply
# Esperado: 409 Conflict
```

### 5.6 Sprint 6 — Client Reporting

```bash
# Fact Sheet institucional
GET /api/v1/wealth/fact-sheets/{portfolio_id}?mode=institutional&lang=pt
```

Verificar (ref: Section 5.3 e 5.6):

- `attribution[]` presente (Brinson-Fachler por bloco)
- `fee_drag{}` presente com `total_drag_pct` e `by_fund`
- Se dados insuficientes: `attribution = []`, `fee_drag = null` (never-raises)
- PDF com 6 páginas: cover, allocation, attribution (p.3), regime overlay, fee drag (p.4-5), disclaimer

```bash
# Gerar Long Form Report (máx 2 simultâneos)
POST /api/v1/wealth/reporting/model-portfolios/{portfolio_id}/long-form-report
# Esperado: 202 + { job_id }
```

```bash
# SSE stream — via curl (simula fetch + ReadableStream)
curl -N -H "Authorization: Bearer {token}" \
  https://{railway-domain}/api/v1/wealth/reporting/model-portfolios/{portfolio_id}/long-form-report/stream/{job_id}
```

Verificar eventos SSE (ref: Section 5.5):

- `event=started`
- `event=chapter_complete` × 8 (`macro_context`, `strategic_allocation`, `portfolio_composition`, `performance_attribution`, `risk_decomposition`, `fee_analysis`, `per_fund_highlights`, `forward_outlook`)
- `event=done` com PDF URL

Verificar status rollup do `LongFormReportResult` (ref: Section 5.2):

- Todos 8 completos → `"completed"`
- Algum falhou → `"partial"` (não `"failed"` — o ciclo continua)
- Falha no pre-load → `"failed"`

Verificar semaphore (ref: Section 5.5):

```bash
# Disparar 3 simultaneamente — terceiro deve retornar 429
POST /long-form-report  # 1
POST /long-form-report  # 2
POST /long-form-report  # 3 → 429 Too Many Requests
```

```bash
# Verificar i18n (PT e EN)
GET /fact-sheets/{portfolio_id}?mode=institutional&lang=pt
GET /fact-sheets/{portfolio_id}?mode=institutional&lang=en
# Labels de "Fee Drag Analysis" e "Attribution" devem mudar por idioma
```

---

## Fase 6 — Testes de Performance

### 6.1 Latências alvo (p95)

| Endpoint | Alvo | Crítico |
|----------|------|---------|
| `GET /health` | < 50ms | > 200ms |
| `GET /analytics/entity/{id}` | < 500ms | > 2s |
| `GET /screener/catalog` | < 200ms | > 500ms (cache 120s) |
| `POST /construct` (CLARABEL) | < 10s | > 30s |
| `POST /macro/reviews/generate` | < 5s | > 15s |
| `GET /fact-sheets` institucional | < 8s | > 20s |
| Worker `macro_ingestion` | < 5min | > 15min |
| Worker `portfolio_nav_synthesizer` | < 2min | > 10min |
| Worker `nport_ingestion` | < 15min | > 45min |

### 6.2 Medir baseline

```bash
for i in {1..10}; do
  curl -o /dev/null -s -w "%{time_total}\n" \
    -H "Authorization: Bearer {token}" \
    https://{railway-domain}/api/v1/analytics/entity/{portfolio_id}
done
```

### 6.3 CLARABEL timing

O solver CLARABEL típico: 50-200ms. SCS fallback: mais lento.

```bash
# Inspecionar log do construct — deve conter solver_info="CLARABEL"
# Se "SCS": CLARABEL falhou silenciosamente, investigar
```

### 6.4 Query plan nas hypertables críticas

```sql
-- Analytics entity — confirmar Index Scan (não Seq Scan)
EXPLAIN ANALYZE
SELECT nav_date, nav, daily_return
FROM model_portfolio_nav
WHERE portfolio_id = '{uuid}'
  AND nav_date >= NOW() - INTERVAL '1 year'
ORDER BY nav_date;
-- Esperado: Index Scan on model_portfolio_nav ou Chunk Append

-- Benchmark NAV — global, sem RLS
EXPLAIN ANALYZE
SELECT nav_date, nav
FROM benchmark_nav
WHERE ticker = 'SPY'
  AND nav_date >= NOW() - INTERVAL '1 year'
ORDER BY nav_date;
```

### 6.5 Compressão (após dados suficientes)

```sql
SELECT hypertable_name,
       pg_size_pretty(before_compression_total_bytes) AS before,
       pg_size_pretty(after_compression_total_bytes) AS after
FROM timescaledb_information.compression_stats
ORDER BY before_compression_total_bytes DESC;
```

> ⚠️ `model_portfolio_nav` só comprime após 3 meses de dados — normal não aparecer aqui inicialmente.

---

## Fase 7 — Frontend

```bash
cd frontends/wealth
npm run build    # Zero erros TypeScript
npm run dev      # ou deploy Railway/Vercel
```

### 7.1 Páginas críticas

| Rota | Descrição |
|------|-----------|
| `/screener` | 3 tabs (Fund Catalog, Equities & ETFs, Managers) |
| `/screener?tab=catalog` | Global — sem RLS |
| `/entity-analytics?entity_id={fund_id}` | Analytics de fundo externo |
| `/entity-analytics?entity_id={port_id}` | Mesmo render — polimorfismo |

### 7.2 Polimorfismo visual (DevTools)

- **Network:** ambos chamam `GET /api/v1/analytics/entity/{id}` — mesma URL, nenhum branch
- **Response shape:** idêntico — apenas `entity_type` muda para label/display
- 5 painéis ECharts renderizados em ambos os casos

### 7.3 SSE no frontend

```javascript
// Verificar que usa fetch + ReadableStream — nunca EventSource
// Abrir DevTools > Network > filtrar por "stream"
// Deve aparecer como request HTTP normal com response streaming
// NÃO deve aparecer como EventSource na aba de Network
```

---

## Fase 8 — Validação Final de Integridade

### 8.1 Audit trail do ciclo completo

```sql
SELECT event_type, COUNT(*), MAX(created_at)
FROM audit_events
WHERE organization_id = '{org_id}'
GROUP BY event_type
ORDER BY MAX(created_at) DESC;
```

Esperado após smoke test: `macro_approved`, `allocation_proposed`, `portfolio_constructed`, `rebalance_applied`, `long_form_report_generated`.

### 8.2 Time-versioning das StrategicAllocations

```sql
-- Alocações antigas devem ter effective_to preenchido
SELECT profile, block_id, effective_from, effective_to, actor_source
FROM strategic_allocations
WHERE organization_id = '{org_id}'
ORDER BY profile, block_id, effective_from;
-- Esperar: linhas antigas com effective_to = today, novas com effective_to = null
```

### 8.3 RLS — zero cross-tenant leakage

```sql
-- Com JWT de org_A, não deve ver dados de org_B
SELECT COUNT(*) FROM model_portfolio_nav
WHERE portfolio_id IN (
  SELECT id FROM model_portfolios
  WHERE organization_id = '{org_B_id}'
);
-- Esperado: 0
```

### 8.4 Manifest de workers

```bash
GET /api/v1/workers/manifest
```

Verificar que `portfolio_nav_synthesizer` (lock 900_030) está registrado. Era failure pré-existente — confirmar status.

### 8.5 Advisory lock IDs — sem colisão

```sql
-- Verificar locks ativos durante execução de worker
SELECT locktype, objid, mode, granted
FROM pg_locks
WHERE locktype = 'advisory'
ORDER BY objid;
-- Nenhum ID deve aparecer duplicado
```

---

## Go / No-Go

| # | Item | Critério | Status |
|---|------|----------|--------|
| 1 | Health check | 200 OK, db + redis ok | - [ ] |
| 2 | Migrations | `alembic current == heads` | - [ ] |
| 3 | Hypertable `model_portfolio_nav` | Na lista com `segmentby=portfolio_id` | - [ ] |
| 4 | RLS | Global tables sem RLS, org-scoped com RLS | - [ ] |
| 5 | FRED séries críticas | VIX, CPI, HY Spread populados | - [ ] |
| 6 | Benchmark NAV | SPY e tickers dos blocos disponíveis | - [ ] |
| 7 | N-PORT | Holdings populados para overlap scan | - [ ] |
| 8 | Ponte 1 | `StrategicAllocation` com `actor_source=macro_proposal`, pesos somando 1.0 | - [ ] |
| 9 | Regime tilts | CRISIS reduz equity mecanicamente vs RISK_ON | - [ ] |
| 10 | Time-versioning | Alocações antigas com `effective_to = today` | - [ ] |
| 11 | Ponte 2 | `cvar_current < cvar_limit`, `solver=CLARABEL` no snapshot | - [ ] |
| 12 | Ponte 2 fallback | Status documentado (`optimal` / `cvar_constrained` / etc) | - [ ] |
| 13 | Ponte 3 | NAV Day-0 = 1000.0, série contínua, sem duplicatas | - [ ] |
| 14 | Duck typing | `daily_return` (não `return_1d`) em `model_portfolio_nav` | - [ ] |
| 15 | Polimorfismo | JSON shape idêntico fund vs portfolio | - [ ] |
| 16 | Benchmark source | `benchmark_source` em capture ratios documenta tier usado | - [ ] |
| 17 | Overlap | `breaches[]` com CUSIPs > 5%, `sec_nport_holdings` sem RLS | - [ ] |
| 18 | Rebalancing | 409 em proposta já applied, breakpoint NAV `daily_return=0.0` | - [ ] |
| 19 | FactSheet institucional | `attribution[]` e `fee_drag{}` no payload | - [ ] |
| 20 | Long Form Report | 8 capítulos via SSE, status `completed` ou `partial` (nunca crash) | - [ ] |
| 21 | Semaphore | Terceiro request simultâneo retorna 429 | - [ ] |
| 22 | i18n | Labels mudam entre `lang=pt` e `lang=en` | - [ ] |
| 23 | Audit trail | Eventos do ciclo E2E registrados | - [ ] |
| 24 | RLS cross-tenant | Zero leakage entre orgs | - [ ] |
| 25 | Performance analytics | < 500ms p95 para `entity/{id}` | - [ ] |
| 26 | Advisory locks | Sem colisão de IDs durante workers | - [ ] |
| 27 | Manifest workers | `portfolio_nav_synthesizer` registrado | - [ ] |
| 28 | Railway Cron Jobs | `[[crons]]` no `railway.toml`, workers executando via `python -m app.workers.cli` | - [ ] |

**Todos 28 itens marcados = sistema em produção.**

---

## Issues Conhecidas (não bloqueadoras)

Descobertas durante execução do checklist em 2026-03-26:

| # | Issue | Impacto | Ação |
|---|-------|---------|------|
| I1 | PG18 + TimescaleDB: compressão e RLS mutuamente exclusivos em hypertables | Storage levemente maior em `model_portfolio_nav` | Documentado. Monitorar quando TimescaleDB suportar. |
| I2 | `WORKER_SECRET` listado no checklist original — env var correta é `WORKER_DISPATCH_SECRET` | Cloudflare Cron aposentado — variável não é mais necessária | Removido do checklist. Endpoint `/internal/` mantido mas não é chamado por scheduler externo. |
| I3 | `CLERK_SECRET_KEY` no system env do Windows bloqueia dev mode local | Apenas ambiente local Windows | Usar `.env` com prefixo ou `unset CLERK_SECRET_KEY` antes de rodar localmente. |
| I4 | SEC 13F rate-limited pelo EDGAR API (~7-10 min para 180 managers) | Não bloqueia deploy — worker é trimestral | Garantir `EDGAR_IDENTITY` configurado. Rodar off-peak. |

---

## Go/No-Go — Resultados Fase 0-4 (2026-03-26)

| # | Item | Status |
|---|------|--------|
| 1 | Health check 200 OK | ✅ GO |
| 2 | Migrations current == heads (0055) | ✅ GO |
| 3 | Hypertable `model_portfolio_nav` (sem compressão — PG18+RLS) | ✅ GO |
| 4 | RLS correto (org-scoped=true, globais=false) | ✅ GO |
| 5 | FRED séries críticas (VIX=25.33, CPI=327.46, HY=317bps) | ✅ GO |
| 6 | Benchmark NAV (16/16 blocos, SPY + todos tickers) | ✅ GO |
| 7 | N-PORT holdings (243.784 holdings, 146 CIKs) | ✅ GO |
| 8-28 | Smoke test E2E — Fases 5-8 pendentes | ⏳ PENDENTE |
