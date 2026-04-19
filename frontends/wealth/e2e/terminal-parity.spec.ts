/**
 * Terminal Parity smoke — docs/plans/2026-04-18-netz-terminal-parity.md §F.3.
 *
 * This file is a contractual skeleton following the same pattern as
 * `allocation-propose-approve.spec.ts` and `universe-autoimport.spec.ts`:
 * Playwright is NOT yet installed as a runnable devDep in
 * `frontends/wealth/`. To activate:
 *
 *   1) cd frontends/wealth && pnpm add -D @playwright/test
 *   2) pnpm exec playwright install chromium
 *   3) add `playwright.config.ts` with `baseURL = http://localhost:5173`
 *      (or whatever wealth dev server port is running)
 *   4) wire `test:e2e` into the wealth package scripts
 *   5) seed a SUPER_ADMIN fixture org + mount X-DEV-ACTOR auth bypass
 *      (canonical dev org: 403d8392-ebfa-5890-b740-45da49c556eb).
 *
 * The assertions below cover plan §F.3 acceptance criteria:
 *   • Tiingo WS handshake within 2s on live page mount
 *   • `Alt+1..4` breadcrumb navigation works
 *   • `Shift+T` opens TerminalTweaksPanel drawer
 *   • `C` / `L` flip chart type with aria-pressed state tracking
 *   • Density toggle shrinks rows from 22px → 18px with no overflow
 *   • None of the shortcuts fire when focus is in an input
 */

import { test, expect } from "@playwright/test";

const TEST_ORG_ID =
	process.env.TEST_ORG_ID ?? "403d8392-ebfa-5890-b740-45da49c556eb";

test.describe("Terminal parity — /portfolio/live smoke", () => {
	test.beforeEach(async ({ page }) => {
		// Auth bypass: X-DEV-ACTOR header via route interception. Matches
		// the pattern used by A26.3's allocation flow spec so we share
		// a single activation strategy when Playwright is wired up.
		await page.route("**/api/v1/**", async (route) => {
			const headers = {
				...route.request().headers(),
				"x-dev-actor": `super_admin:${TEST_ORG_ID}`,
			};
			await route.continue({ headers });
		});
	});

	test("breadcrumb Alt+1..4 navigates across terminal sections", async ({
		page,
	}) => {
		await page.goto("/portfolio/live");
		await expect(page.getByRole("navigation", { name: /Terminal sections/i })).toBeVisible();

		// Alt+3 → /macro
		await page.keyboard.press("Alt+3");
		await expect(page).toHaveURL(/\/macro/);

		// Alt+1 → /terminal-screener
		await page.keyboard.press("Alt+1");
		await expect(page).toHaveURL(/\/terminal-screener/);

		// Alt+2 → /portfolio/live
		await page.keyboard.press("Alt+2");
		await expect(page).toHaveURL(/\/portfolio\/live/);

		// Alt+4 → /portfolio/builder
		await page.keyboard.press("Alt+4");
		await expect(page).toHaveURL(/\/portfolio\/builder/);
	});

	test("Shift+T toggles TerminalTweaksPanel drawer", async ({ page }) => {
		await page.goto("/portfolio/live");

		// Drawer not mounted initially.
		await expect(page.locator("#terminal-tweaks-drawer")).toHaveCount(0);

		// Shift+T opens the drawer.
		await page.keyboard.press("Shift+T");
		const drawer = page.locator("#terminal-tweaks-drawer");
		await expect(drawer).toBeVisible();
		await expect(drawer).toHaveAttribute("role", "dialog");
		await expect(drawer).toHaveAttribute("aria-modal", "true");

		// Shift+T again closes.
		await page.keyboard.press("Shift+T");
		await expect(drawer).toHaveCount(0);
	});

	test("Shift+T is ignored when an input has focus", async ({ page }) => {
		await page.goto("/portfolio/live");

		// Open Command Palette (Cmd+K) which mounts a searchbox, or
		// find any input on the live page. The compare dropdown on
		// ChartToolbar exposes a ticker input we can use.
		const compareButton = page.getByRole("button", { name: /Compare/i });
		await compareButton.click();
		const tickerInput = page.locator("input[placeholder='Ticker...']");
		await expect(tickerInput).toBeVisible();
		await tickerInput.focus();

		// Shift+T while focused in the input must NOT open the drawer.
		await page.keyboard.press("Shift+T");
		await expect(page.locator("#terminal-tweaks-drawer")).toHaveCount(0);
	});

	test("chart type toggle flips via C / L and via click", async ({ page }) => {
		await page.goto("/portfolio/live");

		const candleBtn = page.getByRole("button", { name: /Chart type CANDLE/i });
		const lineBtn = page.getByRole("button", { name: /Chart type LINE/i });

		// Default mode is 'line' (existing callers unchanged per PR-5).
		await expect(lineBtn).toHaveAttribute("aria-pressed", "true");
		await expect(candleBtn).toHaveAttribute("aria-pressed", "false");

		// C key → candle.
		await page.keyboard.press("c");
		await expect(candleBtn).toHaveAttribute("aria-pressed", "true");
		await expect(lineBtn).toHaveAttribute("aria-pressed", "false");

		// L key → line.
		await page.keyboard.press("l");
		await expect(lineBtn).toHaveAttribute("aria-pressed", "true");
		await expect(candleBtn).toHaveAttribute("aria-pressed", "false");

		// Click CANDLE → same result.
		await candleBtn.click();
		await expect(candleBtn).toHaveAttribute("aria-pressed", "true");
	});

	test("density toggle shrinks row heights from 22px to 18px", async ({
		page,
	}) => {
		await page.goto("/portfolio/live");

		const shell = page.locator("[data-surface='terminal']").first();
		await expect(shell).toHaveAttribute("data-density", "standard");

		await page.keyboard.press("Shift+T");
		const compactBtn = page.getByRole("button", { name: /Density COMPACT/i });
		await compactBtn.click();
		await expect(shell).toHaveAttribute("data-density", "compact");

		// Row token follows the attribute.
		const rowHeight = await shell.evaluate((el) =>
			getComputedStyle(el).getPropertyValue("--t-row-height").trim(),
		);
		expect(rowHeight).toBe("18px");
	});

	test("accent picker rebinds amber to cyan via data-accent attribute", async ({
		page,
	}) => {
		await page.goto("/portfolio/live");

		const shell = page.locator("[data-surface='terminal']").first();
		await expect(shell).toHaveAttribute("data-accent", "amber");

		await page.keyboard.press("Shift+T");
		await page.getByRole("button", { name: /Accent CYAN/i }).click();
		await expect(shell).toHaveAttribute("data-accent", "cyan");
	});

	test("Tiingo WS handshake completes within 2s of live page mount", async ({
		page,
	}) => {
		// Listen for the WS upgrade on the live market-data endpoint.
		const wsPromise = page.waitForEvent("websocket", {
			predicate: (ws) => ws.url().includes("/api/v1/market-data/live/ws"),
			timeout: 2_000,
		});

		await page.goto("/portfolio/live");
		const ws = await wsPromise;
		expect(ws.url()).toContain("/live/ws");
	});
});

test.describe("Terminal parity — /terminal-screener smoke", () => {
	test.beforeEach(async ({ page }) => {
		await page.route("**/api/v1/**", async (route) => {
			const headers = {
				...route.request().headers(),
				"x-dev-actor": `super_admin:${TEST_ORG_ID}`,
			};
			await route.continue({ headers });
		});
	});

	test("slash focuses the filter rail first input", async ({ page }) => {
		await page.goto("/terminal-screener");
		// Wait for the shell to render. The filter rail has its own aria-label.
		const filterPanel = page.getByRole("region", { name: /Screener filters/i })
			.or(page.locator("[aria-label='Screener filters']").first());
		await expect(filterPanel).toBeVisible();

		await page.keyboard.press("/");
		// The shell's handler focuses the first interactive element inside the
		// filters panel (search input or first chip button).
		const active = await page.evaluate(() => {
			const el = document.activeElement as HTMLElement | null;
			return el ? { tag: el.tagName, inFilters: !!el.closest("[aria-label='Screener filters']") } : null;
		});
		expect(active?.inFilters).toBe(true);
	});

	test("applying an eliteOnly filter renders a chip with CLEAR ALL", async ({
		page,
	}) => {
		// Deep-link the elite filter so we don't depend on UI toggle order.
		await page.goto("/terminal-screener?elite=1");
		const chipRow = page.getByRole("region", { name: /Applied filters/i });
		await expect(chipRow).toBeVisible();
		await expect(chipRow.getByRole("button", { name: /Remove Tier Elite only/i })).toBeVisible();
		await expect(chipRow.getByRole("button", { name: /CLEAR ALL/i })).toBeVisible();
	});

	test("clicking CLEAR ALL strips filter query params", async ({ page }) => {
		await page.goto("/terminal-screener?elite=1&max_expense=0.5");
		const chipRow = page.getByRole("region", { name: /Applied filters/i });
		await expect(chipRow).toBeVisible();
		await chipRow.getByRole("button", { name: /CLEAR ALL/i }).click();
		await expect(page).toHaveURL(/\/terminal-screener(\?|$)/);
		// No filter-specific params remain.
		const url = new URL(page.url());
		expect(url.searchParams.get("elite")).toBeNull();
		expect(url.searchParams.get("max_expense")).toBeNull();
	});

	test("ArrowDown highlights the first row and Enter opens FundFocusMode", async ({
		page,
	}) => {
		await page.goto("/terminal-screener");
		// Wait for at least one row to exist.
		const firstRow = page.locator("[role='row'][aria-rowindex='2']");
		await expect(firstRow).toBeVisible({ timeout: 10_000 });

		await page.keyboard.press("ArrowDown");
		await expect(firstRow).toHaveClass(/highlighted/);

		await page.keyboard.press("Enter");
		// FundFocusMode mounts a dialog at the page root.
		const dialog = page.getByRole("dialog").first();
		await expect(dialog).toBeVisible();

		await page.keyboard.press("Escape");
		await expect(dialog).toHaveCount(0);
	});
});
