# Wealth Vector Embedding — Referencia de Implementacao

> Status: **Implementado** (2026-03-27)
> Migration: `0059_wealth_vector_chunks`
> Worker lock: `900_041`
> Cron: daily 03:00 UTC

---

## 1. Visao Geral

O vertical Wealth possui uma tabela propria de vetores (`wealth_vector_chunks`) separada da `vector_chunks` do Credit. A separacao existe porque:

- **Credit** e deal-centric: `deal_id` central, `organization_id` obrigatorio (RLS)
- **Wealth** e fund-centric: `entity_id` pode ser CRD, ISIN ou UUID; `organization_id` nullable (dados globais SEC/ESMA nao tem tenant)

O worker `wealth_embedding_worker` vetoriza 5 fontes de conteudo semantico em `wealth_vector_chunks`. Tres funcoes de busca fund-centric no `pgvector_search_service` expoe o indice para o Copilot RAG e vertical engines.

---

## 2. Tabela `wealth_vector_chunks`

### Schema

| Coluna | Tipo | Nullable | Descricao |
|--------|------|----------|-----------|
| `id` | TEXT PK | N | Formula: `{source}_{entity_id}_{section}` |
| `organization_id` | UUID | S | NULL = dado global (SEC, ESMA) |
| `entity_id` | TEXT | S | CRD, ISIN, UUID do fundo, ou UUID do macro_review |
| `entity_type` | TEXT | N | `"firm"` / `"fund"` / `"macro"` — **nunca** `"manager"` |
| `source_type` | TEXT | N | `"brochure"` / `"esma_fund"` / `"esma_manager"` / `"dd_chapter"` / `"macro_review"` |
| `section` | TEXT | S | Secao dentro da fonte (ex: `"investment_philosophy"`) |
| `content` | TEXT | N | Texto embeddado (com prefixo de secao quando aplicavel) |
| `language` | TEXT | S | Default `"en"` |
| `source_row_id` | TEXT | S | PK da row fonte original |
| `firm_crd` | TEXT | S | CRD da firma gestora — habilita resolucao fund→firma |
| `filing_date` | DATE | S | Data de filing da fonte (brochures ADV) |
| `embedding` | vector(3072) | S | text-embedding-3-large |
| `embedding_model` | TEXT | S | Nome do modelo usado |
| `embedded_at` | TIMESTAMPTZ | S | Quando o embedding foi gerado |
| `created_at` | TIMESTAMPTZ | N | server_default NOW() |
| `updated_at` | TIMESTAMPTZ | N | server_default NOW(), onupdate NOW() |

### Indexes

| Index | Colunas | Tipo |
|-------|---------|------|
| `wealth_vector_chunks_embedding_hnsw` | `embedding::halfvec(3072)` | HNSW (halfvec_cosine_ops, m=16, ef=64) |
| `ix_wvc_org` | `organization_id` | B-tree |
| `ix_wvc_entity_id` | `entity_id` | B-tree |
| `ix_wvc_firm_crd` | `firm_crd` | B-tree |
| `ix_wvc_entity` | `(entity_type, entity_id)` | B-tree composto |
| `ix_wvc_source` | `(source_type, section)` | B-tree composto |
| `ix_wvc_org_entity` | `(organization_id, entity_type)` | B-tree composto |

### Decisoes de design

- **Sem `OrganizationScopedMixin`**: o mixin forca NOT NULL em `organization_id`, incompativel com dados globais SEC/ESMA
- **Sem RLS policy**: dados globais (org_id NULL) exigem filtragem por WHERE explicito nas queries, nao por policy de tabela
- **Sem relacao com `vector_chunks`**: tabelas independentes — Credit nao e afetado
- **HNSW via halfvec**: pgvector HNSW suporta ate 2000 dims no tipo `vector`, mas `halfvec` suporta ate 4000 — mesmo pattern da migration original `e2f3a4b5c6d7`

---

## 3. Fontes de Embedding

### 3.1 Brochures ADV (entity_type="firm")

| Campo | Valor |
|-------|-------|
| Tabela fonte | `sec_manager_brochure_text` |
| Escopo | Global (org_id NULL) |
| ID formula | `brochure_{crd_number}_{section}` |
| entity_id | `crd_number` |
| firm_crd | `crd_number` |
| Volume estimado | ~7,000 chunks (6 secoes x ~3k CRDs com fundos) |

**Secoes embeddadas** (alto valor semantico):

| Secao | Label no embedding |
|-------|--------------------|
| `investment_philosophy` | Investment Philosophy |
| `methods_of_analysis` | Methods of Analysis |
| `advisory_business` | Advisory Business |
| `risk_management` | Risk Management |
| `performance_fees` | Performance Fees |
| `full_brochure` | ADV Part 2A Brochure |

**Secoes excluidas** (operacionais, baixo valor): `brokerage_practices`, `custody`, `code_of_ethics`, `disciplinary`, `client_types`, `fees_compensation`.

**Texto embeddado**: `[{Section Label}] {content[:4000]}`

**Incrementalidade**: Re-embeda quando `filing_date > embedded_at::date` (brochure atualizada).

### 3.2 ESMA Funds (entity_type="fund")

| Campo | Valor |
|-------|-------|
| Tabela fonte | `esma_funds` |
| Escopo | Global (org_id NULL) |
| ID formula | `esma_fund_{isin}` |
| entity_id | `isin` |
| firm_crd | NULL |
| Volume | ~10,400 chunks |

**Texto embeddado**: `{fund_name} | {fund_type or 'UCITS'} | {domicile or ''}`

### 3.3 ESMA Managers (entity_type="firm")

| Campo | Valor |
|-------|-------|
| Tabela fonte | `esma_managers` |
| Escopo | Global (org_id NULL) |
| ID formula | `esma_manager_{esma_id}` |
| entity_id | `esma_id` |
| firm_crd | `sec_crd_number` (quando linkado a RIA americana) |
| Volume | ~660 chunks |

**Texto embeddado**: `{company_name} | {country or ''} | {authorization_status or ''}`

### 3.4 DD Chapters (entity_type="fund")

| Campo | Valor |
|-------|-------|
| Tabela fonte | `dd_chapters` JOIN `dd_reports` |
| Escopo | Org-scoped (org_id da dd_report) |
| ID formula | `dd_chapter_{chapter_id}` |
| entity_id | `str(instrument_id)` — via FK `dd_reports.instrument_id` |
| firm_crd | NULL |
| Volume | ~96 chunks (crescimento) |

**Texto embeddado**: `content_md[:6000]`

**Filtros**: content_md NOT NULL e length > 100 chars.

### 3.5 Macro Reviews (entity_type="macro")

| Campo | Valor |
|-------|-------|
| Tabela fonte | `macro_reviews` |
| Escopo | Org-scoped |
| ID formula | `macro_review_{id}_rationale` |
| entity_id | `str(review_id)` |
| firm_crd | NULL |
| Volume | ~4 chunks (crescimento) |

**Texto embeddado**: `decision_rationale[:6000]`

---

## 4. Worker `wealth_embedding_worker`

### Localizacao

```
backend/app/domains/wealth/workers/wealth_embedding_worker.py
```

### Configuracao

| Parametro | Valor |
|-----------|-------|
| Advisory lock | `900_041` |
| Escopo | global |
| Timeout tier | `_HEAVY` (600s) |
| EMBED_BATCH_SIZE | 100 (chunks por batch OpenAI) |
| UPSERT_BATCH_SIZE | 200 (rows por batch DB) |
| Embedding service | `ai_engine.extraction.embedding_service.async_generate_embeddings` |

### Fluxo de execucao

```
run_wealth_embedding()
  ├── pg_try_advisory_lock(900041)
  ├── _embed_brochure_sections(db)   → entity_type="firm"
  ├── _embed_esma_funds(db)          → entity_type="fund"
  ├── _embed_esma_managers(db)       → entity_type="firm"
  ├── _embed_dd_chapters(db)         → entity_type="fund"
  ├── _embed_macro_reviews(db)       → entity_type="macro"
  └── pg_advisory_unlock(900041)
```

Cada `_embed_*` segue o padrao:
1. SELECT rows pendentes (LEFT JOIN wealth_vector_chunks, WHERE w.id IS NULL)
2. Preparar textos com formatacao por fonte
3. `async_generate_embeddings()` em batches de 100
4. `_batch_upsert()` com ON CONFLICT DO UPDATE (idempotente)

### Registro

- **Worker registry**: `backend/app/domains/admin/routes/worker_registry.py` — `"wealth_embedding": (run_wealth_embedding, "global", _HEAVY)`
- **Railway cron**: `railway.toml` — `0 3 * * *` (daily 03:00 UTC)

### Cadeia de dependencias

```
brochure_download (Sun 03:00) → brochure_extract (Sun 03:30) ─┐
sec_adv_ingestion (quarterly)  ──────────────────────────────────┤
esma_ingestion (Mon 04:00)  ─────────────────────────────────────┤
                                                                 └→ wealth_embedding (daily 03:00)
```

---

## 5. Funcoes de Busca (pgvector_search_service)

Tres funcoes fund-centric adicionadas a `backend/ai_engine/extraction/pgvector_search_service.py`.

### 5.1 `search_fund_firm_context_sync`

**Proposito**: buscar contexto da firma gestora de um fundo especifico.

```python
search_fund_firm_context_sync(
    query_vector=embed("investment philosophy"),
    sec_crd="12345",               # US funds (via instrument.attributes["sec_crd"])
    # OU
    esma_manager_id="ESM_001",     # UCITS funds
    section_filter=["investment_philosophy", "methods_of_analysis"],
    top=20,
) -> list[dict]
```

- Retorna `entity_type="firm"` de `wealth_vector_chunks`
- Filtra por `firm_crd` (US) ou `entity_id` (ESMA)
- Retorna `[]` se ambos `sec_crd` e `esma_manager_id` forem None

### 5.2 `search_esma_funds_sync`

**Proposito**: busca semantica de fundos UCITS por nome/tipo/domicilio.

```python
search_esma_funds_sync(
    query_vector=embed("global aggregate bond UCITS"),
    domicile_filter="LU",   # opcional
    top=20,
) -> list[dict]
```

- Retorna `source_type="esma_fund"` (entity_type="fund")
- Filtragem de domicilio via LIKE no conteudo

### 5.3 `search_fund_analysis_sync`

**Proposito**: busca semantica em analises org-scoped (DD chapters, macro reviews).

```python
search_fund_analysis_sync(
    organization_id="uuid-org",
    query_vector=embed("risk assessment"),
    instrument_id="uuid-fund",     # opcional — filtra por fundo
    source_type="dd_chapter",      # opcional — filtra por tipo
    top=20,
) -> list[dict]
```

- Sempre filtra por `organization_id` (obrigatorio — dados org-scoped)
- `instrument_id` filtra `entity_id` para chunks do fundo especifico
- Valida UUIDs via `validate_uuid()`

---

## 6. Principio Fund-Centric

### Regra fundamental

> O objeto de analise e sempre o **fundo**, nunca a firma.

- `"manager"` no sistema = Portfolio Manager (individuo/PM), nao a firma RIA
- A firma RIA/ManCo usa `entity_type="firm"`
- O agente AI busca contexto de um fundo e recebe contexto da firma como resultado derivado

### Resolucao de identidade

```
instrument_id
  → instrument.attributes["sec_crd"]     → firm_crd → brochure chunks
  → instrument.attributes["esma_manager_id"] → entity_id → esma_manager chunks
```

O caller (Copilot RAG, DD report engine) resolve `instrument_id → sec_crd` e passa para a funcao de busca. A busca nunca recebe "firma" diretamente.

### entity_type permitidos

| entity_type | Significado | Fontes |
|-------------|-------------|--------|
| `"firm"` | RIA / Management Company | brochure, esma_manager |
| `"fund"` | Instrumento fundo | esma_fund, dd_chapter |
| `"macro"` | Macro review | macro_review |
| ~~`"manager"`~~ | **PROIBIDO** — manager = PM individual no sistema | — |

---

## 7. Arquivos Implementados

### Criados

| Arquivo | Descricao |
|---------|-----------|
| `backend/app/domains/wealth/models/wealth_vector_chunk.py` | Model SQLAlchemy (Base, sem OrganizationScopedMixin) |
| `backend/app/core/db/migrations/versions/0059_wealth_vector_chunks.py` | Migration com HNSW halfvec index |
| `backend/app/domains/wealth/workers/wealth_embedding_worker.py` | Worker com 5 fontes, lock 900_041 |
| `backend/tests/test_wealth_embedding_worker.py` | 12 testes (model, worker, search) |

### Modificados

| Arquivo | Alteracao |
|---------|-----------|
| `backend/ai_engine/extraction/pgvector_search_service.py` | +3 funcoes fund-centric |
| `backend/app/domains/admin/routes/worker_registry.py` | +registro `wealth_embedding` |
| `railway.toml` | +cron daily 03:00 UTC |

---

## 8. Custo e Volume

### Seed inicial

| Fonte | Chunks | Tokens estimados |
|-------|--------|-----------------|
| Brochures (6 secoes) | ~7,000 | ~10M |
| ESMA funds | ~10,400 | ~500k |
| ESMA managers | ~660 | ~30k |
| DD chapters | ~96 | ~200k |
| Macro reviews | ~4 | ~40k |
| **Total** | **~18,160** | **~11M** |

**Custo OpenAI** (text-embedding-3-large @ $0.13/1M tokens): **~$1.43 inicial**, centavos/dia incremental.

### Crescimento

- Brochures: +semanal (brochure_extract → wealth_embedding)
- ESMA: +semanal (esma_ingestion → wealth_embedding)
- DD chapters: +sob demanda (cada DD report gera ~8 chapters)
- Macro reviews: +mensal (~4 reviews/mes)

---

## 9. Failure Modes

| Cenario | Mitigacao |
|---------|-----------|
| OpenAI rate limit no seed | Batch size 100, retry com backoff em `async_generate_embeddings` |
| Brochure > 8192 tokens | Truncada a 4000 chars antes do embed |
| org_id NULL em query org-scoped | Queries globais (brochure, esma) nao usam WHERE org_id |
| DD chapter sem instrument_id | Skip — JOIN com dd_reports garante que so processa rows validas |
| Worker falha no meio | Incremental por design — reroda so processa pending |
| Lock held por outro processo | Retorna `{"status": "skipped", "reason": "lock_held"}` |
| Embedding model upgrade (dim change) | `embedding_model` e `embedded_at` rastreiam versao — rebuild seletivo |
