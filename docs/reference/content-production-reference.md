# Content Production — Referencia Tecnica

> Status: **Implementado** (2026-04-01) | Feature flag: `FEATURE_WEALTH_CONTENT`
> Migration: `wealth_content` table (org-scoped, RLS)
> Concorrencia: `asyncio.Semaphore(3)` — max 3 geracoes simultaneas
> SSE: Redis pub/sub via `app.core.jobs.tracker`

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

| Engine | Source Types Buscados | Scope |
|--------|----------------------|-------|
| InvestmentOutlook | `macro_review` | org-scoped |
| FlashReport | `macro_review` | org-scoped |
| ManagerSpotlight | firm chunks (brochure, sec_profile) + analysis chunks (dd_chapter, macro_review) | global (firm) + org (analysis) |

### DD Report / Quant Injection

O ManagerSpotlight reutiliza funcoes do DD Report para enriquecimento de dados:

- `gather_quant_metrics()` — metricas quant do `fund_risk_metrics`
- `gather_risk_metrics()` — metricas de risco do `fund_risk_metrics`
- `gather_fund_enrichment()` — SEC N-CEN flags + share classes
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
