# Prompt: Doc Update Pós-Sprint de Wiring (2026-04-01)

## Contexto

Cinco prompts de wiring foram executados com sucesso nesta data:
- A — Phantoms fixes (PATCH /model-portfolios/{id}, GET /instruments/{id}/risk-metrics)
- B — Correlation Regime Heatmap (2 endpoints)
- C — Active Share Panel (1 endpoint)
- D — Manager Screener List + Compare (2 endpoints)
- E — Screener Batch (5 endpoints)

Esta tarefa atualiza dois documentos de referência para refletir o estado atual:
1. `docs/audit/endpoint-coverage-audit-2026-04-01.md`
2. `docs/reference/analytical-capabilities-reference.md`

**Não modificar nenhum arquivo de código.**

---

## Tarefa 1 — Atualizar o audit de cobertura

**Arquivo:** `docs/audit/endpoint-coverage-audit-2026-04-01.md`

### 1.1 Mover os seguintes endpoints de DISCONNECTED → CONNECTED

Leia o arquivo inteiro antes de editar. Os endpoints abaixo foram conectados neste sprint:

**Phantom fixes (agora com backend):**
- `PATCH /model-portfolios/{portfolio_id}` — novo handler em `model_portfolios.py`
- `GET /instruments/{instrument_id}/risk-metrics` — nova sub-rota em `instruments.py`

**Prompt B — Correlation Regime:**
- `GET /analytics/correlation-regime/{profile}` → `analytics/+page.server.ts`
- `GET /analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` → `CorrelationRegimePanel.svelte`

**Prompt C — Active Share:**
- `GET /analytics/active-share/{entity_id}` → `analytics/[entityId]/+page.server.ts`

**Prompt D — Manager Screener:**
- `GET /manager-screener/` → `screener/managers/+page.server.ts`
- `POST /manager-screener/managers/compare` → `screener/managers/+page.svelte`

**Prompt E — Screener Batch:**
- `POST /screener/run` → `ScreeningRunPanel.svelte`
- `GET /screener/runs` → `ScreeningRunPanel.svelte`
- `GET /screener/runs/{run_id}` → `screener/runs/[runId]/+page.server.ts`
- `GET /screener/results` → `ScreeningRunPanel.svelte`
- `GET /screener/facets` → `ScreeningRunPanel.svelte`

### 1.2 Reclassificar Phantoms resolvidos

Os dois phantom calls que eram bugs de produção agora têm backend:
- `PATCH /model-portfolios/{portfolio_id}` — remover da seção Phantom Calls
- `GET /instruments/{instrument_id}/risk-metrics` — remover da seção Phantom Calls

### 1.3 Recalcular o resumo executivo

Atualizar o bloco no topo do arquivo:

```
Data: 2026-04-01 (atualizado pós-sprint)
Total endpoints backend wealth (excl. infra/workers): 176
Conectados: [recalcular: 145 + 13 novos = 158]
Desconectados: [recalcular: 31 - 13 = 18]
Infra/workers (excluídos): 28
Phantom calls (frontend → backend inexistente): 0
```

Recalcular a % de cobertura: 158/176 = 89.8%.

### 1.4 Atualizar o Top 10

Remover do Top 10 os itens resolvidos (phantoms, active share, correlation regime,
manager screener list, screener batch). Não adicionar novos itens — deixar a lista
refletir apenas o que permanece desconectado.

### 1.5 Atualizar a tabela "Coverage by Route File"

Atualizar os números das linhas afetadas:
- `correlation_regime.py`: era 0% → agora 100% (2/2)
- `entity_analytics.py`: era 50% → agora 100% (2/2)
- `manager_screener.py`: era 85% (11/13) → agora 100% (13/13)
- `screener.py`: era 40% (6/15) → agora 73% (11/15) — ainda faltam 4 P3
- `model_portfolios.py`: era 100% → continua 100% (PATCH é novo endpoint)
- `instruments.py`: era 86% (6/7) → agora 100% (7/7)
- Adicionar nota de rodapé: "Updated 2026-04-01 after wiring sprint (Prompts A-E)"

---

## Tarefa 2 — Atualizar analytical-capabilities-reference.md

**Arquivo:** `docs/reference/analytical-capabilities-reference.md`

### 2.1 Corrigir seção 14.1 — Entity Analytics Page

A tabela atual tem Active Share marcado como "Future":
```
| Active Share | `ActiveSharePanel.svelte` | Future: `/active-share/{id}` (hero metric + overlap) |
```

Corrigir para:
```
| Active Share | `ActiveSharePanel.svelte` | `/analytics/active-share/{entity_id}` — benchmark_id obrigatório via URL param. Hero metric: active share %, classification badge (Stock Picker/Active/Moderately Active/Closet Indexer), overlap %, efficiency com sinal explícito, position counts. Empty state quando benchmark_id ausente. |
```

O total de painéis passa de "10 panels" para "11 panels" no parágrafo acima da tabela.

### 2.2 Corrigir seção 14.2 — Portfolio Analytics Page

Adicionar as linhas que faltam na tabela. A tabela atual termina em "Factor Analysis".
Adicionar após a última linha existente:

```
| Correlation Regime | `CorrelationRegimePanel.svelte` | `/analytics/correlation-regime/{profile}` — heatmap divergente RdBu, Marchenko-Pastur eigenvalue decomposition, contagion pairs, regime shift badge. Drill-down pairwise via RegimeChart ao clicar célula do heatmap. |
| Screening | `ScreeningRunPanel.svelte` | `POST /screener/run`, `GET /screener/runs`, `GET /screener/results` — trigger de batch screening 3-layer, histórico de runs, tabela de resultados correntes com PASS/FAIL/WATCHLIST badges e layer breakdown expandível. |
```

### 2.3 Adicionar seção 14.4 — Screener Page (`/screener`)

Após a seção 14.3 (Risk Monitor), inserir nova seção:

```markdown
### 14.4 Screener Page (`/screener`)

Dois modos via tabs controladas por URL param `?tab=`:

| Tab | Componentes | Endpoints |
|-----|-------------|-----------|
| Catalog (`?tab=catalog`) | `CatalogTable`, `CatalogFacets`, `CatalogDetailPanel` | `GET /screener/catalog`, `GET /screener/catalog/facets`, `GET /screener/catalog/{id}/detail` |
| Screening (`?tab=screening`) | `ScreeningRunPanel` | `POST /screener/run` (202 fire-and-forget), `GET /screener/runs`, `GET /screener/results`, `GET /screener/facets` |

**Screener Managers** (`/screener/managers`):
- Listagem paginada de RIA managers com filtros (text search, AUM, paginação)
- Checkboxes para selecionar até 3 managers → `POST /manager-screener/managers/compare`
- Compare result em ContextPanel side-by-side (AUM, disclosures, funds, holdings overlap)
- Navega para `/screener/managers/{crd}` para detalhe individual (já existia)
```

### 2.4 Adicionar seção 14.5 — Novos componentes de chart

Após a seção 14.4, inserir:

```markdown
### 14.5 Novos componentes de chart (2026-04-01)

Criados neste sprint — todos em `frontends/wealth/src/lib/components/`:

| Componente | Localização | Descrição |
|-----------|------------|-----------|
| `CorrelationHeatmap.svelte` | `charts/` | Heatmap divergente RdBu 7-stop. Paleta via `visualMap`, click handler via `echarts.getInstanceByDom()`, dark mode neutral via `getComputedStyle`. `$state.raw()` para dados. |
| `EigenvalueChart.svelte` | `charts/` | Barras Marchenko-Pastur: azul (signal) / cinza (noise). `markLine` dashed no threshold. Labels λ1, λ2, ... |
| `CorrelationRegimePanel.svelte` | `entity-analytics/` | Orquestrador: badge de regime shift, 4 KPI MetricCards, contagion pairs clicáveis, heatmap, eigenvalue chart, lazy-fetch de pair drill-down. |
| `ActiveSharePanel.svelte` | `entity-analytics/` | 3 estados: empty (sem benchmark), erro (sem N-PORT data), dados (hero metric + classification badge). Lazy-load de instruments para selector. |
| `ScreeningRunPanel.svelte` | `screener/` | 3 sub-seções: trigger dialog (POST 202 + toast), run history table, resultados correntes com expandable layer detail. |
```

### 2.5 Atualizar seção 13 — Portfolio Analytics Endpoints

A tabela de endpoints não lista `correlation-regime`. Adicionar ao final da tabela:

```
| `/analytics/correlation-regime/{profile}` | GET | Regime-conditioned correlation matrix com Marchenko-Pastur denoising |
| `/analytics/correlation-regime/{profile}/pair/{a}/{b}` | GET | Rolling pairwise correlation com regime overlay |
| `/analytics/active-share/{entity_id}` | GET | Active Share vs benchmark (requer benchmark_id query param) |
```

---

## Regras

- **Não modificar nenhum arquivo de código** (backend ou frontend)
- Editar apenas os dois arquivos de documentação especificados
- Manter o estilo e formatação existente de cada arquivo
- Não adicionar seções além das descritas acima
- Se um número calculado parecer incorreto, reportar a discrepância em vez de inventar

## Definition of Done

- [ ] Resumo executivo do audit atualizado (158 conectados, 18 desconectados, 89.8%, 0 phantoms)
- [ ] 13 endpoints movidos de DISCONNECTED para CONNECTED no audit
- [ ] 0 phantom calls na seção de phantoms
- [ ] Top 10 atualizado (sem itens resolvidos neste sprint)
- [ ] Tabela "Coverage by Route File" com números corretos
- [ ] Seção 14.1 do reference corrigida (Active Share sem "Future:")
- [ ] Seção 14.2 do reference com Correlation Regime e Screening adicionados
- [ ] Seção 14.4 criada (Screener Page)
- [ ] Seção 14.5 criada (novos componentes de chart)
- [ ] Seção 13 do reference com 3 endpoints novos na tabela
