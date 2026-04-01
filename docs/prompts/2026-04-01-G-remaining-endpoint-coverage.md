# Prompt: Remaining Endpoint Coverage — Wire, Deprecate, or Defer

## Contexto

Após o sprint de wiring (Prompts A-E, 2026-04-01), a cobertura subiu de 82.4% para 89.8% (158/176). Restam 18 endpoints desconectados + 5 worker triggers candidatos. Este prompt resolve TODOS os pendentes em 3 categorias: wire, deprecate, ou defer.

**Referência:** `docs/audit/endpoint-coverage-audit-2026-04-01.md`

---

## Categoria 1 — WIRE (conectar frontend ↔ backend)

### 1.1 Rebalancing Apply — P1

**Endpoint:** `POST /rebalancing/proposals/{proposal_id}/apply`
**Backend:** `rebalancing.py`
**Frontend alvo:** `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte` → `RebalancingTab.svelte`

**Implementação:**
- O `RebalancingTab.svelte` já tem a listagem de proposals e botões approve/execute
- Adicionar botão "Apply" no proposal aprovado que chama `POST /rebalancing/proposals/{id}/apply`
- Exibir ConsequenceDialog antes de aplicar (similar ao stage change do Kanban)
- Após apply: invalidar snapshot do portfolio, mostrar toast de sucesso
- Tratar erro 409 (proposal já aplicada) com mensagem amigável

### 1.2 Screener Catalog Detail — P2

**Endpoint:** `GET /screener/catalog/{external_id}/detail`
**Backend:** `screener.py`
**Frontend alvo:** `frontends/wealth/src/routes/(app)/screener/+page.svelte` → `CatalogDetailPanel.svelte`

**Implementação:**
- O `CatalogDetailPanel` já existe mas faz fetch de dados parciais
- Conectar ao endpoint `/catalog/{external_id}/detail` que retorna N-CEN + XBRL + N-PORT enriched data
- Lazy-load no click de uma row da tabela de catálogo
- Exibir: expense_ratio, holdings_count, portfolio_turnover, is_index, is_target_date, fund_inception_date, AUM
- Botão "Import to Universe" já conectado (`POST /screener/import/{identifier}`)

### 1.3 Risk SSE Stream — P2

**Endpoint:** `GET /risk/stream`
**Backend:** `risk.py`
**Frontend alvo:** `frontends/wealth/src/routes/(app)/risk/+page.svelte`

**Implementação:**
- Atualmente a risk page faz polling via SSR load function
- Adicionar conexão SSE via `fetch()` + `ReadableStream` (NUNCA `EventSource` — precisa de auth headers)
- Padrão idêntico ao usado em `dd-reports/[fundId]/[reportId]` e `content/+page.svelte`
- SSE events: `risk_update` (CVaR refresh), `regime_change`, `drift_alert`
- Reconnect automático com backoff exponencial (1s, 2s, 4s, max 30s)
- Mostrar badge "Live" quando SSE conectado, "Polling" quando em fallback
- **Atenção:** `risk.py` já tem o endpoint implementado com `EventSourceResponse`. Verificar se o Redis pub/sub channel está configurado para risk events.

### 1.4 Strategy Drift Scan Trigger — P2

**Endpoint:** `POST /analytics/strategy-drift/scan`
**Backend:** `strategy_drift.py`
**Frontend alvo:** `frontends/wealth/src/routes/(app)/risk/+page.svelte` ou `analytics/+page.svelte`

**Implementação:**
- Adicionar botão "Scan Now" na seção de drift alerts (risk page ou analytics page)
- POST sem body → retorna 202 com job tracking
- Mostrar toast "Drift scan triggered" e invalidar drift alerts após conclusão
- Pode ser um `<Button variant="outline" size="sm">` ao lado do header "Strategy Drift"

### 1.5 SEC Private Funds Tab — P2

**Endpoint:** `GET /sec/managers/{crd}/private-funds`
**Backend:** `sec_funds.py`
**Frontend alvo:** `frontends/wealth/src/lib/components/screener/ManagerDetailPanel.svelte`

**Implementação:**
- O `ManagerDetailPanel` já tem tabs (Overview, Holdings, Drift, Docs)
- Adicionar tab "Private Funds" que carrega `GET /sec/managers/{crd}/private-funds`
- Renderizar tabela: fund_name, fund_type (PE/VC/Hedge/RE/Securitized/Liquidity/Other), strategy_label, gross_asset_value, is_section3
- Badge de fund_type com cores distintas (similar ao strategy_label badges existentes)
- Se lista vazia: empty state "No private funds reported in ADV Schedule D"

### 1.6 SEC Fund Style History — P2

**Endpoint:** `GET /sec/funds/{cik}/style-history`
**Backend:** `sec_funds.py`
**Frontend alvo:** `frontends/wealth/src/routes/(app)/screener/[cik]/+page.svelte`

**Implementação:**
- A página de detalhe do fund (`/screener/[cik]`) já tem seções de holdings, peer analysis, prospectus
- Adicionar seção "Style History" com chart de área empilhada (ECharts)
- Mostra evolução de sector/asset allocation ao longo de quarters N-PORT
- X-axis: quarters (2021Q3 → atual), Y-axis: % allocation
- Tooltip com breakdown por sector
- Se endpoint retorna vazio: "Insufficient N-PORT history for style analysis"

### 1.7 Worker Triggers no Settings — P3

**Endpoints (5):**
- `POST /workers/run-sec-13f-ingestion`
- `POST /workers/run-sec-adv-ingestion`
- `POST /workers/run-nport-ingestion`
- `POST /workers/run-esma-ingestion`
- `POST /workers/run-regime-fit`

**Backend:** `workers.py`
**Frontend alvo:** `frontends/wealth/src/routes/(app)/settings/system/+page.svelte`

**Implementação:**
- Localizar array `WORKER_TRIGGERS` no `+page.svelte` (circa linha 89)
- Adicionar 5 entradas ao array com scope `global`:

```typescript
{ label: 'SEC 13F Holdings', endpoint: '/workers/run-sec-13f-ingestion', scope: 'global' },
{ label: 'SEC ADV Managers', endpoint: '/workers/run-sec-adv-ingestion', scope: 'global' },
{ label: 'N-PORT Holdings', endpoint: '/workers/run-nport-ingestion', scope: 'global' },
{ label: 'ESMA Fund Register', endpoint: '/workers/run-esma-ingestion', scope: 'global' },
{ label: 'Regime Fit (HMM)', endpoint: '/workers/run-regime-fit', scope: 'global' },
```

- A UI de trigger já existe (botão + toast). Apenas adicionar ao array.
- Atualizar nota no audit: 14/28 workers wired.

---

## Categoria 2 — DEPRECATE (remover endpoint do backend)

Endpoints que NÃO serão conectados porque são duplicados ou substituídos. Remover do backend para reduzir superfície de API.

### 2.1 Remover de `sec_analysis.py` (4 endpoints)

| Endpoint | Motivo |
|----------|--------|
| `GET /sec/managers/search` | Duplicado por `GET /manager-screener/` (já conectado) |
| `GET /sec/managers/{cik}/holdings` | Duplicado por `GET /manager-screener/managers/{crd}/holdings` |
| `GET /sec/managers/{cik}/style-drift` | Duplicado por `GET /manager-screener/managers/{crd}/drift` |
| `GET /sec/managers/sic-codes` | Referência estática, nunca consumido |

**Ação:** Remover os 4 handlers de `sec_analysis.py`. Se algum teste referencia esses endpoints, atualizar para usar os equivalentes em `manager_screener.py`. Atualizar `routes.json` manifest.

### 2.2 Remover de `sec_funds.py` (1 endpoint)

| Endpoint | Motivo |
|----------|--------|
| `GET /sec/managers/{crd}/registered-funds` | Duplicado por `GET /manager-screener/managers/{crd}/registered-funds` (já conectado) |

**Ação:** Remover handler. Atualizar testes e `routes.json`.

### 2.3 Remover de `funds.py` (2 endpoints)

| Endpoint | Motivo |
|----------|--------|
| `GET /funds/scoring` | Deprecated — scoring é via `/instruments` + `fund_risk_metrics` |
| `GET /funds/{fund_id}/nav` | Deprecated — NAV via entity analytics ou `nav_timeseries` direto |

**Ação:** Remover handlers. Os 3 endpoints restantes de `funds.py` (`GET /funds`, `GET /funds/{fund_id}`, `GET /funds/{fund_id}/risk`) continuam ativos até migração completa para instruments.

### 2.4 Remover de `documents.py` (1 endpoint)

| Endpoint | Motivo |
|----------|--------|
| `POST /wealth/documents/upload` | Legacy direct upload — frontend usa pre-signed URL flow (`upload-url` + `upload-complete`) |

**Ação:** Remover handler. Manter os 6 endpoints restantes de documents.py.

### 2.5 Remover de `instruments.py` (1 endpoint)

| Endpoint | Motivo |
|----------|--------|
| `POST /instruments/import/csv` | Frontend usa Yahoo import ou screener import |

**Ação:** Remover handler. Manter os 7 endpoints restantes.

---

## Categoria 3 — DEFER (manter no backend, não conectar agora)

Endpoints que têm valor mas são cobertos por alternativas no frontend. Manter no backend para uso futuro ou API direta.

| Endpoint | File | Motivo para defer |
|----------|------|-------------------|
| `GET /screener/securities` | screener.py | Post-screening pipeline view — valor quando fluxo de aprovação evoluir |
| `GET /screener/securities/facets` | screener.py | Acompanha securities acima |
| `POST /screener/import-esma/{isin}` | screener.py | Generic import cobre, mas ESMA-specific enrichment pode ser útil |
| `GET /analytics/backtest/{run_id}` | analytics.py | Útil se backtest virar async com histórico de runs |
| `POST /analytics/optimize` | analytics.py | Single-point optimization para API consumers (frontend usa Pareto) |
| `GET /analytics/strategy-drift/{instrument_id}` | strategy_drift.py | Current score, frontend usa /history. Pode servir API/webhook |

---

## Pós-execução — Atualizar audit

Após completar todas as categorias, atualizar `docs/audit/endpoint-coverage-audit-2026-04-01.md`:

1. **WIRE (Cat 1):** Mover 6 endpoints de DISCONNECTED → CONNECTED + 5 worker triggers wired
2. **DEPRECATE (Cat 2):** Remover 9 endpoints da seção DISCONNECTED e do total backend
3. **DEFER (Cat 3):** Manter 6 endpoints como DISCONNECTED com nota "deferred"

**Novos números esperados:**
```
Total endpoints backend wealth: 167 (176 - 9 deprecated)
Conectados: 164 + 5 workers em settings (169 se contarmos workers)
Desconectados: 6 (deferred) + 3 remanescentes de screener/securities
Coverage: ~96%+ (excluindo deferred)
```

Recalcular Coverage by Route File para cada arquivo afetado.

---

## Regras

- **Não modificar lógica de negócio** — apenas wiring (SSR loaders, fetch calls, componentes de UI)
- Para cada endpoint wired: ler o schema de resposta do backend antes de construir UI
- Usar os padrões existentes no frontend (api client, error handling, loading states)
- SSE: sempre `fetch()` + `ReadableStream`, nunca `EventSource`
- Cada endpoint deprecated: verificar se há testes que o referenciam antes de remover
- Atualizar `routes.json` manifest para cada rota adicionada/removida

## Definition of Done

- [ ] 1.1 Rebalancing apply wired (P1)
- [ ] 1.2 Catalog detail wired (P2)
- [ ] 1.3 Risk SSE stream wired (P2)
- [ ] 1.4 Strategy drift scan trigger wired (P2)
- [ ] 1.5 Private funds tab wired (P2)
- [ ] 1.6 Style history chart wired (P2)
- [ ] 1.7 5 worker triggers added to settings page (P3)
- [ ] 2.1-2.5 9 deprecated endpoints removed from backend
- [ ] Audit doc updated with final numbers
- [ ] All tests passing (`make check`)
