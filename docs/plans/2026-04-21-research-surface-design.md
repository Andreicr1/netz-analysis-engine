---
title: feat: Research Surface Design and Implementation
type: feat
status: active
date: 2026-04-21
deepened: 2026-04-21
---

# feat: Research Surface Design and Implementation

## Overview
A "Research Surface" no Terminal opera em duas fases interligadas do ciclo institucional: exploração de universo (cross-fund) via scatter plot de risco-retorno/matriz de correlação, e o mergulho profundo no fundo (single-fund) para análise de sensibilidade e estilo. O objetivo é fornecer uma interface fluida, matematicamente rigorosa no backend, mas livre de jargões no frontend.

## Problem Frame
A plataforma precisa de uma interface para análise quantitativa multi-ativo e análise de exposição de fatores. O desafio é renderizar gráficos complexos sem vazar jargões técnicos para a UI (filosofia "Smart Backend, Dumb Frontend") e processar matrizes pesadas (O(N³)) no backend sem travar o event loop do FastAPI ou engatilhar conditions de corrida no frontend.

## Requirements Trace
- R1. Explorar ativos no nível do universo via Scatter de Risco-Retorno, focado em "Tail Risk" e "Expected Return".
- R2. Analisar matrizes de correlação estrutural (denoised) vs histórica (raw) entre fundos.
- R3. Visualizar sensibilidades de mercado (fatores PCA) e viés de estilo (KPS) por fundo.
- R4. Suportar cálculos pesados (N > 50) de forma assíncrona, com cache e single-flight locking no frontend.

## Scope Boundaries
- **Deferred to Separate Tasks:**
  - Ingestão de novos dados KPS/PCA (já tratado no worker `equity_characteristics_monthly`).

## Context & Research
### Relevant Code and Patterns
- `frontends/terminal/src/routes/screener/research/+page.svelte` (Base component for multi-fund).
- `@netz/ui/formatters` para formatação institucional (obrigatório).
- `quant_engine` (Regime-conditioned covariance and PCA factor model).

## Key Technical Decisions
- **Correlation Denoise Job-or-Stream**: Cálculos para N > 50 usarão SSE via `/jobs/{id}/stream`.
  - *Rationale*: Evita bloquear o event loop do FastAPI com cálculos O(N³).
- **Marchenko-Pastur PSD Enforcement**: O backend aplicará normalização diagonal e projeção Higham nearest-correlation-matrix após o clipping de eigenvalues.
  - *Rationale*: Garante que a matriz reconstruída seja estritamente Positive Semi-Definite (PSD) para os otimizadores downstream.
- **SHA-256 Analytics Caching**: O backend fará hash (SHA-256) dos parâmetros/universo da matriz e armazenará em cache no Redis por 1 hora.
  - *Rationale*: Previne recalcular decomposições O(N³) no hot path se o job já foi processado recentemente.
- **Columnar Scatter Data**: A API retornará tuplas e arrays colunares para o scatter.
  - *Rationale*: Minimiza payload e tempo de serialização JSON para universos massivos.
- **Single-Flight SSE e AbortController**: O frontend Svelte 5 usará um lock `$state` e invocará `controller.abort()` antes de disparar novos requests SSE.
  - *Rationale*: Previne memory leaks e race conditions se o usuário alternar abas/filtros rapidamente.
- **UX Sanitization**: Jargões quantitativos (KPS, PCA, t_stat, Denoised, Marchenko-Pastur) são proibidos na UI. 
  - *Rationale*: Filosofia "Smart Backend, Polished Frontend". Termos mapeados para: "Market Sensitivities", "Style Bias", "Structural Correlation", "Historical Correlation".

## Open Questions
### Resolved During Planning
- **Como agrupar o hairball do scatter plot?** O scatter usará o `strategy_map` retornado pela API para colorir os fundos por mandato, destacando outliers e aplicando `dim` ao restante da massa.

### Deferred to Implementation
- Parâmetros e limiares exatos do `visualMap` divergente para o heatmap de correlação.

## Implementation Units

- [ ] **Unit 1: Backend API Contracts (Market Sensitivities & Style Bias)**
**Goal**: Criar rotas para retornar dados single-fund (PCA e KPS).
**Requirements**: R3
**Dependencies**: None
**Files**:
- Modify: `backend/app/domains/wealth/models.py` (ou schemas correspondentes)
- Modify: `backend/app/domains/wealth/routes/research.py`
**Approach**: Definir `FactorExposure` (incluindo `significance` derivado de `t_stat`) e incluir métricas agregadas `r_squared` e `systematic_risk_pct` para auditoria do comitê.
**Test scenarios**:
- Happy path: Retorna dados completos para fundo com histórico, formatados de acordo com os schemas esperados.

- [ ] **Unit 2: Backend API Contracts (Scatter & Structural Correlation)**
**Goal**: Criar rotas para Scatter colunar e Correlação (Job-or-Stream).
**Requirements**: R1, R2, R4
**Dependencies**: Unit 1
**Files**:
- Modify: `backend/app/domains/wealth/routes/correlation.py`
**Approach**: Implementar síncrono para N<=50, 202 Accepted para N>50. Implementar SHA-256 caching no Redis e normalização PSD/Higham para a matriz estrutural (denoised). Retornar `regime_state_at_calc` e `effective_window_days` na resposta.
**Test scenarios**:
- Edge case: Para universo N>50, valida a criação do job e o hash correto de Redis cache.
- Happy path: Cálculo de N<=50 retorna 200 OK com matriz PSD estrita (diagonal 1).

- [ ] **Unit 3: Frontend Research Scatter & Correlation (Multi-Fund)**
**Goal**: Implementar a rota `/screener/research` com Scatter e Heatmap.
**Requirements**: R1, R2
**Dependencies**: Unit 2
**Files**:
- Modify: `frontends/terminal/src/routes/screener/research/+page.svelte`
- Create: `frontends/terminal/src/lib/components/research/CorrelationHeatmap.svelte`
- Create: `frontends/terminal/src/lib/components/research/RiskReturnScatter.svelte`
**Approach**: Fetch+ReadableStream com Single-Flight `AbortController`. Heatmap toggle rotulado "Structural" vs "Historical". Scatter colorido por `strategy_map`.
**Test scenarios**:
- Error path: Interromper carregamento SSE se novo fetch for iniciado (Single-Flight/Abort).
- Happy path: Matriz renderizada. Toggles e eixos atualizados usando nomenclatura não-quant (UX sanitization).

- [ ] **Unit 4: Frontend Single Fund Research (Sensitivities & Style)**
**Goal**: Implementar a análise de fatores e estilo por fundo.
**Requirements**: R3
**Dependencies**: Unit 1
**Files**:
- Modify: `frontends/terminal/src/routes/fund/[id]/research/+page.svelte`
- Create: `frontends/terminal/src/lib/components/research/MarketSensitivitiesBar.svelte`
- Create: `frontends/terminal/src/lib/components/research/StyleBiasRadar.svelte`
**Approach**: Radar para KPS ("Style Bias") e Horizontal Bar para PCA ("Market Sensitivities"). O campo `t_stat` é traduzido via `significance` para opacidade no ECharts. Injetar CTA "Add to Model Portfolio / Watchlist" no header.
**Test scenarios**:
- Happy path: Gráficos montam as legendas com termos traduzidos ("Market Sensitivities", etc.). Eixos renderizados com o CTA injetado corretamente.

## System-Wide Impact
- **State lifecycle risks**: SSE connections devem ser rigorosamente limpas (`controller.abort()`) com um padrão single-flight lock no Svelte `$effect`.
- **API surface parity**: Adição de rotas focadas em dados colunares; otimização do event loop do FastAPI.
- **Integration coverage**: As projeções Higham no backend garantem que o otimizador downstream (CLARABEL) não quebre ao ingerir matrizes denoised geradas por este painel.

## Risks & Dependencies
| Risk | Mitigation |
|------|------------|
| O(N³) Correlation travando API | Limite rígido (Top 200), Job-or-Stream para N > 50, e SHA-256 Redis Caching (1h). |
| Matriz MP Denoised quebrando otimizador | Normalização diagonal e projeção Higham para garantir Strict PSD. |
| Race Conditions com SSE no Frontend | Single-flight lock em Svelte (`if (activeController) activeController.abort()`) e Loading Skeletons. |
| Vazamento de jargões para clientes | Sanitização estrita de UI: "Market Sensitivities", "Style Bias", "Structural Correlation". |

## Sources & References
- **Origin document:** `docs/plans/2026-04-21-research-surface-design.md` (original draft)
- AGENTS.md / GEMINI.md (Smart Backend, Dumb Frontend; Formatter discipline).
- Svelte 5 / Runes documentation for SSE management.
