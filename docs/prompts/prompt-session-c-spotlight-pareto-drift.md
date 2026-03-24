# Sessao C — Content Spotlight + Analytics Pareto + Drift Export (3 endpoints)

**Projeto:** netz-analysis-engine
**Branch:** main
**Plano:** docs/plans/wm-coverage-plan-2026-03-23.md
**Executor:** Claude Opus (sessao fresca)
**Revisor:** Andrei
**Criterio de saida:** `make check` verde (backend) + `pnpm run check` verde no wealth frontend (erros pre-existentes em credit e portfolios/[profile] sao ignoraveis) + endpoints testaveis end-to-end no frontend

---

## Contexto

Ler CLAUDE.md para regras do projeto. Ler o plano revisado em
docs/plans/wm-coverage-plan-2026-03-23.md para contexto completo.

**Status anterior:**
- Pre-sessao (HC-1 a HC-3): DONE
- Sessao A (DD Report Lifecycle): DONE
- Sessao B (Macro Expansion + Risk Summary): DONE — BIS e IMF panels adicionados a
  macro page seguindo padrao Treasury/OFR. Risk Summary banner adicionado ao topo da
  risk page com metricas agregadas (worst utilization, breached, warnings, drift alerts).

**Regras invariantes:**
- `async def` + `AsyncSession` em routes. Sync Session apenas dentro de `asyncio.to_thread()`
- Formatacao via `@netz/ui` formatters (`formatNumber`, `formatPercent`, `formatDate`, etc.), nunca `.toFixed()` / `.toLocaleString()`
- SSE sempre via `fetch()` + `ReadableStream`, nunca `EventSource`
- Backend-first: verificar se rota existe e responde antes de wiring frontend
- Sem over-engineering: componentes simples antes de abstracoes
- Import-linter enforced: nao importar entre verticais

---

## Endpoints a conectar

### 1. POST /content/spotlights

**Backend:** Verificar existencia e response schema em
`backend/app/domains/wealth/routes/content.py`. Provavelmente similar a
`POST /content/flash-reports` e `POST /content/outlooks` (que ja estao conectados).

**Dados esperados:** Gera um Manager Spotlight report. HC-1 (SET LOCAL) confirmado
fechado na pre-sessao.

**Frontend:** Adicionar botao "Manager Spotlight" na content listing page em
`frontends/wealth/src/routes/(app)/content/+page.svelte`.
- Flash Reports e Outlooks ja tem botoes nessa page — replicar o padrao
- O botao deve disparar `POST /content/spotlights` e atualizar a listing

### 2. GET /analytics/optimize/pareto/{job_id}/stream

**Backend:** Verificar existencia em
`backend/app/domains/wealth/routes/analytics.py` (provavel).
`POST /analytics/optimize/pareto` ja esta conectado e retorna 202 com job_id.
O stream endpoint fornece progresso SSE do job.

**Frontend:** Adicionar painel SSE para Pareto na analytics/optimize page.
- `POST /analytics/optimize/pareto` ja esta conectado — resultado fica inacessivel
  porque o stream SSE nao esta wired
- Usar `fetch()` + `ReadableStream` (NUNCA EventSource — auth headers necessarios)
- Provavelmente em `frontends/wealth/src/routes/(app)/analytics/+page.svelte`
  ou sub-componente

### 3. GET /analytics/strategy-drift/{instrument_id}/export

**Backend:** Verificar existencia em
`backend/app/domains/wealth/routes/analytics.py`.
Retorna CSV com historico de drift para o instrumento.

**Frontend:** Adicionar botao "Export CSV" no DriftHistoryPanel.
- `GET /analytics/strategy-drift/{instrument_id}/history` ja mostra o historico
- Falta botao que chama o endpoint de export e triggers download do CSV
- Procurar por `DriftHistoryPanel` no frontend wealth
  (provavelmente em `src/lib/components/` ou inline na analytics page)

---

## Passo a passo recomendado

1. Ler `backend/app/domains/wealth/routes/content.py` para confirmar endpoint spotlight
2. Ler `frontends/wealth/src/routes/(app)/content/+page.svelte` para ver padrao de flash-reports/outlooks
3. Adicionar botao Manager Spotlight replicando o padrao
4. Ler `backend/app/domains/wealth/routes/analytics.py` para confirmar pareto stream e drift export
5. Ler a analytics page frontend para entender onde wiring o pareto SSE
6. Adicionar SSE stream para pareto job progress
7. Localizar DriftHistoryPanel e adicionar botao Export CSV
8. Rodar `make lint` + `pnpm run check` no wealth frontend
9. Rodar testes relacionados

---

## Prompt Chain

Ao final desta sessao, preparar um prompt self-contained para a **Sessao D**
(Screener Detail + Rebalance Event + Fact Sheet Download — 3 endpoints) e salvar em
`docs/prompts/prompt-session-d-screener-rebalance-factsheet.md`.
Incluir instrucao para o proximo agente tambem preparar prompt para a sessao seguinte
(se houver endpoints restantes no plano).
