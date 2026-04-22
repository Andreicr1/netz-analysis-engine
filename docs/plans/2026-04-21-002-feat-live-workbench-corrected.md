---
title: feat: LIVE Workbench e TopNav Real-Time — Plano Corrigido
type: feat
status: active
date: 2026-04-21
supersedes: 2026-04-21-001-feat-live-workbench-plan.md
---

# feat: LIVE Workbench e TopNav Real-Time — Plano Corrigido

## Contexto da Revisão

Este documento substitui `2026-04-21-001-feat-live-workbench-plan.md` após auditoria de repositório.
O plano original propunha recriar infraestrutura que já existe, com índices de parsing Tiingo incorretos
e targets de frontend errados. Ver review completo em conversa de 2026-04-21.

## Estado Atual — O que já existe

| Componente | Arquivo | Estado |
|---|---|---|
| Bridge Tiingo WS→Redis | `backend/app/core/ws/tiingo_bridge.py` | **Completo** — IdleBridgePolicy + SingleFlightLock + buffer 50ms |
| WS manager Redis | `backend/app/core/ws/manager.py` | **Completo** — `market:prices:{TICKER}`, RateLimitedBroadcaster |
| Rota WS `/live/ws` | `backend/app/domains/wealth/routes/market_data.py:68` | **Completo** — `/api/v1/market-data/live/ws?token=<jwt>` |
| Store WS frontend | `packages/ii-terminal-core/src/lib/stores/market-data.svelte.ts` | **Completo** — `createTickBuffer`, subscribe/unsubscribe |
| `createTickBuffer` | `@investintell/ui/runtime` | **Completo** |
| `AlertTicker.svelte` | `packages/ii-terminal-core/src/lib/components/terminal/shell/` | **Completo** |
| `TerminalTopNav.svelte` | `packages/ii-terminal-core/src/lib/components/terminal/shell/` | **Completo** — já tem regime polling de `/allocation/regime` |
| Formato mensagem Tiingo | `tiingo_bridge.py:389-391` | `data[3]=ticker, data[4]=size, data[5]=price` |
| Canal Redis | `manager.py:64` | `market:prices:{TICKER}` (per-ticker) + `market:prices` (global) |
| `WS_THRESHOLD_LEVEL` | `tiingo_bridge.py:54` | `0` (firehose institucional) |

## Lacunas Genuínas — O que precisa ser construído

1. **Persistência de ticks em TimescaleDB** — bridge atual só publica no Redis, sem histórico
2. **Rota SSE `/events`** — eventos de baixa frequência (regime change, alertas de portfólio) via SSE; distinto da rota WS de preços
3. **`LiveMarquee.svelte`** — componente de fita de preços no shell do terminal
4. **`MarketFeedList.svelte`** — lista de eventos de mercado com sparklines ECharts
5. **TopNav → SSE** — substituir o polling periódico de regime por subscrição SSE (elimina N requests/min por client)

## Problem Frame

A interface atual recebe preços em tempo real via WebSocket, mas:
- **Sem histórico**: ticks vivem apenas em Redis (TTL), não há hypertable para carregar candles do dia ao abrir a página
- **TopNav polled**: regime atualiza por polling (`onMount` + interval) em vez de push event
- **Sem event feed**: não existe rota SSE para eventos de baixa frequência (regime change, drift alert, price staleness)
- **Sem `LiveMarquee`**: o shell não tem fita de preços nos componentes `ii-terminal-core`

## Requirements Trace

- R1. Persistência de ticks em `intraday_market_ticks` (hypertable) via extensão do `_drain_buffer_inner` existente
- R2. `market_candles_1m` CAGG para carregar histórico intraday sem custo de reprocessamento
- R3. Rota SSE `/events` no router `market_data.py` existente — filtra por `tags` e emite regime/alertas
- R4. TopNav consume SSE de regime em vez de polling — sem mudança visual, só wiring interno
- R5. `LiveMarquee.svelte` e `MarketFeedList.svelte` em `packages/ii-terminal-core`, usando store e `createTickBuffer` já existentes
- R6. Nenhum componente novo em `packages/ui` — tudo pertence ao `ii-terminal-core`

## Scope Boundaries

- **Não tocar** `tiingo_bridge.py` além de `_drain_buffer_inner` — IdleBridgePolicy e SingleFlightLock não mudam
- **Não criar** novo worker de ingestão — bridge já é lifespan-managed, não usa advisory lock
- **Não criar** `/ticks` WS route — `@router.websocket("/live/ws")` já existe em `market_data.py`
- **Não criar** `MarketConnectionManager` — `market-data.svelte.ts` já gerencia a conexão WS
- **Não criar** `createTickBuffer` — já existe em `@investintell/ui/runtime`
- **`WS_THRESHOLD_LEVEL = 0`** — manter conforme código (firehose institucional); não alterar para 6

## Implementation Units

### Unit 1: Persistência DB — Extensão de `_drain_buffer_inner`

**Goal:** Gravar batch de ticks em TimescaleDB durante cada flush do bridge existente.

**Approach:** Estender `TiingoStreamBridge._drain_buffer_inner` em `tiingo_bridge.py` para fazer
`asyncpg.executemany` em `intraday_market_ticks` **após** o `publish_price_ticks_batch` existente.
A conexão asyncpg vem do pool global — não abrir conexão nova por flush.

O write para TimescaleDB é best-effort: se falhar, apenas loga warning e continua (Redis é fonte de
verdade para o frontend; DB é para histórico). Não reverter nem bloquear o flush de Redis.

**Files:**
- Modify: `backend/app/core/ws/tiingo_bridge.py` — `_drain_buffer_inner` + import asyncpg pool
- Create: `backend/app/core/ws/_tick_persist.py` — função `persist_ticks_batch(pool, ticks)` isolada

**Pseudo-código de `_drain_buffer_inner` após mudança:**
```python
async def _drain_buffer_inner(self) -> None:
    if not self._buffer:
        return
    batch = self._buffer
    self._buffer = []
    try:
        await publish_price_ticks_batch(batch)        # existente — não muda
    except Exception:
        logger.exception("tiingo_bridge_publish_error count=%d", len(batch))
    try:
        await persist_ticks_batch(self._db_pool, batch)  # novo — best-effort
    except Exception:
        logger.warning("tiingo_bridge_persist_error count=%d", len(batch))
```

**Test scenarios:**
- `persist_ticks_batch` falha → Redis publish não é afetado, warning logado
- Batch de 4999 ticks (abaixo do `BUFFER_MAX_SIZE=5000`) → `executemany` executa em ≤1 round-trip

---

### Unit 2: Migration `0172` — Hypertable + CAGG

**Goal:** Criar `intraday_market_ticks` (hypertable global) e `market_candles_1m` (CAGG).

**Files:**
- Create: `backend/app/core/db/migrations/versions/0172_add_intraday_market_ticks.py`

**Schema:**

```sql
-- Tabela global: sem organization_id, sem RLS
CREATE TABLE intraday_market_ticks (
    time        TIMESTAMPTZ NOT NULL,
    ticker      TEXT        NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    size        INTEGER     NOT NULL,
    source      TEXT        NOT NULL DEFAULT 'tiingo'
);

SELECT create_hypertable('intraday_market_ticks', 'time',
    chunk_time_interval => INTERVAL '1 day');

ALTER TABLE intraday_market_ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'ticker',
    timescaledb.compress_orderby   = 'time DESC'
);

SELECT add_compression_policy('intraday_market_ticks',
    INTERVAL '7 days');

-- CAGG: candles de 1 minuto para servir histórico ao frontend
CREATE MATERIALIZED VIEW market_candles_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    ticker,
    first(price, time)            AS open,
    max(price)                    AS high,
    min(price)                    AS low,
    last(price, time)             AS close,
    sum(size)                     AS volume
FROM intraday_market_ticks
GROUP BY bucket, ticker
WITH NO DATA;

SELECT add_continuous_aggregate_policy('market_candles_1m',
    start_offset => INTERVAL '2 hours',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');
```

**Regras globais (CLAUDE.md):**
- Sem `organization_id` — dados de mercado são globais
- `compress_segmentby = 'ticker'` — padrão para hypertables globais com chave natural
- CAGG criado com `WITH NO DATA` — população inicial pelo worker

**Test scenarios:**
- Migration executa em banco vazio sem erro
- `SELECT hypertable_size('intraday_market_ticks')` retorna row após insert de teste
- `SELECT * FROM market_candles_1m` retorna row após 1min de ticks inseridos

---

### Unit 3: Rota SSE `/events` — Eventos de Baixa Frequência

**Goal:** Adicionar endpoint SSE no router `market_data.py` existente para regime changes,
drift alerts e price_staleness. Distinto do WS de preços (alta frequência).

**Files:**
- Modify: `backend/app/domains/wealth/routes/market_data.py` — novo `@router.get("/events")`
- Modify: `backend/app/domains/wealth/schemas/market_data.py` — `MarketEventPayload`

**Approach:**
- Rota: `GET /api/v1/market-data/events?tags=regime,alert` (SSE, JWT auth via header)
- Consome Redis Pub/Sub canal `market:events` (novo canal, separado de `market:prices`)
- Usa `RateLimitedBroadcaster` existente para fan-out (padrão guardrails §3)
- Filtra eventos por `tags` query param antes de enviar ao client
- Publica em `market:events` um `{"type": "regime_change", "data": {...}, "tags": ["regime"]}`
  quando o worker `regime_detection` escrever novo regime — hookar via `view_refresh.py`

**Producers para `market:events` (futuro hook):**
- `regime_detection.py` — ao finalizar detecção, publicar no canal
- `portfolio_alerts.py` — drift/price_staleness já emitem via SSE de portfólio; regime change é novo

**Schema `MarketEventPayload`:**
```python
class MarketEventPayload(BaseModel):
    type: Literal["regime_change", "drift_alert", "price_staleness", "heartbeat"]
    data: dict[str, Any]
    tags: list[str]
    timestamp: datetime
```

**Test scenarios:**
- Client se conecta com `tags=regime` → recebe apenas `regime_change` events
- Redis publica `market:events` → client SSE recebe dentro de `RateLimitedBroadcaster` window
- Client desconecta → sem leak de listener task

---

### Unit 4: TopNav SSE — Eliminar Polling de Regime

**Goal:** Substituir o polling periódico em `TerminalTopNav.svelte` por subscrição SSE ao canal
`market:events?tags=regime`. Mesma UI, zero polling.

**Files:**
- Modify: `packages/ii-terminal-core/src/lib/components/terminal/shell/TerminalTopNav.svelte`

**Approach:**
- Remover o `setInterval` / `onMount` fetch de `/allocation/regime`
- Adicionar `$effect` com `fetch() + ReadableStream` para `/api/v1/market-data/events?tags=regime`
- `AbortController` atrelado ao teardown do `$effect` (`return () => controller.abort()`)
- Capturar silenciosamente `AbortError` (padrão `AlertTicker.svelte` existente)
- `regimeLabel` continua sendo `$state` — só muda o produtor do valor

**Nota:** `TerminalTopNav` já tem `regimeLabel = $state("STANDBY")` e os CSS classes de cor por regime.
A única mudança é no source dos dados — nenhum impacto visual.

**Test scenarios:**
- Página carrega → regime exibido após primeiro SSE event (ou mantém "STANDBY" se canal vazio)
- Regime muda no backend → TopNav atualiza sem reload de página
- Aba vai para background → `AbortController` não dispara (SSE mantém conexão)
- Componente desmonta → `AbortController.abort()` chamado, sem zombie connection

---

### Unit 5: Componentes de Feed — `LiveMarquee` e `MarketFeedList`

**Goal:** Criar `LiveMarquee.svelte` (fita de preços) e `MarketFeedList.svelte` (lista de eventos)
no shell do terminal.

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/shell/LiveMarquee.svelte`
- Create: `packages/ii-terminal-core/src/lib/components/terminal/shell/MarketFeedList.svelte`
- Modify: `packages/ii-terminal-core/src/lib/index.ts` — exportar novos componentes

**Approach — LiveMarquee:**
- Recebe `tickers: string[]` via `$props()`
- Importa `marketDataStore` de `market-data.svelte.ts` (store já existente)
- O store provê a fila de ticks via `createTickBuffer` já configurado
- Renderiza com ECharts sparkline por ticker: `animation: false`, `sampling: 'lttb'`, `.slice(-100)`
- Usa `var(--color-success)` / `var(--color-error)` do design system para variação de preço
- Altura: não pode ultrapassar a régua de `88px` do TopNav — embutir com `height: 100%`

**Approach — MarketFeedList:**
- Recebe `tags: string[]` via `$props()` para filtrar eventos SSE
- Abre própria conexão SSE para `/api/v1/market-data/events?tags={tags.join(',')}` via `$effect`
- `AbortController` no teardown — padrão `AlertTicker.svelte`
- Exibe lista scrollável de `MarketEventPayload` com timestamp e badge de tipo
- Combobox Svelte para redirecionar `tags` (remonta o `$effect` ao mudar)
- Sem `localStorage` — estado em memória via `$state`

**Regras ECharts (ambos os componentes):**
- `animation: false` — obrigatório
- `sampling: 'lttb'` — redução de dados para renderização fluida
- `.slice(-100)` — janela deslizante de 100 pontos (equivalente a ~100s de ticks)
- Cores via CSS vars do design system — jamais hex hardcoded

**Test scenarios:**
- `LiveMarquee` com 3 tickers → 3 sparklines renderizam sem thrashing após batch do TickBuffer
- `MarketFeedList` com `tags=["regime"]` → exibe apenas regime changes
- Mudar combobox de tags → lista limpa e reconnecta SSE
- Desmonte → todas as conexões SSE fechadas, sem console errors

## Ordem de Execução

```
Unit 2 (migration) → Unit 1 (bridge + persist) → Unit 3 (SSE route) → Unit 4 (TopNav) → Unit 5 (componentes)
```

Units 1 e 2 podem ser feitas em paralelo (backend independente de frontend).
Unit 3 depende do canal Redis `market:events` estar definido (Unit 3 o define).
Units 4 e 5 dependem da Unit 3 estar deployada.

## System-Wide Impact

| Área | Impacto |
|---|---|
| `tiingo_bridge.py` | `_drain_buffer_inner` ganha chamada DB best-effort — sem mudança de comportamento de Redis |
| TimescaleDB | +2 objetos globais: `intraday_market_ticks` (hypertable) + `market_candles_1m` (CAGG) |
| Redis | +1 canal: `market:events` (baixa frequência, separado de `market:prices`) |
| `market_data.py` | +1 rota SSE — não altera rotas existentes |
| `TerminalTopNav.svelte` | Troca polling por SSE — UI idêntica |
| `ii-terminal-core` | +2 novos componentes exportados — retrocompatível |
| `make check` | Nenhuma mudança de import-linter DAG; novos componentes dentro do pacote existente |

## Risks & Mitigations

| Risco | Mitigação |
|---|---|
| Write DB falha durante burst de ticks | Best-effort em `_drain_buffer_inner` — Redis não é bloqueado; DBA repara via `search_rebuild.py` analog |
| CAGG `market_candles_1m` atrasado | Policy refresh de 1min é suficiente; frontend pode mostrar "dados até X" |
| SSE `/events` sem producers iniciais | Rota existe mas canal Redis vazio → heartbeat a cada 30s mantém conexão ativa |
| Thrashing de re-render no `LiveMarquee` | TickBuffer 200ms flush + ECharts `animation:false` + `.slice(-100)` |
| Conexão SSE zombie após desmonte | `AbortController` no teardown do `$effect` — padrão validado em `AlertTicker.svelte` |

## Definições Abertas (Decisão de Produto)

Estes pontos precisam de decisão antes da implementação de Unit 3:

1. **Producers de `market:events`**: apenas `regime_detection.py`, ou também `drift_check.py` e `portfolio_eval.py`?
2. **Taxonomia de `event_type`**: o enum `MarketEventPayload.type` precisa ser fixado antes da migration de `market_events` (se optar por persistir eventos além de ticks)
3. **`market_events` table**: o plano original propunha persistir eventos em hypertable. Esta versão **não persiste** eventos — apenas Redis Pub/Sub. Se histórico de eventos for necessário, adicionar `market_events` como Unit 2b.
