---
title: feat: Implement LIVE Workbench and Real-Time TopNav
type: feat
status: active
date: 2026-04-21
---

# feat: Implement LIVE Workbench and Real-Time TopNav

## Overview

A Sprint 2a.2 estabelece a camada de tempo real do Netz Terminal: o "LIVE Workbench" e os indicadores globais do "TopNav". Este plano detalha a integração de fluxos de dados ao vivo do Tiingo e eventos processados pelo backend via SSE e WebSocket, garantindo que o SvelteKit mantenha estabilidade sob alta frequência, e que o banco de dados armazene o histórico para backtesting usando TimescaleDB (regras DB-first).

## Problem Frame

A interface atual não reflete os dados ao vivo. Precisamos integrar fluxos de alta frequência (Tiingo) e baixa frequência (eventos Netz, macro regime) sem causar *render thrashing* na UI e sem violar o padrão arquitetural "DB-First" para ingestão de dados externos.

## Requirements Trace

- R1. Ingestão segura via Background Worker único conectado ao Tiingo (WS) com *batch inserts* e Redis Pub/Sub, preservando a API Key.
- R2. Persistência no TimescaleDB em hypertables globais e Continuous Aggregates (CAGG) de 1 minuto para carregar o histórico no frontend sem travar o browser.
- R3. Conexão SSE para eventos e WS proxy para preços do backend Netz ao Svelte usando `fetch() + ReadableStream`.
- R4. Exibir o indicador do Regime Macro atual no TopNav, atualizado em tempo real.
- R5. Proteger a UI de "render thrashing" usando `createTickBuffer<T>` e ECharts com alta performance (animações desligadas).
- R6. Integração agnóstica com componentes visuais da `@netz/ui` via `$props()`.

## Scope Boundaries

- **Proxy e DB-First**: A API Key do Tiingo não toca o frontend. O fluxo é roteado obrigatoriamente por um background worker global que persiste os dados e publica no Redis. A FastAPI assina o Redis.
- **Sem EventSource Nativo**: Para conexões SSE, utilizamos apenas `fetch() + ReadableStream` devido ao Header de Autenticação JWT.
- **Sem Código Funcional Nesta Etapa**: Apenas arquitetura, tipagens e esquemas.

## Context & Research

### Relevant Code and Patterns

- **Svelte 5 Runes & Lifecycle**:
  - Utilização estrita do `$effect` retornando a função de teardown (ex: `return () => controller.abort()`).
  - `MarketConnectionManager` instanciado como uma Classe reativa (com `$state`) via Context API (`setContext`/`getContext`), nunca stores globais ou funções soltas.
- **Frontend ECharts Performance**: Desativar animações (`animation: false`), usar janelas deslizantes (`.slice(-100)`) e `sampling: 'lttb'` para garantir a renderização de Sparklines no MarketFeedList.
- **Frontend Consistency**: Componentes de `@netz/ui` não podem importar de `wealth/`. Dados passam via `$props()`. Uso obrigatório de `formatCurrency` e `formatNumber`.
- **Database Architecture**: Uso de `pg_try_advisory_lock` para o worker global. Hypertables sem `organization_id` (dados globais de mercado).

## Key Technical Decisions

- **Worker de Ingestão Global (DB-First)**: Um background worker manterá a conexão com o Tiingo (com `thresholdLevel=6` para compliance IEX). Ele fará *batch inserts* usando `asyncpg.executemany` e publicará no Redis.
- **Persistência TimescaleDB**: Criação da hypertable `intraday_market_ticks` (chunk 1 dia, compressão por ticker) e `market_events` (chunk 1 mês, índice GIN). Criação do Continuous Aggregate `market_candles_1m` para servir histórico ao UI.
- **Svelte Connection Manager**: Uma classe reativa `$state` registrada no `+layout.svelte`. Capturará silenciosamente o `AbortError` do `fetch()`.
- **Render Thrashing Protection**: O uso do `createTickBuffer<T>` fará flush (ex: 200ms) dos dados recebidos via WS Proxy para atualizar os Sparklines do ECharts.

## Implementation Units

- [ ] **Unit 1: Ingestion Worker (Backend)**

**Goal:** Criar o worker isolado que consome o Tiingo WS e persiste/publica.

**Files:**
- Create: `backend/app/domains/wealth/workers/tiingo_ingestion_worker.py`

**Approach:**
- Usar `pg_try_advisory_lock` (ex: lock ID 800_001 determinístico).
- Conectar ao Tiingo `wss://api.tiingo.com/iex?thresholdLevel=6`.
- Processar mensagens (Array index 3 para ticker, 9 para lastPrice).
- Acumular em memória e fazer batch insert (`asyncpg.executemany`) a cada ~1s em `intraday_market_ticks`.
- Publicar no Redis Pub/Sub nos canais `tiingo:ticks` e `market:events`.

**Test scenarios:**
- Happy path: Valida lock exclusivo; processa batch inserts para a base de dados em intervalos fixos.

- [ ] **Unit 2: Database Schema & Continuous Aggregates (Backend)**

**Goal:** Estruturar as tabelas e CAGG otimizadas no TimescaleDB.

**Files:**
- Create: `backend/app/core/db/migrations/versions/XXXX_add_live_market_hypertables.py`

**Approach:**
- Criar tabelas globais (sem `organization_id`, sem RLS).
- `intraday_market_ticks`: `create_hypertable` (1 day), `add_compression_policy` (7 days), `compress_segmentby='ticker'`.
- `market_events`: `create_hypertable` (1 month), GIN index no campo `payload`.
- Criar Materialized View Continuous Aggregate `market_candles_1m` baseada em `intraday_market_ticks`.

**Test scenarios:**
- Happy path: Migração executa sem erros; tabelas configuradas corretamente como hypertables globais.

- [ ] **Unit 3: API Contracts e FastAPI Routes (Backend & Frontend)**

**Goal:** Definir os schemas e a rota que assina o Redis Pub/Sub e devolve o SSE/WS Proxy.

**Files:**
- Create/Modify: `backend/app/domains/wealth/schemas/live_events.py`
- Create/Modify: `backend/app/domains/wealth/routes/live.py`
- Create/Modify: `frontends/wealth/src/lib/types/live.ts`

**Approach:**
- Definir interfaces `MarketPriceTick`, `NewsPayload`, `MarketEvent`.
- Rota `/events` (SSE): Consome do Redis usando `RateLimitedBroadcaster` e retorna `EventSourceResponse`. Aceita queries `tickers` e `tags` para filtrar eventos e notícias.
- Rota `/ticks` (WS): Proxy do Redis `tiingo:ticks` para o Svelte.

**Test scenarios:**
- Test expectation: none -- Tipagens, schemas e assinaturas puramente.

- [ ] **Unit 4: SSE Client & Svelte Connection Manager (Frontend)**

**Goal:** Implementar a lógica de orquestração SSE/WS orientada a Svelte 5 (Runes/Classes).

**Files:**
- Create: `frontends/wealth/src/lib/services/MarketConnectionManager.ts`
- Create: `frontends/wealth/src/lib/services/sseClient.ts`
- Modify: `frontends/wealth/src/routes/(app)/+layout.svelte`

**Approach:**
- Criar a classe `MarketConnectionManager` contendo campos `$state` para os eventos.
- `sseClient`: Usar `fetch()` + `ReadableStream` com `AbortController`. Capturar silenciosamente `err.name === 'AbortError'`.
- Instanciar a classe no `$effect` do `+layout.svelte`, definindo o cleanup (`manager.destroy()`) e passando para os filhos via `setContext`.
- Para os preços (WS), engatilhar `createTickBuffer` (200ms flush).

**Test scenarios:**
- Happy path: Manager inicializa e captura as reações; abort encerra conexões e limpa loops.

- [ ] **Unit 5: Componentes Visuais e ECharts Sparklines (Frontend)**

**Goal:** Atualizar componentes visuais com formatadores estritos e performance.

**Files:**
- Modify: `packages/ui/src/lib/components/TopNav.svelte`
- Create/Modify: `packages/ui/src/lib/components/LiveMarquee.svelte`
- Create/Modify: `packages/ui/src/lib/components/MarketFeedList.svelte`

**Approach:**
- Componentes da `@netz/ui` recebem dados primitivos via `$props()`.
- Usar formatadores institucionais (`formatCurrency`).
- `MarketFeedList`: Inserir combobox para filtros de fontes e tags (reengatilha SSE se mudar).
- `MarketFeedList`/`LiveMarquee`: Incorporar **ECharts Sparklines**.
- Regras ECharts: `animation: false`, matriz de dados `.slice(-100)`, uso de `var(--color-success)` do design system, e `sampling: 'lttb'`.
- Validar altura no `TopNav` para não quebrar a restrição de layout `calc(100vh - 88px)`.

**Test scenarios:**
- Happy path: Componentes rendem sem erro. Formatação de moeda exata. Sparklines não causam render thrashing ao receber lotes do Tick Buffer.

## System-Wide Impact

- **Database Performance**: O uso de batching no worker protege o TimescaleDB contra WAL bloat de alta frequência.
- **Frontend Render Thrashing**: O Tick Buffer isola a UI; animações desligadas no ECharts mantêm o event-loop fluido.
- **Security**: Nenhuma API Key do Tiingo é exposta ao client; os dados estão isolados e o auth baseia-se no framework Clerk / JWT do Netz.
- **Arquitetura Svelte 5**: Evita loops de reatividade perigosos aderindo aos padrões oficiais.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Render thrashing (Frontend). | Uso de `createTickBuffer` (200ms), `$state` fora de loops de leitura assíncrona, e ECharts `animation: false`. |
| Exaustão de Conexões no BD. | Worker único executa `asyncpg.executemany` acumulado por tempo, não inserindo a cada tick. |
| Bloqueio do Event Loop do FastAPI. | O Broadcaster SSE consome passivamente via Redis Pub/Sub (`RateLimitedBroadcaster`). |
| Vazamento de memória (Zumbis SSE/WS). | Uso de `AbortController` atrelado perfeitamente ao teardown (`return () => controller.abort()`) do `$effect` no Svelte 5. |