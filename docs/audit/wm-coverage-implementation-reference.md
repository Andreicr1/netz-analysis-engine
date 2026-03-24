# Referencia de Implementacao — Cobertura Wealth Vertical

**Data:** 2026-03-23
**Plano original:** `docs/plans/wm-coverage-plan-2026-03-23.md`
**Audit fonte:** `docs/audit/endpoint_coverage_audit.md`
**Executores:** Claude Opus (4 sessoes + pre-sessao) | Revisor: Andrei
**Gate de qualidade:** `make check` (backend) + `pnpm run check` (wealth frontend) verde em todas as sessoes

---

## Resumo Executivo

O audit de cobertura identificou 30 endpoints aparentemente desconectados. Validacao profunda
via grep no frontend revelou que **16 eram falsos negativos** (ja conectados em sub-rotas,
componentes dinamicos ou chamadas com query params). Trabalho efetivo: **11 endpoints em
4 sessoes** + 1 pre-sessao de seguranca. Resultado: **~98-99% dos endpoints wealth com UI funcional**.

### Metricas

| Metrica | Valor |
|---------|-------|
| Endpoints auditados | 30 |
| Falsos negativos (ja conectados) | 16 |
| Endpoints conectados (sessoes A-D) | 11 |
| Endpoints programaticos (sem UI) | 3 |
| Arquivos modificados | 17 |
| Linhas adicionadas | ~1033 |
| Linhas removidas | ~50 |
| Sessoes | 5 (pre + A/B/C/D) |

### Endpoints Programaticos (sem UI — correto)

- `POST /wealth/documents/upload` (multipart upload)
- `POST /documents/upload-url` (pre-signed URL)
- `POST /documents/upload-complete` (finalize upload)

---

## Pre-Sessao — Security Fixes (HC-1 a HC-4)

**Objetivo:** Corrigir vulnerabilidades identificadas no audit antes de iniciar wiring.

### HC-1 (CRITICAL) — Cross-tenant data leak no ManagerSpotlight

| Item | Detalhe |
|------|---------|
| **Arquivo** | `backend/app/domains/wealth/routes/content.py` |
| **Problema** | `_sync_generate_content` abria `sync_session_factory()` sem `SET LOCAL` — path `manager_spotlight` podia retornar dados de outro tenant |
| **Fix** | Adicionado `SET LOCAL app.current_organization_id = :oid` logo apos abrir sessao sync |
| **Padrao correto** | Ja existia em `dd_reports.py:531` — replicado |

### HC-2 (MEDIUM) — Defense-in-depth: organization_id explicito

Tres arquivos com queries que filtravam por `instrument_id`/`fund_id` sem `organization_id`
explicito. RLS protege em prod, mas defense-in-depth previne cross-tenant em callers futuros.

| Arquivo | Mudancas |
|---------|----------|
| `vertical_engines/wealth/dd_report/quant_injection.py` | Assinatura de `gather_quant_metrics` e `gather_risk_metrics` recebem `organization_id`; query em `FundRiskMetrics` filtra por `organization_id` |
| `vertical_engines/wealth/dd_report/dd_report_engine.py` | `_build_evidence` recebe `organization_id`; query em `Fund` filtra por `organization_id`; calls propagam parametro |
| `vertical_engines/wealth/manager_spotlight.py` | `_gather_fund_data` recebe `organization_id`; query em `Fund` filtra por `organization_id`; calls em `generate()` propagam parametro |

### HC-3 (MEDIUM) — Silent exception swallowing em R2StorageClient

| Item | Detalhe |
|------|---------|
| **Arquivo** | `backend/app/services/storage_client.py` |
| **Problema** | `exists()` retornava `False` para qualquer excecao (auth failures, rede); `delete()` fazia noop silencioso |
| **Fix** | Distingue `ClientError 404/NoSuchKey` (retorna False/noop) de erros reais (loga warning) |

### HC-4 (LOW) — f-string path em adv_service

| Item | Detalhe |
|------|---------|
| **Status** | N/A — import-linter impede fix (cross-vertical import); divida tecnica documentada |

---

## Sessao A — DD Report Lifecycle

**Endpoints:** 2 | **Prioridade:** P1

### POST /dd-reports/funds/{fund_id}

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/dd_reports.py` |
| **Status** | **Falso negativo** — ja estava conectado via `+page.server.ts` com form action |
| **Acao** | Nenhuma modificacao necessaria |

### GET /dd-reports/{report_id}/audit-trail

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/dd_reports.py` |
| **Frontend** | `frontends/wealth/src/routes/(app)/dd-reports/[fundId]/[reportId]/+page.svelte` |
| **Implementacao** | Secao colapsavel "Audit Trail" no final da report detail page |
| **Componentes** | Toggle button com `▸/▾`, timeline vertical com eventos (CREATE/UPDATE/APPROVE/REJECT/REGENERATE), lazy-load no toggle |
| **Padrao** | `api.get<AuditEvent[]>(/dd-reports/${reportId}/audit-trail)` |

**Tipo `AuditEvent`** adicionado em `frontends/wealth/src/lib/types/dd-report.ts`:
```typescript
interface AuditEvent {
  id: string;
  action: string;
  actor_id: string | null;
  created_at: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}
```

---

## Sessao B — Macro Expansion + Risk Summary

**Endpoints:** 3 | **Prioridade:** P1

### GET /macro/bis

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/macro.py` — leitura de hypertable global `bis_statistics` |
| **Frontend** | `frontends/wealth/src/routes/(app)/macro/+page.svelte` |
| **Implementacao** | Secao "Global Credit — BIS" na macro page, replicando padrao OFR/Treasury |
| **Dados** | Credit gap, debt-service ratio (DSR), property prices por pais/regiao |
| **Worker** | `bis_ingestion` (lock ID 900_014, quarterly) |

### GET /macro/imf

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/macro.py` — leitura de hypertable global `imf_weo_forecasts` |
| **Frontend** | `frontends/wealth/src/routes/(app)/macro/+page.svelte` |
| **Implementacao** | Secao "Economic Outlook — IMF WEO" na macro page |
| **Dados** | GDP growth, inflation, fiscal balance por regiao (WEO forecasts) |
| **Worker** | `imf_ingestion` (lock ID 900_015, quarterly) |

**Tipos** adicionados em `frontends/wealth/src/lib/types/macro.ts`:
```typescript
interface BISRecord { country: string; indicator: string; value: number; date: string; }
interface IMFRecord { country: string; indicator: string; value: number; year: number; estimate: boolean; }
```

### GET /risk/summary

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/risk.py` — aggregate risk cross-profile |
| **Frontend** | `frontends/wealth/src/routes/(app)/risk/+page.svelte` |
| **Implementacao** | Banner no topo da risk page com metricas agregadas |
| **Metricas** | Worst CVaR utilization, breached profiles count, warning count, active drift alerts |
| **Padrao** | `api.get<RiskSummary>('/risk/summary')` com loading state |

---

## Sessao C — Content Spotlight + Analytics Pareto + Drift Export

**Endpoints:** 3 | **Prioridade:** P1-P2

### POST /content/spotlights

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/content.py` |
| **Frontend** | `frontends/wealth/src/routes/(app)/content/+page.svelte` |
| **Implementacao** | Botao "Manager Spotlight" com fund picker na content listing page, replicando padrao Flash Report/Outlook |
| **Server-side** | `frontends/wealth/src/routes/(app)/content/+page.server.ts` — adicionada action que chama o endpoint e retorna resultado |
| **UX** | Select fund → POST → pagina recarrega com novo spotlight na listagem |

### GET /analytics/optimize/pareto/{job_id}/stream

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/analytics.py` — SSE stream via Redis pub/sub |
| **Frontend** | `frontends/wealth/src/routes/(app)/analytics/+page.svelte` |
| **Implementacao** | Apos `POST /analytics/optimize/pareto` retornar 202 + job_id, conecta SSE stream. Mostra barra de progresso e resultados parciais em tempo real |
| **SSE** | `fetch()` + `ReadableStream` (nunca `EventSource` — auth headers) via `createSSEStream` do `@netz/ui` |
| **Eventos** | `progress` (porcentagem), `result` (fronteira Pareto), `complete`, `error` |

**Tipos** adicionados em `frontends/wealth/src/lib/types/analytics.ts`:
```typescript
interface ParetoSSEEvent {
  type: "progress" | "result" | "complete" | "error";
  progress?: number;
  portfolios?: ParetoPortfolio[];
  error?: string;
}
```

### GET /analytics/strategy-drift/{instrument_id}/export

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/analytics.py` — retorna CSV |
| **Frontend** | `frontends/wealth/src/lib/components/DriftHistoryPanel.svelte` |
| **Implementacao** | Botao "Export CSV" no header do painel de historico de drift |
| **Download** | `fetch()` blob → `URL.createObjectURL()` → click `<a>` → revoke |

---

## Sessao D — Screener Detail + Rebalance Event + Fact Sheet Download

**Endpoints:** 3 | **Prioridade:** P2-P3

### GET /screener/results/{instrument_id}

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/screener.py:273-291` — retorna `list[ScreeningResultRead]` (historico de screening) |
| **Frontend** | `frontends/wealth/src/routes/(app)/screener/+page.svelte` |
| **Implementacao** | Secao "Screening History" no fund detail panel (ContextPanel). Ao clicar um fund na tabela de managers, o panel abre mostrando layer breakdown (ja existente) + tabela de historico com data, status, score, failed layer |
| **Funcoes** | `loadFundHistory(instrumentId)` chamada em `openFundDetail()` |
| **Padrao** | `api.get<ScreeningResult[]>(/screener/results/${instrumentId})` |

### GET /portfolios/{profile}/rebalance/{event_id}

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/portfolios.py:179-202` — retorna `RebalanceEventRead` com `weights_before`, `weights_after`, `cvar_before`, `cvar_after` |
| **Frontend** | `frontends/wealth/src/lib/components/RebalancingTab.svelte` |
| **Implementacao** | Click-to-expand nos event cards. Cada card agora tem `▸/▾` toggle. Ao expandir, busca detalhe do evento via API e mostra: CVaR before/after side-by-side + tabela de weights before/after com delta (pp) |
| **Funcoes** | `toggleEventDetail(event)` com `expandedEventId` state |
| **Padrao** | `api.get<Record<string, unknown>>(/portfolios/${profile}/rebalance/${eventId})` |

### GET /fact-sheets/dd-reports/{report_id}/download

| Item | Detalhe |
|------|---------|
| **Backend** | `backend/app/domains/wealth/routes/fact_sheets.py:216-286` — gera PDF on-demand a partir dos chapters do DD report |
| **Frontend** | `frontends/wealth/src/routes/(app)/dd-reports/[fundId]/[reportId]/+page.svelte` |
| **Implementacao** | Botao "Download PDF" na action bar, visivel quando `report.status` e `completed`, `pending_approval`, `approved` ou `published` |
| **Download** | `fetch()` com Bearer token → blob → `URL.createObjectURL()` → click `<a>` → revoke |
| **Filename** | `dd_report_{fundId}_pt.pdf` |

---

## Inventario de Arquivos Modificados

### Backend (5 arquivos)

| Arquivo | Sessao | Mudanca |
|---------|--------|---------|
| `backend/app/domains/wealth/routes/content.py` | Pre | `SET LOCAL` adicionado no sync path |
| `backend/app/services/storage_client.py` | Pre | `exists()`/`delete()` distinguem 404 de erros reais |
| `backend/vertical_engines/wealth/dd_report/dd_report_engine.py` | Pre | `organization_id` em `_build_evidence` e calls |
| `backend/vertical_engines/wealth/dd_report/quant_injection.py` | Pre | `organization_id` em `gather_quant_metrics`/`gather_risk_metrics` |
| `backend/vertical_engines/wealth/manager_spotlight.py` | Pre | `organization_id` em `_gather_fund_data` e calls |

### Frontend — Tipos (3 arquivos)

| Arquivo | Sessao | Mudanca |
|---------|--------|---------|
| `frontends/wealth/src/lib/types/dd-report.ts` | A | `AuditEvent` interface, helpers `chapterTitle`, `anchorLabel`, `anchorColor`, `confidenceColor` |
| `frontends/wealth/src/lib/types/macro.ts` | B | `BISRecord`, `IMFRecord` interfaces |
| `frontends/wealth/src/lib/types/analytics.ts` | C | `ParetoSSEEvent` interface |

### Frontend — Componentes (2 arquivos)

| Arquivo | Sessao | Mudanca |
|---------|--------|---------|
| `frontends/wealth/src/lib/components/DriftHistoryPanel.svelte` | C | Botao "Export CSV" com fetch blob download |
| `frontends/wealth/src/lib/components/RebalancingTab.svelte` | D | Click-to-expand com detalhe do evento (CVaR + weights table) |

### Frontend — Paginas (7 arquivos)

| Arquivo | Sessao | Mudanca |
|---------|--------|---------|
| `frontends/wealth/src/routes/(app)/dd-reports/[fundId]/[reportId]/+page.svelte` | A, D | Audit trail colapsavel (A) + botao Download PDF (D) |
| `frontends/wealth/src/routes/(app)/macro/+page.svelte` | B | Secoes BIS "Global Credit" e IMF "Economic Outlook" |
| `frontends/wealth/src/routes/(app)/risk/+page.svelte` | B | Banner Risk Summary no topo |
| `frontends/wealth/src/routes/(app)/content/+page.svelte` | C | Botao "Manager Spotlight" com fund picker |
| `frontends/wealth/src/routes/(app)/content/+page.server.ts` | C | Server action para POST spotlight |
| `frontends/wealth/src/routes/(app)/analytics/+page.svelte` | C | SSE stream para Pareto progress + results |
| `frontends/wealth/src/routes/(app)/screener/+page.svelte` | D | Screening history no fund detail panel |

---

## Padroes de Implementacao Reutilizados

### 1. Download de arquivo (blob pattern)

Usado em: Drift Export (C), Fact Sheet Download (D)

```typescript
const token = await getToken();
const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
const blob = await res.blob();
const url = URL.createObjectURL(blob);
const a = document.createElement("a");
a.href = url;
a.download = filename;
a.click();
URL.revokeObjectURL(url);
```

### 2. SSE Stream (fetch + ReadableStream)

Usado em: Pareto SSE (C), DD Report generation (ja existia)

```typescript
const stream = createSSEStream<EventType>({
  url: `/endpoint/${id}/stream`,
  getToken,
  onEvent(event) { /* handle event */ },
});
stream.connect();
```

Nunca `EventSource` — requer auth headers.

### 3. Lazy-load em panel/toggle

Usado em: Audit Trail (A), Rebalance Detail (D), Screening History (D)

```typescript
let data = $state<T | null>(null);
let loading = $state(false);

async function load() {
  loading = true;
  try {
    data = await api.get<T>(url);
  } catch { data = null; }
  finally { loading = false; }
}
```

### 4. Secao macro (DB-only read)

Usado em: BIS (B), IMF (B), Risk Summary (B)

- Hypertable global (sem RLS)
- Worker ingere dados periodicamente
- Frontend faz GET simples e renderiza tabela/cards
- Formatacao via `@netz/ui` formatters

---

## Regras Invariantes Aplicadas

Todas as sessoes seguiram:

1. **Async-first:** Routes usam `async def` + `AsyncSession`. Sync apenas em `asyncio.to_thread()`
2. **SSE via fetch:** Nunca `EventSource` — `fetch()` + `ReadableStream` para auth headers
3. **Formatacao @netz/ui:** `formatNumber`, `formatPercent`, `formatDate`, `formatDateTime`, `formatAUM` — nunca `.toFixed()` / `.toLocaleString()`
4. **Backend-first:** Verificar rota existe e responde antes de wiring frontend
5. **Sem over-engineering:** Componentes simples, sem abstracoes desnecessarias
6. **Import-linter:** Nao importar entre verticais (`credit` ↔ `wealth`)
7. **RLS:** `SET LOCAL` em sync paths; `organization_id` explicito em defense-in-depth
8. **Gate:** `make check` + `pnpm run check` verde antes de fechar cada sessao

---

## Cobertura Final

| Categoria | Count | Status |
|-----------|-------|--------|
| Endpoints wealth total | ~80+ | — |
| Com UI funcional | ~98-99% | DONE |
| APIs programaticas (sem UI) | 3 | By design |
| Security fixes | 3 de 4 | HC-4 deferido (import-linter) |
