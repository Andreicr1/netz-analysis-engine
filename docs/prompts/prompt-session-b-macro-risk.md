# Sessao B — Macro Expansion + Risk Summary (3 endpoints)

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
- Sessao A (DD Report Lifecycle): DONE — `POST /dd-reports/funds/{fund_id}` ja estava
  conectado (falso negativo do scanner). `GET /dd-reports/{report_id}/audit-trail` foi
  conectado com secao colapsavel na report detail page.

**Regras invariantes:**
- `async def` + `AsyncSession` em routes. Sync Session apenas dentro de `asyncio.to_thread()`
- Formatacao via `@netz/ui` formatters (`formatNumber`, `formatPercent`, `formatDate`, etc.), nunca `.toFixed()` / `.toLocaleString()`
- SSE sempre via `fetch()` + `ReadableStream`, nunca `EventSource`
- Backend-first: verificar se rota existe e responde antes de wiring frontend
- Sem over-engineering: componentes simples antes de abstracoes
- Import-linter enforced: nao importar entre verticais

---

## Endpoints a conectar

### 1. GET /macro/bis

**Backend:** Verificar existencia e response schema em
`backend/app/domains/wealth/routes/macro.py` (provavel). Lê de hypertable global
`bis_statistics` (sem RLS — tabela global).

**Dados esperados:** BIS credit gap, debt-service ratio (DSR), property prices.
Worker `bis_ingestion` (lock ID 900_014) ja popula a hypertable.

**Frontend:** Adicionar secao "Global Credit" na macro page existente em
`frontends/wealth/src/routes/(app)/macro/+page.svelte`.
- A macro page ja conecta: regime, scores, snapshot, reviews, OFR, treasury
- BIS e uma extensao direta no mesmo padrao
- Verificar como OFR e treasury sao chamados (provavelmente `api.get('/macro/ofr', { params })`)
  e replicar o padrao para BIS

### 2. GET /macro/imf

**Backend:** Verificar existencia e response schema em
`backend/app/domains/wealth/routes/macro.py`. Le de hypertable global
`imf_weo_forecasts` (sem RLS — tabela global).

**Dados esperados:** IMF WEO forecasts — GDP growth, inflation, fiscal balance por regiao.
Worker `imf_ingestion` (lock ID 900_015) ja popula a hypertable.

**Frontend:** Adicionar secao "Economic Outlook" na macro page existente.
Mesmo padrao de implementacao que BIS.

### 3. GET /risk/summary

**Backend:** Verificar existencia e response schema em
`backend/app/domains/wealth/routes/risk.py` (provavel). Retorna aggregate risk
cross-profile para o dashboard top-level.

**Frontend:** Adicionar widget "Risk Summary" no topo do wealth dashboard.
- Dashboard provavel: `frontends/wealth/src/routes/(app)/+page.svelte` ou
  `frontends/wealth/src/routes/(app)/dashboard/+page.svelte`
- Widget compacto com metricas agregadas (CVaR, regime, drift count, etc.)

---

## Passo a passo recomendado

1. Ler os arquivos de backend para confirmar endpoints e schemas
2. Ler a macro page frontend para entender o padrao existente de OFR/treasury
3. Adicionar secoes BIS e IMF replicando o padrao
4. Localizar o dashboard e adicionar widget Risk Summary
5. Rodar `make lint` + `pnpm run check` no wealth frontend
6. Rodar testes relacionados

---

## Prompt Chain

Ao final desta sessao, preparar um prompt self-contained para a **Sessao C**
(Content Spotlight + Analytics Pareto + Drift Export — 3 endpoints) e salvar em
`docs/prompts/prompt-session-c-spotlight-pareto-drift.md`.
Incluir instrucao para o proximo agente tambem preparar prompt para a sessao seguinte (Sessao D).
