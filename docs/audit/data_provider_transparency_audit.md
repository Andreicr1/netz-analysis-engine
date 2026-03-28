# Data Provider Transparency Audit

**Date:** 2026-03-27
**Scope:** Backend `/esma/*` endpoint lifecycle + Frontend data-provider label exposure
**Principle:** The frontend never exposes the origin of fund data. SEC and ESMA are internal data providers — users see "Mutual Funds", "Private Funds", "UCITS".

---

## Parte 1 — Status dos endpoints /esma/* no backend

### 1.1 Consumidores internos

Os 5 endpoints `/esma/*` **não têm consumidores internos no backend**. Nenhum worker, engine ou service chama esses endpoints via HTTP. O fluxo real é:

| Componente | Acesso a dados ESMA | Via |
|---|---|---|
| `esma_ingestion` worker | Direto em `esma_funds`, `esma_managers` | SQLAlchemy ORM |
| `wealth_embedding_worker` | Direto em `esma_funds`, `esma_managers` | SQLAlchemy query |
| `screener.py` routes | Direto em `esma_funds` | SQLAlchemy Core (`_build_esma_query()`) |
| `catalog_sql.py` | Direto em `esma_funds` JOIN `esma_managers` | SQLAlchemy Core (UNION ALL branch) |
| `esma_import_service.py` | Direto em `esma_funds`, `esma_managers` | SQLAlchemy ORM |
| DD Report engines | Indireto via `wealth_vector_chunks` | pgvector search |

**Conclusão:** Os endpoints são puramente HTTP para navegação standalone de dados ESMA. Toda a lógica interna acessa as tabelas diretamente.

### 1.2 Router ESMA

- **Arquivo:** `backend/app/domains/wealth/routes/esma.py`
- **Registrado em main.py:** SIM (linha 93 import, linha 396 `api_v1.include_router(wealth_esma_router)`)
- **Endpoints:**
  - `GET /esma/managers` — lista paginada com filtros
  - `GET /esma/managers/{esma_id}` — detalhe com fundos
  - `GET /esma/funds` — lista paginada com filtros
  - `GET /esma/funds/{isin}` — detalhe com manager
  - `GET /esma/managers/{esma_id}/sec-crossref` — cross-reference SEC CRD
- **Frontend consumers:** ZERO (confirmado em R1 e R2 do endpoint_gaps_verification)
- **Schemas:** `backend/app/domains/wealth/schemas/esma.py` — 6 Pydantic models dedicados
- **Query builder:** `backend/app/domains/wealth/queries/esma_sql.py`
- **Testes:** `backend/tests/routes/test_esma_endpoints.py`
- **Recomendação:** DEPRECAR — endpoints são orphaned, toda funcionalidade absorvida pelo Unified Catalog (`/screener/catalog`)

### 1.3 Workers ESMA

- **Worker:** `backend/app/domains/wealth/workers/esma_ingestion.py`
- **Lock ID:** 900_023
- **Trigger HTTP:** `POST /workers/esma` (via `workers.py` linha 644)
- **Escrita:** Direta em tabelas PostgreSQL, nunca via endpoints `/esma/*`
  - Fase 1-3: `pg_insert().on_conflict_do_update()` em `esma_managers` e `esma_funds`
  - Fase 4: Update `esma_isin_ticker_map` e `esma_funds.yahoo_ticker`
- **Tabelas de destino:** `esma_managers`, `esma_funds`, `esma_isin_ticker_map` (todas globais, sem RLS)

### 1.4 Componentes dependentes (tabelas ESMA, não endpoints)

Os seguintes componentes dependem das **tabelas** `esma_funds`/`esma_managers` (e devem ser preservados):

| Componente | Arquivo | Dependência |
|---|---|---|
| Catalog UNION ALL (ucits_eu branch) | `queries/catalog_sql.py:353-416` | `esma_funds` JOIN `esma_managers` |
| ESMA fund import | `services/esma_import_service.py` | `esma_funds`, `esma_managers`, `esma_isin_ticker_map` |
| Wealth embedding (sources B+C) | `workers/wealth_embedding_worker.py:163-254` | `esma_funds`, `esma_managers` |
| Screener ESMA query | `routes/screener.py:417-475` | `esma_funds` |
| Screener facets | `routes/screener.py:740-756` | `esma_funds` count |

---

## Parte 2 — Violações de Data Provider Transparency no Frontend

### Violações encontradas

| # | Arquivo | Linha | Conteúdo | Severidade |
|---|---|---|---|---|
| 1 | `screener/InstrumentDetailPanel.svelte` | 84 | Badge exibe `source` raw: "sec", "esma", "internal" | **ALTA** |
| 2 | `screener/InstrumentDetailPanel.svelte` | 109 | Texto: `"ESMA fund"` / `"US security"` hardcoded | **ALTA** |
| 3 | `screener/InstrumentDetailPanel.svelte` | 135 | Metadata label: `{ label: "Source", value: source }` | **ALTA** |
| 4 | `screener/CatalogDetailPanel.svelte` | 129 | Disclosure: "N-PORT" / "13F" como label visível | **ALTA** |
| 5 | `screener/CatalogDetailPanel.svelte` | 135 | Disclosure: "YFinance" como label visível | **ALTA** |
| 6 | `screener/CatalogDetailPanel.svelte` | 153 | Disclosure: "Schedule D" como label visível | **ALTA** |
| 7 | `screener/CatalogDetailPanel.svelte` | 159 | Disclosure: "13F Overlay" como label visível | **ALTA** |
| 8 | `screener/CatalogDetailPanel.svelte` | 206 | Texto: "Style snapshots require N-PORT filings (US Registered funds only)" | **MÉDIA-ALTA** |
| 9 | `screener/CatalogDetailPanel.svelte` | 194 | Texto referencia `UNIVERSE_LABELS[fund.universe]` — labels OK mas contexto expõe | **MÉDIA** |
| 10 | `screener/InstrumentTable.svelte` | 143 | Lógica: `source === "esma" \|\| source === "sec"` | **MÉDIA** |
| 11 | `screener/InstrumentDetailPanel.svelte` | 34, 37 | Endpoints hardcoded: `/import-esma/`, `/import-sec/` | **MÉDIA** |
| 12 | `screener/CatalogDetailPanel.svelte` | 61, 64 | Endpoints hardcoded: `/import-esma/`, `/import-sec/` | **MÉDIA** |
| 13 | `routes/(app)/screener/+page.svelte` | 116, 119 | Endpoints hardcoded: `/import-esma/`, `/import-sec/` | **MÉDIA** |
| 14 | `screener/screener.css` | 983-985 | CSS classes: `.source-badge--esma`, `.source-badge--sec` | **MÉDIA** |
| 15 | `lib/types/screening.ts` | 64 | TypeScript enum: `source: "internal" \| "esma" \| "sec"` | **MÉDIA** |

### CRD como identificador SEC

| Arquivo | Linha | Conteúdo | Severidade |
|---|---|---|---|
| `routes/(app)/screener/+page.svelte` | 480 | `CRD {manager.crd_number}` | **BAIXA-MÉDIA** |
| `screener/ManagerDetailPanel.svelte` | 155 | Label: "CRD" + valor | **BAIXA-MÉDIA** |
| `screener/ManagerHierarchyTable.svelte` | 130 | `CRD {manager.crd_number}` | **BAIXA-MÉDIA** |
| `screener/PeerComparisonView.svelte` | 40 | `CRD {mgr.crd_number}` | **BAIXA-MÉDIA** |

**Nota:** CRD (Central Registration Depository) é um identificador regulatório SEC. Exibir "CRD" como label expõe indiretamente que o dado vem do SEC. Labels mais neutros: "Registration #" ou "Reg. ID".

### Filtros do screener

- **Universe labels (catalog.ts:93-97):** CONFORME
  ```typescript
  UNIVERSE_LABELS = {
    registered_us: "US Registered",
    private_us: "US Private",
    ucits_eu: "EU UCITS"
  }
  ```
  Labels traduzem chaves internas para nomes orientados ao usuário. Não mencionam "SEC" ou "ESMA".

- **Valores internos:** `registered_us`, `private_us`, `ucits_eu` são usados como chaves de filtro (não visíveis como texto raw). CONFORME.

- **Recomendação menor:** "US Registered" implica registro SEC; considerar "Mutual Funds". "EU UCITS" é aceitável (UCITS é a classificação do produto, não do provedor).

### Import buttons

- **Texto dos botões:** "Add to Review" / "Send to DD Review" — CONFORME (neutro)
- **URLs das chamadas API:** VIOLAÇÃO — URLs `/screener/import-esma/{isin}` e `/screener/import-sec/{ticker}` expõem provedor no path. Embora não visíveis ao usuário na UI, violam o princípio de transparência no código.

---

## Parte 3 — Schema da API

### Campos de origem retornados pela API

| Campo | Endpoint | Valores | Uso no frontend |
|---|---|---|---|
| `universe` | `/screener/catalog` | `registered_us`, `private_us`, `ucits_eu` | Filtro interno + label traduzido via `UNIVERSE_LABELS` — **CONFORME** |
| `source` | `/screener/search` | `internal`, `esma`, `sec` | Badge visível raw — **VIOLAÇÃO** |
| `disclosure.holdings_source` | `/screener/catalog` | `nport`, `13f` | Exibido como "N-PORT" / "13F" — **VIOLAÇÃO** |
| `disclosure.has_nav_history` | `/screener/catalog` | boolean | Exibido como "YFinance" — **VIOLAÇÃO** |
| `disclosure.has_private_fund_data` | `/screener/catalog` | boolean | Exibido como "Schedule D" — **VIOLAÇÃO** |
| `disclosure.has_13f_overlay` | `/screener/catalog` | boolean | Exibido como "13F Overlay" — **VIOLAÇÃO** |
| `external_id` | `/screener/catalog` | CIK, UUID, ISIN | Não exibido como label — **CONFORME** |
| `manager_id` | `/screener/catalog` | CRD, esma_id | Não exibido diretamente — **CONFORME** |
| `esma_manager_id` | Import response attrs | ESMA ID | Armazenado em instrument attributes — **CONFORME** (interno) |

### Campos `sec_crd`, `esma_id` em componentes screener

- `sec_crd`: Não encontrado como label visível em componentes screener de fundos
- `esma_id`: Usado apenas internamente para import flow, não exibido
- `crd_number`: Exibido como "CRD {number}" em 4 arquivos do manager screener (ver tabela acima)

---

## Recomendações

### Ações imediatas (violações de UI — ALTA severidade)

1. **Source badge** (`InstrumentDetailPanel.svelte:84`): Substituir exibição raw de `source` por mapeamento:
   - `"sec"` → "US Registered" ou "Mutual Fund"
   - `"esma"` → "European" ou "UCITS"
   - `"internal"` → "Universe"

2. **"ESMA fund" / "US security"** (`InstrumentDetailPanel.svelte:109`): Substituir por "European fund" / "US fund" ou simplesmente "fund".

3. **Source metadata row** (`InstrumentDetailPanel.svelte:135`): Remover label "Source" ou substituir por classificação de produto.

4. **Disclosure labels** (`CatalogDetailPanel.svelte:129-159`): Substituir nomes de filing por capacidades:
   - "N-PORT" / "13F" → "Holdings Data" ou "Portfolio Holdings"
   - "YFinance" → "NAV History" ou "Price History"
   - "Schedule D" → "Fund Details"
   - "13F Overlay" → "Institutional Holdings"

5. **N-PORT reference** (`CatalogDetailPanel.svelte:206`): Substituir "Style snapshots require N-PORT filings (US Registered funds only)" por "Style snapshots are available for US Registered funds with holdings disclosure."

### Ações de médio prazo (refactor de código)

6. **Import endpoints unificados**: Criar `POST /screener/import/{identifier}` que detecta automaticamente ESMA (ISIN format) vs SEC (ticker format) no backend. Eliminar `/import-esma/` e `/import-sec/` separados.

7. **TypeScript enum**: Renomear `source: "internal" | "esma" | "sec"` para valores neutros ou usar campo `universe` consistentemente.

8. **CSS classes**: Renomear `.source-badge--esma` / `.source-badge--sec` para `.source-badge--european` / `.source-badge--us-registered`.

9. **Conditional logic**: Substituir `source === "esma"` por checagem de capacidade (`disclosure.has_*` flags) onde possível.

### CRD labels (baixa prioridade)

10. **CRD exposure**: Considerar renomear label "CRD" para "Registration #" nos 4 componentes do manager screener. Decisão de produto: CRD é um identificador regulatório legítimo que profissionais do mercado reconhecem — pode ser aceitável manter.

### Decisão sobre /esma/* backend

**Recomendação: DEPRECAR**

Justificativa:
- Zero consumidores frontend (confirmado em 2 rodadas de auditoria)
- Zero consumidores internos backend (todos acessam tabelas diretamente)
- Funcionalidade 100% absorvida pelo Unified Fund Catalog (`/screener/catalog` UNION ALL)
- Router, schemas, query builder e testes podem ser removidos sem impacto
- **Tabelas** (`esma_managers`, `esma_funds`, `esma_isin_ticker_map`) devem ser PRESERVADAS — são consumidas por catalog, embedding worker, import service

**Artefatos para remoção:**
- `backend/app/domains/wealth/routes/esma.py` — router completo
- `backend/app/domains/wealth/schemas/esma.py` — schemas REST (ORM models preservados)
- `backend/app/domains/wealth/queries/esma_sql.py` — query builder dos endpoints
- `backend/tests/routes/test_esma_endpoints.py` — testes dos endpoints
- Import + registration em `backend/app/main.py` (linhas 93, 396)

---

## Resumo de Conformidade

| Área | Status | Itens |
|---|---|---|
| Universe filter labels | ✅ CONFORME | `UNIVERSE_LABELS` traduz chaves corretamente |
| Import button text | ✅ CONFORME | "Add to Review" / "Send to DD Review" |
| Source badge | ❌ VIOLAÇÃO | Exibe "sec", "esma" raw |
| Disclosure labels | ❌ VIOLAÇÃO | "N-PORT", "13F", "YFinance", "Schedule D" |
| Conditional text | ❌ VIOLAÇÃO | "ESMA fund", "US security" |
| Import API paths | ⚠️ PARCIAL | Texto OK, URLs expõem provedor |
| CRD label | ⚠️ PARCIAL | Identificador legítimo mas expõe SEC indiretamente |
| `/esma/*` endpoints | 🗑️ ORPHANED | Sem consumidores, candidatos a deprecação |
