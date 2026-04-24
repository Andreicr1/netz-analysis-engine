# Sprint S2-Builder Phase 3 — Playwright Happy-Path E2E

**Date:** 2026-04-24
**Branch:** `feat/builder-phase3-playwright`
**Base:** `main` (after PR #274 merge)
**Scope:** Playwright infrastructure + happy-path spec + SSE fixture
**Estimated:** 1 day (single PR)

---

## 0. Pre-Flight

```bash
git checkout main && git pull origin main
git checkout -b feat/builder-phase3-playwright
```

---

## 1. Playwright Infrastructure Setup

The root `playwright.config.ts` already exists with projects `credit` (5173) and `wealth` (5174). The terminal frontend (`frontends/terminal/`) has NO Playwright yet. Follow the skeleton instructions in `frontends/terminal/e2e/x2-route-smoke.spec.ts`.

### 1a. Install Playwright in terminal frontend

```bash
cd frontends/terminal
pnpm add -D @playwright/test
pnpm exec playwright install chromium
```

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

Add to `"scripts"`:

```json
"test:e2e": "playwright test",
"test:e2e:ui": "playwright test --ui"
```

---

## 2. Auth Bypass Helper

Create `frontends/terminal/e2e/helpers/auth.ts`:

```typescript
import type { Page } from "@playwright/test";

/**
 * Canonical dev org — see project_canonical_dev_org memory.
 * X-DEV-ACTOR header bypasses Clerk JWT in dev mode.
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

This pattern is already used in `frontends/terminal/e2e/x2-route-smoke.spec.ts` (line 41-47).

---

## 3. SSE Fixture

Create `frontends/terminal/e2e/fixtures/cascade-stream-clean.ts`:

This file exports a function that returns an SSE text body simulating a complete `winner_signal=optimal` construction run. The event sequence and payload shapes come from `construction_run_executor.py` and `portfolio-workspace.svelte.ts:_applyBuildEvent`.

```typescript
/**
 * Simulates a complete, successful (phase_1_succeeded) construction SSE stream.
 *
 * Event order mirrors construction_run_executor.py:
 *   run_started → optimizer_started → prefilter_dedup_completed →
 *   shrinkage_completed → optimizer_phase_complete ×3 →
 *   cascade_telemetry_completed → stress_started → run_succeeded
 *
 * Humanized event names match humanize_event_type() server-side convention.
 * Frontend dispatches on BOTH `type` (humanized) and `raw_type` (original).
 */

const RUN_ID = "e2e-run-00000000-0000-0000-0000-000000000001";

interface SseFrame {
  event?: string;
  data: Record<string, unknown>;
}

const frames: SseFrame[] = [
  {
    data: {
      type: "Run started",
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
      type: "Prefilter dedup completed",
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
      type: "Cascade telemetry completed",
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
          {
            phase: "phase_1_ru_max_return",
            status: "succeeded",
            solver: "CLARABEL",
            wall_ms: 340,
            objective_value: 0.0922,
            cvar_within_limit: true,
          },
          {
            phase: "phase_2_ru_robust",
            status: "skipped",
            solver: null,
            wall_ms: 0,
            objective_value: null,
            cvar_within_limit: null,
          },
          {
            phase: "phase_3_min_cvar",
            status: "skipped",
            solver: null,
            wall_ms: 0,
            objective_value: null,
            cvar_within_limit: null,
          },
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

/**
 * Serialize frames into SSE text/event-stream format.
 * Each frame is `data: {json}\n\n`.
 */
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

## 4. Builder Happy-Path Spec

Create `frontends/terminal/e2e/builder-happy-path.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";
import { loginAsAdmin, DEV_ORG_ID } from "./helpers/auth";
import { buildCleanSseStream, RUN_ID } from "./fixtures/cascade-stream-clean";

/**
 * Builder happy path: select portfolio → run construction → view cascade →
 * click through tabs → activate.
 *
 * SSE stream is mocked via Playwright route interception to avoid needing
 * a running backend with real data. API calls that the builder makes
 * (list portfolios, get construction run, activate) are also intercepted.
 */

// ── Mock data ────────────────────────────────────────────────────

const PORTFOLIO_ID = "e2e-portfolio-00000000-0000-0000-0000-000000000001";
const PROFILE = "balanced";

const MOCK_PORTFOLIO = {
  id: PORTFOLIO_ID,
  profile: PROFILE,
  display_name: "E2E Balanced Portfolio",
  description: "Playwright happy-path fixture",
  status: "draft",
  state: "draft",
  inception_date: "2026-01-01",
  allowed_actions: ["ACTIVATE"],
  fund_selection_schema: null,
  composition: [],
  metadata: {},
};

const MOCK_CONSTRUCTION_RUN = {
  id: RUN_ID,
  portfolio_id: PORTFOLIO_ID,
  status: "succeeded",
  winner_signal: "optimal",
  cascade_telemetry: {
    phase_attempts: [
      {
        phase: "phase_1_ru_max_return",
        status: "succeeded",
        solver: "CLARABEL",
        wall_ms: 340,
        objective_value: 0.0922,
        cvar_within_limit: true,
      },
      {
        phase: "phase_2_ru_robust",
        status: "skipped",
        solver: null,
        wall_ms: 0,
        objective_value: null,
        cvar_within_limit: null,
      },
      {
        phase: "phase_3_min_cvar",
        status: "skipped",
        solver: null,
        wall_ms: 0,
        objective_value: null,
        cvar_within_limit: null,
      },
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
    operator_signal: {
      kind: "feasible",
      binding: null,
    },
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

const MOCK_ACTIVATED_PORTFOLIO = {
  ...MOCK_PORTFOLIO,
  status: "live",
  state: "live",
};

// ── Route interception ───────────────────────────────────────────

async function setupApiMocks(page: import("@playwright/test").Page) {
  // Auth bypass
  await loginAsAdmin(page);

  // GET /model-portfolios — list
  await page.route("**/api/v1/model-portfolios", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([MOCK_PORTFOLIO]),
      });
    } else {
      await route.continue();
    }
  });

  // GET /model-portfolios/:id — single portfolio
  await page.route(`**/api/v1/model-portfolios/${PORTFOLIO_ID}`, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_PORTFOLIO),
      });
    } else {
      await route.continue();
    }
  });

  // POST /portfolios/:id/build — trigger build, return job_id
  await page.route(`**/api/v1/portfolios/${PORTFOLIO_ID}/build`, async (route) => {
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "e2e-job-001",
        stream_url: `/api/v1/jobs/e2e-job-001/stream`,
        status: "accepted",
      }),
    });
  });

  // GET /jobs/:id/stream — SSE stream (mocked)
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

  // GET /construction-runs/:id — load persisted run after SSE completes
  await page.route(`**/api/v1/construction-runs/${RUN_ID}**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_CONSTRUCTION_RUN),
    });
  });

  // GET /model-portfolios/:id/latest-run — latest construction run
  await page.route(`**/api/v1/model-portfolios/${PORTFOLIO_ID}/latest-run**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_CONSTRUCTION_RUN),
    });
  });

  // POST /model-portfolios/:id/activate — activation
  await page.route(`**/api/v1/model-portfolios/${PORTFOLIO_ID}/activate`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_ACTIVATED_PORTFOLIO),
    });
  });

  // GET /allocation/:profile/strategic — strategic allocation (needed by workspace)
  await page.route(`**/api/v1/allocation/${PROFILE}/strategic**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  // GET /portfolio/profiles/:profile/latest-proposal — no proposal yet
  await page.route(`**/api/v1/portfolio/profiles/${PROFILE}/latest-proposal**`, async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "No proposal found" }),
    });
  });

  // Catch-all for other wealth API calls — return empty/200 to avoid 404 noise
  await page.route("**/api/v1/**", async (route) => {
    // Only intercept GETs that haven't been caught above
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    } else {
      await route.continue();
    }
  });
}

// ── Tests ────────────────────────────────────────────────────────

test.describe("Builder happy path — Phase 1 succeeded", () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test("portfolio is auto-selected on page load", async ({ page }) => {
    await page.goto("/portfolio/builder");
    // PortfolioPicker renders the portfolio name
    await expect(page.getByText("E2E Balanced Portfolio")).toBeVisible();
  });

  test("run construction → cascade timeline → activation", async ({ page }) => {
    await page.goto("/portfolio/builder");

    // Wait for portfolio to load
    await expect(page.getByText("E2E Balanced Portfolio")).toBeVisible();

    // ── Step 1: Click "Run Construction" ──────────────────────
    const runBtn = page.getByRole("button", { name: /run construction/i });
    await expect(runBtn).toBeVisible();
    await runBtn.click();

    // ── Step 2: Cascade timeline appears with phase results ───
    // After SSE completes, the CascadeTimelineCore renders 3 phases.
    // Phase 1 should show "succeeded" status.
    await expect(page.getByText("Phase 1")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("succeeded")).toBeVisible();

    // Coverage bar should render (89%)
    await expect(page.getByText("89%")).toBeVisible();

    // Winner signal badge should render (optimal → translated label)
    await expect(
      page.getByText(/alocação ótima/i),
    ).toBeVisible();

    // ── Step 3: Run button transitions to "Complete" ──────────
    await expect(
      page.getByRole("button", { name: /complete/i }),
    ).toBeVisible({ timeout: 10_000 });

    // ── Step 4: ActivationBar appears ─────────────────────────
    // For winner_signal="optimal", no degraded gate — button is enabled.
    const activateBtn = page.getByRole("button", {
      name: /send to compliance/i,
    });
    await expect(activateBtn).toBeVisible({ timeout: 5_000 });
    await expect(activateBtn).toBeEnabled();

    // ── Step 5: Click activate → ConsequenceDialog ────────────
    await activateBtn.click();

    // Dialog appears asking to type "ACTIVATE"
    const dialog = page.getByRole("dialog", { name: /activate portfolio/i });
    await expect(dialog).toBeVisible();

    // Type the confirmation word
    const input = dialog.getByRole("textbox");
    await input.fill("ACTIVATE");

    // Confirm button should now be enabled
    const confirmBtn = dialog.getByRole("button", { name: /confirm/i });
    await expect(confirmBtn).toBeEnabled();
    await confirmBtn.click();

    // ── Step 6: Success banner ────────────────────────────────
    await expect(
      page.getByText(/portfolio activated/i),
    ).toBeVisible({ timeout: 5_000 });

    // Link to live workbench
    await expect(page.getByRole("link", { name: /live workbench/i })).toBeVisible();
  });
});
```

**CRITICAL implementation notes:**

1. The route patterns above (`**/api/v1/portfolios/...`, `**/api/v1/model-portfolios/...`, etc.) must match the ACTUAL fetch URLs the frontend uses. Before writing the final spec, **grep the workspace and API client for actual fetch paths** and adjust mock routes accordingly. Key files:
   - `packages/ii-terminal-core/src/lib/state/portfolio-workspace.svelte.ts` — all API calls
   - `packages/ii-terminal-core/src/lib/api/` — API client base paths

2. The SSE stream is delivered as a single fulfilled body (all frames at once). This is the simplest approach. If the frontend's `ReadableStream` parser requires chunked delivery, switch to Playwright's `route.fulfill` with a `ReadableStream` body that drips frames with small delays (50ms between frames).

3. The `page.route` catch-all at the bottom must be registered LAST — Playwright matches routes in registration order, most-specific first.

4. Selector strategy: prefer `getByRole` and `getByText` over CSS classes. The builder uses BEM classes (`ab-btn--activate`, `rc-btn`, `ctc__phase-status`) but these are implementation details. Use accessible selectors:
   - Run button: `getByRole("button", { name: /run construction/i })`
   - Activate: `getByRole("button", { name: /send to compliance/i })`
   - Dialog: `getByRole("dialog", { name: /activate portfolio/i })`
   - Phase labels: `getByText("Phase 1")` etc.

5. If any selector doesn't match, **open the dev server** (`pnpm dev` in `frontends/terminal/`) and inspect the actual DOM to find the correct text/role. Do not guess — verify.

---

## 5. Verification

### 5a. Typecheck

```bash
cd frontends/terminal
pnpm exec tsc --noEmit --project tsconfig.json
```

The spec file uses standard `@playwright/test` imports — no Svelte compilation needed.

### 5b. Run the spec

**Requires a running backend** only for the SvelteKit dev server to start (SSR may call load functions). If SvelteKit load functions make API calls during SSR, those will also need mocking. Two approaches:

- **Option A (preferred):** If the builder page's `+page.ts` load function makes API calls, mock them via a test-only API proxy or `page.route` (already handled above — Playwright intercepts ALL requests including SSR fetches from the browser).
- **Option B:** Start the backend with `make serve` and let SSR calls hit real endpoints (slower, requires DB).

Run:

```bash
cd frontends/terminal
pnpm test:e2e --headed
```

Watch the test execute visually. Fix any selector mismatches.

### 5c. Verify selectors against live DOM

Before committing, start the dev server and manually navigate to `/portfolio/builder`. Confirm:

1. The "Run Construction" button text matches `runBtn` selector
2. After a real run (or by inspecting the cascade component), phase labels say "Phase 1 · Max Return" (the `getByText("Phase 1")` partial match should work)
3. The ActivationBar button says "SEND TO COMPLIANCE" (verify in `ActivationBar.svelte:120`)
4. The ConsequenceDialog has `role="dialog"` with `aria-label="Activate Portfolio"` (verify in `ConsequenceDialog.svelte:86-88`)
5. The confirm button text — check `ConsequenceDialog.svelte` for the exact label

---

## 6. Acceptance Criteria

- [ ] `frontends/terminal/playwright.config.ts` exists and targets port 5175
- [ ] `pnpm test:e2e` runs from `frontends/terminal/` without import errors
- [ ] `builder-happy-path.spec.ts` passes with `--headed` (visual confirmation)
- [ ] SSE fixture replays all 10 events in correct order
- [ ] Cascade timeline renders 3 phase cards after stream completes
- [ ] ActivationBar appears with "SEND TO COMPLIANCE" enabled (no degraded gate for `optimal`)
- [ ] ConsequenceDialog type-to-confirm flow works
- [ ] Success banner with "Portfolio activated" appears
- [ ] No hardcoded waits (`page.waitForTimeout`) — only `waitForSelector` / `expect().toBeVisible()`

---

## 7. Commit

```bash
git add frontends/terminal/playwright.config.ts \
        frontends/terminal/e2e/ \
        frontends/terminal/package.json \
        frontends/terminal/pnpm-lock.yaml

git commit -m "test(builder): Playwright happy-path e2e spec (S2 Phase 3 D14)

Scaffold Playwright infrastructure for ii-terminal frontend.
Happy-path spec: select portfolio → run construction (mocked SSE) →
view cascade timeline → activate → type ACTIVATE confirmation.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

Then push and create PR:

```bash
git push -u origin feat/builder-phase3-playwright
gh pr create --title "test(builder): S2 Phase 3 — Playwright happy-path" --body "## Summary
- Scaffold Playwright infrastructure for ii-terminal frontend
- Happy-path e2e: select portfolio → run → cascade → activate
- SSE fixture with 10 realistic events (phase_1_succeeded stream)
- All API routes mocked via page.route()

## Test plan
- [ ] \`pnpm test:e2e\` passes in frontends/terminal/
- [ ] Visual confirmation with \`--headed\`
- [ ] No flaky selectors (all use getByRole/getByText)
"
```

---

## 8. Known Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| SvelteKit SSR load functions call APIs before page.route intercepts | page.route intercepts ALL browser requests including SSR fetches; if server-side `fetch` in `+page.server.ts` bypasses browser, add a `+page.ts` (client-side) load or mock at the HTTP level |
| ReadableStream parser needs chunked delivery, not single body | Switch to chunked route.fulfill: split SSE body into frames, delay 50ms each, deliver via ReadableStream |
| Selectors break because component text changes | All selectors use partial regex matches (`/run construction/i`); grep component files for exact text before finalizing |
| Workspace loads data from multiple endpoints on mount | The catch-all `page.route("**/api/v1/**")` returns `[]` for unhandled GETs — prevents 404 errors from unmocked endpoints |
| `pnpm-lock.yaml` at root may need regeneration after adding dep | Run `pnpm install` at repo root to sync the lockfile |

---

## 9. NOT in Scope (deferred per plan)

- `cascade-phase-3-fallback.spec.ts` (degraded run path) — post-merge backlog
- `block-coverage-insufficient.spec.ts` (hard-block path) — post-merge backlog
- Seed SQL fixture (`fixtures/builder-dev-org.sql`) — only needed for non-mocked runs; mocked approach is simpler
- CI integration — wiring `test:e2e` into GitHub Actions workflow is a separate infra PR
