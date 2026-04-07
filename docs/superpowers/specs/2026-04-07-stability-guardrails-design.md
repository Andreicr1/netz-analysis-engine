# Stability Guardrails — Design Spec

**Date:** 2026-04-07
**Status:** Approved for implementation
**Owner:** Andrei (Netz)
**Branch:** `feat/stability-guardrails`
**Sprint sizing:** L + M + M + M + S (5 phases)

---

## §0 — Princípio Fundador

> **Em gestão institucional de patrimônio, imprevisibilidade é risco
> operacional inaceitável.** Todo caminho crítico do engine deve ter
> limite explícito, batching explícito e contrato de ciclo de vida
> explícito. Funcionalidade sem guardrail não está pronta — está
> postergando incidente.

Esta frase é a Navalha de Occam do sprint. Sempre que houver dúvida
entre "entregar mais rápido assumindo risco de concorrência" e "fazer
o controle estrito de limites", a frase decide a favor da estabilidade.
Ela transforma o que seria preferência técnica em regra de negócio.

---

## §1 — Os Seis Princípios Não-Negociáveis

| # | Nome              | Significado prático |
|---|-------------------|----------------------|
| P1 | **Bounded**        | Toda fila/buffer/fan-out/página de resultado tem teto numérico declarado. Sem teto = bug. |
| P2 | **Batched**        | Eventos de alta frequência são coalescidos em lotes alinhados a um clock (frame, janela ms, transação). Sem batching = self-DDoS. |
| P3 | **Isolated**       | Cliente lento, query lenta, componente quebrado não afeta outros clientes/queries/componentes. Sem isolamento = falha cascateia. |
| P4 | **Lifecycle-correct** | Recursos (listeners, tasks, transações, subscriptions) têm dono claro, são criados em hook explícito, destruídos em hook explícito, e checam "ainda válido?" antes de escrever. Sem lifecycle = race condition. |
| P5 | **Idempotent**     | Mutações suportam re-execução N vezes com o mesmo input sem corromper estado. Sem idempotência = dados corrompidos no retry. |
| P6 | **Fault-Tolerant** | Falha de terceiros = fail-fast com timeout rígido + fallback/erro mapeado. Indisponibilidade externa nunca vira indisponibilidade nossa. |

---

## §2 — Backend Runtime Kit

**Localização:** `backend/app/core/runtime/` *(novo módulo)*
**Cobertura de testes exigida:** ≥ 95% via `pytest --cov`

### 2.1 — `BoundedOutboundChannel` *(P1 + P3 + P4)*

**Arquivo:** `backend/app/core/runtime/outbound_channel.py`

Fila de saída **por conexão WS**. Substitui `await conn.ws.send_bytes(payload)`
direto no fan-out. Cada cliente recebe uma fila bounded e uma drain task
própria. Cliente lento enche a fila → política de drop explícita → eventualmente
é evicted. Os outros não percebem.

```python
class DropPolicy(StrEnum):
    DROP_OLDEST = "drop_oldest"   # market data — perder ticks antigos é OK
    DROP_NEWEST = "drop_newest"   # eventos críticos — manter os primeiros
    BLOCK       = "block"         # zero perda, backpressure ao publisher

@dataclass(frozen=True)
class ChannelConfig:
    max_queued: int = 256
    send_timeout_s: float = 2.0
    drop_policy: DropPolicy = DropPolicy.DROP_OLDEST
    eviction_threshold: int = 3   # consecutive drops/timeouts → evict

class BoundedOutboundChannel:
    def __init__(self, ws: WebSocket, cfg: ChannelConfig): ...
    async def start(self) -> None: ...
    async def stop(self, *, drain: bool = False) -> None: ...
    def offer(self, payload: bytes) -> bool: ...
    @property
    def is_evictable(self) -> bool: ...
    @property
    def metrics(self) -> ChannelMetrics: ...
```

**Garantias:**
- `offer()` é **não-bloqueante** sempre. Publisher nunca espera.
- Drain task aplica `asyncio.wait_for(ws.send_bytes(payload), send_timeout_s)`. Timeout = drop + contador.
- Após `eviction_threshold` falhas consecutivas, `is_evictable = True`.
- `stop(drain=True)` espera fila esvaziar até `send_timeout_s`. `stop(drain=False)` cancela imediato. Sempre cancela a task — nunca vaza.

### 2.2 — `RateLimitedBroadcaster` *(P1 + P3 + P4)*

**Arquivo:** `backend/app/core/runtime/broadcaster.py`

Substitui o `_fanout` de `ConnectionManager`. Mantém um
`BoundedOutboundChannel` por conexão, faz fan-out concorrente com limite
global (`max_concurrent_sends`), e expõe métricas agregadas.

```python
ConnectionId = NewType("ConnectionId", uuid.UUID)

class RateLimitedBroadcaster:
    def __init__(self, channel_cfg: ChannelConfig, max_concurrent_sends: int = 64): ...
    async def attach(self, conn_id: ConnectionId, ws: WebSocket) -> None: ...
    async def detach(self, conn_id: ConnectionId, *, drain: bool = False) -> None: ...
    def fanout(self, payload: bytes, conn_ids: Iterable[ConnectionId]) -> FanoutResult: ...
    @property
    def metrics(self) -> BroadcasterMetrics: ...
```

**Diferenças vs. `_fanout` atual:**
- `id(ws)` proibido como chave — usa `ConnectionId` UUID gerado no `accept`.
- Mutação do dict é serializada por lock interno; iteração faz snapshot.
- Fan-out concorrente (até `max_concurrent_sends`) mas cada send roda no canal do próprio cliente — slow consumer não segura ninguém.
- Eviction acontece fora do hot path, em background.

### 2.3 — `SingleFlightLock` *(P2 + P3)*

**Arquivo:** `backend/app/core/runtime/single_flight.py`

Garante que **uma única coroutine por chave** está rodando uma operação
cara. Mata "10 tasks de drain do Tiingo bridge competindo no mesmo buffer".

```python
class SingleFlightLock(Generic[K, V]):
    async def run(
        self,
        key: K,
        coro_factory: Callable[[], Awaitable[V]],
        *,
        ttl_s: float | None = None,
    ) -> V: ...
```

**Comportamento:**
- Nenhuma flight ativa → executa, cacheia por `ttl_s`, retorna.
- Flight ativa → aguarda, retorna o mesmo resultado.
- Resultado cacheado não vencido → retorna direto, não executa.
- Cancelamento: flight original cancelada → todos os waiters recebem `CancelledError`. Sem órfãos.

### 2.4 — `IdleBridgePolicy` *(P4)*

**Arquivo:** `backend/app/core/runtime/idle_bridge.py`

Mixin/policy para conectores externos persistentes. Regra de ouro: o
**único** lugar que pode chamar `shutdown()` é o `lifespan` no `main.py`.

```python
class IdleBridgePolicy:
    state: Literal["stopped", "running", "idle", "stopping"]
    async def request_demand(self, items: set[str]) -> None: ...
    async def release_demand(self, items: set[str]) -> None: ...
    async def shutdown(self) -> None: ...   # assert chamado só pelo lifespan
```

State machine: `stopped → running → idle → running → stopping → stopped`.
Transições inválidas levantam `IllegalStateError`.

### 2.5 — `ExternalProviderGate` *(P6)*

**Arquivo:** `backend/app/core/runtime/provider_gate.py`

Wrapper **obrigatório** para toda chamada a API externa REST rápida e
previsível (Tiingo HTTP, SEC EDGAR, FRED, Yahoo, Mistral OCR). Combina
timeout rígido + circuit breaker + fallback de cache.

```python
@dataclass(frozen=True)
class GateConfig:
    name: str
    timeout_s: float
    failure_threshold: int = 5
    recovery_after_s: float = 30.0
    cache_ttl_s: float | None = None

class ExternalProviderGate(Generic[T]):
    async def call(
        self,
        op_key: str,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        on_open: Callable[[], T] | None = None,
    ) -> T: ...
    @property
    def state(self) -> Literal["closed", "open", "half_open"]: ...
```

**Comportamento:**
- `closed` → executa, conta falhas.
- `failure_threshold` consecutivas → `open`. Retorna cache ou `ProviderUnavailableError` mapeado para HTTP 503.
- Após `recovery_after_s`, probe em `half_open`.
- `recovery_after_s` **configurável por gate** (SEC=30s, Tiingo=10s, FRED=30s).

### 2.6 — `LLMGate` *(P6 caso especial)*

**Arquivo:** `backend/app/core/runtime/llm_gate.py`

Dedicado a LLM (OpenAI). **Não herda** de `ExternalProviderGate` porque
semântica é diferente: latência variável, 429 requer backoff com jitter,
fallback model.

```python
@dataclass(frozen=True)
class LLMGateConfig:
    primary_model: str
    fallback_model: str | None = None
    soft_timeout_s: float = 60.0
    hard_timeout_s: float = 180.0
    max_retries: int = 3
    backoff_base_s: float = 2.0
    backoff_max_s: float = 30.0
    jitter_ratio: float = 0.25
    rate_limit_threshold: int = 5

class LLMGate:
    async def chat(
        self,
        messages: list[dict],
        *,
        op_key: str,
        prefer_fallback: bool = False,
    ) -> LLMResponse: ...
```

**Comportamento:**
- **429** → exponential backoff com jitter, respeita `Retry-After`. Não conta como falha do circuit.
- **5xx / network** → retry até `max_retries`. Contam como falha real.
- **Soft timeout** → log `WARNING` (não aborta).
- **Hard timeout** → aborta via `wait_for`.
- **Sem cache** — chamadas LLM são não-idempotentes (temperatura, estocástica).
- `call_openai_fn` existente vira shim delegando a `LLMGate.chat()`.

### 2.7 — `@idempotent` decorator *(P5)*

**Arquivo:** `backend/app/core/runtime/idempotency.py`

Decorator para rotas que mutam estado. Funciona com chave via header
`Idempotency-Key` ou derivada determinística.

```python
def idempotent(
    *,
    key: Callable[..., str],
    ttl_s: int = 86400,
    storage: Literal["redis"] = "redis",
): ...
```

**Comportamento (apoiado em Redis `SETNX`):**
- Primeira chamada → executa, armazena `(status, body)` com TTL.
- Chamada concorrente mesma chave → bloqueia esperando, recebe mesmo resultado.
- Chamada repetida dentro do TTL → retorna cache, não re-executa.
- **Fallback de degradação graciosa:** Redis indisponível → log WARNING + executa sem cache (flag `X-Idempotency-Bypassed: true` na resposta).

### 2.8 — Política "Job-or-Stream" *(operacionaliza P1 + P3)*

**Não é primitiva — é regra de engenharia.**

Toda rota com p95 > 500ms → refatorada para padrão job:
1. Rota valida input → enfileira job → devolve `202 { job_id }`.
2. Cliente abre `GET /jobs/{job_id}/stream` (SSE existente).
3. Worker faz trabalho pesado, publica eventos no canal Redis.

**Reuso obrigatório:** `backend/app/core/jobs/tracker.py`, `sse-starlette`,
Redis pub/sub canais `job:{id}:events`. **Zero infra nova.**

**Middleware `p95_guard`** (arquivo `backend/app/core/middleware/p95_guard.py`):
passive observability — mede p95 por rota em janela de 100 requests, loga
`WARNING` estruturado quando ultrapassa 500ms. Não bloqueia, não quebra,
só reporta. `@async_job` decorator fica para iteração futura.

### 2.9 — Mapa Princípio → Primitiva Backend → Bug Eliminado

| Princípio | Primitiva | Bug eliminado |
|---|---|---|
| P1 Bounded | `BoundedOutboundChannel`, `RateLimitedBroadcaster` | Fila sem teto, OOM no servidor |
| P2 Batched | `SingleFlightLock` no Tiingo drain | Tasks de drain racing no mesmo buffer |
| P3 Isolated | `BoundedOutboundChannel`, `ExternalProviderGate` | Cliente lento bloqueia fan-out; Tiingo lento esgota pool |
| P4 Lifecycle | `IdleBridgePolicy`, `ConnectionId` UUID | Bridge morre no unsubscribe-all; colisão de `id(ws)` |
| P5 Idempotent | `@idempotent` decorator | Duplo-clique no import duplica registros |
| P6 Fault-tolerant | `ExternalProviderGate`, `LLMGate` | Tiingo down = backend down; OpenAI lento = pool drained |

---

## §3 — Frontend Runtime Kit

**Localização:** `packages/ui/src/runtime/` *(novo módulo dentro do `@netz/ui`)*

### 3.1 — `createTickBuffer<T>()` *(P1 + P2 + P4)*

**Arquivo:** `packages/ui/src/runtime/tick-buffer.svelte.ts`

Primitiva **mandatória** para qualquer fonte de dados que emite > 10
eventos/s. Coalesce eventos por chave em lotes alinhados a clock (rAF
ou interval). Mata a classe "self-DDoS reativo".

```typescript
export interface TickBufferConfig<T> {
  keyOf: (item: T) => string;
  maxKeys?: number;
  evictionPolicy?: "drop_oldest" | "drop_newest";
  clock?: "raf" | { intervalMs: number };
}

export interface TickBuffer<T> {
  readonly snapshot: ReadonlyMap<string, T>;
  readonly dropped: number;
  readonly written: number;
  write(item: T): void;
  writeMany(items: T[]): void;
  pause(): void;
  resume(): void;
  dispose(): void;
}
```

**Garantias:**
1. Acumulação em `Map<string, T>` interno — `write()` sobrescreve existente. Last-write-wins por chave. **Sem spread**, **sem alocação por tick**.
2. Flush alinhado a clock — uma única atribuição reativa por ciclo (`snapshot = new Map(internal)`).
3. **Dois modos de clock:**
   - `"raf"` (16ms) — para sparklines animadas, gráficos em tempo real.
   - `{ intervalMs: 250 }` — para grades tabulares (Dashboard Market Data). Evita "efeito slot machine" e economiza CPU/bateria.
4. Pause automático em `document.visibilityState === "hidden"`. Retoma em `visible` com flush imediato.
5. `dispose()` cancela rAF/interval, desconecta `visibilitychange`, libera o Map. Obrigatório em `onDestroy`.

### 3.2 — Route Data Contract *(P3 + P4 + P6)*

**Arquivo de tipos:** `packages/ui/src/runtime/route-contract.ts`

Não é primitiva — é **contrato obrigatório** para toda página de detalhe.

```typescript
export interface RouteError {
  code: string;
  message: string;
  recoverable: boolean;
}

export interface RouteData<T> {
  data: T | null;
  error: RouteError | null;
  loadedAt: string;
}

export function okData<T>(data: T): RouteData<T>;
export function errData(code: string, message: string, recoverable: boolean): RouteData<never>;
export function isStale(d: RouteData<unknown>, maxAgeMs: number): boolean;
```

**Regras (enforçadas por lint rules):**

- **R3.2.1** — `+page.ts`/`+page.server.ts` de detalhe retorna `RouteData<T>`. Nunca `throw error()`.
- **R3.2.2** — `<svelte:boundary>` obrigatório em todo painel top-level, com `failed` snippet mostrando `PanelErrorState` (nunca tela preta).
- **R3.2.3** — `$derived` que lê de `data` async deve usar optional chaining + default.
- **R3.2.4** — Listeners WS atachados em `onMount`, removidos em `onDestroy`. Nunca subscribe no top-level de `<script>`.
- **R3.2.5** — `load` tem timeout via `AbortSignal.timeout(8000)` (configurável por rota).

### 3.3 — `createMountedGuard()` *(P4)*

**Arquivo:** `packages/ui/src/runtime/listener-safe.svelte.ts`

Helper para callbacks async que podem disparar após componente desmontado.

```typescript
export function createMountedGuard(): {
  readonly mounted: boolean;
  guard<T>(fn: () => T): T | undefined;
  start(): void;
  stop(): void;
};
```

Uso: `lifecycle.guard(() => { localState = value; })` dentro de callbacks.
Se componente desmontado, `fn` não executa, retorna `undefined`.

### 3.4 — Componentes de Estado

**Arquivos** (no `@netz/ui`):
- `packages/ui/src/components/PanelErrorState.svelte` — estado de erro acionável: título, mensagem, botão "Tentar novamente". Props: `{ title, message, onRetry? }`.
- `packages/ui/src/components/PanelEmptyState.svelte` — estado neutro "nenhum dado disponível". Props: `{ title, message, action? }`.

Centralizar aqui garante reuso pelas outras páginas de detalhe (Manager, Fund, Model Portfolio) quando forem migradas.

### 3.5 — Mapa Princípio → Primitiva Frontend → Bug Eliminado

| Princípio | Primitiva / Regra | Bug eliminado |
|---|---|---|
| P1 Bounded | `TickBufferConfig.maxKeys` + `evictionPolicy` | priceMap cresce infinito |
| P2 Batched | `createTickBuffer` com flush rAF/interval | 500 invalidações reativas/s → 4/s |
| P3 Isolated | `<svelte:boundary>` em todo painel | Erro num painel quebra a página inteira |
| P4 Lifecycle | `onMount/onDestroy` + `createMountedGuard` | Listener escreve em componente desmontado |
| P6 Fault-tolerant | `load` com `AbortSignal.timeout` + `RouteData.error` | Página trava esperando fetch que nunca volta |

---

## §4 — Plano de Ataque: Retrofits dos 3 Alvos

### 4.1 — Alvo 1: Dashboard Market Data Path

**Bug class:** Self-DDoS reativo + bridge fragility + slow consumer cascade.

| # | Arquivo:linha | Bug | Primitiva |
|---|---|---|---|
| B1.1 | `tiingo_bridge.py:106-107` | `unsubscribe()` → `shutdown()` quando set vazio | `IdleBridgePolicy` |
| B1.2 | `tiingo_bridge.py:231-273` | `subscribe_approved_universe()` no boot | Removido |
| B1.3 | `tiingo_bridge.py:335-336` | `asyncio.create_task(_drain_buffer())` race | `SingleFlightLock("drain")` |
| B1.4 | `tiingo_bridge.py:158-163` | Swap sem lock no buffer | Mesma `SingleFlightLock` |
| B1.5 | `ws/manager.py:67` | `dict[int, ClientConnection]` por `id(ws)` reciclável | `ConnectionId` UUID |
| B1.6 | `ws/manager.py:232-248` | `_fanout` sequencial sem timeout | `RateLimitedBroadcaster` + `BoundedOutboundChannel` |
| B1.7 | `market-data.svelte.ts:172-186` | Spread por tick | `createTickBuffer<PriceTick>` |
| B1.8 | `market-data.svelte.ts:325` | `pendingTickers` só cresce | `Set` interno do buffer + dispose |
| B1.9 | `market-data.svelte.ts:140-143` | `MAX_RETRIES` → `error` permanente | Método `reconnect()` público |

**Arquivos editados (backend):** `manager.py`, `tiingo_bridge.py`, `main.py`, `market_data.py` route.
**Arquivos editados (frontend):** `market-data.svelte.ts`, `dashboard/+page.svelte`, `charts/PortfolioNAVChart.svelte` (se ler priceMap direto).

**Critério Playwright:** 5000 ticks em 10s → frame budget p99 < 16ms, < 60 invalidações reativas, sem freeze. **Obrigatório.**
**Critério soak (C18):** 30min Dashboard ativo → heap < 10MB crescimento, tab responsiva. **Obrigatório antes de merge da Fase 2**, roda local ou nightly.

### 4.2 — Alvo 2: FactSheet Navigation

**Bug class dupla descoberta em `+page.server.ts:14-19`:**
1. **Causa A:** `throw error(404)` / `throw error(status)` em load → SvelteKit cai no `+error.svelte` default minimalista (tela preta). Não é race — é tratamento errado de erro de carga.
2. **Causa B:** Race no componente — `FundDetailPanel.svelte` (350 linhas) tem `$derived` ou `{#each}` assumindo `factSheet.X` existe; falha intermitente quando timing do fetch bate com próximo tick WS ou com store do contexto anterior.

| # | Arquivo:linha | Bug | Primitiva |
|---|---|---|---|
| B2.1 | `+page.server.ts:14-19` | `throw error()` em vez de `RouteData` | Route Data Contract |
| B2.2 | `+page.server.ts:11` | `api.get()` sem timeout | `AbortSignal.timeout(8000)` |
| B2.3 | `+page.svelte` | Sem `<svelte:boundary>` | Wrapping obrigatório |
| B2.4 | `FundDetailPanel.svelte` | `$derived` sem optional chaining | Lint + retrofit defensivo |
| B2.5 | `FundDetailPanel.svelte` | Listener sem `mounted` guard | `createMountedGuard` |

**Arquivos editados:** `+page.server.ts`, `+page.svelte`, `FundDetailPanel.svelte`, novos `PanelErrorState.svelte`, `PanelEmptyState.svelte` no `@netz/ui`.

**Critério Playwright (obrigatório):** 50 navegações Screener → FactSheet → 0 telas pretas, 100% mostram conteúdo ou `PanelErrorState` acionável.

### 4.3 — Alvo 3: Screener L3 Import

**Bug class:** Trabalho síncrono pesado em request + duplo-clique stampede + integração SEC sem fault tolerance.

| # | Arquivo:linha | Bug | Primitiva |
|---|---|---|---|
| B3.1 | `screener.py:921-940` | `import_fund` síncrono sem timeout | Job-or-Stream |
| B3.2 | `screener.py:951-1100+` | `import_sec_security` faz fetch+fallback+insert+commit no handler | Mover para service + worker |
| B3.3 | `screener.py:961-987` | Sem `@idempotent` — duplo-clique gera 409 ou race | `@idempotent` + `SingleFlightLock` |
| B3.4 | `screener.py:~958` | `_require_investment_role` chamado após queries | Mover para topo |
| B3.5 | chamadas SEC | Sem `ExternalProviderGate` | Wrap obrigatório |

**Arquivos editados:**
- `backend/app/domains/wealth/services/screener_import_service.py` *(novo — lógica pura, idempotente)*
- `backend/app/domains/wealth/workers/screener_import_worker.py` *(novo — job runner, lock ID a auditar antes)*
- `backend/app/domains/wealth/routes/screener.py` *(patch — vira enfileirador 202)*
- `frontends/wealth/src/lib/components/screener/ImportButton.svelte` *(arquivo a confirmar via grep na implementação)*

**Critério Playwright (obrigatório):** 5 cliques rápidos → 1 job criado, 1 instrumento adicionado, sem duplicatas.

### 4.4 — Sequenciamento (5 Fases, 23 Commits)

```
Fase 1 — Foundations (L)            [primitivas + lint + middleware]
  01 feat(runtime): bounded outbound channel + tests
  02 feat(runtime): rate limited broadcaster + tests
  03 feat(runtime): single flight lock + tests
  04 feat(runtime): idle bridge policy + tests
  05 feat(runtime): external provider gate + tests
  06 feat(runtime): llm gate + tests
  07 feat(runtime): idempotency decorator + tests
  08 feat(runtime): p95 guard middleware
  09 feat(ui/runtime): tick buffer + listener safe + tests
  10 feat(ui/runtime): route contract types + helpers
  11 feat(eslint): netz-runtime plugin (4 svelte rules) + tests
  12 chore(eslint): inline AST rules in frontends/eslint.config.js

Fase 2 — Retrofit Dashboard (M)
  13 refactor(ws): connection manager uses ConnectionId + broadcaster
  14 refactor(tiingo): bridge inherits IdleBridgePolicy + single-flight drain
  15 refactor(market-data): store uses tick buffer (drops spreads)
  16 refactor(dashboard): subscribe via mounted guard + boundary panels

Fase 3 — Retrofit FactSheet (M)
  17 refactor(factsheet): page.server load returns RouteData + timeout
  18 refactor(factsheet): FundDetailPanel defensive derived + boundary

Fase 4 — Retrofit Screener Import (M)
  19 feat(screener): idempotent import enqueues job
  20 feat(screener): import worker reads SEC via provider gate
  21 feat(screener-ui): import button uses idempotency key + SSE progress

Fase 5 — Doc + Governança (S)
  22 docs(reference): stability-guardrails.md charter
  23 test(e2e): factsheet 50x + dashboard 30min soak + import 5x click
```

Ordem linear. Fases independentes na arquitetura. Se Fase 2 atrasar, Fases 3-4 permanecem viáveis isoladamente. Fase 5 pode começar em paralelo com Fase 2 (doc não bloqueia código).

---

## §5 — Enforcement & Governança

### 5.1 — Charter `docs/reference/stability-guardrails.md`

Documento normativo. Índice:

```
§0  Princípio fundador
§1  Os 6 princípios (P1–P6)
§2  Catálogo de primitivas
    2.1 Backend runtime kit
    2.2 Frontend @netz/ui runtime
§3  Padrões obrigatórios
    3.1 WebSocket: aceitar, fan-out, evict
    3.2 Background jobs: enqueue, SSE, progress
    3.3 External APIs: wrap, timeout, fail
    3.4 Páginas de detalhe: load → RouteData → boundary → component
    3.5 LLM calls: retry, fallback, timeout
§4  Anti-patterns proibidos (com exemplos antes/depois)
§5  Enforcement (lint, import-linter, p95, PR checklist)
§6  Backlog conhecido (dívida documentada)
§7  Histórico de incidentes (post-mortem light — ver §7 deste spec)
§8  Quando relaxar uma regra (processo de exceção)
```

Cada seção: **regra → razão → exemplo errado → exemplo certo → como detectar**.
Sem prosa filosófica. Tudo verificável.

### 5.2 — ESLint — Definição Final

**Pacote novo:** `packages/eslint-plugin-netz-runtime/`

Regras que precisam do parser Svelte:

| Regra | Severity v1 | Detecta |
|---|---|---|
| `require-svelte-boundary` | `warn` | `+page.svelte`/`+layout.svelte` que renderiza componentes filhos no top-level sem `<svelte:boundary>` + `failed` snippet |
| `no-unsafe-derived` | `error` | `$derived(expr)` que acessa propriedade de fonte tipada `T \| null` sem optional chaining |
| `require-load-timeout` | `error` | `+page.{ts,server.ts}` load que faz fetch sem `AbortSignal.timeout(...)` |
| `require-tick-buffer-dispose` | `error` | `createTickBuffer(...)` sem `.dispose()` em `onDestroy` |

Regras AST inline em `frontends/eslint.config.js`:

```javascript
{
  files: ['wealth/**/*.svelte', 'wealth/**/*.svelte.ts', 'credit/**/*.svelte', 'credit/**/*.svelte.ts'],
  rules: {
    'no-restricted-syntax': [
      'error',
      // Regra A: spread em assignment de map reativo (handler WS)
      {
        selector:
          "AssignmentExpression[left.type='Identifier'][right.type='ObjectExpression'] > " +
          "ObjectExpression > SpreadElement[argument.name=/^(priceMap|holdings|tickMap|.*Map)$/]",
        message: 'Spread on reactive map/array causes O(N) re-render per tick. Use createTickBuffer from @netz/ui/runtime.',
      },
      // Regra B: subscribe top-level
      {
        selector:
          "Program > ExpressionStatement > CallExpression[callee.property.name='subscribe'][arguments.0.type='ArrayExpression']",
        message: 'Store .subscribe() must live inside onMount with cleanup in onDestroy.',
      },
    ],
  },
},
{
  files: ['**/+page.server.ts', '**/+page.ts', '**/+layout.server.ts', '**/+layout.ts'],
  rules: {
    'no-restricted-syntax': [
      'error',
      // Regra C: throw error() em load
      {
        selector: "CallExpression[callee.name='error'][arguments.length>=1]",
        message: 'Server load functions must return RouteData<T> with { data, error } shape, not throw.',
      },
    ],
  },
},
```

### 5.3 — `CLAUDE.md` — Adição Enxuta

Inserido antes de "Critical Rules":

```markdown
## Stability Guardrails

> Em gestão institucional de patrimônio, imprevisibilidade é risco operacional inaceitável.

Six principles enforced across the stack: **P1 Bounded**, **P2 Batched**,
**P3 Isolated**, **P4 Lifecycle**, **P5 Idempotent**, **P6 Fault-Tolerant**.
Primitives live in `backend/app/core/runtime/` and `packages/ui/src/runtime/`.
**Full charter: `docs/reference/stability-guardrails.md`**.
```

### 5.4 — PR Template `.github/PULL_REQUEST_TEMPLATE.md`

Nova seção:

```markdown
## Stability Guardrails Checklist

### Backend
- [ ] New WS handlers use `BoundedOutboundChannel` via `RateLimitedBroadcaster`
- [ ] New external HTTP/REST wrapped in `ExternalProviderGate`
- [ ] New OpenAI/LLM calls go through `LLMGate`
- [ ] New mutating endpoints use `@idempotent` or justify
- [ ] New endpoints with expected p95 > 500ms are jobs (not sync)
- [ ] New persistent bridges inherit `IdleBridgePolicy`
- [ ] New concurrent dedupe uses `SingleFlightLock`

### Frontend
- [ ] New event sources > 10/s use `createTickBuffer<T>()`
- [ ] New async listeners use `createMountedGuard` or onMount cleanup
- [ ] New detail pages return `RouteData<T>` (no `throw error()`)
- [ ] New top-level panels wrapped in `<svelte:boundary>`
- [ ] New fetch in load has `AbortSignal.timeout(...)`
- [ ] No spread on reactive map/array inside WS handler

### Tests
- [ ] Regression test for fixed failure mode
- [ ] No `eslint-disable netz-runtime/...` without justification
- [ ] `make check` passes

Charter: `docs/reference/stability-guardrails.md`
```

### 5.5 — `import-linter` Contracts

```toml
[[tool.importlinter.contracts]]
name = "Routes must not import httpx directly"
type = "forbidden"
source_modules = ["app.domains"]
forbidden_modules = ["httpx"]
ignore_imports = ["app.core.runtime.provider_gate -> httpx"]
```

Contratos que `import-linter` não expressa (chamada de método específica)
viram **regression tests estáticos** em
`backend/tests/architecture/test_runtime_invariants.py`.

### 5.6 — Migration Path

1. **Código novo** — obrigado a seguir charter. Lint + PR checklist + review.
2. **Código tocado** — Boy Scout rule cobrada **em code review humano** (sem lint `warn` para evitar alert fatigue).
3. **Código intocado** — dívida documentada em `§6 Backlog conhecido` do charter.
4. **Exceções legítimas** — comentário no código com link para §8 e prazo de reavaliação.

---

## §6 — Riscos, Rollback, Sizing, Critérios de Aceitação

### 6.1 — Riscos Críticos por Fase (resumo)

| ID | Risco | Prob | Impacto | Mitigação |
|---|---|---|---|---|
| R1.2 | `SingleFlightLock` deadlock em factory raise | Baixa | Alto | `try/finally` rigoroso + teste explícito |
| R1.3 | `IdleBridgePolicy` state inconsistente | Média | Alto | Enum + transições válidas explícitas + `IllegalStateError` |
| R1.6 | Redis cai → `@idempotent` trava toda rota | Média | Alto | Fallback graceful: execute sem cache + WARNING + header `X-Idempotency-Bypassed` |
| R1.9 | ESLint plugin quebra build do monorepo | Alta | Alto | Regras complexas em `warn` no v1, promoção para `error` em commit separado |
| R2.1 | Refactor `ConnectionManager` quebra testes WS | Alta | Médio | Atualizar `test_market_data_ws.py` no mesmo commit |
| R2.2 | Bridge migrada perde ticks em idle→running | Média | Alto | `request_demand` força flush sincronizado + teste |
| R2.4 | Substituir `priceMap` quebra componentes que dependiam de reatividade do objeto inteiro | Alta | Médio | Auditoria de cada uso no commit + testes Vitest |
| R3.2 | `<svelte:boundary>` mascara bugs reais | Média | Alto | `failed` snippet sempre loga erro completo no console + structured logger |
| R4.2 | `@idempotent` cacheia resultado com `block_id` errado | Média | Médio | Chave inclui `block_id` do payload |
| R8 | Sprint estoura escopo | Alta | Médio | Princípio de corte: pausa se fase ultrapassar size em >50% |
| R9 | Charter vira doc esquecido | Alta | Alto | Lint rules = defesa primária; PR template = secundária; review humano = terciária |

### 6.2 — Rollback

**Estratégia:** `git revert` granular por commit. **Sem feature flags** (decisão consciente — código limpo desde o dia zero).

- Reverter primitiva → `git revert` do commit. Zero efeito colateral se retrofit ainda não começou.
- Reverter retrofit → `git revert` do retrofit. Primitivas continuam vivas no código mas inutilizadas.
- Reverter sprint inteiro → `git revert -m 1 <merge_sha>`.

**Ordem de rollback se múltiplas primitivas falharem:** camada mais alta → mais baixa (lint → frontend store → frontend boundary → backend route → backend primitive).

### 6.3 — T-Shirt Sizing por Fase

| Fase | Size | Justificativa |
|---|---|---|
| Fase 1 — Foundations | **L** | 7 primitivas backend + 3 frontend + ESLint plugin + 4 regras Svelte + AST inline + 9 suítes com ≥95% coverage. Volume grande mas greenfield. |
| Fase 2 — Dashboard | **M** | 3 arquivos backend densos + 2 frontend. Efeito dominó do `market-data.svelte.ts`. |
| Fase 3 — FactSheet | **M** | Escopo cirúrgico. `FundDetailPanel` (350 linhas) + defensive retrofit. |
| Fase 4 — Screener Import | **M** | Service novo + worker novo + refactor de rota grande + cliente frontend. Template para futuras migrações. |
| Fase 5 — Doc + Governança | **S** | Charter doc + CLAUDE.md patch + PR template. Sequencial. |

**Total:** L+M+M+M+S. Caminho crítico: Fase 1 → Fase 2. Fase 5 paraleliza com Fase 2.

### 6.4 — Trade-offs Aceitos

1. Latência humana (250ms) sobre throughput máximo no Dashboard. Reversível por config.
2. Memória extra por conexão (~16KB buffer × 50 conexões = ~800KB).
3. Pacote extra no monorepo (`@netz/eslint-plugin-runtime`).
4. Charter doc de ~600 linhas para manter atualizado.
5. `<svelte:boundary>` pode mascarar bugs em dev (mitigado por log obrigatório).
6. `@idempotent` adiciona round-trip Redis (~5-10ms) em toda rota mutante.

### 6.5 — Critérios de Aceitação Final

**Código:**
- [ ] C1. `backend/app/core/runtime/` contém 7 primitivas + `p95_guard` middleware. Cobertura ≥ 95%.
- [ ] C2. `packages/ui/src/runtime/` contém 3 primitivas. Cobertura ≥ 95%.
- [ ] C3. `packages/eslint-plugin-netz-runtime/` publicado com 4 regras + ≥5 testes cada.
- [ ] C4. AST inline rules ativas em `frontends/eslint.config.js`.
- [ ] C5. `make check` passa sem **novos** erros (baseline lint debt documentado abaixo, não deve crescer).
- [ ] C6. `import-linter` contracts novos passam.

**Retrofits:**
- [ ] C7. `tiingo_bridge.py` usa `IdleBridgePolicy` + `SingleFlightLock`. Nunca `shutdown` fora do lifespan.
- [ ] C8. `ConnectionManager` usa `RateLimitedBroadcaster` + `ConnectionId` UUID.
- [ ] C9. `market-data.svelte.ts` usa `createTickBuffer`. Zero spread em handlers.
- [ ] C10. FactSheet `+page.server.ts` retorna `RouteData`. Zero `throw error()`.
- [ ] C11. `FundDetailPanel.svelte` envolto em `<svelte:boundary>`. Zero `$derived` unsafe.
- [ ] C12. `POST /screener/import/{identifier}` retorna `202 { job_id }` em < 100ms.
- [ ] C13. `@idempotent` ativo. Duplo POST → mesmo `job_id`.
- [ ] C14. SEC calls envolvidas em `ExternalProviderGate(name="sec_edgar")`.

**Testes manuais:**
- [ ] C15. Playwright: 50 nav Screener → FactSheet, 0 telas pretas.
- [ ] C16. Playwright: 5 cliques import, 1 job criado, sem duplicatas.
- [ ] C17. Playwright sintético: 5000 ticks em 10s, frame budget p99 < 16ms, < 60 invalidações.
- [ ] C18. Soak test **obrigatório** (local ou nightly): 30min Dashboard, heap < 10MB, 0 freezes. Roda ao menos 1x antes do merge da Fase 2.

**Documentação:**
- [ ] C19. `docs/reference/stability-guardrails.md` com §0–§8 completas.
- [ ] C20. `CLAUDE.md` patch enxuto (4 linhas + link).
- [ ] C21. `.github/PULL_REQUEST_TEMPLATE.md` com checklist.
- [ ] C22. §7 do charter com post-mortem light dos 3 bugs (escrito a partir da análise mecânica).

**Meta:**
- [ ] C23. Branch mergeada em `main` via PR, sem `eslint-disable`/`type: ignore` injustificados.

### 6.6 — Definição Operacional de "Estável e Previsível"

Na semana seguinte ao merge, em uso single-user normal, **nenhum** dos três sintomas originais reproduz:

1. Dashboard congelando em sessão de 30 min com Tiingo ativo.
2. FactSheet abrindo tela preta em 50 navegações consecutivas.
3. Screener L3 import com duplicatas ou botão girando em 10 imports com cliques agressivos.

Se qualquer um voltar, sprint é **incompleto** → novo ciclo diagnóstico → fix → re-validação.

### 6.7 — O que NÃO está coberto (dívida explícita)

1. Migration completa de **todas** integrações externas para `ExternalProviderGate` (sprint cobre apenas SEC no import path).
2. Migration completa de **todas** chamadas OpenAI para `LLMGate` (sprint cobre apenas o shim).
3. Worker idempotency (sprint separado "Hardening Workers").
4. Retrofit das 3 outras páginas de detalhe (Manager, Fund, Model Portfolio Detail).
5. Promoção de `require-svelte-boundary` de `warn` para `error` (sprint "Hardening Frontend").
6. Refactoring geral do `screener.py` (2.541 linhas).
7. Observability stack (APM, tracing distribuído).

---

## §7 — Post-Mortem Light dos 3 Bugs Alvo

Memória institucional. Baseado em análise mecânica do código-fonte, não
em reprodução narrativa. Chesterton's Fence — quem ler o charter em 6 meses
entende por que cada regra existe.

### §7.1 — Tiingo Dashboard Self-DDoS (ocorrência contínua, abril 2026)

**Sintoma relatado:** "Dashboard trava após alguns minutos com Tiingo ativo.
Aba congelando, memória crescendo, ocasionalmente WS de outros componentes
desconecta."

**Análise mecânica:**

1. **Fonte de emissão** — `tiingo_bridge.py` conectado ao IEX com
   `thresholdLevel: 0` (firehose completo). Em janelas de alta atividade
   de mercado, o stream emite centenas de ticks por segundo por ticker.
2. **Pipeline backend** — `_handle_message` (linha 290) enfileira cada tick
   em `self._buffer` (list). Quando buffer atinge `BUFFER_MAX_SIZE=5000`
   (linha 335), dispara `asyncio.create_task(self._drain_buffer())` —
   fire-and-forget sem single-flight. Sob burst sustentado, N tasks de
   drain acumulam, todas competindo pelo mesmo `self._buffer = []` (linha
   158). Race condition silenciosa: tasks podem perder ticks, duplicar
   publish, ou corromper contagem.
3. **Fan-out WS** — `ConnectionManager._fanout` (manager.py:232-248) itera
   sequencialmente por `ws_ids` e faz `await conn.ws.send_bytes(payload)`
   **sem timeout**. Cliente lento (tab em background, rede ruim, navegador
   sobrecarregado) bloqueia o fan-out inteiro daquele ticker por quanto
   tempo levar. Chave `dict[int, ClientConnection]` usa `id(ws)` — `id()`
   é reciclável após GC, criando risco de colisão silenciosa entre
   conexões.
4. **Reatividade frontend** — `market-data.svelte.ts:172-186` executa
   `priceMap = { ...priceMap, [tick.ticker]: tick }` **a cada tick** e
   `holdings = [...holdings]` logo depois. Com 500 ticks/s, isso é 500
   alocações de objeto + 500 invalidações reativas/s. O Svelte 5 invalida
   toda computação derivada e re-renderiza tudo que depende. O event loop
   do browser nunca termina um frame antes do próximo lote de ticks chegar.
5. **Acúmulo em tab oculta** — sem listener de `visibilitychange`, o buffer
   continua crescendo quando a tab está em background. Ao voltar ao foco,
   o browser tenta processar tudo de uma vez.
6. **Pre-subscribe no boot** — `subscribe_approved_universe()` (linha 231)
   pré-inscrevia todo o universo aprovado no startup, mesmo sem demanda
   ativa. Multiplicava o firehose pelo tamanho do catálogo.

**Causas raiz:** P1 (buffer sem teto efetivo — `BUFFER_MAX_SIZE` só dispara
drain, não aplica pressão), P2 (reatividade per-tick sem batching), P3
(slow consumer não isolado), P4 (bridge se desliga quando set vazio via
`unsubscribe()` → `shutdown()`, criando fragilidade de ciclo de vida).

**Motivação do guardrail:** O Tiingo bridge é o primeiro caso real de
conector de alta frequência no engine. Padrões de consumo futuros
(Bloomberg, Refinitiv, order books) herdarão todas essas classes de bug
se não formalizarmos o contrato agora.

### §7.2 — FactSheet Black Screen Intermitente (abril 2026)

**Sintoma relatado:** "Ao clicar no FactSheet a partir do Screener L3, a
tela fica preta com erro no console estilo `FundDetailPanel.svelte:123`.
Não acontece todas as vezes."

**Análise mecânica:**

1. **Causa imediata** — `+page.server.ts` (linhas 14-19) trata qualquer erro
   de backend com `throw error(404, 'Fund not found')` ou
   `throw error(status, 'Failed to load fund data')`. O SvelteKit captura
   esses throws no `+error.svelte` default, que é minimalista/preto. O
   usuário vê tela preta sem mensagem acionável.
2. **Causa secundária (intermitência)** — mesmo quando o load passa, o
   `FundDetailPanel.svelte` (350 linhas) tem múltiplos `$derived` que
   assumem `factSheet.X` está populado. Cenários de race que disparam
   `Cannot read properties of undefined`:
   - **Race A:** Usuário navega rápido Screener → FactSheet → Screener →
     FactSheet. Segunda montagem do componente pode receber contexto
     residual da primeira enquanto fetch novo ainda está pendente.
   - **Race B:** Componente faz subscribe a store de market-data fora de
     `onMount` (ou sem cleanup em `onDestroy`). Callback WS escreve em
     `localState` após o componente ter sido destruído pela navegação.
     Svelte 5 dispara erro reativo ao tentar atualizar grafo desmontado.
   - **Race C:** `+page.server.ts` load usa `api.get(...)` sem
     `AbortSignal.timeout`. Request trava. Usuário clica de novo. Dois
     fetches in-flight. Primeiro resolve, componente monta. Segundo
     resolve depois, tenta escrever em componente já reativo, gera erro.
3. **Ausência de boundary** — `+page.svelte` (a confirmar na
   implementação) não envolve `FundDetailPanel` em `<svelte:boundary>`.
   Qualquer erro de `$derived` explode até o topo → error boundary do
   SvelteKit → tela preta.

**Causas raiz:** P3 (erro num componente quebra a página inteira), P4
(subscribe sem lifecycle contract + fetch sem cancelamento), P6 (load
sem timeout + sem shape de erro acionável).

**Motivação do guardrail:** O padrão "tela preta sem informação" é o pior
resultado institucional possível — o usuário não sabe o que aconteceu,
não tem como recuperar, e desenvolvedor não tem informação estruturada
para diagnóstico. Formalizar o Route Data Contract + boundary obrigatório
+ load timeout previne essa classe inteira em toda página de detalhe
futura.

### §7.3 — Screener L3 Import Stampede (abril 2026)

**Sintoma relatado:** "Botão 'Import' do Screener L3 fica girando
longamente. Ocasionalmente erro 500. Ocasionalmente cria registros
duplicados quando clico de novo."

**Análise mecânica:**

1. **Request síncrono pesado** — `POST /screener/import/{identifier}`
   (screener.py:921-940) é um handler síncrono que:
   - Detecta formato do identificador (ISIN ou ticker)
   - Chama `import_esma_fund` ou `import_sec_security` internamente
   - `import_sec_security` (linhas 951-1100+) faz:
     - Query `Instrument` para verificar existência global
     - Query `InstrumentOrg` para verificar link com org
     - Query `SecCusipTickerMap` para lookup de ticker
     - Fallback para `SecFundClass` + `SecRegisteredFund` se ticker é
       mutual fund (linhas 1003-1024)
     - INSERT em `Instrument` e `InstrumentOrg` com commit
   - Tudo dentro de uma única request. Nenhuma chamada externa SEC tem
     timeout; nenhuma query tem budget.
2. **Ausência de idempotência** — não há `@idempotent` decorator nem
   single-flight. Duplo-clique dispara dois handlers concorrentes. O
   segundo, se chegar depois do primeiro completar, recebe erro 409
   (`Instrument with ticker X already exists in your universe`, linha
   975-978). Se chegar durante o primeiro, ambos executam queries
   independentes, e o comportamento depende da ordem exata de commit —
   possível criar duplicatas em `InstrumentOrg` ou falhar por violação
   de constraint. Não determinístico.
3. **Frontend loop de request stampede** — request demora muito, usuário
   fica sem feedback além do botão girando, clica de novo por intuição,
   multiplica o problema. Sem estado `submitting/running/done/error`
   explícito.
4. **Validação de autorização tardia** — `_require_investment_role(actor)`
   é chamado logo no início (linha 958), mas antes dele há lookup em
   `Instrument` que já consome uma query. Se autorização falhar, query
   foi desperdiçada. (Custo baixo, mas contra princípio de fail-fast.)
5. **Chamadas externas sem gate** — o caminho completo do import provavelmente
   toca SEC EDGAR (via `data_providers/sec/`) em outras variações do endpoint
   ou no caminho de fallback. Qualquer hiccup do SEC trava a request até
   timeout do pool asyncpg.

**Causas raiz:** P1 (rota pesada sem budget), P3 (chamada externa não
isolada), P5 (sem idempotência em mutação), P6 (sem timeout nem fallback
em chamada externa). Trabalho pesado em caminho de request ao invés de
job + SSE.

**Motivação do guardrail:** `import` é o primeiro caso real de "rota que
deveria ser job". Estabelecer o padrão Job-or-Stream agora cria o template
para migração de outras rotas pesadas identificadas pelo `p95_guard`
middleware. `@idempotent` é defesa obrigatória contra padrões de UX
humana (duplo-clique, reload) que são universais.

---

## §8 — Baseline de `make check`

Rodado em `main` em **2026-04-07** antes da criação da branch
`feat/stability-guardrails`.

**Resultado:** `make check` falha na etapa `lint` com **21 erros
pré-existentes** (ruff I001 — import ordering, todos auto-fixable com
`ruff check --fix`). Arquivos afetados (fora do escopo deste sprint):

- `ai_engine/ingestion/pipeline_ingest_runner.py`
- `app/domains/credit/modules/ai/extraction.py` (4 ocorrências)
- `app/domains/wealth/routes/manager_screener.py`
- `vertical_engines/credit/domain_ai/service.py`
- (mais 14 em arquivos do `credit` domain AI + wealth routes)

**Decisão (acordada com Andrei):** esses 21 erros são dívida pré-sprint.
**Não serão corrigidos neste sprint** (scope creep). O critério C5
("`make check` passa sem **novos** erros") será avaliado contra este
baseline: o sprint é aceito se o número de erros ruff **não aumentar**
em relação a 21 após o merge. Arquivos novos criados pelo sprint devem
ser 100% lint-clean.

**Etapas que não chegaram a rodar por falha do lint:** `architecture`,
`typecheck`, `test`. Serão rodadas separadamente durante a Fase 1 para
confirmar que passam em verde sobre `main` — se alguma dessas também
estiver com dívida herdada, será documentada em revisão do baseline
antes do primeiro commit de código.

---

## Fim do spec.

Próximo passo após aprovação deste documento: execução da Fase 1 nos
seguintes commits atômicos, com testes antes do código (TDD):

```
01 feat(runtime): bounded outbound channel + tests
02 feat(runtime): rate limited broadcaster + tests
03 feat(runtime): single flight lock + tests
04 feat(runtime): idle bridge policy + tests
05 feat(runtime): external provider gate + tests
06 feat(runtime): llm gate + tests
07 feat(runtime): idempotency decorator + tests
08 feat(runtime): p95 guard middleware
09 feat(ui/runtime): tick buffer + listener safe + tests
10 feat(ui/runtime): route contract types + helpers
11 feat(eslint): netz-runtime plugin (4 svelte rules) + tests
12 chore(eslint): inline AST rules in frontends/eslint.config.js
```

Por mandato do Engenheiro-Chefe (Andrei, 2026-04-07), o escopo do próximo
turno é **apenas**:
- `backend/app/core/runtime/outbound_channel.py`
- `backend/app/core/runtime/broadcaster.py`
- `backend/tests/runtime/test_outbound_channel.py`
- `backend/tests/runtime/test_broadcaster.py`

**Nenhuma integração com `manager.py` ou `tiingo_bridge.py` ainda.** As
primitivas entram como código isolado, testado, pronto para retrofit na
Fase 2 após revisão humana.
