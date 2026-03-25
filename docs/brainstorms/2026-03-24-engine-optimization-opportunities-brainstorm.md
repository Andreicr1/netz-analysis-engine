---
date: 2026-03-24
topic: engine-optimization-opportunities
---

# Engine Optimization Opportunities — Wealth-First

> Inventário de oportunidades de performance, caching, indexação e paralelização across `vertical_engines/wealth/`, `quant_engine/`, e `ai_engine/`. Inspirado pelo trabalho de indexação do Screener (33 índices, `docs/reference/screener-index-reference.md`).

---

## Context

O trabalho no Screener identificou um padrão: **índices no banco + caching no Redis + queries otimizadas = resposta instantânea**. Esse mesmo padrão pode ser replicado em outros engines do sistema. A análise abaixo mapeia oportunidades em 5 dimensões:

1. **Caching** — routes sem `route_cache` que deveriam ter
2. **Indexação** — tabelas críticas sem índices compostos
3. **Paralelização** — operações sequenciais que poderiam rodar em paralelo
4. **Computação** — cálculos repetidos que poderiam ser pré-computados ou materializados
5. **UX** — melhorias na experiência que dependem de otimizações técnicas

---

## 1. Caching — O Gap Mais Impactante

### Diagnóstico

**5 de 25 route files usam `route_cache`** (screener, macro, sec_analysis, manager_screener, risk). Os outros 20 não têm nenhum caching.

### Routes que DEVEM ter caching

| Route File | Endpoints | Motivo | TTL sugerido | Scope |
|---|---|---|---|---|
| `correlation_regime.py` | `GET /{profile}`, `GET /{profile}/pair/{a}/{b}` | Eigenvalue decomposition + Marchenko-Pastur + rolling correlation — operações NumPy/SciPy pesadas | 300s | org |
| `attribution.py` | `GET /{profile}` | Brinson-Fachler per-period com compound returns — loop com N períodos | 300s | org |
| `blended_benchmark.py` | `GET /blocks`, `GET /{profile}`, `GET /{id}/nav` | Blocks raramente mudam; NAV computation per-request é desperdício | blocks: 600s, benchmark: 300s, nav: 120s | org |
| `exposure.py` | `GET /matrix`, `GET /metadata` | Matrix computation com joins + aggregation — muda 1x/dia (daily worker) | 300s | org |
| `funds.py` | `GET /scoring`, `GET /`, `GET /{id}`, `GET /{id}/risk`, `GET /{id}/nav` | Read-heavy, dados mudam 1x/dia por workers | scoring: 120s, list: 60s, detail: 120s, nav: 300s | org |
| `instruments.py` | `GET /`, `GET /{id}` | Read-heavy, seed data | 120s | org |
| `model_portfolios.py` | `GET /`, `GET /{id}`, `GET /{id}/track-record` | Read-heavy, track record é computação pesada | list: 120s, detail: 120s, track: 300s | org |
| `portfolios.py` | `GET /`, `GET /{id}`, `GET /{id}/snapshot`, `GET /{id}/history` | Read-heavy, snapshots mudam 1x/dia | list: 60s, snapshot: 120s, history: 300s | org |
| `esma.py` | `GET /managers`, `GET /funds` | Global data, muda 1x/mês (ESMA ingestion) | 600s | global |
| `content.py` | `GET /` (list) | Content production — list é read-heavy | 60s | org |

### Impacto estimado

~40 endpoints ganhariam caching. Para um tenant com 5 analistas acessando dashboards simultaneamente, cada endpoint sem cache = 5 queries idênticas ao DB por 60s window. Com cache, 1 query + 4 cache hits.

---

## 2. Indexação — Tabelas Core Sem Índices Dedicados

### `nav_timeseries` — A tabela mais consultada do sistema

**Status atual:** Hypertable com PK `(instrument_id, nav_date)`. TimescaleDB cria chunk-level indexes automaticamente, MAS queries compostas (multi-instrument + date range + return_1d filter) não são otimizadas.

**Queries críticas sem índice dedicado:**

```sql
-- Correlation regime, attribution, analytics — todas fazem isso:
SELECT instrument_id, nav_date, return_1d
FROM nav_timeseries
WHERE instrument_id IN (:ids...)
  AND nav_date >= :date_floor
  AND return_1d IS NOT NULL
ORDER BY nav_date;

-- Backtest, rolling correlation — date-range heavy:
SELECT instrument_id, nav_date, nav, return_1d
FROM nav_timeseries
WHERE instrument_id = :id
  AND nav_date BETWEEN :start AND :end
ORDER BY nav_date;
```

**Índices propostos:**

| Índice | Tipo | Query habilitada |
|---|---|---|
| `ix_nav_timeseries_instrument_date` | btree composite `(instrument_id, nav_date)` | PK já cobre — confirmar que TimescaleDB não descarta |
| `ix_nav_timeseries_instrument_date_return` | btree covering `(instrument_id, nav_date)` INCLUDE `(return_1d)` | Index-only scan para correlation/attribution (evita heap fetch) |
| `ix_nav_timeseries_org_instrument` | btree composite `(organization_id, instrument_id)` | RLS + instrument filter (RLS subselect optimization) |

### `fund_risk_metrics` — Scoring e risk dashboard

**Status atual:** Hypertable com PK `(instrument_id, calc_date)`. Sem índices adicionais.

**Queries críticas:**

```sql
-- Scoring route — DISTINCT ON pattern:
SELECT DISTINCT ON (instrument_id) *
FROM fund_risk_metrics
WHERE instrument_id IN (:ids...)
ORDER BY instrument_id, calc_date DESC;

-- Risk summary:
SELECT * FROM fund_risk_metrics
WHERE instrument_id = :id
ORDER BY calc_date DESC
LIMIT 1;

-- Risk history:
SELECT calc_date, cvar_95_3m, sharpe_1y, volatility_1y
FROM fund_risk_metrics
WHERE instrument_id = :id
  AND calc_date >= :start
ORDER BY calc_date;
```

**Índices propostos:**

| Índice | Tipo | Query habilitada |
|---|---|---|
| `ix_fund_risk_latest` | btree `(instrument_id, calc_date DESC)` | DISTINCT ON + latest metric lookup |
| `ix_fund_risk_org` | btree composite `(organization_id, instrument_id, calc_date DESC)` | RLS + instrument filter + latest |
| `ix_fund_risk_score` | btree partial `(manager_score DESC WHERE manager_score IS NOT NULL)` | Scoring ranking queries |

### `model_portfolios` — Frequent profile lookups

**Status atual:** Sem índices dedicados visíveis.

```sql
-- Used in: correlation_regime, attribution, track_record
SELECT * FROM model_portfolios
WHERE profile = :profile AND status = 'live';
```

**Índice proposto:**

| Índice | Tipo | Query habilitada |
|---|---|---|
| `ix_model_portfolios_profile_status` | btree partial `(profile WHERE status = 'live')` | Profile lookup para correlation/attribution (1 row per profile) |

### `strategic_allocation` — Attribution queries

```sql
SELECT * FROM strategic_allocation
WHERE profile = :profile
  AND effective_from <= :date
  AND (effective_to IS NULL OR effective_to >= :date);
```

**Índice proposto:**

| Índice | Tipo | Query habilitada |
|---|---|---|
| `ix_strategic_alloc_profile_dates` | btree composite `(profile, effective_from, effective_to)` | Temporal range scan |

### `benchmark_nav` — Attribution + blended benchmark

```sql
SELECT * FROM benchmark_nav
WHERE block_id IN (:ids...)
  AND nav_date BETWEEN :start AND :end
ORDER BY block_id, nav_date;
```

**Índice proposto:**

| Índice | Tipo | Query habilitada |
|---|---|---|
| `ix_benchmark_nav_block_date` | btree composite `(block_id, nav_date)` | Attribution per-block date range |

### `dd_reports` / `dd_chapters` — Report listing

```sql
-- List reports:
SELECT * FROM dd_reports
WHERE instrument_id = :id AND organization_id = :org
ORDER BY version DESC;

-- Current report:
SELECT * FROM dd_reports
WHERE instrument_id = :id AND organization_id = :org AND is_current = true;
```

**Índices propostos:**

| Índice | Tipo | Query habilitada |
|---|---|---|
| `ix_dd_reports_instrument_current` | btree partial `(instrument_id, organization_id WHERE is_current = true)` | Current report lookup (1 row) |
| `ix_dd_chapters_report` | btree `(dd_report_id, chapter_order)` | Chapter listing ordered |

---

## 3. Paralelização — Operações Sequenciais

### 3.1 DD Report Chapters (MAIOR OPORTUNIDADE)

**Problema:** `dd_report_engine.py:349` — chapters 1-7 são gerados SEQUENCIALMENTE em um loop `for`. Cada chapter faz uma chamada LLM (5-30s cada). Total: 35-210s.

**Oportunidade:** Chapters 1-7 são INDEPENDENTES (compartilham apenas o `EvidencePack` frozen). Apenas chapter 8 (Recommendation) depende dos summaries dos anteriores.

**Solução:** `ThreadPoolExecutor` com `max_workers=5` (respeitando `_DEFAULT_LLM_CONCURRENCY`):
```python
# Phase A: Chapters 1-7 em paralelo
with ThreadPoolExecutor(max_workers=5) as pool:
    futures = {
        pool.submit(generate_chapter, call_fn, ch["tag"], evidence_context, evidence): ch
        for ch in CHAPTER_REGISTRY if ch["tag"] != SEQUENTIAL_CHAPTER_TAG
    }
    for future in as_completed(futures):
        result = future.result()
        chapters.append(result)
# Phase B: Chapter 8 sequencial (depende dos summaries)
```

**Speedup estimado:** 5-7x (de 35-210s para 7-42s).

### 3.2 DD Report Evidence Gathering

**Problema:** `dd_report_engine.py:312-319` — 4 queries DB sequenciais:
```python
quant_profile = gather_quant_metrics(db, ...)
risk_metrics = gather_risk_metrics(db, ...)
sec_13f = gather_sec_13f_data(db, ...)
sec_adv = gather_sec_adv_data(db, ...)
```

**Oportunidade:** Estas são queries independentes que poderiam rodar em paralelo. Porém, o engine roda em sync (dentro de `asyncio.to_thread`), então precisaria de um ThreadPoolExecutor interno ou refactor para async.

**Impacto:** ~200-500ms savings (4 DB roundtrips → 1 roundtrip wall-clock).

### 3.3 Attribution Per-Period Loop

**Problema:** `attribution.py:183-222` — para cada período (mensal/trimestral), instancia `AttributionService()` e roda `asyncio.to_thread()`.

**Oportunidade:**
1. Instanciar `AttributionService` UMA vez fora do loop
2. Coletar todos os dados de todos os períodos e computar em batch (um único `asyncio.to_thread` call)

**Impacto:** Elimina N `to_thread` calls (cada um tem overhead de ~1ms para thread spawn).

### 3.4 N+1 Regime Trigger Detection (rebalancing)

**Problema:** `rebalancing/service.py:143-180` — queries `PortfolioSnapshot` PER PROFILE em um loop:
```python
for profile in profiles:
    snapshots = db.execute(
        select(PortfolioSnapshot).where(...)
    ).scalars().all()  # ← 1 query PER profile
```

**Oportunidade:** Single query para ALL snapshots, group in-memory by profile. Elimina N+1.

### 3.5 Quant Analyzer Sequential Computations

**Problema:** `quant_analyzer.py:61-67` — 3 métodos sequenciais, cada um com DB query:
```python
result["cvar"] = self._compute_cvar(db, fid)             # DB query 1
result["scoring"] = self._compute_scoring(db, fid)       # DB query 2
result["peer_comparison"] = self._compute_peer(db, fid)  # DB query 3
```

**Oportunidade:** Parallelize at route layer via `asyncio.gather()`.

### 3.6 Content Production (Outlooks, Flash Reports, Spotlights)

**Status:** Já usa `asyncio.Semaphore(3)` para limitar concorrência — BOM. Mas cada content piece faz uma única LLM call. Se o engine gera multiple sections, há espaço para paralelização intra-report.

---

## 4. Computação — Pre-computation e Materialized Views

### 4.1 Correlation Regime — Materialized via Worker

**Problema:** Correlation regime calcula eigenvalues, Marchenko-Pastur denoising, absorption ratio e rolling correlation ON EVERY REQUEST. Estas são operações NumPy/SciPy pesadas (~500ms-2s).

**Oportunidade:** Pré-computar no daily `portfolio_eval` worker e armazenar em nova tabela `correlation_snapshots`. Route lê snapshot + caching = resposta instantânea.

**Tabela proposta:**

| Coluna | Tipo | Descrição |
|---|---|---|
| `profile` | varchar(80) | Portfolio profile |
| `snapshot_date` | date | Data do cálculo |
| `window_days` | int | Window usado |
| `correlation_matrix` | jsonb | NxN matrix |
| `contagion_pairs` | jsonb | Pairs flagged |
| `concentration_metrics` | jsonb | Eigenvalues, absorption ratio |
| `regime_shift_detected` | boolean | Flag |

### 4.2 Track Record — Pre-computation

`model_portfolios.py` track record endpoint computes NAV-weighted portfolio returns historically. Este cálculo cresce linearmente com o histórico e é repetido a cada request.

**Oportunidade:** Materializar track record como time series (similar a `portfolio_snapshots`), atualizando no daily worker.

### 4.3 TimescaleDB Continuous Aggregates

Já usamos continuous aggregates para `sec_13f_holdings_agg` e `sec_13f_drift_agg`. O mesmo padrão aplica-se a:

| Aggregate proposto | Source table | Granularity | Usado por |
|---|---|---|---|
| `nav_monthly_returns_agg` | `nav_timeseries` | monthly | Attribution, backtest, track record |
| `risk_latest_agg` | `fund_risk_metrics` | latest per instrument | Scoring, risk summary, DD evidence |
| `benchmark_monthly_agg` | `benchmark_nav` | monthly | Attribution, blended benchmark |

**Impacto:** Queries de attribution/backtest que hoje fazem compound return calculation per-row passariam a ler pre-aggregated monthly returns.

---

## 5. Quant Engine — Oportunidades Específicas

### 5.1 Optimizer — Já Bem Otimizado

- `optimize_portfolio()` usa CLARABEL solver (50-200ms) — adequado
- `optimize_portfolio_pareto()` (NSGA-II) já roda como background job com SSE — correto
- Parametric CVaR (Cornish-Fisher) como fast proxy — correto
- Redis caching com SHA-256 hash — já implementado

### 5.2 Scoring Service — Oportunidade de Batch

`compute_fund_score()` é chamado per-fund em loop no route handler. O service é sync e stateless.

**Oportunidade:** Batch scoring — passar lista de `(risk_metrics, momentum)` tuples e retornar scores em batch. Elimina overhead de N function calls Python.

### 5.3 Regime Service — Cache de State

`regime_service` determina market regime (RISK_ON / RISK_OFF / CRISIS). O regime muda infrequentemente (days-weeks). Atualmente recalculado on-demand.

**Oportunidade:** Pre-compute no `macro_ingestion` worker, cache no Redis com TTL de 1h. Routes leem regime do cache.

### 5.4 DTW Drift — O(T²) para Timeseries Longas

`drift_service.py` usa Dynamic Time Warping que é O(T² × B) onde T = length da timeseries e B = blocks. Para T=500 (2 anos daily), isso vira caro.

**Oportunidade:** Sliding window (últimos N dias) ou downsampling (weekly) ao invés de full history.

### 5.5 Backtest Folds — Sequential Loop

`backtest_service.py` roda `n_splits=5` folds sequencialmente. Cada fold é independente.

**Oportunidade:** `ThreadPoolExecutor` para rodar folds em paralelo. Speedup ~3-5x para backtests com muitos folds.

### 5.6 Padrões Bem Projetados (não mexer)

- Config injection via parâmetros (zero `@lru_cache`, zero YAML loading)
- Frozen dataclasses para thread safety
- CLARABEL solver chain com SCS fallback
- Cornish-Fisher CVaR como fast proxy para NSGA-II
- Token bucket rate limiters (FRED sync, Treasury/OFR async)
- Graceful degradation para dependências opcionais (ta-lib, pymoo)
- Zero TODO/FIXME/HACK comments

---

## 6. AI Engine — Oportunidades Específicas

### 6.1 pgvector Upsert N+1 (HOTSPOT CONFIRMADO)

**Problema:** `pgvector_search_service.py:231-288` — upsert loop faz **1 INSERT per chunk**:
```python
for doc in documents:  # ← 200 chunks = 200 sequential INSERTs
    await db.execute(text("""INSERT INTO vector_chunks ... ON CONFLICT DO UPDATE"""), {...})
```

**Oportunidade:** Batch INSERT com multi-row VALUES (50 chunks por roundtrip):
```sql
INSERT INTO vector_chunks (id, organization_id, ..., embedding)
VALUES (:id1, :org1, ..., :emb1), (:id2, :org2, ..., :emb2), ...
ON CONFLICT (id) DO UPDATE SET ...
```

**Speedup estimado:** 10-50x (200 queries → 4 queries para um documento de 200 chunks).

### 6.2 TF-IDF Vectorizer Recreation

**Problema:** `hybrid_classifier.py` — TF-IDF vectorizer é recriado (fitted) a cada chamada de classificação (~10-20ms overhead per call).

**Oportunidade:** Cache fitted vectorizer como singleton thread-safe. `TfidfVectorizer.transform()` é thread-safe após `fit()`.

### 6.3 Embedding Batch Size

O embedding service faz batching correto (batch_size=500), mas batches são **seriais**:
```python
for i in range(0, len(texts), batch_size):
    batch = texts[i : i + batch_size]
    result = await async_create_embedding(inputs=batch)  # ← serial await
```
Aceitável dado rate limits da OpenAI API, mas se a API permitir, 2-3 batches concorrentes dariam 2-3x speedup.

### 6.4 OCR Cache — JÁ IMPLEMENTADO

OCR cache via SHA-256 keying in-memory. Pipeline retry reutiliza OCR result da bronze layer. **Porém:** cache é in-memory per-instance. Para multi-instance Railway deployment, Redis-backed cache seria mais eficiente (cross-instance reuse).

### 6.5 Padrões Bem Projetados (não mexer)

- Metadata extraction + summarization: **já paralelo** via `asyncio.gather()` (gpt-5.1 + gpt-4.1)
- Storage writes (bronze/silver/metadata): **já paralelo** via `asyncio.gather()`
- OCR rate limiter: token bucket async — correto
- Local reranker (MS Marco MiniLM): thread-safe singleton, ~100ms for 50 pairs — correto
- OpenAI retry: exponential backoff com jitter, 429 handling com Retry-After — correto

---

## Priorização — Impacto vs Esforço

### Alta Prioridade (alto impacto, baixo esforço)

| # | Oportunidade | Impacto | Esforço | Área |
|---|---|---|---|---|
| 1 | Cache em 15+ routes sem caching | Reduz DB load 80% em read-heavy endpoints | Baixo — `@route_cache(ttl=N)` decorator | Routes |
| 2 | pgvector batch INSERT (N+1 hotspot) | 10-50x speedup no pipeline upsert | Baixo — SQL restructure | AI Engine |
| 3 | Paralelizar DD report chapters 1-7 | 5-7x speedup na geração de DD reports | Médio — ThreadPoolExecutor refactor | DD Report |
| 4 | Índices em `nav_timeseries` (covering) | Index-only scan para correlation/attribution | Baixo — 1 migration | DB |
| 5 | Índices em `fund_risk_metrics` (latest) | DISTINCT ON otimizado para scoring | Baixo — 1 migration | DB |
| 6 | Fix N+1 regime trigger detection | Elimina N queries → 1 query | Baixo — batch query refactor | Rebalancing |

### Média Prioridade (médio impacto, médio esforço)

| # | Oportunidade | Impacto | Esforço | Área |
|---|---|---|---|---|
| 7 | Continuous aggregates (monthly returns) | Attribution/backtest leem pre-aggregated | Médio — migration + refresh policy | DB |
| 8 | Correlation regime pre-computation ou cache | Elimina 500ms-2s compute on-demand | Médio — cache 300s ou nova tabela + worker | Worker |
| 9 | Attribution batch computation | Elimina N `to_thread` calls | Baixo — refactor loop | Attribution |
| 10 | Partial indexes em model_portfolios, dd_reports | Lookup de "live" e "current" instantâneo | Baixo — 1 migration | DB |
| 11 | Track record materialization | Elimina crescente computation per-request | Médio — nova tabela + worker | Worker |
| 12 | TF-IDF vectorizer singleton cache | ~10-20ms savings per classification | Baixo — singleton pattern | AI Engine |

### Baixa Prioridade (refinamentos)

| # | Oportunidade | Impacto | Esforço | Área |
|---|---|---|---|---|
| 13 | Scoring batch API | Menor overhead Python | Baixo | Quant |
| 14 | Regime cache no Redis | Evita recálculo infrequente | Baixo | Quant |
| 15 | DTW sliding window / downsampling | Reduz O(T²) para longas timeseries | Baixo | Quant |
| 16 | Backtest folds parallelization | ~3-5x speedup em backtests | Baixo | Quant |
| 17 | Evidence gathering parallelization | ~200-500ms savings | Médio — sync→async refactor | DD Report |
| 18 | Quant analyzer parallel computations | ~100-300ms savings | Médio — async route refactor | Wealth |
| 19 | SEC injection batch CIK resolution | Elimina double-query per manager | Baixo | DD Report |
| 20 | Peer group: migrate all callers to batch | 10x faster peer lookups | Baixo — caller refactor | Wealth |

---

## Relação com Screener Index Reference

O `screener-index-reference.md` cobre 8 tabelas com 33 índices — todas globais (SEC, ESMA, instruments_global). Este documento complementa focando nas tabelas **org-scoped** que alimentam os engines analíticos:

| Screener Reference (global) | Este documento (org-scoped) |
|---|---|
| `sec_managers` (10 índices) | `nav_timeseries` (3 propostos) |
| `sec_13f_holdings` (2 + hypertable) | `fund_risk_metrics` (3 propostos) |
| `instruments_global` (8 índices) | `model_portfolios` (1 proposto) |
| `esma_funds` (5 índices) | `strategic_allocation` (1 proposto) |
| | `benchmark_nav` (1 proposto) |
| | `dd_reports` / `dd_chapters` (2 propostos) |

**Total proposto:** ~11 novos índices + 3 continuous aggregates + caching em 15+ routes + batch pgvector INSERT + 4 N+1 fixes.

---

## Open Questions

1. **Correlation pre-computation granularity:** diário (overkill?) ou on-demand com cache? O cache de 300s pode ser suficiente sem worker.
2. **DD report parallelism:** o `asyncio.to_thread()` wrapper no route handler já cria um thread — paralelizar dentro via ThreadPoolExecutor cria threads-dentro-de-threads. Alternativa: refactor para async chapters com `asyncio.gather()`.
3. **Continuous aggregates vs application-level cache:** para monthly returns, o TimescaleDB cagg é mais robusto que Redis cache, mas exige refresh policy management.
4. **Index maintenance overhead:** 11 novos índices em hypertables com 1M+ rows — insert performance impact nos workers precisa ser medido.
5. **pgvector batch INSERT size:** qual o sweet spot? 50 chunks/batch? 100? Precisa de benchmark com a dimensão 3072 dos embeddings (cada row é ~25KB com o vetor).
6. **Multi-instance cache:** OCR/embedding cache é in-memory per-instance. Se Railway escalar para 2+ instâncias, Redis-backed cache economiza API calls duplicados. Vale o esforço agora ou só quando escalar?

---

## Resumo Quantitativo

| Dimensão | Oportunidades | Impacto estimado |
|---|---|---|
| **Caching** | 15+ routes (40+ endpoints) | -80% DB load em read-heavy paths |
| **Indexação** | 11 novos índices + 3 continuous aggregates | Index-only scan em tabelas core |
| **Paralelização** | DD chapters, evidence, quant analyzer, attribution, backtest | 5-7x em DD reports, 2-3x em analytics |
| **N+1 Fixes** | pgvector upsert, regime trigger, SEC injection, quant analyzer | 10-50x no pipeline, eliminação de sequential queries |
| **Pre-computation** | Correlation regime, track record, monthly returns | Resposta instantânea em endpoints pesados |

**Total: 20 oportunidades priorizadas, organizáveis em 3-4 sprints.**

---

## Next Steps

-> `/ce:plan` para priorizar e detalhar implementação (provavelmente em 3-4 sprints)
