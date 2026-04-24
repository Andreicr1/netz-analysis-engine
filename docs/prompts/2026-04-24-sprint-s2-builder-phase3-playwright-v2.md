# Sprint S2-Builder Phase 3 — Playwright Happy-Path E2E (v2)

**Date:** 2026-04-24
**Branch:** `feat/builder-phase3-playwright` (ALREADY CREATED from `65201fb8` = `origin/main` after PR #274 merge; ready for you to push work to)
**Supersedes:** v1 (`2026-04-24-sprint-s2-builder-phase3-playwright.md`) after senior-advisor validation against live codebase.
**Estimated:** 1 day (single PR)

---

## 0. Read this before you do anything

**Six corrections versus v1 — all baked into this document. Do not cross-reference v1 while implementing.**

1. **`/portfolio/builder` in the terminal frontend is a 307 redirect** to `/allocation/{profile}?tab=portfolio`. The actual builder surface lives at [frontends/terminal/src/routes/allocation/[profile]/+page.svelte](frontends/terminal/src/routes/allocation/[profile]/+page.svelte) rendering `PortfolioTabContent.svelte`. The spec's `page.goto("/portfolio/builder")` is fine (Playwright follows redirects) but the test must expect the final URL `/allocation/moderate?tab=portfolio` (or another profile).

2. **ActivationBar button label is "Activate Portfolio", NOT "SEND TO COMPLIANCE".** See [ActivationBar.svelte:49-50](frontends/wealth/src/lib/components/terminal/builder/ActivationBar.svelte). Selector must be `/activate portfolio/i`.

3. **ConsequenceDialog confirm button label is "Activate", NOT "Confirm".** See [ConsequenceDialog.svelte:126](frontends/wealth/src/lib/components/terminal/builder/ConsequenceDialog.svelte). Use an exact-anchor regex `/^activate$/i` on the button **inside the dialog** so it does not also match the outer ActivationBar "Activate Portfolio" button. `within(dialog).getByRole("button", { name: /^activate$/i })` is the safe pattern.

4. **Winner signal translated label is "Alocação ótima dentro do limite de risco"**, not just "alocação ótima". See [metric-translators.ts:330-334](packages/ii-terminal-core/src/lib/utils/metric-translators.ts). Substring regex `/alocação ótima/i` still matches, so v1's selector is OK. Keep it.

5. **Three fixture event `type` humanizations in v1 did NOT match the backend's `humanize_event_type()` in [schemas/sanitized.py:283-313](backend/app/domains/wealth/schemas/sanitized.py).** Corrected in §3 below. The frontend dispatcher reads `raw_type` first (workspace:2029) so functionally both work, but we want contract fidelity.

6. **CRITICAL — Playwright `page.route` does NOT intercept SvelteKit SSR fetches.** SSR `+page.server.ts` runs in the Node process and uses `createServerApiClient(token)` which talks HTTP directly to the backend — those calls bypass the browser and therefore bypass Playwright route interception. v1's Option A ("Playwright intercepts ALL requests including SSR fetches from the browser") is wrong.

   **Correct strategy (established pattern, mirrors `x2-route-smoke.spec.ts`):**
   - **Backend MUST be running** (`make serve` on :8000) for SSR loaders to populate `portfolios[]` and `strategic`.
   - Use `X-DEV-ACTOR` header injection via `page.route("**/api/v1/**", ...)` so the real backend accepts the requests without Clerk JWT — this is a **continue-with-headers** handler, not a fulfill.
   - Mock only the **client-side post-hydration flows** that must be deterministic: `POST /portfolios/{id}/build`, `GET /api/v1/jobs/{job_id}/stream`, `GET /construction-runs/{run_id}`, `POST /model-portfolios/{id}/activate`. These are triggered by user action after mount, so `page.route` intercepts them correctly.
   - Let SSR hit real endpoints. The test picks the **first portfolio in the picker** (whatever is seeded in the canonical dev org `403d8392-ebfa-5890-b740-45da49c556eb`) — do **not** hard-code a portfolio name.

---

## 1. Playwright infrastructure setup

The root `playwright.config.ts` already exists with projects `credit` (5173) and `wealth` (5174). The terminal frontend has NO Playwright yet and has a dormant skeleton spec `frontends/terminal/e2e/x2-route-smoke.spec.ts` waiting for activation.

### 1a. Install

```bash
cd frontends/terminal
pnpm add -D @playwright/test
pnpm exec playwright install chromium
```

Then at repo root: `pnpm install` (to sync lockfile).

### 1b. Create `frontends/terminal/playwright.config.ts`

```typescript
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  use: {
    baseURL: "http://localhost:5175",
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },
  webServer: {
    command: "pnpm dev --port 5175",
    port: 5175,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```

### 1c. Add scripts to `frontends/terminal/package.json`

```json
"test:e2e": "playwright test",
"test:e2e:ui": "playwright test --ui"
```

---

## 2. Auth bypass helper

Create `frontends/terminal/e2e/helpers/auth.ts`:

```typescript
import type { Page } from "@playwright/test";

/**
 * Canonical dev org (see CLAUDE.md).
 * X-DEV-ACTOR header bypasses Clerk JWT in dev mode when backend runs
 * with CLERK_SECRET_KEY absent or DEV mode enabled.
 */
export const DEV_ORG_ID = "403d8392-ebfa-5890-b740-45da49c556eb";

export async function loginAsAdmin(page: Page): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const headers = {
      ...route.request().headers(),
      "x-dev-actor": `super_admin:${DEV_ORG_ID}`,
    };
    await route.continue({ headers });
  });
}
```

Exact pattern used by `x2-route-smoke.spec.ts` (lines 41-47). Keep identical.

---

## 3. SSE fixture

Create `frontends/terminal/e2e/fixtures/cascade-stream-clean.ts`:

```typescript
/**
 * Simulates a complete, successful (phase_1_succeeded, winner_signal=optimal)
 * construction SSE stream.
 *
 * Event order mirrors construction_run_executor.py. Humanized `type` values
 * match EVENT_TYPE_LABELS in backend/app/domains/wealth/schemas/sanitized.py
 * (verified 2026-04-24). Frontend dispatches on raw_type first
 * (portfolio-workspace.svelte.ts:2029), but we still keep `type` in sync
 * with backend convention for contract fidelity.
 */

const RUN_ID = "e2e-run-00000000-0000-0000-0000-000000000001";

interface SseFrame {
  event?: string;
  data: Record<string, unknown>;
}

const frames: SseFrame[] = [
  {
    data: {
      type: "Construction started",           // ← v2 fix (v1 said "Run started")
      raw_type: "run_started",
      phase: "STARTED",
      message: "Construction run started",
      progress: 0.0,
      run_id: RUN_ID,
    },
  },
  {
    data: {
      type: "Optimizer started",
      raw_type: "optimizer_started",
      phase: "FACTOR_MODELING",
      message: "Factor model estimation",
      progress: 0.1,
    },
  },
  {
    data: {
      type: "Universe pre-filter completed", // ← v2 fix (v1 said "Prefilter dedup completed")
      raw_type: "prefilter_dedup_completed",
      phase: "FACTOR_MODELING",
      message: "Universe deduplication complete",
      progress: 0.15,
      metrics: {
        universe_size_before_dedup: 42,
        universe_size_after_dedup: 38,
        n_clusters: 4,
        pair_corr_p50: 0.32,
        pair_corr_p95: 0.71,
      },
    },
  },
  {
    data: {
      type: "Shrinkage completed",
      raw_type: "shrinkage_completed",
      phase: "SHRINKAGE",
      message: "Covariance estimation complete",
      progress: 0.3,
      metrics: {
        kappa_sample: 12400,
        kappa_final: 5800,
        kappa_factor_fallback: null,
        covariance_source: "sample",
      },
    },
  },
  {
    data: {
      type: "Optimizer phase completed",
      raw_type: "optimizer_phase_complete",
      phase: "SOCP_OPTIMIZATION",
      message: "Phase 1: Max Return completed",
      progress: 0.5,
      metrics: {
        phase: "phase_1_ru_max_return",
        phase_label: "Phase 1 · Max Return",
        status: "succeeded",
        objective_value: 0.0922,
      },
    },
  },
  {
    data: {
      type: "Optimizer phase completed",
      raw_type: "optimizer_phase_complete",
      phase: "SOCP_OPTIMIZATION",
      message: "Phase 2: Robust completed",
      progress: 0.6,
      metrics: {
        phase: "phase_2_ru_robust",
        phase_label: "Phase 2 · Robust",
        status: "skipped",
        objective_value: null,
      },
    },
  },
  {
    data: {
      type: "Optimizer phase completed",
      raw_type: "optimizer_phase_complete",
      phase: "SOCP_OPTIMIZATION",
      message: "Phase 3: Min Tail Risk completed",
      progress: 0.7,
      metrics: {
        phase: "phase_3_min_cvar",
        phase_label: "Phase 3 · Min Tail Risk",
        status: "skipped",
        objective_value: null,
      },
    },
  },
  {
    data: {
      type: "Optimizer cascade summary",      // ← v2 fix (v1 said "Cascade telemetry completed")
      raw_type: "cascade_telemetry_completed",
      phase: "SOCP_OPTIMIZATION",
      message: "Cascade resolved",
      progress: 0.75,
      metrics: {
        cascade_summary: "phase_1_succeeded",
        winner_signal: "optimal",
        operator_signal: {
          kind: "feasible",
          binding: null,
          message_key: "feasible",
          min_achievable_cvar: 0.032,
          user_cvar_limit: 0.05,
        },
        min_achievable_cvar: 0.032,
        achievable_return_band: { lower: 0.068, upper: 0.094 },
        operator_message: {
          title: "Allocation within risk budget",
          body: "The portfolio was optimised for maximum return within your CVaR limit.",
          severity: "info",
          action_hint: null,
        },
        coverage: {
          pct_covered: 0.89,
          hard_fail: false,
          n_total_blocks: 18,
          n_covered_blocks: 16,
          missing_blocks: ["alt_commodities", "fi_em_hard_currency"],
        },
        phase_attempts: [
          { phase: "phase_1_ru_max_return", status: "succeeded", solver: "CLARABEL", wall_ms: 340, objective_value: 0.0922, cvar_within_limit: true },
          { phase: "phase_2_ru_robust", status: "skipped", solver: null, wall_ms: 0, objective_value: null, cvar_within_limit: null },
          { phase: "phase_3_min_cvar", status: "skipped", solver: null, wall_ms: 0, objective_value: null, cvar_within_limit: null },
        ],
      },
    },
  },
  {
    data: {
      type: "Stress tests started",
      raw_type: "stress_started",
      phase: "BACKTESTING",
      message: "Running stress scenarios",
      progress: 0.85,
    },
  },
  {
    data: {
      type: "Construction succeeded",
      raw_type: "run_succeeded",
      phase: "COMPLETED",
      message: "Construction complete",
      progress: 1.0,
      run_id: RUN_ID,
      status: "succeeded",
      metrics: { wall_clock_ms: 8400 },
    },
  },
];

export function buildCleanSseStream(): string {
  return frames
    .map((f) => {
      const lines: string[] = [];
      if (f.event) lines.push(`event: ${f.event}`);
      lines.push(`data: ${JSON.stringify(f.data)}`);
      lines.push("");
      return lines.join("\n");
    })
    .join("\n");
}

export { RUN_ID };
```

---

## 4. Builder happy-path spec

Create `frontends/terminal/e2e/builder-happy-path.spec.ts`:

```typescript
import { test, expect, type Page } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";
import { buildCleanSseStream, RUN_ID } from "./fixtures/cascade-stream-clean";

/**
 * Builder happy path for phase_1_succeeded / winner_signal=optimal run.
 *
 * Strategy (see v2 prompt §0.6):
 *   - Backend MUST be running (`make serve`) because SSR loaders on
 *     /allocation/[profile]/+page.server.ts call it directly and cannot
 *     be intercepted by page.route.
 *   - X-DEV-ACTOR header injection authenticates browser-side fetches.
 *   - Mock only post-hydration flows (build / SSE / run fetch / activate).
 *   - Do not hard-code portfolio name — pick the first one in the picker.
 */

const MOCK_CONSTRUCTION_RUN = {
  id: RUN_ID,
  status: "succeeded",
  winner_signal: "optimal",
  cascade_telemetry: {
    phase_attempts: [
      { phase: "phase_1_ru_max_return", status: "succeeded", solver: "CLARABEL", wall_ms: 340, objective_value: 0.0922, cvar_within_limit: true },
      { phase: "phase_2_ru_robust", status: "skipped", solver: null, wall_ms: 0, objective_value: null, cvar_within_limit: null },
      { phase: "phase_3_min_cvar", status: "skipped", solver: null, wall_ms: 0, objective_value: null, cvar_within_limit: null },
    ],
    cascade_summary: "phase_1_succeeded",
    winner_signal: "optimal",
    coverage: {
      pct_covered: 0.89,
      hard_fail: false,
      n_total_blocks: 18,
      n_covered_blocks: 16,
      missing_blocks: ["alt_commodities", "fi_em_hard_currency"],
    },
    operator_message: {
      title: "Allocation within risk budget",
      body: "The portfolio was optimised for maximum return within your CVaR limit.",
      severity: "info",
      action_hint: null,
    },
    operator_signal: { kind: "feasible", binding: null },
    min_achievable_cvar: 0.032,
    achievable_return_band: { lower: 0.068, upper: 0.094 },
  },
  weights: [
    { instrument_id: "i1", block_id: "eq_us_large", weight: 0.25, ticker: "SPY" },
    { instrument_id: "i2", block_id: "fi_us_treasury", weight: 0.35, ticker: "TLT" },
    { instrument_id: "i3", block_id: "eq_intl_dev", weight: 0.20, ticker: "EFA" },
    { instrument_id: "i4", block_id: "fi_us_ig", weight: 0.20, ticker: "LQD" },
  ],
  stress_results: [],
  advisor_narrative: null,
  created_at: "2026-04-24T12:00:00Z",
};

async function setupMocks(page: Page): Promise<void> {
  // 1. Auth bypass first — continue-with-headers for everything.
  await loginAsAdmin(page);

  // 2. Intercept the build trigger — return a stream_url pointing at the mocked SSE endpoint.
  //    Path matches portfolio-workspace.svelte.ts:1868 — POST /portfolios/{id}/build
  await page.route("**/api/v1/portfolios/*/build", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "e2e-job-001",
        stream_url: "/api/v1/jobs/e2e-job-001/stream",
        status: "accepted",
      }),
    });
  });

  // 3. Mocked SSE stream — whole body fulfilled at once.
  //    If the browser parser needs chunked delivery, switch to a ReadableStream
  //    body that drips frames (see §6 Known Risks).
  await page.route("**/api/v1/jobs/e2e-job-001/stream", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "keep-alive",
      },
      body: buildCleanSseStream(),
    });
  });

  // 4. Persisted run fetch after SSE completes.
  await page.route(`**/api/v1/construction-runs/${RUN_ID}*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_CONSTRUCTION_RUN),
    });
  });

  // 5. Activation — return portfolio with status=live.
  await page.route("**/api/v1/model-portfolios/*/activate", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        // Minimum viable shape — the UI only needs status/state/id.
        id: "IGNORED_MATCHES_PORTFOLIO_SELECTED",
        status: "live",
        state: "live",
      }),
    });
  });
}

test.describe("Builder happy path — phase_1_succeeded / winner=optimal", () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test("run construction → cascade timeline → activation flow", async ({ page }) => {
    // Goes to the redirect, which resolves to /allocation/{profile}?tab=portfolio.
    await page.goto("/portfolio/builder");

    // Wait for URL to settle on the destination.
    await page.waitForURL(/\/allocation\/(moderate|conservative|growth)\?tab=portfolio/, {
      timeout: 15_000,
    });

    // ── 1. A portfolio is auto-selected by the workspace (portfolios[0]). ──
    //    The PortfolioPicker renders its name somewhere visible. We don't
    //    hard-code a name — instead we wait for the Run Construction button
    //    to be present, which only happens after a portfolio is bound.
    const runBtn = page.getByRole("button", { name: /run construction/i });
    await expect(runBtn).toBeVisible({ timeout: 15_000 });
    await expect(runBtn).toBeEnabled();

    // ── 2. Click Run Construction. SSE stream flows via the mocked handler. ──
    await runBtn.click();

    // ── 3. Cascade timeline renders phase cards. ──
    await expect(page.getByText(/phase 1/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/succeeded/i).first()).toBeVisible();

    // Coverage bar renders 89% (Math.round(0.89*100) — CascadeTimelineCore.svelte:171).
    await expect(page.getByText("89%")).toBeVisible();

    // Winner signal translated to "Alocação ótima dentro do limite de risco".
    await expect(page.getByText(/alocação ótima/i)).toBeVisible();

    // ── 4. ActivationBar appears enabled (no degraded gate for optimal). ──
    const activateBtn = page.getByRole("button", { name: /activate portfolio/i });
    await expect(activateBtn).toBeVisible({ timeout: 10_000 });
    await expect(activateBtn).toBeEnabled();
    await activateBtn.click();

    // ── 5. ConsequenceDialog opens; type-to-confirm with the literal word ACTIVATE. ──
    const dialog = page.getByRole("dialog", { name: /activate portfolio/i });
    await expect(dialog).toBeVisible();

    await dialog.getByRole("textbox").fill("ACTIVATE");

    // The confirm button lives INSIDE the dialog and is labeled "Activate"
    // (or "Activating..." during submit). Scope to the dialog to avoid
    // matching the outer ActivationBar button.
    const confirmBtn = dialog.getByRole("button", { name: /^activate$/i });
    await expect(confirmBtn).toBeEnabled();
    await confirmBtn.click();

    // ── 6. Post-activation confirmation. ──
    //    Either an inline banner or the page state changes. Assert on any of
    //    the plausible confirmation copies. Confirm the exact string in the
    //    DOM before finalizing — §5c below.
    await expect(
      page.getByText(/portfolio activated|status.*live/i),
    ).toBeVisible({ timeout: 10_000 });
  });
});
```

---

## 5. Verification before opening a PR

### 5a. Typecheck

```bash
cd frontends/terminal
pnpm exec tsc --noEmit --project tsconfig.json
```

### 5b. Run the spec with a live backend

**This is mandatory before committing. Do not open the PR if the spec doesn't pass locally.**

In one terminal:
```bash
make serve            # backend on :8000
```

In another:
```bash
cd frontends/terminal
pnpm test:e2e --headed
```

Watch the test execute visually. You should see:
- redirect from /portfolio/builder to /allocation/{profile}?tab=portfolio
- a portfolio bound in the workspace
- Run Construction clicked → phase cards appear → winner badge green
- Activate button enabled → dialog → confirm → success state

### 5c. Selector audit against live DOM

Selectors in this document are derived from code inspection, not live DOM. Before committing:

1. Start `make serve` + `pnpm dev --port 5175` in `frontends/terminal`.
2. Open `http://localhost:5175/portfolio/builder` in a browser and sign in as super admin.
3. For each selector below, right-click → Inspect → confirm the text/role matches the selector:

| Selector | Must match (copy this EXACT text from DOM if different) |
|---|---|
| `/run construction/i` | `RunConstructionButton.svelte` text content |
| `/phase 1/i` | First phase card in cascade timeline |
| `/89%/` (exact string) | Coverage bar percentage |
| `/alocação ótima/i` | Winner badge label |
| `/activate portfolio/i` | ActivationBar main button |
| `role=dialog, name=/activate portfolio/i` | ConsequenceDialog aria-label |
| Inside dialog: `/^activate$/i` on a button | Dialog confirm button |
| `/portfolio activated\|status.*live/i` | Post-activation banner |

If ANY selector doesn't match exactly, update the spec with the actual text **before** committing. Do not guess.

---

## 6. Known risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Playwright does NOT intercept SvelteKit SSR fetches | Backend running + X-DEV-ACTOR is the path. See §0.6. |
| Frontend's `ReadableStream` SSE parser needs chunked delivery, not a single body | If single-body fulfill doesn't trigger `_applyBuildEvent` calls, switch to a streaming body: `await route.fulfill({ body: new ReadableStream(...) })` that enqueues frames with 50ms between each. Detect the problem by watching console for missing event logs. |
| Portfolio picker auto-selects a portfolio we don't know the name of | Don't assert on portfolio name — assert on presence of the Run Construction button, which is bound only after a portfolio is loaded. |
| No dev portfolio seeded for canonical org → picker is empty | Verify at least one model portfolio exists for org `403d8392-ebfa-5890-b740-45da49c556eb`. If empty, seed manually via `POST /model-portfolios` before running the spec (document this in the PR body). |
| `pnpm-lock.yaml` at root needs regeneration after adding `@playwright/test` | Run `pnpm install` at repo root after the filter install. |
| `x2-route-smoke.spec.ts` was a skeleton — will it run now? | Yes — after §1 it activates automatically. If you don't want to run it in this PR, the simplest fix is to add `test.describe.skip(...)` wrapping it, with a TODO referencing a follow-up issue. Otherwise fix any breakage too. |
| Confirm button in dialog also matches outer ActivationBar button | Always scope via `dialog.getByRole(...)` — never call `page.getByRole("button", { name: /activate/i })` directly. |

---

## 7. Commit + PR

```bash
git add frontends/terminal/playwright.config.ts \
        frontends/terminal/e2e/helpers/ \
        frontends/terminal/e2e/fixtures/ \
        frontends/terminal/e2e/builder-happy-path.spec.ts \
        frontends/terminal/package.json \
        pnpm-lock.yaml

git commit -m "$(cat <<'EOF'
test(builder): Playwright happy-path e2e (S2 Phase 3)

Activates Playwright in frontends/terminal/ and ships one deterministic
end-to-end spec covering the successful winner_signal=optimal path:
portfolio auto-select → run construction (real build trigger, mocked SSE
+ persisted run) → cascade timeline renders 3 phase cards → ActivationBar
enabled → ConsequenceDialog type-to-confirm → live status asserted.

Architecture:
- page.route intercepts only post-hydration client flows (build / SSE /
  run fetch / activate). SSR loaders hit the real backend (page.route
  cannot intercept SvelteKit server-side fetches) with X-DEV-ACTOR
  injection for authz.
- SSE fixture event labels aligned with backend humanize_event_type().
- All selectors use getByRole / getByText with regex — no CSS classes.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"

git push -u origin feat/builder-phase3-playwright

gh pr create --title "test(builder): S2 Phase 3 — Playwright happy-path" --body "$(cat <<'EOF'
## Summary
- Activates Playwright in the ii-terminal frontend (first spec for this app)
- Happy-path e2e: select portfolio → run → cascade timeline → activate
- SSE fixture with 10 events aligned to backend `humanize_event_type()`
- Post-hydration flows mocked via `page.route`; SSR loaders hit the real backend via `X-DEV-ACTOR`

## Test plan
- [ ] `pnpm test:e2e --headed` passes locally with `make serve` running
- [ ] No hard-coded waits (only `expect().toBeVisible` + `waitForURL`)
- [ ] Selectors audited against live DOM (see §5c of the dispatch prompt)
- [ ] x2-route-smoke.spec.ts also runs (or is explicitly skipped with a TODO)

## Follow-ups (not in this PR)
- Degraded / fallback spec (`cascade-phase-3-fallback.spec.ts`)
- Hard-block / insufficient coverage spec (`block-coverage-insufficient.spec.ts`)
- CI wiring (separate infra PR)
EOF
)"
```

---

## 8. Acceptance criteria

- [ ] `frontends/terminal/playwright.config.ts` targets port 5175
- [ ] `pnpm test:e2e` runs from `frontends/terminal/` without import errors
- [ ] `builder-happy-path.spec.ts` passes with `--headed` when backend is running
- [ ] SSE fixture replays all 10 events in correct order and `cascade-phase-3` status matches `winner_signal=optimal`
- [ ] Cascade timeline renders 3 phase cards after stream completes
- [ ] ActivationBar button is enabled (no degraded gate for `optimal`)
- [ ] ConsequenceDialog type-to-confirm flow works with literal string `ACTIVATE`
- [ ] Post-activation success state asserted
- [ ] No hardcoded `page.waitForTimeout`
- [ ] Typecheck passes (`pnpm exec tsc --noEmit`)

---

## 9. Not in scope (deferred)

- `cascade-phase-3-fallback.spec.ts` (degraded path)
- `block-coverage-insufficient.spec.ts` (hard-block path)
- CI integration in `.github/workflows/`
- Any fixture SQL — we use real backend + real seeded dev org
