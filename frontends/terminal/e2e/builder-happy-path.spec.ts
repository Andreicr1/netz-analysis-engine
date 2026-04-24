import { test, expect, type Page } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";
import { buildCleanSseStream, RUN_ID } from "./fixtures/cascade-stream-clean";

/**
 * Builder happy path for phase_1_succeeded / winner_signal=optimal run.
 *
 * Strategy:
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

  // 1b. Approval gate — workspace-approval.svelte.ts checks has_active_approval
  //     before allowing runBuildJob(). Return approved so the build gate passes.
  await page.route("**/api/v1/portfolio/profiles/*/strategic-allocation", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        has_active_approval: true,
        last_approved_at: "2026-04-24T00:00:00Z",
        last_approved_by: "dev-user",
        cvar_limit: 0.075,
        profile: "moderate",
      }),
    });
  });

  // 2. Intercept the build trigger — POST /portfolios/{id}/build
  await page.route("**/portfolios/*/build", async (route) => {
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

  // 4. Persisted run fetch — GET /model-portfolios/{id}/runs/{runId}
  await page.route(`**/model-portfolios/*/runs/${RUN_ID}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_CONSTRUCTION_RUN),
    });
  });

  // 5. Activation — POST /model-portfolios/{id}/transitions { action: "activate" }
  await page.route("**/model-portfolios/*/transitions", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "e2e-portfolio-id",
        display_name: "Limit PCT Test Portfolio",
        state: "live",
        status: "live",
        profile: "moderate",
        fund_selection_schema: { funds: [] },
        created_at: "2026-04-24T00:00:00Z",
      }),
    });
  });

  // 6. Portfolio refresh — GET /model-portfolios/{id} (bare, no sub-path).
  //    After SSE completes, workspace refreshes the portfolio model.
  await page.route("**/model-portfolios/*", async (route) => {
    const url = route.request().url();
    if (route.request().method() !== "GET") return route.fallback();
    // Sub-paths (/runs/, /transitions, /calibration, etc.) should fall through.
    const pathAfterModelPortfolios = url.split("/model-portfolios/")[1] ?? "";
    if (pathAfterModelPortfolios.includes("/")) return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: pathAfterModelPortfolios.split("?")[0],
        display_name: "Limit PCT Test Portfolio",
        state: "constructed",
        status: "constructed",
        profile: "moderate",
        fund_selection_schema: { funds: [] },
        created_at: "2026-04-24T00:00:00Z",
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
    //    Wait for the Run Construction button to be present and enabled,
    //    which only happens after a portfolio is bound to the workspace.
    const runBtn = page.getByRole("button", { name: /run construction/i });
    await expect(runBtn).toBeVisible({ timeout: 15_000 });
    await expect(runBtn).toBeEnabled({ timeout: 15_000 });

    // ── 2. Click Run Construction. SSE stream flows via the mocked handler. ──
    await runBtn.click();

    // ── 3. Cascade timeline renders phase cards. ──
    await expect(page.getByText(/phase 1/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/succeeded/i).first()).toBeVisible();

    // Coverage bar renders 89%.
    await expect(page.getByText("89%")).toBeVisible();

    // Winner signal translated to "Alocação ótima dentro do limite de risco".
    await expect(page.getByText(/alocação ótima/i)).toBeVisible();

    // ── 4. ActivationBar appears — button is "SEND TO COMPLIANCE". ──
    const sendBtn = page.getByRole("button", { name: /send to compliance/i });
    await expect(sendBtn).toBeVisible({ timeout: 10_000 });
    await expect(sendBtn).toBeEnabled();
    await sendBtn.click();

    // ── 5. ConsequenceDialog opens; type-to-confirm with the literal word ACTIVATE. ──
    const dialog = page.getByRole("dialog", { name: /activate portfolio/i });
    await expect(dialog).toBeVisible();

    await dialog.getByRole("textbox").fill("ACTIVATE");

    // The confirm button inside the dialog is labeled "Activate".
    const confirmBtn = dialog.getByRole("button", { name: /^activate$/i });
    await expect(confirmBtn).toBeEnabled();
    await confirmBtn.click();

    // ── 6. Post-activation confirmation banner. ──
    await expect(
      page.getByText(/portfolio activated/i),
    ).toBeVisible({ timeout: 10_000 });
  });
});
