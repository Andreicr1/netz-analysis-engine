# Construction Engine PR-A5 — Frontend Migration to Job-or-Stream Builder

**Date:** 2026-04-15
**Executor:** Opus 4.6 (1M context)
**Branch:** `feat/construction-engine-pr-a5-frontend-migration`
**Base:** `main` at commit `0d8f8da8` (PR #183 — PR-A3+A4 remediation merged)
**Scope:** Single frontend PR migrating the Builder UI from the legacy `POST /api/v1/model-portfolios/{portfolio_id}/construct` endpoint to the hardened `POST /api/v1/portfolios/{id}/build` endpoint delivered in the PR-A4 remediation. Includes phase-aware UI, sanitisation-aware rendering, idempotency/cancel/error UX, deprecation of the legacy route, and mandatory visual validation via Playwright.

> **This PR MUST be opened from a clean branch cut off `main@0d8f8da8`. Do NOT bundle other scope (no quant changes, no new backend endpoints, no design-token churn). Reviewability is a PR-level invariant.**

---

## Why this PR exists

Two endpoints currently reach `execute_construction_run`:

1. **Legacy — actively used by the UI today**
   `POST /api/v1/model-portfolios/{portfolio_id}/construct` in `backend/app/domains/wealth/routes/model_portfolios.py:511`.
   - No `@idempotent`, no `SingleFlightLock`, no `pg_advisory_xact_lock`.
   - No `require_ic_member` RBAC gate.
   - SSE events use legacy phase names (`run_started`, `optimizer_started`, `stress_started`, `done`, `error`).
   - Called from `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts:1541`.

2. **New — hardened, but no client**
   `POST /api/v1/portfolios/{id}/build` in `backend/app/domains/wealth/routes/portfolios/builder.py:311`.
   - `@idempotent` (Redis 600s) + `SingleFlightLock` (in-process) + `pg_try_advisory_xact_lock(zlib.crc32(...))` (cross-process).
   - `require_ic_member()` RBAC.
   - 5 nominal pipeline phases: `STARTED → FACTOR_MODELING → SHRINKAGE → SOCP_OPTIMIZATION → BACKTESTING → COMPLETED` plus terminal `ERROR` / `CANCELLED` / `DEDUPED`.
   - Sanitised payloads via `_publish_phase` + canonical executor `_publish_event_sanitized` (message = human sentence; `metrics` = raw numbers).
   - Job-owner enforcement on `/jobs/{id}/stream` (cross-tenant 403).

The gap is **product risk**: today a non-IC operator can trigger a 120s institutional construction run with no advisory lock, no idempotency guarantee, no audit identity. Users double-clicking RUN CONSTRUCTION race the same worker. Cross-tenant job stream snooping is theoretically possible on the legacy route because `verify_job_owner` is not wired there.

Additionally, **124 lines uncommitted** in the working tree (`CalibrationPanel.svelte` + 4 sub-components + `builder/+page.svelte`) add `originalValue={snapshot?.X}` to every calibration field. This is the final piece of the "Compare with: Last run" dropdown visible in the current Builder screenshot. It must be audited, completed, and committed as part of this PR (it is the last unmerged delta from the Phase 4 Builder sprint).

---

## Mandates (non-negotiable)

1. **Frontend-only PR.** Do NOT touch backend files except the single `deprecated=True` marker on the legacy route (Section E). No backend schema changes. No new quant code.
2. **Smart backend, dumb frontend** (memory `feedback_smart_backend_dumb_frontend.md`). The backend already sanitises messages via `sanitize_payload` + `humanize_event_type` in `construction_run_executor.py:165`. The frontend does NOT re-sanitise `message` — it renders it verbatim. The frontend MAY add secondary human-friendly chips derived from `payload.metrics` per the translation table in Section C.
3. **No emojis. No `.toFixed()`. No inline `Intl.NumberFormat`.** All number/currency/percent/date formatting via `@investintell/ui` (`formatNumber`, `formatCurrency`, `formatPercent`, `formatDate`, `formatShortDate`, `formatDateTime`). Enforced by `frontends/eslint.config.js`.
4. **Svelte 5 runes only** (`$state`, `$derived`, `$effect`, `$props`, `$bindable`). No legacy `$: ...` reactive statements. No stores unless crossing component trees — prefer `$lib/state/*.svelte.ts` modules.
5. **SSE via `fetch()` + `ReadableStream`.** Never `EventSource` (auth headers are required). Canonical pattern is already in `portfolio-workspace.svelte.ts:1573`.
6. **No localStorage** (memory `feedback_echarts_no_localstorage.md`). All state is in-memory + SSE + polling.
7. **Layout cage preserved.** `calc(100vh-88px)` + `padding: 24px` on the content panel (memory `feedback_layout_cage_pattern.md`). Do not alter the shell.
8. **`svelte-echarts` mandatory** for any new chart. Do not introduce Chart.js / Recharts / d3 direct DOM.
9. **Never remove endpoints** (memory `feedback_no_remove_endpoints.md`). Legacy `/construct` route gets `deprecated=True` + runtime log warning; it stays functional for at least two sprints. Its actual removal is a separate future PR (A6 or A7).
10. **Visual validation in browser is mandatory** (memory `feedback_visual_validation.md`). Playwright run must be executed against `make up` + `pnpm dev-wealth`; pasted screenshots + trace file in PR description.
11. **Idempotency-Key header per click, not per user.** Generate a fresh UUID v4 on every RUN CONSTRUCTION click; re-use the same UUID only on explicit retry flows (Section D.2).
12. **No shortcuts.** Install any types/deps needed (`@types/uuid` etc.). Iterate until `pnpm --filter netz-wealth-os check` and `make check` are green.

---

## Section A — Frontend wiring migration

All paths under `frontends/wealth/src/` unless specified. Line numbers are current-state references; patch where the logical equivalent lives.

### A.1 — Add `uuid` dependency
- File: `frontends/wealth/package.json`.
- Add `"uuid": "^10.0.0"` to `dependencies` and `"@types/uuid": "^10.0.0"` to `devDependencies`.
- Run `pnpm install --filter netz-wealth-os` at repo root. Commit the resulting `pnpm-lock.yaml` delta.
- **Justification:** `crypto.randomUUID()` works in all modern browsers but the codebase has no standing pattern for it; `uuid.v4()` keeps the idempotency-key generation explicit and SSR-safe.

### A.2 — New types for the build endpoint
- File: `frontends/wealth/src/lib/types/portfolio-build.ts` (NEW).
- Export:
  ```ts
  export interface BuildAccepted {
    job_id: string;
    stream_url: string;           // "/api/v1/jobs/{job_id}/stream"
    status: "accepted";
  }
  export type BuildPhase =
    | "STARTED"
    | "FACTOR_MODELING"
    | "SHRINKAGE"
    | "SOCP_OPTIMIZATION"
    | "BACKTESTING"
    | "COMPLETED"
    | "CANCELLED"
    | "ERROR"
    | "DEDUPED";
  export interface BuildEvent {
    type: string;                 // humanised label from backend
    raw_type?: string;            // ORIGINAL type from backend (e.g. "optimizer_phase_complete")
    phase?: BuildPhase | string;  // pipeline phase OR optimizer cascade sub-phase
    message?: string;
    progress?: number;            // 0.0 … 1.0
    metrics?: Record<string, unknown>;
    run_id?: string;              // only on COMPLETED
    status?: string;
    reason?: string;              // only on ERROR/CANCELLED/DEDUPED
    objective_value?: number | null;  // only on optimizer_phase_complete
  }
  ```
- Do NOT reuse `ConstructRunEvent` — keep it alongside for the legacy path until Section E is complete.

### A.3 — Add the `buildPortfolio` state method
- File: `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` around line 1520 (next to `runConstructJob`).
- Add a new class method `async runBuildJob(): Promise<ConstructionRunPayload | null>` that mirrors `runConstructJob` with these changes:
  - Generates `const idempotencyKey = uuidv4();` at the top.
  - Calls `api.post<BuildAccepted>(`/portfolios/${this.portfolioId}/build`, undefined, { timeoutMs: 130_000, headers: { "Idempotency-Key": idempotencyKey } })`. Verify `apiClient` forwards arbitrary headers; if not, extend `HttpRequestOptions` to accept `headers?: Record<string, string>` in the single fetch call without breaking other callers.
  - Stores `this._activeBuildJobId = accepted.job_id` (new `$state` field) so DELETE cancel can target it.
  - Stream parsing loop re-uses the existing `fetch` + `ReadableStream` pattern verbatim (lines 1573–1631). Do NOT copy-paste; extract the shared SSE parser into `$lib/util/sse-reader.ts` with signature `parseSseStream(res: Response, onEvent: (ev: unknown) => void, signal: AbortSignal): Promise<void>` and have BOTH `runConstructJob` and `runBuildJob` call it.
  - On terminal `ERROR`/`CANCELLED`/`DEDUPED` event sets `runPhase = "error"` (for ERROR), `"cancelled"` (new state, see A.6), or behaves as A.4.3 (for DEDUPED).
  - Does NOT call `loadConstructionRun(run_id)` itself — dispatches that only on `phase === "COMPLETED"` via `ev.run_id`.

### A.4 — New `_applyBuildEvent` handler
- File: same as A.3, adjacent to `_applyRunEvent` (line 1685).
- Add `private _applyBuildEvent(ev: BuildEvent): void` that:
  1. Inspects `ev.phase` first (new pipeline phases), falling back to `ev.raw_type` (optimizer sub-phases forwarded by the canonical executor).
  2. **Pipeline phase → top-level runPhase mapping:**
     | `ev.phase`          | `this.runPhase`            | Side effect                                                         |
     |---------------------|----------------------------|----------------------------------------------------------------------|
     | `STARTED`           | `"running"`                | Reset `optimizerPhases` to defaults                                  |
     | `FACTOR_MODELING`   | `"factor_modeling"` (new)  | Store `metrics` on `this.buildMetrics.factor` (new $state field)     |
     | `SHRINKAGE`         | `"shrinkage"` (new)        | Store on `this.buildMetrics.shrinkage` — drives RiskTab badge        |
     | `SOCP_OPTIMIZATION` | `"optimizer"`              | Keep existing optimizer phase display                                |
     | `BACKTESTING`       | `"stress"`                 | Trigger StressTab prefetch spinner                                   |
     | `COMPLETED`         | `"done"`                   | `await this.loadConstructionRun(ev.run_id!)`                         |
     | `ERROR`             | `"error"`                  | `this.runError = ev.message ?? ev.reason`                            |
     | `CANCELLED`         | `"cancelled"` (new)        | `this.runError = null` (not an error)                                |
     | `DEDUPED`           | `"deduped"` (new)          | Re-attach to existing stream — see A.4.3                             |
  3. **Optimizer sub-phase events** (raw_type `optimizer_phase_complete`): reuse existing `optimizerPhases.map(...)` block from `_applyRunEvent` verbatim.
  4. Update `this.runProgress = ev.progress ?? this.runProgress` (new $state, 0–1 scale).

### A.4.1 — Expand `runPhase` type
- Same file, around line 430. Existing type: `"idle" | "running" | "optimizer" | "stress" | "done" | "error"`.
- New type: `"idle" | "running" | "factor_modeling" | "shrinkage" | "optimizer" | "stress" | "done" | "error" | "cancelled" | "deduped"`.
- Update all discriminator checks downstream (`ActivationBar.svelte`, `RunControls.svelte`, `+page.svelte`). Grep for `runPhase ===` and `runPhase !==` — expect ~8 hits; each must be re-evaluated (most want `runPhase === "done"` to stay exactly as-is; the new states should be treated as "in-flight" variants).

### A.4.2 — New `$state` fields on workspace
- Same file, near line 433 where `optimizerPhases` lives.
- Add:
  ```ts
  runProgress = $state<number>(0);
  buildMetrics = $state<{
      factor: Record<string, unknown> | null;
      shrinkage: Record<string, unknown> | null;
      socp: Record<string, unknown> | null;
      backtest: Record<string, unknown> | null;
  }>({ factor: null, shrinkage: null, socp: null, backtest: null });
  private _activeBuildJobId: string | null = null;
  private _activeBuildAbort: AbortController | null = null;   // separate from legacy _activeRunAbort
  ```
- Reset all four `buildMetrics` keys to `null` at the top of `runBuildJob()`.

### A.4.3 — DEDUPED re-attachment
- Path: on receiving a DEDUPED event, do NOT error. Instead: display a toast ("Another build is already running for this portfolio; following the live stream.") and CONTINUE reading the stream — the backend advisory-lock loser still receives the full event stream because it subscribed to the same `job_id`. No re-POST, no re-subscribe. Confirmed by inspecting `builder.py:174-183` (the `DEDUPED` event is published to the same `job_id`, so the already-opened SSE reader receives it). Keep `runPhase = "running"` until `COMPLETED` or a terminal event arrives.

### A.5 — Point the Builder UI at the new method
- File: `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte`.
- File: `frontends/wealth/src/lib/components/terminal/builder/RunControls.svelte`.
- Grep for every call to `workspace.runConstructJob()` and `workspace.constructPortfolio()`. Replace with `workspace.runBuildJob()`.
- Keep `workspace.constructPortfolio` method defined (delegate to `runBuildJob` so external tests don't break).

### A.6 — New `runPhase === "cancelled"` handling
- File: `RunControls.svelte`.
- When `runPhase === "cancelled"`, the button label becomes `RUN AGAIN` (not `RETRY`) with a neutral style (not red). No auto-retry. User must click explicitly; clicking generates a fresh Idempotency-Key.

### A.7 — Reset cascade timeline on STARTED
- File: `portfolio-workspace.svelte.ts`, inside `_applyBuildEvent` for `phase === "STARTED"`.
- Explicitly: `this.optimizerPhases = structuredClone(DEFAULT_CASCADE_PHASES);`
- **Tradeoff note:** `DEFAULT_CASCADE_PHASES` (line 199) describes the OPTIMIZER cascade (primary/robust/variance_capped/min_variance/heuristic). The five NEW pipeline phases (FACTOR_MODELING…) are represented separately via the `runPhase` top-level state and the Zone D `CascadeTimeline`'s header strip (see B.2). Do NOT merge the two concepts. The cascade pills remain optimizer-specific.

### A.8 — Surface `runProgress` to the UI
- File: `RunControls.svelte` and `CascadeTimeline.svelte`.
- Add a thin progress bar (height 2px) under the pills in `CascadeTimeline` bound to `$derived(workspace.runProgress * 100)`. Use `var(--terminal-accent)` for fill, `var(--terminal-border-hairline)` for track. Visible only when `runPhase !== "idle"` AND `runPhase !== "done"` AND `runPhase !== "error"`.
- Do NOT use a `<progress>` element (styling inconsistent across browsers). Use a `<div>` with inline `style:width="{pct}%"` per the existing `ct-rail-fill` pattern.

### A.9 — Cancel button (new, side-effect of DELETE /jobs/{id})
- File: `RunControls.svelte`.
- While `runPhase` is any in-flight state (`running | factor_modeling | shrinkage | optimizer | stress | deduped`), render a secondary `CANCEL` button next to RUN CONSTRUCTION.
- `onclick` → `workspace.cancelActiveBuild()` (new method, A.10). The primary button becomes disabled with label `BUILDING…` until terminal event arrives.

### A.10 — New workspace method `cancelActiveBuild`
- File: `portfolio-workspace.svelte.ts`.
- Implementation:
  ```ts
  async cancelActiveBuild(): Promise<void> {
    const jobId = this._activeBuildJobId;
    if (!jobId) return;
    try {
      await this.api().delete(`/jobs/${jobId}`, { timeoutMs: 5_000 });
    } catch (err) {
      // Best-effort — the SSE CANCELLED event is authoritative
    }
  }
  ```
- DO NOT abort the SSE reader client-side. Let the server-emitted CANCELLED terminal event drive the phase transition (keeps the audit trail intact).
- Verify `DELETE /jobs/{id}` exists in `backend/app/main.py` — it lives on the canonical job router. If it does not, **STOP and report**; do not implement a cancel shim.

### A.11 — Error UX matrix
Render errors inline in Zone B (calibration panel footer) and in the ActivationBar. Use `PanelErrorState` component from `@investintell/ui` if available.

| HTTP / event          | Message shown to user (verbatim)                                                       | Recovery CTA                                             |
|-----------------------|----------------------------------------------------------------------------------------|----------------------------------------------------------|
| 400 invalid UUID      | "Portfolio identifier is invalid. Refresh and re-select."                              | "REFRESH"                                                |
| 403 forbidden (RBAC)  | "You are not authorised to run a construction. Contact an IC member."                  | —                                                        |
| 403 forbidden (stream cross-tenant) | "Build stream unavailable. Please re-open the Builder."                  | "REOPEN"                                                 |
| 409 idempotency conflict (rare — distinct key, same body) | Should not occur — log to console.error for observability. | —                                     |
| 504 gateway timeout / client timeout | "Construction exceeded 120s. Review your calibration (regime override, shrinkage, turnover cap) and try again." | "RE-RUN" (fresh idempotency key) |
| SSE `ERROR`           | `payload.message` verbatim (already sanitised by backend)                              | "RE-RUN"                                                 |
| SSE `CANCELLED`       | "Construction cancelled."                                                              | "RUN AGAIN"                                              |
| SSE stream disconnect (network) | "Lost connection to the build stream. Reconnecting…"                         | Auto-retry SSE GET once, then show "REOPEN"              |

**Note on 409:** The backend `@idempotent` decorator returns the CACHED 202 (same `job_id`, HTTP 202) on duplicate key — it does NOT 409. A 409 only arrives if somehow the cached body diverges. Treat 409 as unexpected — console.error + fall back to "RE-RUN".

---

## Section B — Phase-aware UI rendering

### B.1 — Translation of the 5 pipeline phases to tab hints
When each SSE phase arrives, subtly highlight the relevant result tab header (add a pulsing dot using `var(--terminal-warning)` until data populates). This guides the user to "where is the output I just unlocked":

| Phase                | Tab hint                          | State transition                                                                   |
|----------------------|-----------------------------------|------------------------------------------------------------------------------------|
| `FACTOR_MODELING`    | RISK tab                          | Pulse until `metrics.factor` populated on workspace                                |
| `SHRINKAGE`          | RISK tab                          | Pulse continues; update badge text based on `metrics.shrinkage` (see C)            |
| `SOCP_OPTIMIZATION`  | WEIGHTS tab                       | Pulse until `constructionRun` loaded                                               |
| `BACKTESTING`        | STRESS + BACKTEST tab             | Pulse both                                                                         |
| `COMPLETED`          | All clear                         | Remove all pulses; auto-switch `activeTab` to `WEIGHTS` if user has not interacted |

### B.2 — Pipeline strip above the CascadeTimeline (Zone D)
- File: `frontends/wealth/src/lib/components/terminal/builder/CascadeTimeline.svelte`.
- Above the existing 5 optimizer pills, add a NEW strip of 5 pipeline phase chips: `FACTOR MODEL → COVARIANCE → OPTIMIZER → BACKTEST → COMPLETE`.
- States mirror optimizer pills: `pending | running | succeeded | failed | skipped`. Driven by a new prop `pipelinePhase: BuildPhase`.
- Visual treatment: chips are 24px tall (smaller than optimizer pills); label uses `var(--terminal-text-muted)` when pending, `var(--terminal-text)` when running/succeeded.
- The existing connector rail stays beneath the optimizer pills (not the new strip). The strip is informational context, the optimizer cascade is the drill-down.
- No emojis. Chips labels use words; status is conveyed by color + hairline weight.

### B.3 — RiskTab phase-aware content
- File: `frontends/wealth/src/lib/components/terminal/builder/RiskTab.svelte`.
- Before `constructionRun` is loaded (still in factor/shrinkage phase), show a skeleton card with three chips derived from `workspace.buildMetrics.factor` and `.shrinkage`:
  - **Factor coverage chip**: `"Modelo de fatores: {k_effective} de {k_factors} fatores ativos"` (human labels; numbers via `formatNumber`).
  - **Regime chip**: badge colored by regime severity (see C).
  - **Stability chip**: see C translation table (κ → "Boa estabilidade" / "Ajuste robusto" / "Atenção: modelo instável").
- After `constructionRun` loads, render the existing risk content AND keep the three chips pinned at the top for traceability.

### B.4 — StressTab progress indicator
- File: `frontends/wealth/src/lib/components/terminal/builder/StressTab.svelte`.
- When `runPhase === "stress"`, render a 4-checkbox grid of the 4 parametric scenarios (GFC, COVID, Taper Tantrum, Rate Shock). Each scenario turns from gray dot → green check as `metrics.scenario_results` populates (if backend emits per-scenario; if not, a single spinner with label "Running 4 stress scenarios…").
- Do NOT pre-compute or mock numbers. Wait for server.

### B.5 — AdvisorTab and BacktestTab phase gating
- Both tabs show a placeholder "Aguardando construction run" when `constructionRun === null && runPhase === "idle"`.
- When in-flight, show the existing shimmer skeleton; do NOT reveal partial numbers.

### B.6 — MonteCarloTab
- Out of scope for this PR — Monte Carlo is triggered separately. Leave as-is.

### B.7 — Regime strip stays live
- `RegimeContextStrip.svelte` reads from the macro workspace, not from the build stream. No changes.

---

## Section C — Sanitisation-aware rendering (frontend translation table)

**The backend already sanitises `message` and `type` fields server-side** (`construction_run_executor.py:165` via `sanitize_payload` + `humanize_event_type`). The frontend MUST render those fields verbatim. The ADDITIONAL responsibility of the frontend is: translating raw numbers in `payload.metrics` (where the backend intentionally surfaces the quant values) into **human-friendly chips/badges** that sit next to (not replace) the raw number.

Build this table in `frontends/wealth/src/lib/util/metric-translators.ts` (NEW). Each translator is a pure function `(value) => { label: string; tone: "success" | "neutral" | "warning" | "danger" }`.

| `metrics` key            | Raw value example      | Label (PT-BR institutional)                    | Tone        | Thresholds                                  |
|--------------------------|------------------------|-------------------------------------------------|-------------|---------------------------------------------|
| `kappa` (cond number)    | `23_000`               | "Boa estabilidade do modelo de risco"           | `success`   | `< 1e4` → success                            |
|                          | `230_000`              | "Estabilidade aceitável"                        | `neutral`   | `1e4 ≤ κ < 1e6` → neutral                    |
|                          | `2_500_000`            | "Atenção: modelo instável — considere regime override" | `warning`   | `≥ 1e6` → warning (backend already falls back; surface so user knows) |
| `shrinkage_lambda`       | `0.08`                 | "Estimativa direta"                             | `neutral`   | `< 0.15` → neutral                           |
|                          | `0.42`                 | "Estimativa robusta"                            | `success`   | `0.15 ≤ λ ≤ 0.70` → success                  |
|                          | `0.95`                 | "Forte shrinkage — covariância quase diagonal"  | `warning`   | `> 0.70` → warning                           |
| `regime`                 | `"NORMAL"`             | "Regime normal"                                 | `neutral`   |                                              |
|                          | `"RISK_OFF"`           | "Regime defensivo ativo"                        | `warning`   |                                              |
|                          | `"CRISIS"`             | "Regime de crise — CVaR reforçado"              | `danger`    |                                              |
| `regime_multiplier`      | `0.70`                 | "Tolerância a risco reduzida em 30%"            | `warning`   | Render only if `!= 1.0`                      |
| `k_factors_effective` + `k_factors` | `7 / 8`       | "7 de 8 fatores ativos"                         | `success`   | `effective >= 0.75 * total` → success        |
|                          | `3 / 8`                | "Cobertura de fatores limitada (3 de 8)"        | `warning`   | else → warning (surface `factors_skipped`)   |
| `r_squared_p50`          | `0.82`                 | "Aderência média: alta"                         | `success`   | `≥ 0.7` → success                            |
|                          | `0.45`                 | "Aderência média: moderada"                     | `neutral`   | `0.4–0.7` → neutral                          |
|                          | `0.21`                 | "Aderência média: baixa — revisar benchmarks"   | `warning`   | `< 0.4` → warning                            |
| `cvar_95` (portfolio)    | `-0.087`               | formatPercent(-0.087, 2) — value visible        | —           | Chip colored by threshold vs mandate limit   |
| `max_drawdown_pct`       | `-0.34`                | formatPercent(-0.34, 2)                         | —           | Chip colored if `< mandate.max_drawdown_cap` |
| `phase_used` (optimizer) | `"robust"`             | "Otimizador: robusto"                           | `success`   | Map: primary→"otimizador principal", robust→"otimizador robusto", variance_capped→"variância limitada", min_variance→"variância mínima", heuristic→"fallback heurístico" |

**Rule:** the chip label is what the user READS; the raw number is still accessible in a hover tooltip for the analyst who wants the value (`title` attribute or a `<Popover>` from `@investintell/ui`).

**CVaR labelling exception:** CVaR is a well-known term in the institutional audience; spelling it out is acceptable. Do NOT rename to "tail loss" — Andrei's audience knows the acronym. Treat as exception to smart-backend/dumb-frontend, documented here explicitly.

**κ and shrinkage_lambda — NEVER written as κ or λ in the UI.** Always use the human labels above. The raw number goes in the tooltip.

---

## Section D — Error states, idempotency, cancel, refresh

### D.1 — Idempotency-Key lifecycle
- Generate fresh `uuid.v4()` on every click of RUN CONSTRUCTION.
- Persist `lastIdempotencyKey` in `$state` (not localStorage) so that if the user clicks "RE-RUN" within 600s on the SAME error, they can OPTIONALLY reuse it via a "same key" toggle (default OFF = fresh key). Only surface this toggle in a developer/QA panel if `import.meta.env.DEV` — do NOT expose in production UX.

### D.2 — Single-flight re-POST
- If the user double-clicks RUN CONSTRUCTION within the same render frame: the second click is a no-op because the button is disabled synchronously on `onclick`. Verify the `disabled` attribute is bound to `runPhase !== "idle" && runPhase !== "done" && runPhase !== "error" && runPhase !== "cancelled"`.
- If the user Ctrl+Shift+R mid-run: the `onMount` `$effect` discovers `_activeBuildJobId` is lost (in-memory state wiped). Two options:
  - **Option A (THIS PR):** Show a neutral banner "Any active builds have been disconnected. Click RUN AGAIN to start fresh." The server's Redis idempotency cache will coalesce if the user re-posts within TTL with the same body (portfolio_id unchanged).
  - **Option B (future PR):** Persist `_activeBuildJobId` to sessionStorage and re-subscribe to SSE on mount. Explicitly OUT OF SCOPE for A5 (session persistence touches the `feedback_echarts_no_localstorage.md` boundary — sessionStorage is a separate decision we defer).

### D.3 — 403 cross-tenant on `/jobs/{id}/stream`
- Should NEVER happen in practice (the job_id is generated server-side and given back to the same tenant). If it does: the SSE fetch returns 403 in its initial response. Treat as fatal: `runPhase = "error"`, show "Build stream unavailable. Please re-open the Builder." Log to console.error with `{ job_id, status: 403 }`. Do NOT retry.

### D.4 — Timeout (client-side 130s)
- Existing pattern in `portfolio-workspace.svelte.ts:1543` uses `timeoutMs: 130_000` — **keep this.** Backend bound is 120s + 10s network margin.
- If the client timeout trips BEFORE the server emits a terminal event: the AbortController aborts the fetch; show "Construction exceeded 120s. Review your calibration and try again."
- Concurrently, attempt a best-effort `DELETE /jobs/{id}` to unblock the server advisory lock. Tolerate failure silently.

### D.5 — Cancellation mid-flight
- DELETE /jobs/{id} is fire-and-forget; the authoritative signal is the SSE `CANCELLED` terminal event. UI stays in an "in-flight (cancelling)" state until the event arrives OR the reader errors out. If 30s pass after DELETE with no CANCELLED event: surface "Cancellation accepted but no confirmation received. Refresh to re-sync." This mirrors how long-running workers are handled elsewhere in the platform.

### D.6 — Network reconnect on mid-stream disconnect
- If `reader.read()` throws a network error (not AbortError): retry the SSE GET ONCE after 2s with the same `job_id`. If that also fails, show "Lost connection to the build stream. Reconnecting…" and ultimately "REOPEN" CTA.
- Do NOT loop. One retry only. More aggressive retry is a platform primitive concern, not an A5 concern.

---

## Section E — Legacy endpoint deprecation

### E.1 — Mark legacy route deprecated
- File: `backend/app/domains/wealth/routes/model_portfolios.py:511` (only backend change in this PR).
- Locate the `@router.post("/model-portfolios/{portfolio_id}/construct", ...)` decorator. Add `deprecated=True` and update the `summary=` to prepend `"[DEPRECATED — use POST /portfolios/{id}/build]"`.
- Inside the route body as the very first executable statement after arg validation, emit:
  ```python
  logger.warning(
      "legacy_construct_endpoint_called",
      portfolio_id=portfolio_id,
      organization_id=str(actor.organization_id),
      actor_id=actor.actor_id,
      migration_target="POST /portfolios/{id}/build",
  )
  ```
- Do NOT change behaviour. Do NOT add redirects. Do NOT change status codes.
- The legacy route stays fully functional for ≥ 2 sprints (removed in PR-A6 or A7).

### E.2 — OpenAPI schema regeneration
- Run `make types` after backend is up. The generated `openapi-schema.d.ts` (or equivalent) now flags `/model-portfolios/{portfolio_id}/construct` as `deprecated`. Commit the delta — this is the frontend's audit trail that the switch happened.

### E.3 — Dead code audit
- Grep the wealth frontend for `/model-portfolios/${...}/construct` — there should be ZERO remaining call sites after Section A. If any non-test code still calls it, reroute.
- The legacy `runConstructJob` method stays in the workspace class but is unreferenced. Add a JSDoc `@deprecated — use runBuildJob; kept for Phase 4 test harness compatibility, remove in PR-A7` above it.

---

## Section F — Calibration panel `originalValue` commit + audit

The 124 uncommitted lines add `originalValue={snapshot?.X}` to every calibration field so the user can see draft vs. last applied value.

### F.1 — Audit the diff before committing
- Run `git diff frontends/wealth/src/lib/components/portfolio/CalibrationPanel.svelte` and the 4 sub-component files. Confirm:
  1. No type regressions (the `snapshot` prop exists on each sub-component with matching type to the field).
  2. No removed behaviour — each change is purely additive (new prop passed; sub-component reads it and renders a diff indicator).
  3. `snapshot` is `structuredClone(workspace.constructionRun?.calibration_snapshot)` — NOT the draft. The diff must compare against the LAST APPLIED calibration of the last successful run, not against the draft.
  4. No `.toFixed()` / inline `Intl.NumberFormat` introduced — enforced by `pnpm lint`.
- If ANY sub-component reads `originalValue` via `$effect` instead of `$derived`: convert to `$derived` (idiomatic Svelte 5).

### F.2 — Verify the "Compare with: Last run" dropdown
- Per the current Builder screenshot, the `CalibrationPanel` header hosts a dropdown "Compare with:" with "Last run" selected. Confirm:
  - The dropdown exists in the uncommitted diff OR was committed previously. If NOT present: STOP and report — the originalValue wiring is useless without the selector.
  - Each option (e.g. "Last run", "Seed snapshot", "3 runs ago") maps to a specific `snapshot` source.
  - For A5 scope: commit only the "Last run" wiring. Other options stay disabled (greyed) — they are scope for a follow-up PR.

### F.3 — Commit in a single scoped commit
- Title: `feat(wealth): calibration diff vs last run (originalValue pass-through)`
- Body: explain the OD-1 motivation from CLAUDE.md's Phase 4 Builder goals. Reference the screenshot (attach one to the PR description, not the commit).

---

## Section G — Visual validation (mandatory, blocking)

Playwright MCP is available. Run against the local stack — not prod, not staging.

### G.1 — Pre-flight
```bash
make up                                      # Postgres + Timescale + Redis
make migrate                                 # alembic upgrade head
make serve                                   # FastAPI on :8000 (background)
pnpm --filter netz-wealth-os dev             # SvelteKit on :5173 (background)
```

### G.2 — Playwright scenario script (save to `docs/qa/pr-a5-playwright.md` as narrative + artefacts)
Using the `mcp__plugin_playwright_playwright__*` MCP tools, execute:

1. **Navigate** to `http://localhost:5173/portfolio/builder`. Authenticate via Clerk dev bypass (`X-DEV-ACTOR` header) or existing dev flow.
2. **Select** the first portfolio in the dropdown. Wait for `[data-testid="builder-panel"]` to be attached (or equivalent selector; add `data-testid` if absent).
3. **Calibration change**: drag the "Turnover cap" slider down 10%. Confirm the `originalValue` indicator (small tick mark or number next to slider) shows the ORIGINAL value as a ghosted reference.
4. **Apply**: click APPLY. Wait for workspace `isApplyingCalibration === false`.
5. **Click RUN CONSTRUCTION**. Observe within 5s:
   - Primary button disables, label becomes "BUILDING…".
   - CANCEL button appears.
   - CascadeTimeline pipeline strip activates on FACTOR_MODELING chip.
   - RISK tab header pulses.
6. **Record** SSE events by intercepting `/api/v1/jobs/*/stream` via `browser_network_requests`. Expect sequence containing `STARTED, FACTOR_MODELING, SHRINKAGE, SOCP_OPTIMIZATION, BACKTESTING, COMPLETED` (plus any `optimizer_phase_complete` sub-events).
7. **Terminal state**: on COMPLETED within 120s, confirm: WEIGHTS tab auto-activates, STRESS/RISK/BACKTEST tabs populate, primary button label returns to "RUN CONSTRUCTION".
8. **Double-click idempotency test** (RE-RUN flow):
   - Click RUN CONSTRUCTION.
   - Within 1s, while the button is disabled, attempt to re-click using JS `document.querySelector(...).click()` — must be a no-op.
   - Using a SECOND browser context / incognito window: POST `/portfolios/{id}/build` with the SAME Idempotency-Key as the first click's request (extract from DevTools Network). Expect HTTP 202 with the SAME `job_id`.
9. **Cancel test**:
   - Click RUN CONSTRUCTION.
   - At FACTOR_MODELING phase (within ~15s), click CANCEL.
   - Expect within 5s: SSE emits `CANCELLED`, `runPhase === "cancelled"`, button label becomes "RUN AGAIN" (neutral style, not red).
10. **Cross-tenant 403 test** (optional — seed a second tenant):
    - Trigger build as tenant A, capture `job_id`.
    - Switch to tenant B, GET `/api/v1/jobs/{job_id}/stream`.
    - Expect HTTP 403 + UI displays "Build stream unavailable."
11. **Timeout simulation** (OPTIONAL if operator has a way to stall the worker):
    - Temporarily seed a calibration that forces a slow optimizer (e.g., absurdly tight `turnover_cap` on a large universe). If it completes under 120s, skip this step and document inability to simulate.
    - Otherwise, expect `ERROR` event with message about timeout.

### G.3 — Artefacts to attach to PR
- 3 screenshots: (1) mid-build with pipeline strip lit, (2) COMPLETED state with all tabs populated, (3) CANCELLED state.
- 1 Playwright trace file (`.zip`) from `browser_take_screenshot` + `browser_network_requests` snapshots.
- Copy-paste of the SSE event sequence captured in step 6.

### G.4 — Console must be clean
- Zero `console.error`.
- Zero 4xx/5xx on the `/api/v1/*` network tab EXCEPT the intentional 403 (if step 10 executed).
- Zero Svelte warnings (check browser devtools + terminal output of `pnpm dev-wealth`).

---

## Section H — Verification commands (all must pass before requesting review)

```bash
# Backend (light touch — only E.1 deprecation marker)
cd backend
make lint
make typecheck
make architecture
make test ARGS="-k model_portfolios and construct"   # legacy tests still pass
make test ARGS="-k builder_sse"                       # new builder tests still pass

# Frontend
cd ../frontends
pnpm install
pnpm --filter netz-wealth-os check                    # svelte-check + TypeScript
pnpm --filter netz-wealth-os lint                     # ESLint incl. formatter-discipline rule
pnpm --filter netz-wealth-os build                    # production build

# Types regeneration
cd ..
make types                                            # must succeed against running backend

# Full gate
make check                                            # top-level — must be green
```

**Grep audits (paste output in PR description):**
```bash
# No legacy endpoint calls remain in non-test wealth frontend code
grep -rn "/model-portfolios/.*construct" frontends/wealth/src --include='*.svelte' --include='*.ts' \
  | grep -v "test\|spec\|/\*\*\|@deprecated"
# Expected: ZERO hits.

# No hex colors introduced
grep -rn "#[0-9a-fA-F]\{3,6\}" frontends/wealth/src/lib/components/terminal/builder --include='*.svelte'
# Expected: ZERO hits (all colors via CSS vars).

# No .toFixed / inline Intl.NumberFormat
grep -rn "\.toFixed(\|new Intl\.NumberFormat\|new Intl\.DateTimeFormat" frontends/wealth/src
# Expected: ZERO hits (enforced by eslint, but grep as belt-and-suspenders).

# No EventSource
grep -rn "new EventSource(" frontends/wealth/src
# Expected: ZERO hits.

# No localStorage / sessionStorage in wealth runtime code (tests ok)
grep -rn "localStorage\|sessionStorage" frontends/wealth/src --include='*.svelte' --include='*.ts' \
  | grep -v "test\|spec"
# Expected: ZERO hits.

# No emojis in source (regex: surrogate pairs / extended pictographic)
grep -rnP "[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]" frontends/wealth/src
# Expected: ZERO hits.
```

---

## Section I — Deliverables checklist

- [ ] Branch `feat/construction-engine-pr-a5-frontend-migration` created from `main@0d8f8da8`.
- [ ] A.1–A.11 patches applied, one logical commit per subsection.
- [ ] B.1–B.7 patches applied.
- [ ] C: `metric-translators.ts` created with the full translation table from Section C, plus unit tests in `metric-translators.test.ts`.
- [ ] D.1–D.6 covered (with comments referencing each D.x in the code).
- [ ] E.1–E.3 applied — the ONLY backend change in the PR is the `deprecated=True` + `logger.warning`.
- [ ] F.1–F.3 — 124 uncommitted lines audited, fixed if needed, committed in a scoped commit.
- [ ] G.1–G.4 — Playwright run executed against local stack; artefacts attached.
- [ ] H — all verification commands green.
- [ ] PR title: `feat(wealth): migrate Builder UI to /portfolios/{id}/build (PR-A5)`.
- [ ] PR description includes:
  - Link to this spec.
  - Link to the PR-A3+A4 remediation spec and PR #183.
  - `make check` output (tail 30 lines).
  - `pnpm --filter netz-wealth-os check` output.
  - Grep audit outputs from Section H.
  - Playwright trace zip + 3 screenshots.
  - Explicit statement: "Legacy `/model-portfolios/{id}/construct` remains functional; deprecation warning confirmed in server logs during Playwright run."
- [ ] Self-review of the full diff one more time (open PR "Files changed" tab, read top-to-bottom).
- [ ] Request human review only after everything above is satisfied.

---

## Section J — What NOT to do

- Do NOT remove `/model-portfolios/{id}/construct` in this PR. Deprecate only.
- Do NOT re-sanitise `message` or `type` on the frontend — the backend already did it. Rendering a second sanitisation layer causes divergence.
- Do NOT introduce `sessionStorage` or `localStorage` persistence for `_activeBuildJobId`. Out of scope.
- Do NOT change the cascade timeline's OPTIMIZER pills (primary/robust/...) — keep them; they represent a DIFFERENT concept than the 5 pipeline phases.
- Do NOT use `EventSource`. `fetch()` + `ReadableStream` only.
- Do NOT bundle calibration snapshot diff dropdown options beyond "Last run" — scope creep.
- Do NOT commit the `data-testid` additions as a separate PR — they are part of the visual validation contract here.
- Do NOT add Chart.js, Recharts, or ad-hoc SVG charts. `svelte-echarts` only if a chart is needed (none is needed in A5).
- Do NOT use `.toFixed()`, `.toLocaleString()`, inline `Intl.NumberFormat`, inline `Intl.DateTimeFormat`. Hard rule.
- Do NOT introduce emojis.
- Do NOT set `runPhase` directly from `ev.raw_type` alone — always consider `ev.phase` first, then fall back.
- Do NOT retry the SSE stream more than ONCE on disconnect. Aggressive retries belong in a platform primitive.
- Do NOT proceed to PR-A6 (removal of legacy route) until A5 has baked in production for ≥ 2 sprints AND server logs show zero `legacy_construct_endpoint_called` events over a full week.
- Do NOT treat a passing backend unit test as evidence the UX works. Visual validation is mandatory.

---

## Reference files (absolute paths)

**Backend (read-only for this PR except E.1):**
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\routes\portfolios\builder.py`
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\routes\model_portfolios.py` (line 511 — add `deprecated=True` + log warning)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\domains\wealth\workers\construction_run_executor.py` (reference for `_publish_event_sanitized`, `EVENT_TYPE_LABELS`, `sanitize_payload` — do NOT modify)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\main.py` (reference for `DELETE /jobs/{id}` registration)
- `C:\Users\andre\projetos\netz-analysis-engine\backend\app\core\jobs\tracker.py` (reference for `verify_job_owner`, `is_cancellation_requested`)

**Frontend (primary edit surface):**
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\state\portfolio-workspace.svelte.ts` (A.3, A.4, A.4.1–A.4.3, A.7, A.10)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\routes\(terminal)\portfolio\builder\+page.svelte` (A.5, A.8)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\terminal\builder\RunControls.svelte` (A.5, A.6, A.9)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\terminal\builder\CascadeTimeline.svelte` (A.8, B.2)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\terminal\builder\RiskTab.svelte` (B.3)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\terminal\builder\StressTab.svelte` (B.4)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\terminal\builder\BacktestTab.svelte` (B.5)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\terminal\builder\AdvisorTab.svelte` (B.5)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\terminal\builder\ActivationBar.svelte` (A.4.1 — discriminator update)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationPanel.svelte` (F.1–F.3)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationScenarioGroup.svelte` (F.1)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationSelectField.svelte` (F.1)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationSliderField.svelte` (F.1)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\portfolio\CalibrationToggleField.svelte` (F.1)

**Frontend (new files):**
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\types\portfolio-build.ts` (A.2)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\util\sse-reader.ts` (A.3 — shared SSE parser extraction)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\util\metric-translators.ts` (C)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\util\metric-translators.test.ts` (C — unit tests)
- `C:\Users\andre\projetos\netz-analysis-engine\docs\qa\pr-a5-playwright.md` (G.2 — narrative + artefacts)

**Reference docs:**
- `C:\Users\andre\projetos\netz-analysis-engine\docs\prompts\2026-04-15-construction-engine-pr-a3-a4-remediation.md`
- `C:\Users\andre\projetos\netz-analysis-engine\CLAUDE.md` (Stability Guardrails §3, Frontend formatter discipline)

---

## Risk register — brutally honest

**Easy:**
- A.1, A.2, A.5, E.1 — mechanical wiring.
- Section F commit — the diff is already written; this is audit + commit.

**Medium:**
- A.3/A.4 — the SSE parser extraction is the highest-value refactor but also the highest coupling risk. Mitigation: ship the extraction in its own commit BEFORE wiring the new method. Legacy tests must stay green after the extraction alone.
- Section C translation table — requires taste calls on threshold boundaries. Anchor to the values above; let the first human review tune.
- B.1–B.5 phase-aware tab pulses — stylistic fit against the existing brutalist design. Keep the pulse subtle (1s linear infinite opacity 0.6→1.0 on a 4px dot). Do not animate the entire tab header.

**Hard / risky:**
- A.4.3 DEDUPED re-attachment — untested path today. The backend emits DEDUPED only if `pg_try_advisory_xact_lock` fails, which requires two pods. In local dev with a single backend process, this path can only be reproduced via the in-process SingleFlightLock, which uses a different event payload. Document in the PR that DEDUPED was NOT reproduced in local Playwright and requires a two-pod staging verification before PR-A6.
- G.2 step 10 cross-tenant — only testable if a second tenant is seeded. If operator cannot seed one quickly, downgrade to a unit test that mocks `verify_job_owner` return value.
- G.2 step 11 timeout — hard to simulate deterministically. If cannot reproduce, add a TODO to PR description and ensure the 504/ERROR UX is at least code-reviewed thoroughly.
- Coordination with `svelte5-frontend-consistency` agent running in parallel: their output adds Svelte 5 patterns, formatter discipline, runes migrations. If their patches conflict with A.3/A.4, MERGE THEIRS FIRST (they own primitives), then reapply A.3/A.4 on top. Never the reverse.

---

**End of spec. Execute end-to-end from a clean branch. Report back with PR URL + CI status + Playwright artefact links + grep audit output. Do not proceed to PR-A6 without explicit sign-off.**


---

# Section J — Svelte 5 Implementation Patterns (PR-A5)

> Este anexo complementa as Sections A-I. Foco: como implementar em Svelte 5 sem reintroduzir bugs conhecidos. Coordena com o wealth-architect: ele cobre o "o quê" e "por quê", esta seção cobre o "como" em Svelte 5.

## J.0 — Estado de partida (evidência factual)

Arquivo principal do store: `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` (Svelte 5 `.svelte.ts`, ~2000 linhas). Pontos âncora verificados:

- **L115-138:** `ConstructRunAccepted` e `ConstructRunEvent` — shapes SSE atuais. Não têm campo `metrics`. PR-A5 adiciona.
- **L191-205:** `CascadePhase` e `DEFAULT_CASCADE_PHASES` — 5 fases OPTIMIZER-level (`primary` / `robust` / `variance_capped` / `min_variance` / `heuristic`). Isso NÃO é o mesmo conjunto de 5 fases pipeline-level do PR-A5 (`FACTOR_MODELING` / `SHRINKAGE` / `SOCP_OPTIMIZATION` / `BACKTESTING` / `COMPLETED`). Existem dois níveis ortogonais de cascade — nomear distintamente para evitar retrabalho (ver §J.3).
- **L428:** `runPhase = $state<"idle" | "running" | "optimizer" | "stress" | "done" | "error">("idle")` — rune correto, mas a enumeração precisa mudar.
- **L433:** `optimizerPhases = $state<CascadePhase[]>(structuredClone(DEFAULT_CASCADE_PHASES))` — `structuredClone` evita vazar a constante mutável entre runs. Manter.
- **L1523-1677:** `runConstructJob()` — aponta para `/model-portfolios/${id}/construct` (endpoint ANTIGO). Alvo central de refactor.
- **L1564-1571:** resolução do `streamUrl` concatenando com `VITE_API_BASE_URL` — pattern reutilizável.
- **L1585-1626:** loop `fetch + getReader + TextDecoder` + parsing `data:` + buffer `\r\n→\n`. Código de referência — copiar, não reinventar.
- **L1629-1631:** `reader.cancel().catch(...)` — cleanup correto em terminal normal.
- **L1527-1529 e L1673-1675:** `_activeRunAbort: AbortController` — single-flight cancel em re-press do Run. Manter; backend tem idempotency triple-layer, frontend casa essa semântica.
- **L1685-1718:** `_applyRunEvent()` — dispatcher por `event` string. Ponto único que consome metrics; mantém assim (um switch central, não espalhar pelos tabs).

Componentes em `frontends/wealth/src/lib/components/terminal/builder/`: `CascadeTimeline.svelte` (225 L), `RunControls.svelte` (172 L), `RegimeContextStrip.svelte` (225 L), `RegimeTab/RiskTab/WeightsTab/StressTab/BacktestTab/MonteCarloTab/AdvisorTab/ActivationBar/ConsequenceDialog.svelte`.

Uncommitted no working tree: 5 arquivos `components/portfolio/Calibration*` + `routes/(terminal)/portfolio/builder/+page.svelte`. Conforme `feedback_parallel_gemini_sessions.md`, NÃO tocar nesses arquivos até Gemini session concluir — PR-A5 ortogonal ao CalibrationPanel.

---

## J.1 — Runes patterns para o novo contrato SSE

### J.1.1 — Reestruturar `runPhase` em `pipelinePhase` + `optimizerPhase`

Bug latente se misturados: `SOCP_OPTIMIZATION` (pipeline) com `robust` (optimizer) num único `$state` quebra semântica e força `if`s em cascata.

```ts
export type PipelinePhase =
  | "IDLE"
  | "QUEUED"
  | "FACTOR_MODELING"
  | "SHRINKAGE"
  | "SOCP_OPTIMIZATION"
  | "BACKTESTING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

pipelinePhase = $state<PipelinePhase>("IDLE");
optimizerPhases = $state<CascadePhase[]>(structuredClone(DEFAULT_CASCADE_PHASES));
phaseMetrics = $state<Partial<Record<PipelinePhase, Record<string, unknown>>>>({});
sanitizedMessage = $state<string>("");
terminalState = $state<"pending" | "success" | "error" | "cancelled">("pending");
```

### J.1.2 — `$derived` para labels (não funções no template)

Backend já sanitiza, mas o frontend tem dicionário próprio para PT/EN consistente. Use `$derived`, nunca função chamada em `{...}`:

```ts
currentPhaseLabel = $derived(PHASE_HUMAN_LABEL[this.pipelinePhase] ?? "Preparando");

phaseProgress = $derived.by(() => {
  const order: PipelinePhase[] = [
    "QUEUED", "FACTOR_MODELING", "SHRINKAGE",
    "SOCP_OPTIMIZATION", "BACKTESTING", "COMPLETED"
  ];
  const idx = order.indexOf(this.pipelinePhase);
  return idx < 0 ? 0 : ((idx + 1) / order.length) * 100;
});
```

Dicionário em `portfolio-workspace-labels.ts` separado do store. Nunca inline em componentes — garante PT/EN swap e zero jargão acidental.

### J.1.3 — Nunca `$effect` para derivar — apenas para side-effects

```ts
// PROIBIDO
$effect(() => { this.phaseProgress = compute(this.pipelinePhase); });
```

Cria waterfall reativo + dependência circular. Rejeitar em review.

### J.1.4 — Debounce vs tickBuffer

SSE pipeline-level: ~5-15 eventos em 30-120s. Não precisa `createTickBuffer` (charter §3 é >10/s). Atualização direta basta. Se BACKTESTING emitir 100 bootstraps, bufferize com `requestAnimationFrame` — só se acontecer empiricamente.

### J.1.5 — Cleanup do stream

Três mecanismos concorrentes em L1527-1529 e L1673-1675. Manter todos:
1. `AbortController` com `signal` no `fetch()`.
2. `reader.cancel()` em terminal.
3. `finally { this._activeRunAbort = null; this.isConstructing = false; }`.

Adicional PR-A5: se componente desmontar mid-flight, cancelar:

```ts
$effect(() => {
  return () => workspace.cancelActiveRun();
});
```

`cancelActiveRun()` apenas chama `this._activeRunAbort?.abort()`. Cancel server-side só se contrato backend existir.

---

## J.2 — SSE consumption — contrato PR-A5

### J.2.1 — Endpoint, método, headers

```ts
const idempotencyKey = crypto.randomUUID();
this._activeIdempotencyKey = idempotencyKey;

const accepted = await api.post<BuildRunAccepted>(
  `/portfolios/${this.portfolioId}/build`,
  { /* payload conforme spec wealth-architect */ },
  {
    timeoutMs: 130_000,
    headers: { "Idempotency-Key": idempotencyKey },
  },
);
```

Verificar antes: `api.post()` em `$lib/api/client.ts` aceita headers custom? Se não, refactor pequeno é parte do PR-A5.

### J.2.2 — `Idempotency-Key` lifecycle

- Gerado no click "Run Build" (uma vez).
- Em `$state _activeIdempotencyKey: string | null`.
- NUNCA persistido em localStorage (`feedback_echarts_no_localstorage.md`). F5 = run novo; backend dedup via advisory lock + Redis.
- Reset em terminal event.
- Re-click ANTES de terminal: abort do anterior + nova key. 409 se backend detectar concorrência → toast.

### J.2.3 — Handling de 409

```ts
try {
  const accepted = await api.post(...);
} catch (err) {
  if (err.status === 409) {
    this.lastError = {
      action: "build",
      message: "Build em andamento para este portfolio",
      timestamp: Date.now(),
    };
    return null;
  }
  throw err;
}
```

UX: toast `"Build já em andamento. Aguarde a conclusão."` + disable do botão. Sem retry automático.

### J.2.4 — Parsing `data:` + buffer

Copiar verbatim de L1585-1626. Não reescrever. Apenas substituir `_applyRunEvent()` (L1685) pelo novo (J.2.5).

### J.2.5 — Dispatcher `_applyBuildEvent()` com `metrics`

```ts
private _applyBuildEvent(ev: BuildRunEvent) {
  const phase = ev.phase as PipelinePhase;

  if (phase && PIPELINE_PHASES.includes(phase)) {
    this.pipelinePhase = phase;
  }

  if (ev.metrics && phase) {
    this.phaseMetrics = {
      ...this.phaseMetrics,
      [phase]: { ...(this.phaseMetrics[phase] ?? {}), ...ev.metrics },
    };
  }

  if (phase === "SHRINKAGE" && typeof ev.metrics?.shrinkage_lambda === "number") {
    this.riskMetrics = {
      ...this.riskMetrics,
      shrinkageLambda: ev.metrics.shrinkage_lambda,
    };
  }
  if (phase === "SOCP_OPTIMIZATION" && ev.sub_phase) {
    this._applyOptimizerSubPhase(ev);
  }
  if (phase === "BACKTESTING" && typeof ev.metrics?.sharpe === "number") {
    this.backtestLive = {
      sharpe: ev.metrics.sharpe,
      maxDd: typeof ev.metrics.max_dd === "number" ? ev.metrics.max_dd : null,
    };
  }

  if (phase === "COMPLETED") {
    this.terminalState = "success";
    this.pipelinePhase = "COMPLETED";
  } else if (phase === "FAILED") {
    this.terminalState = "error";
    this.runError = ev.reason ?? "Build failed";
  }

  if (ev.message) this.sanitizedMessage = ev.message;
}
```

Crítico: `ev.metrics` é `Record<string, unknown>` — nunca `any`. Cada tab faz cast com guard `typeof === "number"`.

### J.2.6 — Re-conexão / fallback

Se SSE drop mid-flight, stream termina sem terminal event. Hoje (L1633-1637) seta `runPhase = "error"`. PR-A5:

1. Detectar `terminal === null` após `break`.
2. Polling fallback: `GET /jobs/{job_id}/status` com backoff (1s, 2s, 4s, max 30s).
3. Se polling retornar `completed` → `GET run_url`.
4. Se polling 404 / `failed` → erro.

Padrão a procurar: `pollJobStatus` ou equivalente. Se não existe, PR-A5 introduz `$lib/api/job-polling.ts`.

**Risco médio-alto:** vazamento de handles se usuário navegar. Use `$effect` com cleanup + `AbortController` dedicado. Spec deve listar como sub-task ou cortar escopo (MVP = "Conexão perdida. Recarregue a página.").

---

## J.3 — CascadeTimeline — refactor de dois níveis

### J.3.1 — Pipeline timeline NOVO (5 fases)

Não renomear. Criar:

```
frontends/wealth/src/lib/components/terminal/builder/
  PipelineTimeline.svelte       ← NOVO: FACTOR_MODELING → ... → COMPLETED
  CascadeTimeline.svelte        ← EXISTENTE: primary → ... → heuristic (sub-timeline do SOCP)
```

`PipelineTimeline` recebe `pipelinePhase` + `phaseMetrics` e renderiza 5 pillars. Hover/click em pillar abre popover com `phaseMetrics[phase]` formatado.

```ts
interface Props {
  currentPhase: PipelinePhase;
  phaseMetrics: Partial<Record<PipelinePhase, Record<string, unknown>>>;
  terminalState: "pending" | "success" | "error" | "cancelled";
  sanitizedMessage: string;
}
let { currentPhase, phaseMetrics, terminalState, sanitizedMessage }: Props = $props();
```

Estados visuais (copiar tokens de `CascadeTimeline.svelte:141-179`): `--terminal-status-success`, `--terminal-accent-amber`, `--terminal-status-error`.

### J.3.2 — Sub-timeline optimizer (existente)

Quando `currentPhase === "SOCP_OPTIMIZATION"`, renderizar `CascadeTimeline` inline dentro do pillar SOCP (ou em tab). NÃO muda — apenas renderizado condicionalmente.

### J.3.3 — Snippets para customização por pillar

Em vez de 5 `{#if phase === "X"}`:

```svelte
{#snippet pillar(phase: PipelinePhase, label: string)}
  <PipelinePillar
    {phase}
    {label}
    active={currentPhase === phase}
    metrics={phaseMetrics[phase]}
  />
{/snippet}

<div class="timeline">
  {@render pillar("FACTOR_MODELING", "Modelagem de Fatores")}
  {@render pillar("SHRINKAGE", "Regularização")}
  {@render pillar("SOCP_OPTIMIZATION", "Otimização")}
  {@render pillar("BACKTESTING", "Backtest")}
  {@render pillar("COMPLETED", "Concluído")}
</div>
```

Evita `{#each}` sem `(key)` estável.

---

## J.4 — Formatter discipline (ESLint-enforced)

`frontends/eslint.config.js` proíbe `.toFixed()`, `.toLocaleString()`, `Intl.NumberFormat`, `Intl.DateTimeFormat` inline.

Importar de `@investintell/ui` (verificar nome real em `packages/ui/package.json` — `@netz/ui` é alias histórico no CLAUDE.md):

```ts
import {
  formatNumber, formatCurrency, formatPercent,
  formatDate, formatDateTime, formatShortDate,
} from "@investintell/ui";
```

| Local | Campo | Formatter |
|---|---|---|
| `PipelineTimeline` popover (FACTOR_MODELING) | `kappa_sigma`, `pca_components_retained` | `formatNumber(v, 4)` / `formatNumber(v, 0)` |
| popover (SHRINKAGE) | `shrinkage_lambda` | `formatNumber(v, 4)` |
| popover (SOCP_OPTIMIZATION) | `objective_value`, `solve_time_ms` | `formatNumber(v, 6)` / `formatNumber(v, 0) + " ms"` |
| `RiskTab` | `volatility`, `cvar_95` | `formatPercent(v, 2)` |
| `StressTab` | `drawdown_pct` | `formatPercent(v, 2)` |
| `BacktestTab` | `sharpe`, `calmar` / `ann_return` | `formatNumber(v, 2)` / `formatPercent(v, 2)` |
| `WeightsTab` | pesos | `formatPercent(v, 2)` |
| `ActivationBar` | timestamp | `formatDateTime(v)` |

Se faltar formatter (ex.: `formatDurationMs` para "1.2s"): adicionar em `packages/ui/src/lib/formatters/` e exportar — não improvisar.

Gate ESLint: `pnpm lint` no frontend antes do PR.

---

## J.5 — Componentes @investintell/ui a reusar

Inventário esperado (confirmar `ls packages/ui/src/lib/components/`):

- **Badge** → terminalState pill (verde/vermelho/cinza)
- **Tooltip** → hover em pillar
- **Popover** → click em pillar abre `phaseMetrics`
- **Toast / Sonner** → 409, build completa, falha
- **Skeleton** → loading enquanto `pipelinePhase === "IDLE"` e isConstructing
- **Drawer** → opcional para StressTab fullscreen
- **Button** (32px pill, Urbanist — `feedback_design_direction.md`)

Se componente não existe e padrão pede: criar em `packages/ui` PRIMEIRO, em sub-commit. NUNCA fork em `frontends/wealth/src/lib/components/ui/`.

Tokens semânticos (zero hex): `bg-surface`, `bg-surface-strong`, `text-foreground`, `text-foreground-muted`, `border-border-subtle`, `text-status-positive/negative/neutral`. CSS bruto terminal: `var(--terminal-bg-panel)`, `var(--terminal-status-success)`, `var(--terminal-accent-amber)` (vistos em `CascadeTimeline.svelte:80-110`).

---

## J.6 — ECharts via svelte-echarts

Tabs com chart:
- **WeightsTab** → bar horizontal por ativo ou pie por block
- **BacktestTab** → line NAV + area drawdown
- **RiskTab** → bar volatilidade per fund + marcador regime-conditioned
- **StressTab** → bar comparativo por scenario

Specs institucionais:
- monospace ticks (`font-family: var(--terminal-font-mono)`)
- dim grid (`splitLine: { lineStyle: { color: 'var(--terminal-fg-muted)', opacity: 0.15 } }`)
- sem sombras
- tooltip monospace, sem border-radius exuberante
- série principal cor amarelo Netz

NUNCA Chart.js.

Risco: `svelte-echarts` vs Svelte 5 — `pnpm ls svelte-echarts`. Se warnings, ainda funciona. Se quebrar runtime, fallback `echarts` direto:

```svelte
<script>
  import * as echarts from "echarts";
  let container: HTMLDivElement;
  let chart: echarts.ECharts | null = null;

  $effect(() => {
    chart = echarts.init(container);
    chart.setOption(options);
    return () => chart?.dispose();
  });
</script>
<div bind:this={container} class="chart"></div>
```

---

## J.7 — State em memória (sem localStorage)

Tudo PR-A5 em `$state`:
- `_activeIdempotencyKey` → null após terminal
- `phaseMetrics` → reset em novo build
- `sanitizedMessage` → sobrescreve a cada evento
- `pipelinePhase`, `terminalState`

Preferências UI triviais (tab ativo) → URL query param via `$page.url.searchParams`. Zero localStorage / sessionStorage.

---

## J.8 — Layout cage

`+page.svelte` usa `calc(100vh-88px)` + `padding:24px` (`feedback_layout_cage_pattern.md`). PR-A5 NÃO altera o shell. Header fixo do `PipelineTimeline` usa `position: sticky; top: 0` dentro do container; NUNCA `flex min-h-0` (quebra o cage).

---

## J.9 — Regras Svelte 5

1. **Runes only**: `$state`, `$derived`, `$derived.by`, `$effect`, `$effect.pre`, `$props`, `$bindable`. Sem `let` reativo legacy, sem `$:`.
2. **Snippets** em vez de slots nomeados (`{#snippet}` + `{@render}`).
3. **`$bindable()`** para 2-way bind em forms.
4. **`$effect` cleanup obrigatório** para streams/timers/subs — retornar função.
5. **`(key)` em `{#each}`** sempre.
6. **MCP autofixer**: `npx @sveltejs/mcp svelte-autofixer` antes de finalizar componente novo/editado. Gate.
7. **Escape `$`** no terminal Windows: `\$props`, `\$state` em heredocs.
8. **Svelte MCP `list-sections` + `get-documentation`** antes de inventar API.

---

## J.10 — Testes

Honestidade: o projeto não tem hábito consolidado de testes unitários Svelte. Vitest existe na stack, cobertura baixa. NÃO introduzir Vitest no PR-A5 — custo alto, baixo ROI.

Priorizar Playwright (já no plano):
- E2E: click "Run Build" → 5 pillars passarem → asserta `terminalState === "success"`
- E2E 409: dois builds concorrentes, asserta toast + botão disabled
- E2E cancel: build, desmontar (navegar), asserta zero leak no console
- E2E idempotency: build, F5 mid-run, asserta novo run criado

Validação visual obrigatória (`feedback_visual_validation.md`): `pnpm dev:wealth`, logar, `/portfolio/builder`, build real contra backend local, screenshot de cada fase. Backend-only passing é insuficiente.

---

## J.11 — Triagem de risco por item

| Item | Risco | Justificativa |
|---|---|---|
| Switch endpoint `/construct` → `/build` | **Baixo** | search+replace em 1-2 sites + tipos |
| Header `Idempotency-Key` | **Baixo** | `crypto.randomUUID()` + campo no helper |
| Refactor `runPhase` → `pipelinePhase` | **Médio** | grep `runPhase` (15+ refs) antes de começar |
| `PipelineTimeline` novo | **Baixo-Médio** | CSS+snippets puro, espelha `CascadeTimeline` |
| Consumir `metrics` type-safe | **Médio** | guards por tab; fácil cair em `any` — review estrito |
| Fallback poll `/jobs/{id}/status` | **Médio-Alto** | módulo novo com cleanup; considerar cortar do PR-A5 |
| 409 toast | **Baixo** | patterns existem |
| Cancel server-side | **Alto** | depende de contrato backend; se não existir, NÃO prometer |
| Svelte 5 + svelte-echarts | **Baixo** | já em uso |
| Tanstack Table | **Alto** | `project_frontend_platform.md` registra breakage. Se WeightsTab usa, manter; se não, NÃO introduzir |

**Recomendação de escopo:**
- IN: endpoint switch, Idempotency-Key, refactor `pipelinePhase`, `_applyBuildEvent`, `PipelineTimeline`, metrics + guards, 409 toast, Playwright happy-path + 409
- OUT (PR-A6): fallback polling, cancel server-side, regressão visual por fase

---

## J.12 — Checklist Svelte 5 (pré-merge)

- [ ] `portfolio-workspace.svelte.ts` aponta para `/portfolios/{id}/build`, zero refs ao `/construct`
- [ ] `Idempotency-Key` enviado em todo POST `/build`
- [ ] `pipelinePhase: PipelinePhase` substitui `runPhase` em todos os componentes
- [ ] `PipelineTimeline.svelte` renderiza 5 fases sanitizadas, zero jargão
- [ ] `CascadeTimeline.svelte` (sub-timeline) renderiza apenas quando `pipelinePhase === "SOCP_OPTIMIZATION"`
- [ ] Zero `.toFixed()` / `.toLocaleString()` / `Intl.*` (`pnpm lint`)
- [ ] Zero `localStorage` / `sessionStorage` introduzidos
- [ ] Zero `EventSource` (manter `fetch + ReadableStream`)
- [ ] Todos `$effect` com cleanup quando subscrevem streams/timers
- [ ] Todos `{#each}` com `(key)`
- [ ] `npx @sveltejs/mcp svelte-autofixer` limpo
- [ ] 409 → toast + botão disabled
- [ ] Validação visual: screenshots das 5 fases num build real
- [ ] Playwright happy-path + 409
- [ ] Memory `project_phase4_builder_complete.md` atualizado com PR-A5

---

**Arquivos de referência:**

- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\state\portfolio-workspace.svelte.ts` (L115-205 types, L428-433 state, L1504-1718 runConstructJob + dispatcher)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\terminal\builder\CascadeTimeline.svelte` (template a espelhar para `PipelineTimeline`)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\wealth\src\lib\components\terminal\builder\RunControls.svelte` (click handler)
- `C:\Users\andre\projetos\netz-analysis-engine\frontends\eslint.config.js` (formatter discipline)
- `C:\Users\andre\projetos\netz-analysis-engine\packages\ui\` (formatters + components a reusar)
