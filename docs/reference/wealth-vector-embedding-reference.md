# Wealth Vector Embedding — Referencia Tecnica

> Status: **v2 Implementado** (2026-03-27) | DD Report integration: 2026-03-27
> Migration: `0059_wealth_vector_chunks`
> Worker lock: `900_041`
> Cron: daily 03:00 UTC

---

## 1. Visao Geral

O vertical Wealth possui uma tabela propria de vetores (`wealth_vector_chunks`) separada da `vector_chunks` do Credit. A separacao existe porque:

- **Credit** e deal-centric: `deal_id` central, `organization_id` obrigatorio (RLS)
- **Wealth** e fund-centric: `entity_id` pode ser CRD, CIK, ISIN ou UUID; `organization_id` nullable (dados globais SEC/ESMA nao tem tenant)

O worker `wealth_embedding_worker` vetoriza **9 fontes** de conteudo semantico em `wealth_vector_chunks`. Tres funcoes de busca fund-centric no `pgvector_search_service` expoe o indice para o Copilot RAG e vertical engines.

### Diferenca v1 → v2

| Aspecto | v1 (pre-2026-03-27) | v2 (atual) |
|---------|---------------------|------------|
| Fontes | 5 (brochure, esma_fund, esma_manager, dd_chapter, macro_review) | 9 (+ sec_manager_profile, sec_fund_profile, sec_13f_summary, sec_private_funds; ESMA enriquecido) |
| ESMA chunks | Name-only strings (`"Fund Name \| UCITS \| LU"`) | Prosa estruturada com gestora, domicilio, distribuicao, ticker |
| Dados SEC tabulares | Nao vetorizados | Manager profiles, fund profiles (com N-PORT holdings), 13F summaries, private funds |
| Cobertura do AI Agent | Texto narrativo (brochures, DD) | Texto narrativo + dados estruturados em prosa legivel |

---

## 2. Tabela `wealth_vector_chunks`

### Schema

| Coluna | Tipo | Nullable | Descricao |
|--------|------|----------|-----------|
| `id` | TEXT PK | N | Formula: `{source_type}_{entity_key}[_{qualifier}]` |
| `organization_id` | UUID | S | NULL = dado global (SEC, ESMA) |
| `entity_id` | TEXT | S | CRD, CIK, ISIN, UUID do fundo, ou UUID do macro_review |
| `entity_type` | TEXT | N | `"firm"` / `"fund"` / `"macro"` — **nunca** `"manager"` |
| `source_type` | TEXT | N | Discriminador da fonte (9 valores — ver secao 3) |
| `section` | TEXT | S | Sub-secao dentro da fonte (ex: `"investment_philosophy"`) |
| `content` | TEXT | N | Texto embeddado (template-generated, sem LLM) |
| `language` | TEXT | S | Default `"en"` |
| `source_row_id` | TEXT | S | PK da row fonte original |
| `firm_crd` | TEXT | S | CRD da firma gestora — habilita resolucao fund → firma |
| `filing_date` | DATE | S | Data do filing fonte (brochure ADV, N-PORT, 13F) |
| `embedding` | vector(3072) | S | text-embedding-3-large |
| `embedding_model` | TEXT | S | Nome do modelo usado |
| `embedded_at` | TIMESTAMPTZ | S | Quando o embedding foi gerado |
| `created_at` | TIMESTAMPTZ | N | server_default NOW() |
| `updated_at` | TIMESTAMPTZ | N | server_default NOW(), onupdate NOW() |

### Model SQLAlchemy

```
backend/app/domains/wealth/models/wealth_vector_chunk.py
```

- Herda `Base` — **sem** `OrganizationScopedMixin` (org_id nullable)
- `Vector(3072)` via `pgvector.sqlalchemy`
- Sem `lazy="raise"` (tabela standalone, sem relationships)

### Indexes

| Index | Colunas | Tipo | Uso principal |
|-------|---------|------|---------------|
| `wealth_vector_chunks_embedding_hnsw` | `embedding::halfvec(3072)` | HNSW (halfvec_cosine_ops, m=16, ef=64) | Busca semantica |
| `ix_wvc_org` | `organization_id` | B-tree | Filtragem global vs org-scoped |
| `ix_wvc_entity_id` | `entity_id` | B-tree | Lookup por CRD/CIK/ISIN/UUID |
| `ix_wvc_firm_crd` | `firm_crd` | B-tree | Contexto de firma por CRD |
| `ix_wvc_entity` | `(entity_type, entity_id)` | B-tree composto | Filtragem por tipo de entidade |
| `ix_wvc_source` | `(source_type, section)` | B-tree composto | Filtragem por fonte |
| `ix_wvc_org_entity` | `(organization_id, entity_type)` | B-tree composto | Busca org-scoped por tipo |

### Decisoes de design

- **Sem RLS policy**: dados globais (org_id NULL) exigem filtragem por WHERE explicito nas queries, nao por policy de tabela
- **HNSW via halfvec**: pgvector HNSW suporta ate 2000 dims no tipo `vector`, mas `halfvec` suporta ate 4000 — mesmo pattern da migration de `vector_chunks`
- **PK textual composta**: evita sequence/UUID — ID determinado pela fonte, garante idempotencia no upsert
- **Sem texto gerado por LLM**: todo `content` e gerado por template/f-string — custo zero de LLM para texto, apenas para embedding

---

## 3. Fontes de Embedding (9 source_types)

### Dados globais SEC (4 fontes — novas em v2)

#### 3.1 SEC Manager Profiles (source_type=`"sec_manager_profile"`)

| Campo | Valor |
|-------|-------|
| Tabelas fonte | `sec_managers` + `sec_manager_team` + `sec_manager_funds` (counts) |
| entity_type | `"firm"` |
| Escopo | Global (org_id NULL) |
| ID formula | `sec_manager_profile_{crd_number}` |
| entity_id | `crd_number` |
| firm_crd | `crd_number` |
| filing_date | `last_adv_filed_at` |
| Incrementalidade | Re-embed quando `last_adv_filed_at > embedded_at::date` |
| Volume estimado | ~3,000 chunks |

**Conteudo gerado**: Prosa estruturada com firma, localizacao, AUM (total e discretionary), contagem de contas, breakdown por tipo de fundo (private, hedge, PE, VC, real estate), top 3 membros do time (nome + titulo), fee structures (JSONB), client types (JSONB), ultimo ADV filed, compliance disclosures.

**Exemplo de texto embeddado**:
```
Acme Capital LLC (CRD 55555) is a Approved investment adviser based in NY, US.
Total AUM: $5.0B ($4.5B discretionary). Manages 150 accounts.

Fund breakdown: 3 private funds, 2 hedge funds, 1 PE funds.
Total private fund assets: $3.0B.

Investment team (12 professionals): John Doe (CIO), Jane Smith (PM), Bob Lee (Analyst).

Fee structures: performance: True, fixed: True. Client types: institutional: True.
Last ADV filed: 2026-02-01. Compliance disclosures: 2.
```

#### 3.2 SEC Registered Fund Profiles (source_type=`"sec_fund_profile"`)

| Campo | Valor |
|-------|-------|
| Tabelas fonte | `sec_registered_funds` + `sec_fund_classes` + `sec_nport_holdings` (top 10) + `sec_managers` |
| entity_type | `"fund"` |
| Escopo | Global (org_id NULL) |
| ID formula | `sec_fund_profile_{cik}` |
| entity_id | `cik` (fund CIK, NAO firma CIK) |
| firm_crd | `crd_number` (do adviser) |
| filing_date | `last_nport_date` |
| Incrementalidade | Re-embed quando `last_nport_date > embedded_at::date` |
| Volume estimado | ~400 chunks (fundos com N-PORT) |

**Conteudo gerado**: Nome, CIK, tipo (mutual_fund/etf/closed_end/interval_fund), adviser name + CRD, total assets, inception date, share classes (nome + ticker), top 10 holdings do N-PORT mais recente (issuer, sector, % of NAV), sector allocation.

**Exemplo de texto embeddado**:
```
Acme Growth Fund (CIK 0001234567) is a mutual_fund managed by Acme Capital LLC (CRD 55555).
Total assets: $500.0M. Inception: 2015-06-01.
Share classes: Class A (ACMGX), Class I (ACMIX).

Top 10 holdings (as of 2026-03-01):
Apple Inc (Technology): 5.20%; Microsoft Corp (Technology): 4.80%; ...

Sector allocation: Technology, Healthcare, Financials.
```

#### 3.3 SEC 13F Holdings Summaries (source_type=`"sec_13f_summary"`)

| Campo | Valor |
|-------|-------|
| Tabelas fonte | `sec_13f_holdings` + `sec_managers` |
| entity_type | `"firm"` |
| Escopo | Global (org_id NULL) |
| ID formula | `sec_13f_summary_{cik}_{report_date}` |
| entity_id | `cik` (firma CIK do 13F filer) |
| firm_crd | `crd_number` (via `sec_managers.cik` JOIN) |
| filing_date | `report_date` |
| Incrementalidade | Cria chunk novo para cada `report_date` nao processado |
| Volume estimado | ~3,000 chunks |

**Conteudo gerado**: Nome da firma, CIK, CRD, report date, total market value, position count, top 20 holdings (nome, valor, peso %), concentracao (top 5 %, top 10 %), sector breakdown (sector, %).

**Nota sobre versionamento**: O ID inclui `report_date` — cada filing gera um chunk separado. O worker so processa report_dates ainda nao existentes na tabela.

#### 3.4 SEC Private Funds (source_type=`"sec_private_funds"`)

| Campo | Valor |
|-------|-------|
| Tabelas fonte | `sec_manager_funds` + `sec_managers` |
| entity_type | `"firm"` |
| Escopo | Global (org_id NULL) |
| ID formula | `sec_private_funds_{crd_number}` |
| entity_id | `crd_number` |
| firm_crd | `crd_number` |
| filing_date | NULL |
| Incrementalidade | LEFT JOIN, w.id IS NULL |
| Volume estimado | ~2,087 chunks (pos AUM floor) |
| **AUM floor** | `HAVING SUM(gross_asset_value) >= 1_000_000_000` — managers com AUM < $1B excluidos |

**Conteudo gerado**: Nome da firma, CRD, contagem de fundos, total GAV, lista de fundos (nome, tipo com `[strategy_label]` tag, GAV, investor count), fund-of-funds count, breakdown por tipo.

**fund_type** (coluna `sec_manager_funds.fund_type`): corrigido via deteccao de checkbox por imagem JPEG 17x21px nos PDFs do Form ADV Q10. O minoritario entre 6-7 checkboxes = selecionado. Antes: 100% classificado como "Hedge Fund". Apos: distribuicao correta (Private Equity 46%, Hedge Fund 22%, Other 11%, Real Estate 9%, VC 7%, Securitized 5%).

**strategy_label** (coluna `sec_manager_funds.strategy_label`): taxonomia granular com 37 categorias, classificador 3 camadas — (1) regex em cascata no fund_name (~87%), (2) sub-estrategias hedge fund (+2%), (3) enriquecimento via brochure ADV Part 2A (+127 funds). Top labels: Private Equity 32%, Real Estate 9%, VC 6%, Secondaries/Co-Invest 6%, Structured Credit 4%, Private Credit 4%.

**Scripts de backfill**:
- `backend/scripts/backfill_fund_type.py` — 20 workers paralelos, 5,659 PDFs em 7.5 min
- `backend/scripts/backfill_strategy_label.py` — idempotente, ~5s via SQL puro

**Migration**: `0063_add_strategy_label`

### Dados globais ESMA (2 fontes — enriquecidas em v2)

#### 3.5 ESMA Fund Profiles (source_type=`"esma_fund_profile"`)

> Substitui `esma_fund` da v1

| Campo | Valor |
|-------|-------|
| Tabelas fonte | `esma_funds` + `esma_managers` |
| entity_type | `"fund"` |
| Escopo | Global (org_id NULL) |
| ID formula | `esma_fund_profile_{isin}` |
| entity_id | `isin` |
| firm_crd | NULL |
| Volume estimado | ~10,400 chunks |

**Conteudo gerado** (v2 — enriquecido):
```
iShares Core MSCI World (ISIN IE00B4L5Y983) is a UCITS ETF fund domiciled in IE.
Managed by BlackRock Fund Managers (IE). Distributed in: DE, FR, NL.
Yahoo ticker: IWDA.AS.
```

**Comparacao v1**: texto antigo era apenas `"iShares Core MSCI World | UCITS ETF | IE"` — sem gestora, sem distribuicao, sem ticker.

#### 3.6 ESMA Manager Profiles (source_type=`"esma_manager_profile"`)

> Substitui `esma_manager` da v1

| Campo | Valor |
|-------|-------|
| Tabelas fonte | `esma_managers` + COUNT(`esma_funds`) |
| entity_type | `"firm"` |
| Escopo | Global (org_id NULL) |
| ID formula | `esma_manager_profile_{esma_id}` |
| entity_id | `esma_id` |
| firm_crd | `sec_crd_number` (quando cross-registered com SEC) |
| Volume estimado | ~660 chunks |

**Conteudo gerado** (v2 — enriquecido):
```
BlackRock Fund Managers (ESMA ID ESM_001) is a Authorised UCITS management company
based in IE. LEI: 549300ABCDEF123456. Manages 42 UCITS funds across 5 domiciles.
Cross-registered with US SEC as CRD 99999.
```

### Brochures narrativas (1 fonte — inalterada)

#### 3.7 ADV Brochure Sections (source_type=`"brochure"`)

| Campo | Valor |
|-------|-------|
| Tabela fonte | `sec_manager_brochure_text` |
| entity_type | `"firm"` |
| Escopo | Global (org_id NULL) |
| ID formula | `brochure_{crd_number}_{section}` |
| entity_id | `crd_number` |
| firm_crd | `crd_number` |
| filing_date | `filing_date` da brochure |
| Incrementalidade | Re-embed quando `filing_date > embedded_at::date` |
| Volume estimado | ~7,000 chunks (6 secoes x ~1,200 CRDs) |

**Secoes embeddadas** (alto valor semantico):

| Secao | Label prefixado no embedding |
|-------|------------------------------|
| `investment_philosophy` | Investment Philosophy |
| `methods_of_analysis` | Methods of Analysis |
| `advisory_business` | Advisory Business |
| `risk_management` | Risk Management |
| `performance_fees` | Performance Fees |
| `full_brochure` | ADV Part 2A Brochure |

**Secoes excluidas** (operacionais, baixo valor): `brokerage_practices`, `custody`, `code_of_ethics`, `disciplinary`, `client_types`, `fees_compensation`.

**Texto embeddado**: `[{Section Label}] {content[:4000]}`

### Dados org-scoped (2 fontes — inalteradas)

#### 3.8 DD Chapters (source_type=`"dd_chapter"`)

| Campo | Valor |
|-------|-------|
| Tabelas fonte | `dd_chapters` JOIN `dd_reports` |
| entity_type | `"fund"` |
| Escopo | Org-scoped (org_id da dd_report) |
| ID formula | `dd_chapter_{chapter_id}` |
| entity_id | `str(instrument_id)` — via FK `dd_reports.instrument_id` |
| firm_crd | NULL |
| Volume | Crescimento sob demanda (~8 chapters por DD report) |

**Texto embeddado**: `content_md[:6000]`. Filtros: content_md NOT NULL e length > 100 chars.

#### 3.9 Macro Reviews (source_type=`"macro_review"`)

| Campo | Valor |
|-------|-------|
| Tabela fonte | `macro_reviews` |
| entity_type | `"macro"` |
| Escopo | Org-scoped |
| ID formula | `macro_review_{id}_rationale` |
| entity_id | `str(review_id)` |
| firm_crd | NULL |
| section | `"rationale"` |
| Volume | Crescimento mensal (~4 reviews/mes) |

**Texto embeddado**: `decision_rationale[:6000]`. Filtro: length > 50 chars.

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
| Embedding model | `text-embedding-3-large` (3072 dims) |

### Fluxo de execucao

```
run_wealth_embedding()
  ├── pg_try_advisory_lock(900041)
  ├── _cleanup_legacy_source_types(db)           ← one-time: DELETE esma_fund/esma_manager
  ├── _embed_brochure_sections(db)               → source_type="brochure"
  ├── _embed_sec_manager_profiles(db)            → source_type="sec_manager_profile"
  ├── _embed_sec_fund_profiles(db)               → source_type="sec_fund_profile"
  ├── _embed_sec_13f_summaries(db)               → source_type="sec_13f_summary"
  ├── _embed_sec_private_funds(db)               → source_type="sec_private_funds"
  ├── _embed_esma_fund_profiles(db)              → source_type="esma_fund_profile"
  ├── _embed_esma_manager_profiles(db)           → source_type="esma_manager_profile"
  ├── _embed_dd_chapters(db)                     → source_type="dd_chapter"
  ├── _embed_macro_reviews(db)                   → source_type="macro_review"
  └── pg_advisory_unlock(900041)
```

### Padrao de cada `_embed_*`

1. SELECT rows pendentes (LEFT JOIN wealth_vector_chunks, WHERE w.id IS NULL ou data mais recente)
2. Gerar texto por template/f-string (sem chamada LLM)
3. `async_generate_embeddings(texts, batch_size=100)` — OpenAI API
4. `_batch_upsert(db, rows)` com ON CONFLICT DO UPDATE (idempotente)
5. LIMIT 10000 em cada query — se houver mais, proxima execucao processa

### Isolamento de erros

Cada fonte roda em try/except individual. Se uma fonte falha, rollback e continua com as demais. Stats finais reportam sucesso/erro por fonte.

### Migracao legacy

Na primeira execucao apos deploy do v2, `_cleanup_legacy_source_types()` executa:

```sql
DELETE FROM wealth_vector_chunks WHERE source_type = ANY(ARRAY['esma_fund', 'esma_manager'])
```

Remove chunks name-only antigos. Idempotente — se nao ha rows legacy, nao faz nada.

### Trigger HTTP

```
POST /workers/run-wealth-embedding
```

- **Autenticacao**: ADMIN ou INVESTMENT_TEAM role
- **Resposta**: 202 Accepted
- **Idempotencia**: Redis guard — 409 se ja rodando
- **Timeout**: 600s
- **Arquivo**: `backend/app/domains/wealth/routes/workers.py`

### Cadeia de dependencias

```
brochure_download (Sun 03:00) → brochure_extract (Sun 03:30) ─┐
sec_adv_ingestion (monthly)  ──────────────────────────────────┤
sec_13f_ingestion (weekly)   ──────────────────────────────────┤
nport_ingestion (weekly)     ──────────────────────────────────┤
esma_ingestion (Mon 04:00)   ──────────────────────────────────┤
                                                               └→ wealth_embedding (daily 03:00 UTC)
```

---

## 5. Funcoes de Busca

Tres funcoes fund-centric em `backend/ai_engine/extraction/pgvector_search_service.py`. Todas usam cosine similarity via operador `<=>` do pgvector.

### 5.1 `search_fund_firm_context_sync`

**Proposito**: buscar contexto da firma gestora de um fundo especifico.

```python
search_fund_firm_context_sync(
    query_vector=embed("investment philosophy risk management"),
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
- **Fontes encontradas**: brochure, sec_manager_profile, sec_13f_summary, sec_private_funds (todos com firm_crd=X) + esma_manager_profile (via entity_id)

### 5.2 `search_esma_funds_sync`

**Proposito**: busca semantica de fundos UCITS por nome/tipo/domicilio.

```python
search_esma_funds_sync(
    query_vector=embed("global aggregate bond UCITS"),
    domicile_filter="LU",   # opcional — LIKE no content
    top=20,
) -> list[dict]
```

- Filtra `source_type="esma_fund_profile"` (atualizado em v2)
- Retorna `entity_type="fund"` (ESMA funds)
- Sem filtragem por org_id (dados globais)

### 5.3 `search_fund_analysis_sync`

**Proposito**: busca semantica em analises org-scoped (DD chapters, macro reviews).

```python
search_fund_analysis_sync(
    organization_id="uuid-org",     # OBRIGATORIO
    query_vector=embed("risk assessment"),
    instrument_id="uuid-fund",     # opcional — filtra por fundo
    source_type="dd_chapter",      # opcional — filtra por tipo
    top=20,
) -> list[dict]
```

- Sempre filtra por `organization_id` (obrigatorio)
- `instrument_id` filtra `entity_id` para chunks do fundo especifico
- Valida UUIDs via `validate_uuid()` — raise `ValueError` se invalido

### Diagram: query → fontes

```
search_fund_firm_context_sync(sec_crd="X")
  ├── brochure (6 secoes)              entity_type=firm, firm_crd=X
  ├── sec_manager_profile              entity_type=firm, firm_crd=X
  ├── sec_13f_summary                  entity_type=firm, firm_crd=X
  └── sec_private_funds                entity_type=firm, firm_crd=X

search_fund_firm_context_sync(esma_manager_id="Y")
  └── esma_manager_profile             entity_type=firm, entity_id=Y

search_esma_funds_sync()
  └── esma_fund_profile                source_type=esma_fund_profile

search_fund_analysis_sync(org_id="Z")
  ├── dd_chapter                       org-scoped, entity_type=fund
  └── macro_review                     org-scoped, entity_type=macro
```

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
  → instrument.attributes["sec_crd"]          → firm_crd → brochure + sec_manager_profile + 13f + private_funds
  → instrument.attributes["sec_cik"]          → entity_id → sec_fund_profile
  → instrument.attributes["esma_manager_id"]  → entity_id → esma_manager_profile
  → instrument.attributes["isin"]             → entity_id → esma_fund_profile
```

### entity_type permitidos

| entity_type | Significado | Fontes |
|-------------|-------------|--------|
| `"firm"` | RIA / Management Company | brochure, sec_manager_profile, sec_13f_summary, sec_private_funds, esma_manager_profile |
| `"fund"` | Instrumento fundo | sec_fund_profile, esma_fund_profile, dd_chapter |
| `"macro"` | Macro review | macro_review |
| ~~`"manager"`~~ | **PROIBIDO** — manager = PM individual no sistema | — |

### source_type canonica (9 valores)

| source_type | entity_type | Escopo | Tabela fonte principal |
|-------------|-------------|--------|----------------------|
| `brochure` | firm | global | sec_manager_brochure_text |
| `sec_manager_profile` | firm | global | sec_managers |
| `sec_fund_profile` | fund | global | sec_registered_funds |
| `sec_13f_summary` | firm | global | sec_13f_holdings |
| `sec_private_funds` | firm | global | sec_manager_funds |
| `esma_fund_profile` | fund | global | esma_funds |
| `esma_manager_profile` | firm | global | esma_managers |
| `dd_chapter` | fund | org-scoped | dd_chapters |
| `macro_review` | macro | org-scoped | macro_reviews |

### source_types deprecados (v1)

| source_type | Status | Substituido por |
|-------------|--------|-----------------|
| `esma_fund` | **DELETADO** no primeiro run do v2 worker | `esma_fund_profile` |
| `esma_manager` | **DELETADO** no primeiro run do v2 worker | `esma_manager_profile` |

---

## 7. Custo e Volume

### Volume estimado (v2)

| Fonte | Chunks | Tokens/chunk (est.) | Total tokens | Custo ($0.13/1M) |
|-------|--------|---------------------|-------------|-------------------|
| brochure | ~7,000 | ~500 | 3.5M | $0.46 |
| sec_manager_profile | ~3,000 | ~200 | 600k | $0.08 |
| sec_fund_profile | ~400 | ~300 | 120k | $0.02 |
| sec_13f_summary | ~3,000 | ~500 | 1.5M | $0.20 |
| sec_private_funds | ~2,087 (AUM ≥$1B) | ~600 | 1.3M | $0.08 |
| esma_fund_profile | ~10,400 | ~50 | 520k | $0.07 |
| esma_manager_profile | ~660 | ~60 | 40k | $0.01 |
| dd_chapter | crescimento | ~800 | variavel | variavel |
| macro_review | crescimento | ~800 | variavel | variavel |
| **Total (seed)** | **~26,460** | | **~6.9M** | **~$0.92** |

**Custo incremental diario**: centavos — worker so processa rows pendentes.

### Crescimento

| Fonte | Cadencia | Trigger |
|-------|----------|---------|
| brochure | Semanal | brochure_download → brochure_extract |
| sec_manager_profile | Mensal | sec_adv_ingestion |
| sec_fund_profile | Semanal | nport_ingestion |
| sec_13f_summary | Trimestral (filing) | sec_13f_ingestion |
| sec_private_funds | Mensal | sec_adv_ingestion |
| esma_fund_profile | Semanal | esma_ingestion |
| esma_manager_profile | Semanal | esma_ingestion |
| dd_chapter | Sob demanda | Cada DD report gera ~8 chapters |
| macro_review | Mensal | ~4 reviews/mes |

---

## 8. Failure Modes

| Cenario | Mitigacao |
|---------|-----------|
| OpenAI rate limit no seed | Batch size 100, retry com backoff em `async_generate_embeddings` |
| Brochure > 8192 tokens | Truncada a 4000 chars antes do embed |
| Content muito longo (DD/macro) | Truncado a 6000 chars |
| org_id NULL em query org-scoped | `search_fund_analysis_sync` valida UUID obrigatorio |
| DD chapter sem instrument_id | Skip — JOIN com dd_reports garante rows validas |
| Worker falha no meio | Incremental por design, per-source try/except com rollback |
| Lock held por outro processo | Retorna `{"status": "skipped", "reason": "lock_held"}` |
| Embedding model upgrade (dim change) | `embedding_model` e `embedded_at` rastreiam versao — rebuild seletivo |
| N-PORT sem holdings | sec_fund_profile gera texto sem secao de holdings |
| 13F sem match em sec_managers | firma/CRD aparecem como NULL no texto gerado |

---

## 9. Validacao pos-deploy

### SQL de verificacao

```sql
SELECT source_type, COUNT(*) AS chunks,
       ROUND(AVG(length(content))) AS avg_content_len,
       MIN(embedded_at) AS oldest,
       MAX(embedded_at) AS newest
FROM wealth_vector_chunks
GROUP BY source_type
ORDER BY source_type;
```

### Valores esperados

| source_type | Chunks esperados | avg_content_len |
|-------------|-----------------|-----------------|
| `brochure` | ~7,000 | ~2,000 |
| `sec_manager_profile` | ~3,000 | ~500 |
| `sec_fund_profile` | ~400 | ~800 |
| `sec_13f_summary` | ~3,000 | ~1,200 |
| `sec_private_funds` | ~2,087 (managers AUM ≥$1B) | ~600 |
| `esma_fund_profile` | ~10,400 | ~200 |
| `esma_manager_profile` | ~660 | ~200 |
| `dd_chapter` | variavel | ~3,000 |
| `macro_review` | variavel | ~2,000 |
| `esma_fund` | **0** (migrado) | — |
| `esma_manager` | **0** (migrado) | — |

### Verificar que legacy foi limpo

```sql
SELECT source_type, COUNT(*)
FROM wealth_vector_chunks
WHERE source_type IN ('esma_fund', 'esma_manager')
GROUP BY source_type;
-- Esperado: 0 rows
```

---

## 10. Integracao com Engines de Geracao de Conteudo

### Engines que consomem wealth_vector_chunks

| Engine | Funcoes de busca | Chapters/secoes beneficiadas | Complexidade |
|--------|-----------------|------------------------------|-------------|
| `DDReportEngine` | `search_fund_firm_context_sync` (15) + `search_fund_analysis_sync` (10) | manager_assessment, investment_strategy, risk_framework | Sync (ThreadPoolExecutor) |
| `ManagerSpotlight` | `search_fund_firm_context_sync` (15) + `search_fund_analysis_sync` (10) | Narrativa completa do spotlight | Sync (asyncio.to_thread) |
| `FlashReport` | `search_fund_analysis_sync(source_type="macro_review")` | ## Historical Macro Analysis | Sync, event_description como query |
| `InvestmentOutlook` | `search_fund_analysis_sync(source_type="macro_review")` | ## Historical Macro Analysis | Sync, query macro-focused |
| `LongFormReportEngine` Ch7 | `search_fund_firm_context_sync` (3 chunks por fundo, top-5) | Per-Fund Highlights — contexto por fundo | Async via `asyncio.to_thread()` |
| `LongFormReportEngine` Ch8 | `search_fund_analysis_sync(source_type="macro_review")` | Forward Outlook — contexto historico macro | Async via `asyncio.to_thread()` |
| `FactSheetEngine` | — | Nao candidato — output deterministico, sem LLM | — |

### Padrao de injecao (comum a todos os engines sync)

```python
documents: list[dict] = []
try:
    embed_result = generate_embeddings(["<query especifica do engine>"])
    if embed_result.vectors:
        qvec = embed_result.vectors[0]
        chunks = search_fund_firm_context_sync(query_vector=qvec, sec_crd=..., top=15)
        chunks += search_fund_analysis_sync(organization_id=..., query_vector=qvec, top=10)
        documents = chunks
except Exception:
    logger.warning("<engine>_vector_search_failed")
    documents = []
```

### LongFormReport — padrao async

Ch7 e Ch8 usam helpers sync chamados via `asyncio.to_thread()` pois
`LongFormReportEngine` opera com `AsyncSession`:

```python
# Ch7 — per top-5 fund
chunks = await asyncio.to_thread(_search_fund_highlights, fund_sec_crd)

# Ch8 — macro review semantico
chunks = await asyncio.to_thread(_search_macro_review_chunks, organization_id, query_vec)
```

### ManagerSpotlight — resolucao de sec_crd

`_gather_fund_data()` retorna `sec_crd` via `attrs.get("sec_crd")` do
`Instrument.attributes` JSONB. Sem esse campo, `search_fund_firm_context_sync`
receberia `sec_crd=None` e retornaria `[]` silenciosamente.

### Renderizacao nos prompts

Todos os engines renderizam chunks como secao adicional no user content:

- `DDReportEngine` / `ManagerSpotlight`: `## Document Evidence (N chunks)`
- `FlashReport` / `InvestmentOutlook` / `LongFormReport`: `## Historical Macro Analysis`

Cap: 20 chunks por chamada LLM (truncado em `_build_user_content`).

---

## 11. Integracao com DD Report Engine

> Implementado em 2026-03-27, junto com o v2 do worker.

### Como o DDReportEngine consome wealth_vector_chunks

O `DDReportEngine._build_evidence()` chama as funcoes de busca sync
**apos** o executor de queries SQL, antes de montar o `EvidencePack`.

```
_build_evidence()
  ├── ThreadPoolExecutor(max_workers=5)
  │   ├── gather_quant_metrics()
  │   ├── gather_risk_metrics()
  │   ├── gather_sec_nport_data()
  │   ├── gather_sec_13f_data()
  │   └── gather_sec_adv_data()
  │
  ├── gather_sec_adv_brochure()   ← depende de sec_adv.crd_number
  │
  ├── generate_embeddings(["investment philosophy strategy risk management"])
  ├── search_fund_firm_context_sync(sec_crd=X, top=15)  → firm_chunks
  ├── search_fund_analysis_sync(org_id, instrument_id, top=10) → analysis_chunks
  │
  └── build_evidence_pack(documents=firm_chunks + analysis_chunks, ...)
```

### Capítulos que recebem vector context

| Capitulo | Fontes de chunks consumidas |
|----------|----------------------------|
| `manager_assessment` | brochure, sec_manager_profile, sec_13f_summary, sec_private_funds |
| `investment_strategy` | brochure, sec_manager_profile, sec_13f_summary, sec_private_funds |
| `risk_framework` | brochure, sec_manager_profile, sec_13f_summary, sec_private_funds |
| `executive_summary` | dd_chapter (anteriores), macro_review |
| `recommendation` | **nenhum** — `filter_for_chapter()` limpa `documents=[]` (sintese pura) |

### Resolucao de identidade no engine

```python
# attrs = instrument.attributes (JSONB)
sec_crd = attrs.get("sec_crd") or sec_adv.get("crd_number")
# Passado para search_fund_firm_context_sync(sec_crd=sec_crd)
# Se None (UCITS, fundo privado sem CRD): funcao retorna [] imediatamente
```

### Degradacao gracosa

O bloco de vector search e envolvido em `try/except`:
- OpenAI indisponivel → `documents=[]` → capitulos gerados sem RAG
- `wealth_vector_chunks` vazia → funcoes retornam `[]` → sem impacto
- Fundo sem `sec_crd` (UCITS, privado) → `[]` automatico — sem query

### Campo `"documents"` em `_CHAPTER_FIELD_EXPECTATIONS`

Adicionado a `manager_assessment`, `investment_strategy`, `risk_framework`
em `evidence_pack.py`. O `_resolve_field()` ja trata listas:
`val != []` → aparece como `available` em `compute_source_metadata()`.

### Arquivo do engine

```
backend/vertical_engines/wealth/dd_report/dd_report_engine.py
  → _build_evidence()   ← ponto de integracao
backend/vertical_engines/wealth/dd_report/evidence_pack.py
  → _CHAPTER_FIELD_EXPECTATIONS  ← "documents" adicionado
```

---

## 11. Arquivos

### Implementacao

| Arquivo | Descricao |
|---------|-----------|
| `backend/app/domains/wealth/models/wealth_vector_chunk.py` | Model SQLAlchemy (Base, sem OrganizationScopedMixin) |
| `backend/app/core/db/migrations/versions/0059_wealth_vector_chunks.py` | Migration com HNSW halfvec index |
| `backend/app/core/db/migrations/versions/0063_add_strategy_label.py` | strategy_label column em sec_manager_funds |
| `backend/app/domains/wealth/workers/wealth_embedding_worker.py` | Worker com 9 fontes, lock 900_041, AUM floor $1B, strategy_label no texto |
| `backend/ai_engine/extraction/pgvector_search_service.py` | 3 funcoes de busca fund-centric |
| `backend/ai_engine/extraction/embedding_service.py` | async_generate_embeddings (text-embedding-3-large) |
| `backend/app/domains/wealth/routes/workers.py` | POST /workers/run-wealth-embedding |
| `backend/scripts/seed_private_funds.py` | Reescrito com _build_page_fund_type_map() — deteccao de checkbox por imagem JPEG |
| `backend/scripts/backfill_fund_type.py` | Re-parse paralelo (20 workers) dos PDFs ADV para correcao de fund_type |
| `backend/scripts/backfill_strategy_label.py` | Classificador 3 camadas (regex + sub-estrategia + brochure), idempotente |

### Testes

| Arquivo | Cobertura |
|---------|-----------|
| `backend/tests/test_wealth_embedding_worker.py` | 29 testes: model, todas as 9 fontes, cleanup legacy, _format_aum, idempotencia, lock, search |
| `backend/tests/test_dd_report_engine.py` | 40 testes incluindo vector search injection, paralelismo de evidence, degradacao gracosa |
| `backend/tests/test_manager_spotlight.py` | 21 testes incluindo Fund→Instrument migration, vector search injection |
| `backend/tests/test_flash_report.py` | Testes incluindo vector search por event_description |
| `backend/tests/test_investment_outlook.py` | Testes incluindo vector search macro cross-review |
| `backend/tests/test_long_form_report.py` | Testes incluindo Ch7 per-fund search e Ch8 macro search via asyncio.to_thread |

### Referencia

| Arquivo | Descricao |
|---------|-----------|
| `docs/reference/wealth-vector-embedding-reference.md` | Este documento |
| `docs/reference/wealth-vector-embedding-spec.md` | Spec original (v1) |
| `docs/prompts/wealth-embedding-v2-structured-summaries.md` | Prompt de implementacao v2 |
| `docs/prompts/prompt-dd-report-vector-injection.md` | Prompt de implementacao da integracao DD Report |
