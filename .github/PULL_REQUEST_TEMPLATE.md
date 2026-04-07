<!--
  Pull request template — Netz Analysis Engine.

  The Stability Guardrails section below is MANDATORY for any PR that
  touches the hot paths listed in the charter (WebSocket, background
  jobs, external APIs, detail pages, mutating routes). If your PR is
  pure docs / tests / non-functional, write "N/A — <reason>" against
  each unchecked item.

  Charter: docs/reference/stability-guardrails.md
-->

## Summary

<!-- 1-3 bullet points describing WHAT changed and WHY. Focus on the
     motivation, not the mechanical diff. -->

-
-

## Test plan

<!-- Bulleted markdown checklist. Be specific about how you verified
     each behavior change. -->

- [ ]
- [ ]

---

## Stability Guardrails Checklist

> Charter: `docs/reference/stability-guardrails.md`. Tick every box
> that applies to touched code; write `N/A — reason` on the rest.

### Backend

- [ ] New WebSocket handlers attach/detach via `ConnectionManager` (never `id(ws)` as a key, never direct `ws.send_bytes` in the route).
- [ ] New outbound HTTP / REST calls are wrapped in `ExternalProviderGate` via `get_<provider>_gate()` from `backend/app/core/runtime/gates.py`.
- [ ] New OpenAI / chat-completion calls go through `LLMGate.chat()`.
- [ ] New mutating endpoints that can be retried (import, create, update) use `@idempotent` or justify the exception inline (`# stability-guardrails-exception: …`).
- [ ] New routes with expected p95 > 500 ms are jobs, not synchronous handlers — return 202 + `/jobs/{id}/stream`.
- [ ] New persistent bridges inherit `IdleBridgePolicy`; `shutdown()` is reachable only from the app lifespan via `_from_lifespan=True`.
- [ ] New in-process dedupe uses `SingleFlightLock`; new cross-process dedupe uses `@idempotent`.
- [ ] Advisory lock keys are computed with `zlib.crc32` or `hashlib.md5`, **never** Python built-in `hash()`.
- [ ] `_require_*_role(actor)` (or equivalent authz check) is the FIRST line of the route body, before any query.

### Frontend

- [ ] New event sources emitting > 10/s use `createTickBuffer<T>()` from `@investintell/ui/runtime` — no `priceMap = { ...priceMap, … }` spreads inside WS handlers.
- [ ] New async callbacks (WS `onmessage`, SSE reader loops, `await`-after-unmount risks) use `createMountedGuard` or return cleanly on `mounted.mounted = false`.
- [ ] New detail pages return `RouteData<T>` from their `load` functions — no `throw error()`. Import `errData` / `okData` from `@investintell/ui/runtime`.
- [ ] New top-level panels are wrapped in `<svelte:boundary>` with a `failed` snippet rendering `PanelErrorState`.
- [ ] New `+page.{ts,server.ts}` load fetches pass an explicit `AbortSignal.timeout(8000)` (or a per-route override).
- [ ] New `$derived` expressions reading async-loaded data use optional chaining + safe defaults.
- [ ] New mutating client calls send an `Idempotency-Key` header derived from a stable payload hash (`sha256(identifier + block_id)` etc.) via `api.post(..., { headers: { "Idempotency-Key": ... } })`.
- [ ] All numeric/date/currency formatting uses formatters from `@investintell/ui` (`formatNumber`, `formatCurrency`, `formatPercent`, `formatDate`, etc.) — never raw `.toFixed()` / `.toLocaleString()` / `new Intl.NumberFormat`.

### Tests & verification

- [ ] Regression test added for the failure mode this PR fixes (if fixing a bug).
- [ ] `make check` passes locally — no new lint / typecheck / architecture errors.
- [ ] No `eslint-disable netz-runtime/...` or `# stability-guardrails-exception` added without a charter §8 reference and a 90-day reassessment date.
- [ ] Touched e2e surfaces have a corresponding Playwright spec in `e2e/wealth/` or `e2e/credit/` (C15–C17 class of tests).

### Observability

- [ ] New background jobs publish a terminal event (`done` / `error` / `ingestion_complete`) AND persist state via `persist_job_state` so reconnect-after-close still observes the outcome.
- [ ] New provider gate call sites log a structured warning on `ProviderGateError` (never crash the caller).
- [ ] New long-running async tasks have a `name=` argument to `asyncio.create_task` so they show up in the debugger.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
