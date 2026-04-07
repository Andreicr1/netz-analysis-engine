# Stability Guardrails — Engineering Charter

> **Em gestão institucional de patrimônio, imprevisibilidade é risco
> operacional inaceitável.** Todo caminho crítico do engine deve ter
> limite explícito, batching explícito e contrato de ciclo de vida
> explícito. Funcionalidade sem guardrail não está pronta — está
> postergando incidente.

**Status:** Normative — every new PR touching the hot paths listed
in §3 MUST reference this charter. Enforcement is **lint + PR
checklist + human review**, in that order of precedence. This is
not aspirational; it is the contract.

**Scope:** the full Netz Analysis Engine — `backend/app/**`,
`frontends/**`, `packages/investintell-ui/**`. External data
providers and operational add-ons inherit the charter by reference.

**Design origin:** [`docs/superpowers/specs/2026-04-07-stability-guardrails-design.md`](../superpowers/specs/2026-04-07-stability-guardrails-design.md).

**Sprint implementation log:**
- Phase 1 — runtime primitives (`0ed18a8`, `2cadcbb`, `0030ba5`, `566bbb3`, `42675ca`, `aab1d63`, `7a0b59b`, `f72e7ea`, `bedb29d`, `d2910e1`)
- Phase 2 — dashboard market-data retrofit (`ba9b5a6`)
- Phase 3 — factsheet route data contract (`ea799f7`)
- Phase 4 — screener import job-or-stream (`b521aec`, `37c17e8`) + crc32 hotfix (`d65cde6`)

---

## §0 The Founding Principle

In institutional wealth management, **unpredictability is an
unacceptable operational risk**. The analysis engine serves
portfolio managers who make capital-allocation decisions against
our output — a browser tab that freezes, a route that returns a
black screen, a double-clicked import that creates two instruments,
all of these are functionally worse than returning "service
unavailable". A hard failure is diagnosable; a soft failure that
corrupts displayed state is reputation damage.

Every code path that touches the hot loop MUST carry three
explicit guarantees:

1. **Explicit numerical ceiling** on queues, buffers, fan-out, page
   sizes, connection counts, retries.
2. **Explicit batching** of high-frequency events (frame-aligned,
   interval-aligned, or transaction-aligned).
3. **Explicit lifecycle ownership** — every listener, task,
   transaction, subscription has a declared creator, destroyer, and
   validity check.

Absence of any of the three = defect.

---

## §1 The Six Non-Negotiable Principles

| # | Name              | Rule |
|---|-------------------|------|
| **P1** | **Bounded**        | Every queue, buffer, fan-out, and page result has a declared numerical ceiling. No ceiling = bug. |
| **P2** | **Batched**        | High-frequency events are coalesced into batches aligned to a clock (frame, ms window, transaction). No batching = self-DDoS. |
| **P3** | **Isolated**       | A slow client, a broken query, a failing component does not affect other clients/queries/components. No isolation = failure cascades. |
| **P4** | **Lifecycle-correct** | Resources (listeners, tasks, transactions, subscriptions) have a declared owner, are created in an explicit hook, destroyed in an explicit hook, and check "still valid?" before writing. No lifecycle = race condition. |
| **P5** | **Idempotent**     | Mutations tolerate re-execution N times with the same input without corrupting state. No idempotency = corrupted rows on retry. |
| **P6** | **Fault-Tolerant** | Third-party failure = fail-fast with hard timeout + fallback/mapped error. External unavailability never becomes our unavailability. |

---

## §2 Primitive Catalogue

### 2.1 Backend Runtime Kit

Located in [`backend/app/core/runtime/`](../../backend/app/core/runtime/).
Every primitive is isolated (no dependency on `app.domains.*`), fully
tested (≥ 95 % coverage), and documented with behaviour guarantees.

| Primitive | File | Principles | Purpose |
|-----------|------|------------|---------|
| `BoundedOutboundChannel` | `outbound_channel.py` | P1 P3 P4 | Per-connection write buffer with drop policy + slow-consumer eviction. |
| `RateLimitedBroadcaster` | `broadcaster.py` | P1 P3 P4 | Fan-out over N bounded channels keyed by `ConnectionId` (UUID), never `id(ws)`. |
| `SingleFlightLock` | `single_flight.py` | P2 P3 | Per-key coroutine deduplication + optional TTL cache. At most one in-flight execution per key. |
| `IdleBridgePolicy` | `idle_bridge.py` | P4 | State machine for persistent external connectors (STOPPED ⇄ STARTING ⇄ RUNNING ⇄ IDLE ⇄ STOPPING). Single sanctioned shutdown path. |
| `ExternalProviderGate` | `provider_gate.py` | P6 | Circuit breaker + hard timeout + optional cache fallback for REST APIs. Two call sites with the same `name` share state. |
| `LLMGate` | `llm_gate.py` | P6 (special) | OpenAI-specific gate: 429 backoff with jitter, fallback model, soft/hard timeout split. |
| `@idempotent` | `idempotency.py` | P5 | Cross-process dedup via Redis `SET NX EX` + result cache. Fail-open to direct execution on Redis failure. |
| `p95_guard` middleware | `middleware/p95_guard.py` | observability | Passive p95 measurement per route over a 100-request window; logs `WARNING` when > 500 ms. Never blocks. |

### 2.2 Frontend Runtime Kit

Located in [`packages/investintell-ui/src/lib/runtime/`](../../packages/investintell-ui/src/lib/runtime/). Exposed under the `@investintell/ui/runtime` subpath export.

| Primitive | File | Principles | Purpose |
|-----------|------|------------|---------|
| `createTickBuffer<T>()` | `tick-buffer.svelte.ts` | P1 P2 P4 | Coalesces high-frequency writes into a Svelte 5 `$state(new Map())` flushed on `raf` or `{ intervalMs }` clock. Snapshot owned by the primitive — consumers just read. |
| `createMountedGuard()` | `listener-safe.svelte.ts` | P4 | `guard(fn)` executes only if the component is still mounted. Defence against async callbacks that outlive their component. |
| `RouteData<T>` + `okData` / `errData` / `isLoaded` / `isStale` | `route-contract.ts` | P3 P4 P6 | Typed load return shape for detail pages. No `throw error()` — every load returns `{ data, error, loadedAt }`. |
| `PanelErrorState` / `PanelEmptyState` | `components/analytical/` | P3 | Actionable panel-level states. `PanelErrorState` takes a `recoverable` flag driving whether the retry affordance is shown. |

### 2.3 Shared Helper — `gates.py`

[`backend/app/core/runtime/gates.py`](../../backend/app/core/runtime/gates.py) exposes lazy singletons so routes can decorate themselves at import time:

- `get_idempotency_storage()` — Redis-backed `IdempotencyStorage`
- `get_sec_edgar_gate()` — interactive SEC EDGAR gate (30 s wall, 5-failure threshold)
- `get_sec_edgar_bulk_gate()` — worker-context bulk SEC EDGAR gate (5 min wall, 10-failure threshold, separate circuit)
- `reset_for_tests()` — drops every cached singleton

**Adding a new provider:** pick a stable `name`, add a `get_<name>_gate()` factory with a tuned `GateConfig`, wrap call sites with `await gate.call("op_key", lambda: do_the_call())`.

---

## §3 Mandatory Patterns

### 3.1 WebSocket: accept → fan-out → evict

- **Identity:** every connection gets a `ConnectionId = make_connection_id()` (UUID). `id(ws)` is NEVER used as a key — Python identities are reusable after GC and would silently cause cross-talk.
- **Fan-out:** all writes go through `RateLimitedBroadcaster.fanout(payload, conn_ids)`. Direct `await ws.send_bytes(...)` in a route handler is forbidden.
- **Bounded channel:** the broadcaster owns a `BoundedOutboundChannel` per connection with `max_queued=256`, `send_timeout_s=2.0`, `DropPolicy.DROP_OLDEST`, `eviction_threshold=3`.
- **Eviction:** runs in a background sweeper task, not in the hot path. Slow clients are detached within `eviction_poll_s` (default 0.5 s) of crossing the threshold.
- **Shutdown:** single sanctioned path via `ConnectionManager.shutdown()` called from the app lifespan. Closes the broadcaster (which drains + cancels every channel).

**Example — the only way to accept a WS connection:**

```python
@router.websocket("/live/ws")
async def market_data_ws(ws: WebSocket):
    actor = await authenticate_ws(ws)
    if actor is None:
        return
    manager = ws.app.state.ws_manager
    conn = await manager.accept(ws, actor)
    conn_id = conn.conn_id
    try:
        # ... use manager.send_personal(conn_id, ...) for every send
    finally:
        await manager.disconnect(conn_id)
```

### 3.2 Background jobs: enqueue → SSE → progress

Routes with expected p95 > 500 ms MUST follow the **Job-or-Stream** pattern:

1. Route validates input, calls a worker `dispatch_*` function, returns **202** with `{job_id, ...}`.
2. Worker (background coroutine or process) publishes progress events to `job:{job_id}:events` via `publish_event(job_id, event_type, data)`.
3. Worker publishes a terminal event (`done` / `error` / `ingestion_complete`) via `publish_terminal_event` AND persists state via `persist_job_state` so reconnect-after-close still observes the outcome.
4. Client opens `GET /api/v1/jobs/{job_id}/stream` via `fetch + ReadableStream` (NEVER `EventSource` — auth headers required) and consumes the event sequence.

**Canonical reference implementation:** [`backend/app/domains/wealth/workers/screener_import_worker.py`](../../backend/app/domains/wealth/workers/screener_import_worker.py) + [`frontends/wealth/src/lib/api/screener-import.ts`](../../frontends/wealth/src/lib/api/screener-import.ts).

### 3.3 External APIs: wrap → timeout → fail

Every outbound HTTP call to a third-party provider (SEC EDGAR, FRED, Yahoo, Tiingo REST, Mistral OCR) MUST go through `ExternalProviderGate`. The gate is instantiated once (via `gates.py` singleton) and shared across every call site that addresses the same provider — circuit state is provider-wide, not per-request.

```python
from app.core.runtime.gates import get_sec_edgar_gate
from app.core.runtime.provider_gate import ProviderGateError

gate = get_sec_edgar_gate()
try:
    result = await gate.call(
        f"brochure:{crd}",
        lambda: download_pdf(crd),
    )
except ProviderGateError as exc:
    logger.warning("sec_brochure_gate_blocked crd=%s error=%s", crd, exc)
    return None
```

**Interactive vs bulk gate split:** `get_sec_edgar_gate()` has a 30 s wall and is for request-path calls. `get_sec_edgar_bulk_gate()` has a 5-minute wall for worker-only bulk downloads (FOIA CSV, N-PORT bulk). Never use the interactive gate around a multi-megabyte download — the circuit mismatch will poison downstream callers.

### 3.4 Detail pages: load → RouteData → boundary → component

SvelteKit detail pages (`+page.server.ts` / `+page.ts` / `+page.svelte`) MUST follow the Route Data Contract:

1. `load` returns `RouteData<T> = { data: T | null; error: RouteError | null; loadedAt: string }`. **No `throw error()`.** The lint rule in `frontends/eslint.config.js` enforces this under the `no-restricted-syntax` rule for `**/+page.{ts,server.ts}` + `**/+layout.{ts,server.ts}`.
2. `load` wraps every fetch in `AbortSignal.timeout(8000)` (configurable per route). If the API client is used, pass `{ signal: AbortSignal.timeout(8000) }` explicitly.
3. The page component renders three branches explicitly:
   ```svelte
   {#if routeData.error}
     <PanelErrorState … onRetry={routeData.error.recoverable ? retryLoad : undefined} />
   {:else if !routeData.data}
     <PanelEmptyState … />
   {:else}
     <svelte:boundary>
       <DetailPanel data={routeData.data} />
       {#snippet failed(error, reset)}
         <PanelErrorState … onRetry={reset} />
       {/snippet}
     </svelte:boundary>
   {/if}
   ```
4. `recoverable: false` for terminal states (404 NOT_FOUND). The retry affordance is hidden because retrying cannot succeed.
5. Any `$derived` reading fields from async-loaded data MUST use optional chaining + safe defaults. The component re-renders before `data` is populated.

**Canonical reference implementation:** [`frontends/wealth/src/routes/(app)/screener/fund/[id]/+page.server.ts`](../../frontends/wealth/src/routes/(app)/screener/fund/%5Bid%5D/+page.server.ts) + [`+page.svelte`](../../frontends/wealth/src/routes/(app)/screener/fund/%5Bid%5D/+page.svelte).

### 3.5 LLM calls: retry → fallback → hard timeout

All OpenAI / chat completions MUST go through `LLMGate.chat()`. The gate handles:
- **429** → exponential backoff with jitter, respects `Retry-After`. Does not count toward the circuit.
- **5xx / network** → retry up to `max_retries`. Counts as real failure.
- **Soft timeout** → log WARNING, do not abort.
- **Hard timeout** → abort via `asyncio.wait_for`.
- **Fallback model** → `prefer_fallback=True` switches to `fallback_model` if configured.
- **No result cache** — LLM calls are non-idempotent (temperature, stochasticity).

Legacy helpers (`call_openai_fn`, etc.) MUST delegate to `LLMGate.chat()`.

### 3.6 High-frequency client events: tick buffer

Any client-side source emitting > 10 events/second MUST route through `createTickBuffer<T>()`. Direct `$state` spreads inside WebSocket message handlers are banned by the `no-restricted-syntax` rule in `frontends/eslint.config.js` (catches `priceMap = { ...priceMap, ... }`).

- **Clock:** `"raf"` for animated surfaces (sparklines, canvas). `{ intervalMs: 250 }` for tabular displays — 4 updates/sec is legible for humans and avoids "slot machine".
- **maxKeys:** always set an explicit ceiling. Default eviction: `drop_oldest`.
- **dispose():** MUST be called in the store's `stop()` / `onDestroy`. The `require-tick-buffer-dispose` rule in `@investintell/eslint-plugin-netz-runtime` enforces this in component files.
- **Snapshot ownership:** the buffer exposes its `snapshot` as an internal `$state(new Map())`. Consumers just read `buffer.snapshot` — NO external mirror, NO defensive `flush()` polling. Svelte 5 reactivity propagates the reassignment automatically.

**Canonical reference implementation:** [`frontends/wealth/src/lib/stores/market-data.svelte.ts`](../../frontends/wealth/src/lib/stores/market-data.svelte.ts).

### 3.7 Mutating routes: idempotency

Mutating routes that can be triggered by user action (import, create, update) MUST be decorated with `@idempotent` keyed on a deterministic derivation of the payload. Prefer the Stripe-style `Idempotency-Key` header with server-side namespacing by `organization_id`:

```python
def _import_idempotency_key(identifier, body, request, db, org_id, actor) -> str:
    client_key = request.headers.get("Idempotency-Key", "").strip()
    if client_key:
        return f"resource:{org_id}:{client_key}"
    digest = hashlib.sha256(f"{identifier}|{body.block_id or ''}".encode()).hexdigest()
    return f"resource:{org_id}:{digest}"

@router.post("/import/{identifier}", status_code=202)
@idempotent(key=_import_idempotency_key, ttl_s=300, storage=get_idempotency_storage())
async def import_fund(identifier, body, request, db=…, org_id=…, actor=…):
    _require_investment_role(actor)  # role check FIRST
    …
```

**Triple-layer dedup** for high-concurrency mutations:
1. Cross-process: `@idempotent` decorator (Redis `SET NX EX`).
2. In-process (same uvicorn worker): `SingleFlightLock` in the dispatcher.
3. Database-level: `pg_advisory_xact_lock(class_id, deterministic_key)` in the service.

**CRITICAL:** the advisory lock key MUST use `zlib.crc32` or `hashlib.md5`, **never Python's built-in `hash()`** — the built-in is seeded per-interpreter (`PYTHONHASHSEED=random` since Python 3.3), so two uvicorn workers would compute different keys and the DB-level layer silently degrades to no-op.

---

## §4 Anti-Patterns — DO NOT

| Anti-pattern | Why it's banned | Correct pattern |
|---|---|---|
| `await ws.send_bytes(...)` in a route handler | No per-connection buffer, no timeout — one slow client stalls everyone | `manager.send_personal(conn_id, data)` |
| `dict[int, ClientConnection]` keyed on `id(ws)` | Python identities recycle after GC → silent cross-talk | `dict[ConnectionId, ClientConnection]` where `ConnectionId = UUID` |
| `asyncio.create_task(_drain_buffer())` fired from two places | Two tasks race on `self._buffer = []` | `SingleFlightLock("drain").run(key, _drain)` |
| `unsubscribe()` that calls `shutdown()` when demand = 0 | Kills the transport mid-session on any tab close | `IdleBridgePolicy` state machine — IDLE keeps the bridge alive |
| `priceMap = { ...priceMap, [tick.ticker]: tick }` per WS event | O(N) reactive invalidation per tick → self-DDoS | `tickBuffer.write(tick)` (inside the store's WS handler) |
| `throw error(404)` in a SvelteKit `load` | SvelteKit default error boundary = black screen | `return errData('NOT_FOUND', msg, recoverable=false)` |
| `$derived(data.fund.name)` without optional chaining | Crashes during partial response / async seam | `$derived(data?.fund?.name ?? '—')` |
| Store `.subscribe([...])` at module top-level | Outlives the component → memory leak | `onMount(() => store.subscribe(...))` + cleanup |
| Synchronous long-running work in a request handler | Holds asyncpg connections → pool starvation | Job-or-Stream with 202 + SSE |
| `abs(hash((org, id, block))) % (2**31)` for advisory lock | Non-deterministic across processes | `zlib.crc32(f"{org}:{id}:{block}".encode()) & 0x7FFFFFFF` |
| `httpx.get("https://sec.gov/…")` directly | No timeout, no circuit breaker | `await gate.call("op_key", lambda: httpx.get(...))` |
| Top-level `storage = get_idempotency_storage()` module attribute used after settings change | Singleton binds to wrong Redis | Prefer `get_idempotency_storage()` at call time inside each decorator invocation |

---

## §5 Enforcement

Enforcement runs in layers, each cheaper and faster than the next:

1. **ESLint AST rules (inline)** — `frontends/eslint.config.js` bans the spread-in-reactive-handler pattern, top-level `.subscribe([...])`, and `throw error()` in `load` files. Runs on every pre-commit and CI build.
2. **`@investintell/eslint-plugin-netz-runtime`** — Svelte-parser rules for `require-svelte-boundary`, `no-unsafe-derived`, `require-load-timeout`, `require-tick-buffer-dispose`. Currently `warn` in v1 for the Svelte-parser rules; promotion to `error` lives in a follow-up commit once noise is cleared.
3. **`import-linter` contracts** (`pyproject.toml`) — verticals cannot import each other, routes cannot import `httpx` directly (except through `provider_gate`), model modules cannot import service modules.
4. **`p95_guard` middleware** — passive per-route p95 observability. Not a hard gate, but a WARNING signal that a route has outgrown its budget and should migrate to Job-or-Stream.
5. **PR checklist** (`.github/PULL_REQUEST_TEMPLATE.md`) — mandatory Guardrails section. Reviewers tick the boxes before approval.
6. **Human code review** — Boy Scout rule for touched code; charter violations in new code are blocking.

---

## §6 Known Backlog (Documented Debt)

Code that pre-dates the charter and has not yet been retrofitted. Do **not** copy these patterns in new code.

- `backend/app/domains/credit/**` — credit vertical has its own legacy import/ingest paths that have not been migrated to `@idempotent` + Job-or-Stream. Tracked for Phase 6+.
- `backend/app/domains/wealth/routes/dd_reports.py` — the long-form DD report path has its own SSE handling pre-dating the shared `screener-import.ts` client. Consolidation planned.
- `backend/ai_engine/extraction/**` — OCR / chunking / embedding path is not yet wrapped in `ExternalProviderGate` for Mistral / OpenAI calls. Currently uses ad-hoc retry helpers.
- Tests for legacy test suites (`test_manager_screener.py`) still depend on live PG/Redis — the 24 failures observed during Phase 4 are pre-existing infra debt.

---

## §7 Incident Log (Abbreviated)

Each entry links to its retrofit commit and the primitive that closed the class.

| # | Date | Incident | Root cause | Closed by |
|---|------|----------|------------|-----------|
| 1 | 2026-03-15 | Dashboard tab freezing under Tiingo IEX firehose | `priceMap = {...priceMap}` per tick × 500/sec | Phase 2 `createTickBuffer` + `RateLimitedBroadcaster` (`ba9b5a6`) |
| 2 | 2026-03-22 | FactSheet black screen on 404 during screener nav | `throw error(404)` → default minimal error boundary | Phase 3 Route Data Contract (`ea799f7`) |
| 3 | 2026-03-28 | Screener import double-click → 409 or duplicate row | No cross-process dedup, synchronous handler | Phase 4 `@idempotent` + `pg_advisory_xact_lock` + crc32 hotfix (`b521aec`, `d65cde6`) |
| 4 | 2026-03-31 | Tiingo bridge dying on unsubscribe-all | `release_demand` calling `shutdown()` | Phase 2 `IdleBridgePolicy` (`ba9b5a6`) |

---

## §8 When to Relax a Rule

Exceptions exist. The process:

1. **Document the reason inline** — a `# stability-guardrails-exception: <reason>` comment pointing to this §8 and a date for reassessment (max 90 days).
2. **Open a debt ticket** under `docs/plans/` with the rationale and the class of bugs this exception could enable.
3. **Review in the next charter sync** — every Monday standup briefly touches the exception list and closes any whose reassessment date has passed.

Legitimate exceptions so far (as of 2026-04-07):
- *None.* The charter has not yet had to grant an exception. New exceptions MUST be reviewed by Andrei before landing.

---

## §9 Acceptance Criteria Reference

From the design spec §6.5. These are the gate-level criteria the sprint was measured against:

- **C1** ✅ `backend/app/core/runtime/` contains 7 primitives + `p95_guard` middleware, coverage ≥ 95 %.
- **C2** ✅ `packages/investintell-ui/src/lib/runtime/` contains 3 primitives + `PanelErrorState` / `PanelEmptyState`.
- **C3** ✅ `@investintell/eslint-plugin-netz-runtime` published with 4 Svelte-parser rules.
- **C4** ✅ AST inline rules live in `frontends/eslint.config.js`.
- **C5** ✅ `make check` passes without new errors; baseline lint debt unchanged.
- **C6** ✅ `import-linter` contracts pass.
- **C15** ✅ Dashboard 30-min soak test — heap growth < 10 MB, tab responsive. See `e2e/wealth/stability-guardrails.spec.ts`.
- **C16** ✅ FactSheet 50× navigation — 0 black screens, 100 % show content or `PanelErrorState`.
- **C17** ✅ Screener import 5× rapid click — exactly 1 job created, 1 instrument added, no duplicates.
- **C18** ✅ Dashboard soak with `chrome://memory` — ≤ 10 MB heap growth over 30 min. (Ran nightly, not CI.)

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-04-07 | Andrei + Opus 4.6 | Initial charter landed as part of Phase 5 of the Stability Guardrails sprint. Covers Phases 1–4 retrofits. |
