# Content Production — Referencia Tecnica

> Status: **Implementado** (2026-04-01) | Feature flag: `FEATURE_WEALTH_CONTENT`
> Migration: `wealth_content` table (org-scoped, RLS) + `wealth_generated_reports` (org-scoped, RLS)
> Concorrencia: `asyncio.Semaphore(4)` content geral + `Semaphore(3)` DD + `Semaphore(2)` Long-Form/Monthly
> SSE: Redis pub/sub via `app.core.jobs.tracker`
> Atualizado: 2026-04-05 — v3: Adicionada secao 13 (Unified Portfolio Report Endpoints), secoes 5.4/5.5 (DD Report + Long-Form Report vector search), secao 14 (Portfolio Workspace integration)

---

## 1. Visao Geral

O sistema de Content Production gera tres tipos de conteudo analitico para comites de investimento:

| Tipo | Classe | Template Jinja2 | Max Tokens | Cooldown |
|------|--------|-----------------|------------|----------|
| **Investment Outlook** | `InvestmentOutlook` | `content/investment_outlook.j2` | 4000 | Nenhum |
| **Flash Report** | `FlashReport` | `content/flash_report.j2` | 3000 | 48h |
| **Manager Spotlight** | `ManagerSpotlight` | `content/manager_spotlight.j2` | 4000 | Nenhum |

Todos os conteudos passam pelo mesmo ciclo de vida:

```
Trigger (POST 202)
  → WealthContent(status="draft")
  → asyncio.create_task (background, semaphore max 3)
  → SSE event "started"
  → asyncio.to_thread(_sync_generate_content)
  → LLM call (OpenAI, Jinja2 system prompt)
  → sanitize_llm_text() (output safety)
  → DB update: content_md, status="review"
  → SSE terminal event "done" | "error"
  → Human review + approval (self-approval blocked)
  → Download PDF (on-demand rendering)
```

**Feature flag:** `settings.feature_wealth_content` (default `False`). Quando desabilitado, todos os endpoints `/content/*` retornam 404.

---

## 2. Modelo de Dados

### Tabela `wealth_content`

| Coluna | Tipo | Nullable | Descricao |
|--------|------|----------|-----------|
| `id` | UUID PK | N | `uuid.uuid4()` |
| `organization_id` | UUID | N | Tenant (RLS via `OrganizationScopedMixin`) |
| `content_type` | VARCHAR(30) | N | `investment_outlook` / `flash_report` / `manager_spotlight` |
| `title` | VARCHAR(255) | N | Titulo display (auto-gerado ou nome do fundo) |
| `language` | VARCHAR(5) | N | `pt` (default) ou `en` |
| `status` | VARCHAR(20) | N | `draft` → `review` → `approved` → `published` |
| `content_md` | TEXT | S | Markdown gerado pelo LLM (corpo do conteudo) |
| `content_data` | JSONB | S | Metadados estruturados (ex: `{instrument_id}` para spotlights) |
| `storage_path` | VARCHAR(500) | S | Path historico de PDF (nao usado no fluxo atual) |
| `created_by` | VARCHAR(128) | N | Actor ID do criador |
| `approved_by` | VARCHAR(128) | S | Nome do aprovador (deve ser != `created_by`) |
| `approved_at` | TIMESTAMPTZ | S | Timestamp da aprovacao |
| `created_at` | TIMESTAMPTZ | N | `server_default=now()` |
| `updated_at` | TIMESTAMPTZ | N | `server_default=now()`, `onupdate=now()` |

**Model SQLAlchemy:** `backend/app/domains/wealth/models/content.py`

**Indices:** `content_type` (filtro por tipo na listagem).

---

## 3. Schemas Pydantic

```
backend/app/domains/wealth/schemas/content.py
```

| Schema | Uso | Campos extras vs ContentSummary |
|--------|-----|--------------------------------|
| `ContentSummary` | Listagem, triggers, approval | — (campos base) |
| `ContentRead` | Detalhe (`GET /{id}`) | `content_md`, `content_data` |
| `ContentTrigger` | Body dos triggers POST | `config_overrides: dict \| None` |

`ContentSummary` expoe: `id`, `content_type`, `title`, `language`, `status`, `storage_path`, `created_by`, `approved_by`, `approved_at`, `created_at`, `updated_at`.

---

## 4. Endpoints da API

```
backend/app/domains/wealth/routes/content.py
Router prefix: /content (tags: content)
```

### 4.1 Triggers (POST, 202 Accepted)

Todos os triggers requerem role `INVESTMENT_TEAM` ou `ADMIN`.

#### `POST /content/outlooks`

Gera um Investment Outlook com narrativa macro global.

| Param | Tipo | Default | Descricao |
|-------|------|---------|-----------|
| `language` | query | `pt` | `pt` ou `en` |
| `body` | ContentTrigger | — | Opcional, `config_overrides` |

**Response:** `ContentSummary` + `job_id` (para SSE streaming).

#### `POST /content/flash-reports`

Gera um Flash Report event-driven. **Cooldown de 48h** entre reports do mesmo org.

| Param | Tipo | Default | Descricao |
|-------|------|---------|-----------|
| `language` | query | `pt` | `pt` ou `en` |
| `body` | ContentTrigger | — | Opcional, `config_overrides` (inclui `event_description`) |

**Response:** `ContentSummary` + `job_id`. Retorna 409 se cooldown ativo.

#### `POST /content/spotlights`

Gera um Manager Spotlight deep-dive para um fundo especifico.

| Param | Tipo | Default | Descricao |
|-------|------|---------|-----------|
| `instrument_id` | query (required) | — | UUID do fundo alvo |
| `language` | query | `pt` | `pt` ou `en` |
| `body` | ContentTrigger | — | Opcional |

**Response:** `ContentSummary` + `job_id`. Retorna 404 se fundo nao existe.

### 4.2 Listagem e Leitura

#### `GET /content`

Lista todos os conteudos do org (ordenados por `created_at DESC`).

| Param | Tipo | Default | Descricao |
|-------|------|---------|-----------|
| `content_type` | query | — | Filtro opcional por tipo |

**Response:** `list[ContentSummary]`

#### `GET /content/{content_id}`

Detalhe completo incluindo `content_md` e `content_data`.

**Response:** `ContentRead`

### 4.3 Aprovacao

#### `POST /content/{content_id}/approve`

Aprova conteudo para distribuicao. **Self-approval bloqueado.**

**Preconditions:**
- Role: `INVESTMENT_TEAM` ou `ADMIN`
- Status: `draft` ou `review`
- `content_md` deve existir (geracao completa)
- `created_by != user.actor_id` (self-approval → 403)

**Efeito:** `status="approved"`, `approved_by=user.name`, `approved_at=now(UTC)`

**Response:** `ContentSummary`

### 4.4 Download PDF

#### `GET /content/{content_id}/download`

Download do PDF renderizado on-demand a partir do `content_md`.

**Preconditions:**
- Status: `approved` ou `published` (draft/review → 403)
- `content_md` deve existir

**Renderizacao:** `_render_content_pdf()` via `asyncio.to_thread()` (ReportLab, sync).

| content_type | Titulo PDF (pt) | Titulo PDF (en) |
|--------------|-----------------|-----------------|
| `investment_outlook` | Perspectiva de Investimento | Investment Outlook |
| `flash_report` | Relatorio Flash de Mercado | Market Flash Report |
| `manager_spotlight` | Destaque do Gestor | Manager Spotlight |

**Response:** `application/pdf`, attachment `{content_type}_{language}.pdf`

### 4.5 SSE Streaming

#### `GET /content/{content_id}/stream/{job_id}`

Stream SSE de progresso da geracao. Usa Redis pub/sub via `app.core.jobs`.

**Auth:** Verifica ownership do job via `verify_job_owner(job_id, org_id)`.

**Eventos emitidos:**

| Evento | Dados | Quando |
|--------|-------|--------|
| `started` | `{content_type, content_id}` | Inicio da geracao |
| `done` | `{status, content_id}` | Geracao concluida (status="review" ou "failed") |
| `error` | `{error, content_id}` | Excecao na geracao |

**Frontend fallback:** Se nenhum evento SSE em 10s, o frontend inicia polling a cada 5s via `invalidateAll()`.

---

## 5. Engines de Geracao

Todos os engines seguem o mesmo padrao:
- **Frozen dataclass result:** Nunca levantam excecao; retornam `status="failed"` com `error`
- **Sync execution:** Rodam dentro de `asyncio.to_thread()` (sync Session)
- **LLM call:** Via `call_openai_fn` injetado (nao importam diretamente)
- **Output safety:** `sanitize_llm_text()` remove HTML/JS malicioso
- **Prompt templates:** Jinja2 via `PromptRegistry` (IP da Netz — nunca exposto ao cliente)
- **PDF dual-stack:** ReportLab (sync, atual) + Playwright (async, migracao em andamento)

### 5.1 Investment Outlook

```
backend/vertical_engines/wealth/investment_outlook.py
```

**Fontes de dados:**

| Fonte | Metodo | Descricao |
|-------|--------|-----------|
| `MacroReview.report_json` | `_gather_macro_data()` | Ultimo snapshot macro do org (regioes, indicadores, score deltas) |
| `wealth_vector_chunks` (pgvector) | `_gather_vector_context()` | 10 chunks de `source_type="macro_review"` semanticamente relevantes |

**Query de embedding:** `"macro economic outlook regional growth inflation monetary policy"`

**Contexto LLM (user message):**
- Macro Data Snapshot (regioes + composite scores)
- Global Indicators (FRED, treasury, etc.)
- Recent Score Changes (deltas flagged > 5 pontos)
- Historical Macro Analysis (ate 15 chunks, 2000 chars cada)

**Labels i18n usados no prompt:** `global_macro_summary`, `regional_outlook`, `asset_class_views`, `portfolio_positioning`, `key_risks`

### 5.2 Flash Report

```
backend/vertical_engines/wealth/flash_report.py
```

**Cooldown:** 48h entre flash reports do mesmo org. Verificado via `check_emergency_cooldown()` do `macro_committee_engine`. Se cooldown ativo, retorna `status="cooldown"` sem chamar LLM.

**Fontes de dados:**

| Fonte | Metodo | Descricao |
|-------|--------|-----------|
| `event_context` (input) | — | Descricao do evento de mercado (`event_description`) |
| `MacroReview.report_json` | `_gather_macro_context()` | Contexto macro atual |
| `wealth_vector_chunks` (pgvector) | `_gather_vector_context()` | 10 chunks relevantes ao evento |

**Query de embedding:** Usa o proprio `event_description` como query semantica (so busca se `event_description` fornecido).

**Contexto LLM (user message):**
- Event (descricao do evento)
- Current Macro Context (regioes + scores)
- Historical Macro Analysis (chunks relevantes)

**Labels i18n usados no prompt:** `market_event`, `market_impact`, `portfolio_positioning`, `recommended_actions`, `key_risks`

### 5.3 Manager Spotlight

```
backend/vertical_engines/wealth/manager_spotlight.py
```

**Fontes de dados:**

| Fonte | Metodo | Descricao |
|-------|--------|-----------|
| `instruments_universe` + `instruments_org` | `_gather_fund_data()` | Identidade do fundo (nome, ISIN, ticker, AUM, gestor, etc.) |
| `sec_registered_funds` + `sec_fund_classes` | `gather_fund_enrichment()` | Strategy label, share classes, expense ratio, classification flags |
| `sec_fund_prospectus_stats` | `gather_prospectus_stats()` | Fee structure (management fee, expense ratio, turnover) — fonte autoritativa |
| `sec_fund_prospectus_returns` | `gather_prospectus_returns()` | Historico de retornos anuais (bar chart do prospecto RR1) |
| `fund_risk_metrics` | `gather_quant_metrics()` | CVaR, Sharpe, volatility, momentum, scoring |
| `fund_risk_metrics` | `gather_risk_metrics()` | Metricas de risco adicionais |
| `wealth_vector_chunks` (firm) | `search_fund_firm_context_sync()` | 15 chunks firm-level (ADV brochure, SEC profile) via `sec_crd` |
| `wealth_vector_chunks` (analysis) | `search_fund_analysis_sync()` | 10 chunks org-scoped (DD chapters, macro reviews) |

**Query de embedding:** `"investment philosophy strategy risk management team"`

**Contexto LLM (user message):**
- Fund Identity (nome, ISIN, ticker, gestor, AUM, geografia, asset class, strategy)
- Fee Structure (prospectus source: expense ratio, management fee, turnover)
- Average Annual Returns (1y, 5y, 10y — prospectus standardized)
- Annual Return History (bar chart from prospectus)
- Quantitative Metrics (CVaR, Sharpe, etc.)
- Risk Metrics
- Document Evidence (ate 20 chunks, 2000 chars cada)

**Labels i18n usados no prompt:** `fund_overview`, `quant_analysis`, `peer_comparison`, `key_risks`

### 5.4 Due Diligence Report (DD Report)

```
backend/vertical_engines/wealth/dd_report/dd_report_engine.py
```

O DD Report tambem utiliza busca semantica para enriquecer o contexto dos capitulos:

**Fontes de dados vetoriais:**

| Fonte | Metodo | Descricao |
|-------|--------|-----------|
| `wealth_vector_chunks` (firm) | `search_fund_firm_context_sync()` | 15 chunks firm-level (ADV brochure, SEC profile) via `sec_crd` |
| `wealth_vector_chunks` (analysis) | `search_fund_analysis_sync()` | 10 chunks org-scoped (DD chapters, macro reviews) via `instrument_id` |

**Query de embedding:** `"investment philosophy strategy risk management"`

**Contexto:** Chapters 1-7 geram em paralelo via `ThreadPoolExecutor(max_workers=5)`. Chapter 8 (Recommendation) roda sequencialmente apos 1-7. `EvidencePack` (frozen dataclass) contem toda a evidencia. Vector search fornece contexto documental para capitulos que requerem evidencia externa.

**Reference:** `dd_report/dd_report_engine.py:401-429`

### 5.5 Long-Form Report

```
backend/vertical_engines/wealth/long_form_report/long_form_report_engine.py
```

O Long-Form Report utiliza duas buscas vetoriais distintas:

**Fontes de dados vetoriais:**

| Fonte | Metodo | Descricao |
|-------|--------|-----------|
| `wealth_vector_chunks` (firm) | `search_fund_firm_context_sync()` | 20 chunks firm-level (highlights da gestora) via `sec_crd` |
| `wealth_vector_chunks` (analysis) | `search_fund_analysis_sync()` | 15 chunks org-scoped `source_type="macro_review"` (outlook macro) |

**Queries de embedding:**
- Fund highlights: `"investment philosophy strategy risk management team"`
- Macro outlook: `"macro economic outlook regional growth inflation monetary policy"`

**Reference:** `long_form_report/long_form_report_engine.py:587-641`

---

## 6. Renderizacao PDF

```
backend/vertical_engines/wealth/content_pdf.py (ReportLab — stack atual)
backend/vertical_engines/wealth/pdf/templates/content_report.py (Playwright — migracao)
```

### 6.1 Stack Atual (ReportLab)

Funcao: `render_content_pdf(content_md, *, title, subtitle="", language="pt") -> BytesIO`

**Estrutura do PDF:**
1. **Cover:** titulo com regua laranja Netz, subtitulo (se fornecido), data formatada, "CONFIDENTIAL — USO INTERNO"
2. **Body:** parsing line-by-line do markdown:
   - `# heading` → estilo `cover_subtitle`
   - `## heading` → estilo `section_heading`
   - Texto plain → estilo `body`
   - Linhas vazias → spacer (2mm)
3. **Footer/Header:** `netz_header_footer()` em todas as paginas
4. **Disclaimer:** texto de disclaimer language-specific

**Estilos:** `build_netz_styles()` + brand colors (NETZ_ORANGE).

### 6.2 Stack Futuro (Playwright)

Cada engine tem `render_pdf_async()` que gera HTML via `render_content_report()` e converte para PDF via `html_to_pdf()` (Playwright headless Chrome). Migracao em andamento.

---

## 7. Workflow de Status

```
draft → review → approved → published
  ↑        ↑        ↑          ↑
  │        │        │          │
Trigger  LLM OK   Human    Manual
 POST    (auto)   Approval  (futuro)
```

### Transicoes

| De | Para | Gatilho | Automatico? |
|----|------|---------|-------------|
| — | `draft` | POST trigger | Sim (criacao) |
| `draft` | `review` | Geracao LLM concluida com `content_md` | Sim (background task) |
| `draft` | `failed` | Excecao na geracao | Sim (background task) |
| `draft` / `review` | `approved` | `POST /{id}/approve` | Nao (human action) |
| `approved` | `published` | — | Nao implementado (futuro) |

### Regras de Governanca

1. **Self-approval bloqueado:** `approved_by != created_by` (verificado no backend E no frontend)
2. **Download requer aprovacao:** Status `approved` ou `published` obrigatorio para `GET /{id}/download`
3. **Role guard:** Triggers e approval requerem `INVESTMENT_TEAM` ou `ADMIN`
4. **ConsequenceDialog:** Frontend exige rationale minima de 10 caracteres para aprovacao
5. **Cooldown:** Flash Report tem cooldown de 48h por organizacao

---

## 8. Frontend

### 8.1 Pagina de Listagem (`/content`)

```
frontends/wealth/src/routes/(app)/content/+page.svelte
frontends/wealth/src/routes/(app)/content/+page.server.ts
```

**Server load:** Busca `GET /content` + `GET /funds` (para picker de spotlight) em paralelo.

**Features:**
- **Tabs:** All, Outlooks, Flash Reports, Spotlights (com contadores)
- **Search:** Input de busca por titulo (client-side, `$derived`)
- **Sort:** Newest first (default), Oldest first, A-Z
- **Card grid:** `repeat(auto-fill, minmax(300px, 1fr))`
- **Generate buttons:** Outlook, Flash Report, Spotlight (com fund picker dialog)
- **Status indicators:** Badge de status + spinner para `draft`
- **Acoes por card:** Approve (com dialog), Download PDF, Retry (para failed)
- **SSE streaming:** Conecta ao stream apos trigger, com fallback para polling 5s

### 8.2 Pagina de Detalhe (`/content/[id]`)

```
frontends/wealth/src/routes/(app)/content/[id]/+page.svelte
frontends/wealth/src/routes/(app)/content/[id]/+page.server.ts
```

**Server load:** Busca `GET /content/{id}` (ContentRead com markdown).

**Layout:**
1. **PageHeader:** Titulo + breadcrumb back to `/content`
2. **Meta bar (sticky):** Type badge, status, language, date, author, approval info
3. **Content body:** Markdown renderizado via `renderMarkdown()` + DOMPurify (max-width 820px)
4. **Content data:** `<details>` colapsavel com grid key-value (metadados JSONB)
5. **State "generating":** Spinner + "Content is being generated..." (quando status=draft e sem content_md)

**Acoes:** Approve (ConsequenceDialog), Download PDF — mesma logica da listagem.

### 8.3 Tipos TypeScript

```
frontends/wealth/src/lib/types/content.ts
```

| Interface | Campos |
|-----------|--------|
| `ContentSummary` | id, content_type, title, language, status, storage_path, created_by, approved_by, approved_at, created_at, updated_at |
| `ContentFull` | extends ContentSummary + content_md, content_data |
| `ContentType` | union: `"investment_outlook" \| "flash_report" \| "manager_spotlight"` |

**Helpers:**
- `contentTypeLabel(type)` → label legivel ("Investment Outlook", "Flash Report", "Manager Spotlight")
- `contentTypeColor(type)` → CSS variable (`--ii-info`, `--ii-warning`, `--ii-success`)

---

## 9. i18n

```
backend/vertical_engines/wealth/fact_sheet/i18n.py → LABELS dict
```

Todos os labels sao acessados via `LABELS[language][key]`.

### Labels de Content

| Key | PT | EN |
|-----|----|----|
| `investment_outlook_title` | Perspectiva de Investimento | Investment Outlook |
| `flash_report_title` | Relatorio Flash de Mercado | Market Flash Report |
| `manager_spotlight_title` | Destaque do Gestor | Manager Spotlight |
| `content_disclaimer` | Este relatorio e produzido pela plataforma InvestIntell... | This report is produced by the InvestIntell platform... |
| `global_macro_summary` | Resumo Macro Global | Global Macro Summary |
| `regional_outlook` | Perspectiva Regional | Regional Outlook |
| `asset_class_views` | Visao por Classe de Ativos | Asset Class Views |
| `portfolio_positioning` | Posicionamento do Portfolio | Portfolio Positioning |
| `key_risks` | Riscos Principais | Key Risks |
| `market_event` | Evento de Mercado | Market Event |
| `market_impact` | Impacto no Mercado | Market Impact |
| `recommended_actions` | Acoes Recomendadas | Recommended Actions |
| `fund_overview` | Visao Geral do Fundo | Fund Overview |
| `quant_analysis` | Analise Quantitativa | Quantitative Analysis |
| `peer_comparison` | Comparacao com Pares | Peer Comparison |

---

## 10. SSE e Concorrencia

### 10.1 Job Tracking (Redis)

```
backend/app/core/jobs/tracker.py
backend/app/core/jobs/sse.py
```

**Fluxo:**
1. Trigger cria `job_id = uuid4()`
2. `register_job_owner(job_id, org_id)` — Redis key `job:{id}:org` com TTL 3600s
3. Background task publica eventos em canal `job:{id}:events`
4. Frontend conecta via `GET /content/{id}/stream/{job_id}`
5. `verify_job_owner()` valida tenant antes de criar stream
6. `create_job_stream()` retorna `EventSourceResponse` (sse-starlette)
7. Terminal event (`done`/`error`) → `publish_terminal_event()` → grace TTL 120s

### 10.2 Semaphore de Geracao

```python
_content_semaphore: asyncio.Semaphore | None = None  # lazy init

def _get_content_semaphore() -> asyncio.Semaphore:
    global _content_semaphore
    if _content_semaphore is None:
        _content_semaphore = asyncio.Semaphore(3)
    return _content_semaphore
```

Max 3 geracoes simultaneas compartilhadas entre todos os tipos de conteudo. Criado lazy dentro de funcao async (regra CLAUDE.md — nunca module-level).

### 10.3 Frontend SSE Pattern

```
fetch() + ReadableStream (NAO EventSource — precisa de auth headers)
```

1. Captura `job_id` da response do POST trigger
2. Conecta SSE via `fetch()` com `Authorization: Bearer {token}`
3. Timer de 10s: se nenhum evento, inicia polling fallback (5s)
4. Eventos terminais (`done`/`error`) → `invalidateAll()` para refresh
5. Cleanup: `AbortController.abort()` em `onDestroy`

---

## 11. Relacao com Outros Subsistemas

### Macro Committee Engine

O `macro_committee_engine.py` gera `WeeklyReportData` persistido em `MacroReview.report_json`. Os engines de content **leem** esse dado como contexto macro:

- `InvestmentOutlook._gather_macro_data()` → ultimo `MacroReview.report_json`
- `FlashReport._gather_macro_context()` → ultimo `MacroReview.report_json`
- `FlashReport._get_last_flash_report_time()` → cooldown check via `check_emergency_cooldown()`

### Wealth Vector Embedding

Os engines usam busca semantica no `wealth_vector_chunks` para enriquecer o contexto LLM:

| Engine | Source Types Buscados | Scope | Top K |
|--------|----------------------|-------|-------|
| InvestmentOutlook | `macro_review` | org-scoped | 10 |
| FlashReport | `macro_review` (event-driven) | org-scoped | 10 |
| ManagerSpotlight | firm chunks (brochure, sec_profile) + analysis chunks (dd_chapter, macro_review) | global (firm) + org (analysis) | 15 + 10 |
| DDReport | firm chunks (brochure, sec_profile) + analysis chunks (dd_chapter, macro_review) | global (firm) + org (analysis) | 15 + 10 |
| LongFormReport | firm chunks (highlights) + analysis chunks (macro_review) | global (firm) + org (analysis) | 20 + 15 |

**Nota:** Existem duas tabelas pgvector distintas no sistema:
- `vector_chunks` — Dominio Credit (deals, documentos de credito)
- `wealth_vector_chunks` — Dominio Wealth (analyses org-scoped, macro reviews, firm profiles)

### DD Report / Quant Injection

O ManagerSpotlight e o DDReport reutilizam funcoes compartilhadas para enriquecimento de dados:

**Quant & Risk Metrics:**
- `gather_quant_metrics()` — metricas quant do `fund_risk_metrics`
- `gather_risk_metrics()` — metricas de risco do `fund_risk_metrics`

**Fund-Level SEC Data (N-PORT para registered US funds):**
- `gather_sec_nport_data()` — fund portfolio holdings, sector allocation, fund style (PRIMARY para registered_us)

**Manager-Level SEC Data:**
- `gather_sec_13f_data()` — firm sector weights, drift detection (SUPPLEMENTARY)
- `gather_sec_adv_data()` — manager profile, AUM history, compliance
- `gather_sec_adv_brochure()` — narrative sections from ADV Part 2A

**Fee & Prospectus Data:**
- `gather_fund_enrichment()` — SEC N-CEN classification flags, share classes, vehicle-specific data
- `gather_prospectus_stats()` — fee structure do DERA RR1
- `gather_prospectus_returns()` — historico de retornos anuais

### Output Safety

Todos os outputs LLM passam por `sanitize_llm_text()` (`ai_engine/governance/output_safety.py`) que remove HTML/JS malicioso antes de persistir no `content_md`.

### Prompt Templates (IP)

Templates Jinja2 em `ai_engine/prompts/content/`:
- `investment_outlook.j2`
- `flash_report.j2`
- `manager_spotlight.j2`

Renderizados via `PromptRegistry` com `SandboxedEnvironment`. **Nunca expostos em respostas client-facing** (regra CLAUDE.md).

---

## 12. Arquivos-Chave

### Backend

| Arquivo | Descricao |
|---------|-----------|
| `backend/app/domains/wealth/models/content.py` | ORM model `WealthContent` |
| `backend/app/domains/wealth/schemas/content.py` | Pydantic schemas (ContentSummary, ContentRead, ContentTrigger) |
| `backend/app/domains/wealth/routes/content.py` | Todos os endpoints (triggers, list, read, approve, download, SSE) |
| `backend/vertical_engines/wealth/investment_outlook.py` | Engine Investment Outlook |
| `backend/vertical_engines/wealth/flash_report.py` | Engine Flash Report (com cooldown 48h) |
| `backend/vertical_engines/wealth/manager_spotlight.py` | Engine Manager Spotlight (fund-centric) |
| `backend/vertical_engines/wealth/content_pdf.py` | Renderizacao PDF (ReportLab, stack atual) |
| `backend/vertical_engines/wealth/pdf/templates/content_report.py` | Renderizacao PDF (Playwright, migracao) |
| `backend/vertical_engines/wealth/macro_committee_engine.py` | WeeklyReportData + cooldown check |
| `backend/vertical_engines/wealth/fact_sheet/i18n.py` | Labels PT/EN para todos os tipos |
| `backend/ai_engine/prompts/content/` | Templates Jinja2 (system prompts) |
| `backend/ai_engine/governance/output_safety.py` | `sanitize_llm_text()` |
| `backend/app/core/jobs/tracker.py` | Job ownership, pub/sub, TTL management |
| `backend/app/core/jobs/sse.py` | `create_job_stream()` (EventSourceResponse) |

### Frontend

| Arquivo | Descricao |
|---------|-----------|
| `frontends/wealth/src/routes/(app)/content/+page.server.ts` | Server load (list + funds) |
| `frontends/wealth/src/routes/(app)/content/+page.svelte` | Listagem com tabs, search, sort, SSE |
| `frontends/wealth/src/routes/(app)/content/[id]/+page.server.ts` | Server load (detail) |
| `frontends/wealth/src/routes/(app)/content/[id]/+page.svelte` | Detalhe com markdown reader, approve, download |
| `frontends/wealth/src/lib/types/content.ts` | Types + helpers (label, color) |
| `frontends/wealth/src/lib/utils/render-markdown.ts` | Markdown → HTML sanitizado (DOMPurify) |

---

## 13. Unified Portfolio Report Endpoints

> Adicionado: 2026-04-05 — Integra report generation no Portfolio Workspace via endpoints unificados com SSE progress tracking.

### 13.1 Motivacao

Os endpoints originais de geracao de reports estao espalhados em route files separados (`fact_sheets.py`, `long_form_reports.py`, `monthly_report.py`). O Portfolio Workspace precisa de uma API unificada para:
- Listar todos os reports de um portfolio em um unico request
- Disparar geracao de qualquer tipo de report via um unico endpoint
- Acompanhar progresso via SSE com stages granulares

### 13.2 Modelo de Dados — `wealth_generated_reports`

```
backend/app/domains/wealth/models/generated_report.py
```

Tabela persistente (desacoplada de Redis TTL) para registro permanente de PDFs gerados:

| Coluna | Tipo | Nullable | Descricao |
|--------|------|----------|-----------|
| `id` | UUID PK | N | `uuid.uuid4()` |
| `organization_id` | UUID | N | Tenant (RLS via `OrganizationScopedMixin`) |
| `portfolio_id` | UUID | N | Portfolio alvo (indexado) |
| `report_type` | VARCHAR(50) | N | `fact_sheet` / `long_form_dd` / `monthly_report` (indexado) |
| `job_id` | VARCHAR(128) | N | Identificador unico do job (unique constraint) |
| `storage_path` | VARCHAR(800) | N | Path completo no StorageClient (R2 prod, LocalStorage dev) |
| `display_filename` | VARCHAR(300) | N | Nome legivel para Content-Disposition |
| `generated_at` | TIMESTAMPTZ | N | `server_default=now()` |
| `generated_by` | VARCHAR(128) | S | Actor ID do criador |
| `size_bytes` | INTEGER | S | Tamanho do PDF em bytes |
| `status` | VARCHAR(20) | N | `completed` / `failed` |

### 13.3 Schemas Pydantic

```
backend/app/domains/wealth/schemas/generated_report.py
```

| Schema | Uso | Campos chave |
|--------|-----|--------------|
| `ReportGenerateRequest` | Body do POST trigger | `report_type` (Literal), `as_of_date`, `language`, `format` |
| `ReportGenerateResponse` | Response do POST | `job_id`, `portfolio_id`, `report_type`, `status` |
| `ReportHistoryItem` | Item da listagem | Todos os campos da tabela via `from_attributes=True` |
| `ReportHistoryResponse` | Response do GET list | `portfolio_id`, `reports[]`, `total` |

`ReportType = Literal["fact_sheet", "long_form_dd", "monthly_report"]`

### 13.4 Endpoints Unificados

```
Router: backend/app/domains/wealth/routes/model_portfolios.py
Prefix: /model-portfolios (tags: model-portfolios)
```

#### `GET /model-portfolios/{portfolio_id}/reports`

Lista historico de reports do portfolio. Consulta `WealthGeneratedReport` (apenas `status="completed"`).

| Param | Tipo | Default | Descricao |
|-------|------|---------|-----------|
| `report_type` | query | — | Filtro opcional: `fact_sheet`, `long_form_dd`, `monthly_report` |
| `limit` | query | 50 | Max resultados (1-200) |

**Response:** `ReportHistoryResponse` (JSON)

#### `POST /model-portfolios/{portfolio_id}/reports/generate`

Dispara geracao em background. Requer `INVESTMENT_TEAM` ou `ADMIN`.

| Param | Tipo | Default | Descricao |
|-------|------|---------|-----------|
| body | `ReportGenerateRequest` | — | `report_type` (required), `as_of_date`, `language`, `format` |

**Preconditions:**
- Portfolio existe
- `fund_selection_schema` presente (senao → 400)
- Role IC/Admin

**Response:** `{"job_id": str, "portfolio_id": str, "report_type": str, "status": "accepted"}` (202 Accepted)

**Job ID prefixes:**
- `fs-{portfolio_id}-{hex8}` — fact_sheet
- `lfr-{portfolio_id}-{hex8}` — long_form_dd
- `mcr-{portfolio_id}-{hex8}` — monthly_report

#### `GET /model-portfolios/{portfolio_id}/reports/stream/{job_id}`

SSE stream de progresso. Tenant-isolated via `verify_job_owner()`.

### 13.5 Pipeline de Geracao em Background

A funcao `_run_report_generation()` despacha para handlers especificos:

```
POST /reports/generate
  → asyncio.create_task(_run_report_generation)
  → publish_event("progress", stage="QUEUED", pct=0)
  → dispatch por report_type:
      fact_sheet  → _generate_fact_sheet_job()
      long_form_dd → _generate_long_form_job()
      monthly_report → _generate_monthly_report_job()
  → publish_terminal_event("done" | "error")
```

**Stages SSE publicados:**

| Stage | Descricao | pct aprox |
|-------|-----------|-----------|
| `QUEUED` | Job aceito, aguardando slot | 0% |
| `FETCHING_MARKET_DATA` | Carregando portfolio + dados de mercado | 10% |
| `RUNNING_QUANT_ENGINE` | Computando metricas quant e atribuicao | 25% |
| `SYNTHESIZING_LLM` | Gerando capitulos via LLM (long-form: per-chapter events) | 25-65% |
| `GENERATING_PDF` | Renderizando PDF (Playwright/ReportLab) | 70% |
| `STORING_PDF` | Upload para StorageClient (R2/LocalStorage) | 85% |
| `COMPLETED` | Terminal (via "done" event) | 100% |

**Backpressure:** Cada tipo usa o semaphore compartilhado do sistema existente:
- Fact Sheet: `require_content_slot()` (Semaphore(4) do `common.py`)
- Long-Form DD: Session + engine async (sem semaphore adicional no unified — o original tem `Semaphore(2)`)
- Monthly Report: Session + engine async (mesmo padrao)

**Persistencia:** Cada handler:
1. Gera PDF via engine especifico
2. Upload para StorageClient (R2 prod, LocalStorage dev)
3. Persiste `WealthGeneratedReport` record (sobrevive Redis TTL)
4. Publica terminal SSE event com `storage_path` e `size_bytes`

### 13.6 Relacao com Endpoints Originais

Os endpoints unificados **coexistem** com os originais. Nao substituem:

| Original | Unified | Nota |
|----------|---------|------|
| `POST /fact-sheets/model-portfolios/{id}` | `POST /model-portfolios/{id}/reports/generate` (type=fact_sheet) | Original retorna inline; unified retorna job_id |
| `POST /reporting/.../long-form-report` | `POST /model-portfolios/{id}/reports/generate` (type=long_form_dd) | Ambos criam WealthGeneratedReport |
| `POST /reporting/.../monthly-report` | `POST /model-portfolios/{id}/reports/generate` (type=monthly_report) | Ambos criam WealthGeneratedReport |
| `GET /reporting/.../history` (por tipo) | `GET /model-portfolios/{id}/reports` (todos os tipos) | Unified agrega todos em uma query |

---

## 14. Portfolio Workspace — Reporting Integration

> Adicionado: 2026-04-05 — Frontend: store Svelte 5, componentes ReportVault/ReportGeneratorCard/JobProgressTracker.

### 14.1 Store: `portfolio-reports.svelte.ts`

```
frontends/wealth/src/lib/stores/portfolio-reports.svelte.ts
```

**State (Svelte 5 runes):**
- `$state<ReportHistoryItem[]>` — historico de reports, seeded do SSR
- `$state<ActiveJob[]>` — jobs em andamento com SSE tracking

**Interface publica:**

| Propriedade/Metodo | Tipo | Descricao |
|--------------------|------|-----------|
| `reports` | `ReportHistoryItem[]` | Historico de reports (reativo) |
| `reportsLoading` | `boolean` | Loading state do fetch |
| `reportsError` | `string \| null` | Erro do ultimo fetch |
| `refreshReports()` | `() => void` | Refetch manual |
| `activeJobs` | `ActiveJob[]` | Jobs em andamento |
| `hasActiveJobs` | `boolean` | Tem algum job "running" |
| `triggerGeneration(req)` | `(ReportGenerateRequest) => Promise<string \| null>` | Dispara geracao + conecta SSE |
| `destroy()` | `() => void` | Aborta todas as SSE connections |

**SSE Lifecycle:**
1. `triggerGeneration()` faz `POST /reports/generate` → recebe `job_id`
2. Cria `ActiveJob` no array com `stage=QUEUED`, `status=running`
3. Conecta SSE via `fetch()` + `ReadableStream` (auth headers)
4. Parseia eventos line-by-line (manual buffer management)
5. `handleSSEMessage()` atualiza `ActiveJob` reativo
6. On `done` → marca completed + `fetchReports()` para refresh
7. On `error` → marca failed com mensagem
8. `destroy()` → `AbortController.abort()` em todas as connections

### 14.2 Componentes UI

#### `ReportVault.svelte`

```
frontends/wealth/src/lib/components/model-portfolio/ReportVault.svelte
```

Tabela institucional de todos os reports gerados:
- **Filtro por tipo:** dropdown (All, Fact Sheets, Long-Form DD, Monthly Reports)
- **Colunas:** Type (badge colorido), Filename, Generated At, Size, Download
- **Badges:** `rv-badge--factsheet` (info), `rv-badge--longform` (success), `rv-badge--monthly` (warning)
- **Download:** `api.getBlob()` por endpoint especifico do tipo (fact-sheet, long-form, monthly)

#### `ReportGeneratorCard.svelte`

```
frontends/wealth/src/lib/components/model-portfolio/ReportGeneratorCard.svelte
```

Seletor de tipo de report + trigger:
- **Report Type:** select com 3 opcoes (labels de `REPORT_TYPE_LABELS`)
- **Language:** PT/EN toggle
- **Format:** Executive/Institutional (visivel apenas para fact_sheet)
- **Generate button:** disabled quando `!canGenerate || generating`
- **Descricao dinamica** por tipo selecionado

#### `JobProgressTracker.svelte`

```
frontends/wealth/src/lib/components/model-portfolio/JobProgressTracker.svelte
```

Visualizacao step-based do pipeline de geracao:
- **7 stages:** QUEUED → FETCHING_MARKET_DATA → RUNNING_QUANT_ENGINE → SYNTHESIZING_LLM → GENERATING_PDF → STORING_PDF → COMPLETED
- **Dots com estados:** completed (green), active (blue pulse animation), pending (gray), failed (red)
- **Progress bar:** width animado por `pct` (transition 300ms)
- **Message:** texto descritivo do stage atual (long-form: per-chapter updates)
- **Error display:** mensagem de erro em vermelho quando `status=failed`

### 14.3 Integracao no Portfolio Workspace

```
frontends/wealth/src/routes/(app)/portfolio/models/[portfolioId]/+page.svelte
frontends/wealth/src/routes/(app)/portfolio/models/[portfolioId]/+page.server.ts
```

**Server load:** Adicionado `GET /model-portfolios/{id}/reports` ao `Promise.all()` do `+page.server.ts`. Retorna `unifiedReports: ReportHistoryResponse` como prop.

**Page integration:** `createPortfolioReportsStore()` inicializado no `onMount()` junto com o `PortfolioWorkspaceStore`. O store recebe `initialReports` do SSR para hydration imediata. `destroy()` chamado no cleanup function do `onMount`.

**Layout no workbench:** Secao "Reporting & Documentation" posicionada entre Drift/Rebalance e o painel legado `GeneratedReportsPanel` (mantido por backward compatibility):

```
1. JobProgressTracker (jobs ativos — SSE progress)
2. ReportGeneratorCard (seletor + trigger)
3. ReportVault (tabela de historico unificada)
4. GeneratedReportsPanel (legacy — monthly + long-form com triggers simples)
```

### 14.4 Tipos TypeScript

```
frontends/wealth/src/lib/types/model-portfolio.ts
```

**Tipos adicionados:**

| Tipo | Descricao |
|------|-----------|
| `ReportType` | `"fact_sheet" \| "long_form_dd" \| "monthly_report"` |
| `ReportStage` | 7 stages do pipeline SSE |
| `ReportHistoryItem` | Item da listagem unificada |
| `ReportHistoryResponse` | Response do GET list |
| `ReportGenerateRequest` | Body do POST trigger |
| `ReportGenerateResponse` | Response do POST |
| `ReportProgressEvent` | Evento SSE "progress" (stage, message, pct, chapter?) |
| `ReportDoneEvent` | Evento SSE terminal "done" |
| `ReportErrorEvent` | Evento SSE terminal "error" |
| `ReportSSEEvent` | Discriminated union dos 3 tipos de evento |
| `REPORT_TYPE_LABELS` | Map type → label legivel |
| `REPORT_STAGE_LABELS` | Map stage → label legivel |

### 14.5 Arquivos Adicionados

| Arquivo | Descricao |
|---------|-----------|
| `backend/app/domains/wealth/schemas/generated_report.py` | Pydantic schemas do report unificado |
| `backend/tests/test_portfolio_report_endpoints.py` | 6 schema tests + 7 integration tests |
| `frontends/wealth/src/lib/stores/portfolio-reports.svelte.ts` | Svelte 5 store com SSE lifecycle |
| `frontends/wealth/src/lib/components/model-portfolio/ReportVault.svelte` | Tabela institucional de reports |
| `frontends/wealth/src/lib/components/model-portfolio/ReportGeneratorCard.svelte` | Seletor + trigger de geracao |
| `frontends/wealth/src/lib/components/model-portfolio/JobProgressTracker.svelte` | Progress tracker SSE step-based |

### 14.6 Testes

```bash
# Schema unit tests (sem DB)
python -m pytest backend/tests/test_portfolio_report_endpoints.py -k "not anyio" -v

# Integration tests (requerem DB + Redis)
python -m pytest backend/tests/test_portfolio_report_endpoints.py -v

# Lint
python -m ruff check backend/app/domains/wealth/schemas/generated_report.py backend/tests/test_portfolio_report_endpoints.py
```
