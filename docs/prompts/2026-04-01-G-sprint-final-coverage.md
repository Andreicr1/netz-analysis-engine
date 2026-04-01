# Prompt G — Sprint Final de Coverage (2026-04-01)

## Contexto

Estado atual: 89.8% cobertura (158/176). Objetivo: 100% dos endpoints com valor real.

O sprint tem três partes:
- **Parte 1 — Wiring:** 5 endpoints desconectados com valor real
- **Parte 2 — Cleanup:** 8 rotas deprecated/duplicatas deletadas do backend
- **Parte 3 — Correção de audit:** 1 falso negativo documentado

**Não começar nenhuma implementação sem ler os arquivos indicados em cada fase.**

---

## PARTE 1 — Wiring Frontend (5 endpoints)

---

### G1 — Rebalancing Apply

**Endpoint:** `POST /rebalancing/proposals/{proposal_id}/apply`
**Retorno:** `PortfolioSnapshotRead`

**Contexto:**
O `RebalancingTab.svelte` já tem o fluxo completo de propose/approve/execute via
`/portfolios/{profile}/rebalance/*`. O endpoint `/rebalancing/proposals/{id}/apply`
é uma rota separada em `backend/app/domains/wealth/routes/rebalancing.py` que
aplica diretamente os pesos da proposta ao `ModelPortfolio.fund_selection_schema`
e cria um `PortfolioSnapshot`. Requer `status == "pending"` no evento.

É o "fast path" de aplicação que bypassa o governance flow de approve/execute
quando o IC quer aplicar diretamente uma proposta pendente.

**Arquivos a ler:**
```
backend/app/domains/wealth/routes/rebalancing.py          — handler completo (linhas 1-245)
frontends/wealth/src/lib/components/RebalancingTab.svelte — estado atual (todo o arquivo)
backend/app/domains/wealth/schemas/portfolio.py           — PortfolioSnapshotRead
```

**O que implementar:**

Em `RebalancingTab.svelte`, adicionar:

1. Estado: `let showApplyDialog = $state(false)`

2. Função `handleApply`:
```typescript
async function handleApply(payload: ConsequenceDialogPayload) {
  if (!targetEventId) return;
  actionError = null;
  try {
    const api = createClientApiClient(getToken);
    await api.post(`/rebalancing/proposals/${targetEventId}/apply`, {});
    await loadRebalanceEvents();
    await invalidateAll();
  } catch (e) {
    if (e instanceof Error && e.message.includes("409")) {
      actionError = "Proposal is no longer pending — it may have already been applied.";
    } else {
      actionError = e instanceof Error ? e.message : "Apply failed";
    }
  }
}
```

3. Botão "Apply to Portfolio" visível quando `pendingEvent?.status === "pending"`,
   ao lado dos botões approve/execute existentes. Usa `ConsequenceDialog` com:
   - `title`: "Apply Rebalance to Portfolio"
   - `description`: "This will update the model portfolio weights immediately,
     bypassing the standard approval workflow. This action cannot be undone."
   - `action`: "Apply"
   - `requiresRationale`: true (min 10 chars)

O botão chama `openApplyDialog(pendingEvent)` e o dialog chama `handleApply`.

---

### G2 — Screener Catalog Detail

**Endpoint:** `GET /screener/catalog/{external_id}/detail`
**Retorno:** `FundDetailOut` (mesmo schema que o catalog, com todos os campos enriquecidos)

**Contexto:**
O catalog browse (`screener/+page.svelte`) mostra itens de `/screener/catalog` mas
ao clicar num item não há drill-down — a página `screener/[cik]` só funciona para
fundos SEC com CIK. Para ETFs, BDCs, private funds e UCITS, o detalhe vem de
`GET /screener/catalog/{external_id}/detail`.

**Arquivos a ler:**
```
frontends/wealth/src/routes/(app)/screener/+page.svelte   — ver CatalogTable e como itens são renderizados
frontends/wealth/src/routes/(app)/screener/[cik]/+page.server.ts — padrão da page de detalhe
backend/app/domains/wealth/routes/screener.py              — linhas 1662-1756, FundDetailOut shape
frontends/wealth/src/lib/types/catalog.ts                  — tipos existentes do catalog
```

**O que implementar:**

**Opção A (recomendada):** Criar rota `screener/catalog/[externalId]/+page.server.ts`
e `+page.svelte` que lazy-fetcha `GET /screener/catalog/{external_id}/detail`.

Redirecionar fundos com `universe === "registered_us"` para a rota `screener/[cik]`
existente (que já tem todos os tabs de N-PORT, holdings, etc.).

Para outros universos (etf, bdc, private, ucits): exibir a página de detalhe com:
- Header: nome, ticker/ISIN, tipo, gestor, AUM formatado
- Grid de métricas: expense_ratio_pct, avg_annual_return_1y/10y, inception_date,
  is_index, is_target_date, is_fund_of_funds
- Badge de `disclosure` (has_holdings, has_nav, has_prospectus, has_13f_overlay)
- Botão "Import to Universe" → `POST /screener/import/{external_id}` (já existe)
- Botão "Generate DD Report" → `POST /dd-reports/funds/{fund_id}` (se já importado)

**Navegação:** No CatalogTable existente em `screener/+page.svelte`, fazer cada
linha clicável com `href="/screener/catalog/{external_id}"`. Para fundos
`registered_us`, usar `href="/screener/{cik}"` (rota existente) em vez da nova.

Criar tipo TypeScript `FundDetail` em `lib/types/catalog.ts` baseado no schema
`FundDetailOut` do backend.

---

### G3 — Strategy Drift Scan

**Endpoint:** `POST /analytics/strategy-drift/scan`
**Retorno:** `StrategyDriftScanRead` — `{ scanned_count, alerts_found, alerts: [...] }`

**Contexto:**
A página `/analytics` já mostra drift alerts via `GET /analytics/strategy-drift/alerts`.
Falta um botão para disparar um scan manual que re-avalia todos os instrumentos.
O endpoint usa advisory lock — retorna 409 se scan já está em progresso.

**Arquivos a ler:**
```
frontends/wealth/src/routes/(app)/analytics/+page.svelte  — seção de Strategy Drift
backend/app/domains/wealth/routes/strategy_drift.py       — linhas 84-135 (handler + schema)
```

**O que implementar:**

Na seção de Strategy Drift em `analytics/+page.svelte`, adicionar um botão
"Scan Now" (ícone `ArrowsClockwise` do phosphor-svelte, `weight="light"`).

Comportamento:
```typescript
async function triggerDriftScan() {
  scanning = true;
  scanResult = null;
  try {
    const api = createClientApiClient(getToken);
    scanResult = await api.post<StrategyDriftScanResult>(
      '/analytics/strategy-drift/scan', {}
    );
    // Reload alerts after scan
    await invalidateAll();
  } catch (e) {
    if (e instanceof Error && e.message.includes("409")) {
      scanError = "Scan already in progress — try again in a moment.";
    } else {
      scanError = e instanceof Error ? e.message : "Scan failed";
    }
  } finally {
    scanning = false;
  }
}
```

Após scan concluído, mostrar toast ou inline result:
`"Scanned {scanned_count} instruments, found {alerts_found} alerts."`

Tipo TypeScript a adicionar em `lib/types/analytics.ts`:
```typescript
export interface StrategyDriftScanResult {
  scanned_count: number;
  alerts_found: number;
  alerts: StrategyDriftAlert[];
}
```

---

### G4 — Private Funds Tab no Manager Panel

**Endpoint:** `GET /sec/managers/{crd}/private-funds`
**Retorno:** `PrivateFundListResponse` — `{ funds: PrivateFundSummary[], total_count, total_aum }`
**Onde:** `ManagerDetailPanel.svelte` (ou componente análogo que mostra tabs por manager)

**Contexto:**
O painel de detalhe de um manager (acessado via `/screener/managers/{crd}`)
já tem tabs: Profile, Holdings, Drift, Institutional, Universe Status, N-PORT, Docs.
Falta uma tab "Private Funds" com os dados do Schedule D do ADV.

**Arquivos a ler:**
```
frontends/wealth/src/routes/(app)/screener/managers/      — ver estrutura de tabs existente
backend/app/domains/wealth/routes/sec_funds.py             — linhas 141-215 (handler + PrivateFundListResponse shape)
backend/app/domains/wealth/schemas/sec_funds.py            — PrivateFundSummary, PrivateFundListResponse
```

**O que implementar:**

Adicionar tab "Private Funds" no manager detail. Lazy-load: busca apenas ao
ativar a tab (pattern já usado pelas outras tabs).

```typescript
async function loadPrivateFunds() {
  if (privateFunds) return;  // cache
  loadingPrivate = true;
  try {
    const api = createClientApiClient(getToken);
    privateFunds = await api.get<PrivateFundListResponse>(
      `/sec/managers/${crd}/private-funds`
    );
  } catch {
    privateFunds = null;
  } finally {
    loadingPrivate = false;
  }
}
```

Conteúdo da tab: tabela com colunas `Fund Name`, `Type`, `AUM`, `Investors`,
`Fund of Funds`. AUM com formatador compacto do `@investintell/ui` (nunca `.toFixed()`).
Empty state se `funds.length === 0`: "No Schedule D private fund data available."

Tipos a adicionar em `lib/types/manager-screener.ts`:
```typescript
export interface PrivateFundSummary {
  fund_name: string;
  fund_type: string | null;
  gross_asset_value: number | null;
  investor_count: number | null;
  is_fund_of_funds: boolean | null;
}

export interface PrivateFundListResponse {
  funds: PrivateFundSummary[];
  total_count: number;
  total_aum: number | null;
}
```

---

### G5 — Style History Tab na Página [cik]

**Endpoint:** `GET /sec/funds/{cik}/style-history`
**Retorno:** `StyleHistoryResponse` — `{ snapshots, drift_detected, quarters_analyzed }`
**Onde:** `screener/[cik]/+page.svelte`

**Contexto:**
A página `screener/[cik]` já carrega 6 endpoints em paralelo no SSR
(detail, holdings, prospectus, peers, reverseHoldings, holdingsHistory).
Falta a tab de Style History que mostra a evolução trimestral do estilo
do fundo (growth vs value, sector tilt, allocation percentages).

**Arquivos a ler:**
```
frontends/wealth/src/routes/(app)/screener/[cik]/+page.server.ts — loader atual
frontends/wealth/src/routes/(app)/screener/[cik]/+page.svelte    — tabs existentes
backend/app/domains/wealth/routes/sec_funds.py                   — linhas 441-497 (StyleHistoryResponse shape)
```

**O que implementar:**

1. Em `+page.server.ts`, adicionar ao `Promise.allSettled`:
```typescript
api.get<StyleHistoryResponse>(`/sec/funds/${cik}/style-history`, { limit: '8' })
```
Retornar `styleHistory` no objeto de return.

2. Em `+page.svelte`, adicionar tab "Style" no TabBar existente.

Conteúdo da tab:
- Badge de alerta se `drift_detected === true`: "Style drift detected — classification changed between quarters"
- Timeline de snapshots em ordem cronológica reversa:
  - Cada snapshot: badge do `style_label`, barra horizontal com equity/fixed_income/cash_pct,
    data do relatório
  - Se `sector_weights` não vazio: grid pequeno de % por setor
- Footer: `{quarters_analyzed} quarters analyzed`
- Empty state: "No style classification data available for this fund."

Tipos a adicionar em `lib/types/catalog.ts` (ou novo `sec-funds.ts`):
```typescript
export interface StyleSnapshotItem {
  report_date: string;
  style_label: string | null;
  growth_tilt: number | null;
  sector_weights: Record<string, number>;
  equity_pct: number | null;
  fixed_income_pct: number | null;
  cash_pct: number | null;
  confidence: number | null;
}

export interface StyleHistoryResponse {
  snapshots: StyleSnapshotItem[];
  drift_detected: boolean;
  quarters_analyzed: number;
}
```

---

## PARTE 2 — Backend Cleanup (deletar rotas deprecated/duplicatas)

Estas rotas têm equivalentes funcionais melhores já wirados. Deletar reduz
superfície de API, elimina manutenção desnecessária, e clarifica o modelo.

**Importante:** Antes de deletar qualquer rota, verificar que não há referências
a ela em testes. Executar `make check` após cada arquivo modificado.

### O que deletar

**Em `backend/app/domains/wealth/routes/sec_analysis.py`:**
- `GET /managers/search` — duplicata de `/manager-screener/` (frontend usa manager-screener)
- `GET /managers/{cik}/holdings` — duplicata de `/manager-screener/managers/{crd}/holdings`
- `GET /managers/{cik}/style-drift` — duplicata de `/manager-screener/managers/{crd}/drift`
- `GET /managers/sic-codes` — sem valor de negócio identificado, sem consumidor no frontend

**Em `backend/app/domains/wealth/routes/sec_funds.py`:**
- `GET /managers/{crd}/registered-funds` — duplicata de
  `/manager-screener/managers/{crd}/registered-funds` (mesmo dado, path diferente)

**Em `backend/app/domains/wealth/routes/documents.py`:**
- `POST /upload` (sem path param) — upload legado direto; frontend usa o fluxo
  de pre-signed URL (upload-url → upload-complete) que é mais seguro e performático

**Em `backend/app/domains/wealth/routes/funds.py`:**
- `GET /scoring` — deprecated, substituído por `/instruments` com filtros de score
- `GET /{fund_id}/nav` — deprecated, NAV disponível via entity analytics

**Processo para cada deleção:**
1. Deletar o handler `@router.get/post(...)` e a função correspondente
2. Remover imports não utilizados que ficaram órfãos
3. Se `funds.py` ficar com apenas 3 endpoints todos deprecated-style, adicionar
   comentário `# TODO: Remove this file after instrument migration is complete`

---

## PARTE 3 — Correção de Audit

**`/risk/stream` é um falso negativo no audit.**

O `risk-store.svelte.ts` conecta ao endpoint via:
```typescript
const sseUrl = config.sseEndpoint ?? `${apiBase}/risk/stream`;
sseConnection = createSSEStream<Record<string, unknown>>({ url: sseUrl, ... });
```

O scanner de audit procura por `api.(get|post|...)` e não detecta `createSSEStream(url)`.
O endpoint está corretamente conectado e funcionando.

**No arquivo `docs/audit/endpoint-coverage-audit-2026-04-01.md`:**

1. Mover `GET /risk/stream` de DISCONNECTED → CONNECTED com:
   - Backend File: `risk.py`
   - Frontend File(s): `risk-store.svelte.ts` (via `createSSEStream`)

2. Recalcular summary:
   - Conectados: 159 (89.8% → 90.3%)
   - Desconectados: 17 (10.2% → 9.7%)

3. Remover do Top 4 a linha de `/risk/stream`; atualizar para Top 3.

4. Atualizar `risk.py` na tabela de coverage: 7/7 = 100%
   (era 6/7 = 86%)

5. Adicionar nota: "`GET /risk/stream` conectado via `createSSEStream` em `risk-store.svelte.ts`
   — padrão de SSE direto não detectado pelo scanner `api.(get|post|...)` do audit anterior."

---

## Regras críticas

- **Ler antes de implementar:** Cada G# lista arquivos obrigatórios. Leia-os primeiro.
- **Gate por fase:** `pnpm run check` (wealth frontend) após G1-G5.
  `make check` (backend) após Parte 2.
- **Não modificar outros arquivos:** Cada G# tem escopo definido.
- **Sem novos endpoints:** Esta tarefa é exclusivamente de wiring e cleanup.
- **Deleções precisas:** Deletar apenas os handlers listados, não arquivos inteiros
  (ex: `funds.py` ainda tem 3 endpoints usados pelo frontend).

## Definition of Done

- [ ] G1: Botão "Apply to Portfolio" em RebalancingTab com ConsequenceDialog
- [ ] G2: Rota `screener/catalog/[externalId]` com detail panel + redirect para [cik] quando registered_us
- [ ] G3: Botão "Scan Now" em analytics/+page.svelte com resultado inline
- [ ] G4: Tab "Private Funds" em manager detail (lazy load)
- [ ] G5: Tab "Style" em screener/[cik] com timeline de snapshots
- [ ] Parte 2: 8 handlers deletados do backend, `make check` verde
- [ ] Parte 3: Audit atualizado — `/risk/stream` em CONNECTED, summary recalculado
- [ ] `pnpm run check` 0 erros no wealth frontend
- [ ] `make check` verde no backend
