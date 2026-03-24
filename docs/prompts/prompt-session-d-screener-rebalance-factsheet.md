# Sessao D — Screener Detail + Rebalance Event + Fact Sheet Download (3 endpoints)

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
- Sessao B (Macro Expansion + Risk Summary): DONE
- Sessao C (Content Spotlight + Pareto SSE + Drift Export): DONE — Spotlight button com
  fund picker na content page, Pareto SSE stream com progress+results na analytics page,
  Drift export via backend endpoint no DriftHistoryPanel.

**Regras invariantes:**
- `async def` + `AsyncSession` em routes. Sync Session apenas dentro de `asyncio.to_thread()`
- Formatacao via `@netz/ui` formatters (`formatNumber`, `formatPercent`, `formatDate`, etc.), nunca `.toFixed()` / `.toLocaleString()`
- SSE sempre via `fetch()` + `ReadableStream`, nunca `EventSource`
- Backend-first: verificar se rota existe e responde antes de wiring frontend
- Sem over-engineering: componentes simples antes de abstracoes
- Import-linter enforced: nao importar entre verticais

---

## Endpoints a conectar

### 1. GET /screener/results/{instrument_id}

**Backend:** Verificar existencia em
`backend/app/domains/wealth/routes/screener.py`. Provavelmente retorna score breakdown
com os 6 componentes do `scoring_service` (eliminatory, mandate_fit, quant scores).

**Frontend:** Adicionar drill-down na screener results page.
- `GET /screener/results` ja esta conectado e mostra a tabela de resultados
- Falta: click na row abre drawer/panel com score breakdown por instrumento
- Procurar screener page em `frontends/wealth/src/routes/(app)/screener/` ou similar
- Replicar padrao master/detail ou drawer existente

### 2. GET /portfolios/{profile}/rebalance/{event_id}

**Backend:** Verificar existencia em
`backend/app/domains/wealth/routes/portfolios.py` (ou `rebalancing.py`).
Retorna detalhe de um evento de rebalanceamento com weights propostos.

**Frontend:** Adicionar expand/detail na RebalancingTab.
- Lista de eventos de rebalanceamento ja carrega no mount
- Falta: expandir item individual para ver weights propostos e detalhes
- Procurar `RebalancingTab` em `frontends/wealth/src/lib/components/`
- Usar row expansion no DataTable (padrao ja usado no DriftHistoryPanel)

### 3. GET /fact-sheets/dd-reports/{report_id}/download

**Backend:** Verificar existencia em
`backend/app/domains/wealth/routes/fact_sheets.py` (ou `dd_reports.py`).
Retorna PDF do fact sheet do DD report.

**Frontend:** Adicionar botao "Download Fact Sheet" na DD report detail page.
- DD report detail esta em `frontends/wealth/src/routes/(app)/dd-reports/[fundId]/[reportId]/+page.svelte`
- Approve/reject/regenerate ja conectados — falta botao de download do fact sheet
- Replicar padrao de download da content page (fetch blob + create object URL + click)

---

## Passo a passo recomendado

1. Ler `backend/app/domains/wealth/routes/screener.py` para confirmar endpoint de detail
2. Ler a screener page frontend para entender estrutura atual
3. Adicionar drawer/panel de score breakdown por instrumento
4. Ler routes de portfolios/rebalancing para confirmar endpoint de evento
5. Localizar RebalancingTab e adicionar row expansion
6. Ler routes de fact-sheets para confirmar endpoint de download
7. Ler DD report detail page e adicionar botao de download
8. Rodar `make lint` + `pnpm run check` no wealth frontend
9. Rodar testes relacionados

---

## Nota Final

Esta e a ultima sessao do plano de cobertura. Apos conclusao, a cobertura esperada e
~98-99% dos endpoints wealth com UI funcional. Os 3 endpoints restantes sem UI sao APIs
programaticas (`POST /wealth/documents/upload`, `POST /documents/upload-url`,
`POST /documents/upload-complete`) que nao precisam de frontend.
