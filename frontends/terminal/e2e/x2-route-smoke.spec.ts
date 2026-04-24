/**
 * X2 route-copy smoke — docs/plans/2026-04-19-ii-terminal-extraction.md §X2.
 *
 * This file follows the contractual-skeleton pattern used by parity smoke
 * specs. Playwright is not yet installed as a runnable devDep in
 * frontends/terminal/. To activate:
 *
 *   1) cd frontends/terminal && pnpm add -D @playwright/test
 *   2) pnpm exec playwright install chromium
 *   3) add playwright.config.ts with baseURL = http://localhost:5175
 *   4) wire `test:e2e` into the ii-terminal package scripts
 *   5) seed a SUPER_ADMIN fixture org + mount X-DEV-ACTOR auth bypass
 *      (canonical dev org: 403d8392-ebfa-5890-b740-45da49c556eb).
 *
 * Acceptance: every route copied in X2 renders a non-empty body. This
 * is a smoke gate only — deeper integration lives in later sprints.
 */

import { test, expect } from "@playwright/test";

const TEST_ORG_ID =
	process.env.TEST_ORG_ID ?? "403d8392-ebfa-5890-b740-45da49c556eb";

// X2 route inventory — see §X2 source→target table.
const X2_ROUTES: ReadonlyArray<string> = [
	"/live",
	"/screener",
	"/macro",
	"/allocation",
	"/portfolio/builder",
	"/dd",
	"/alerts",
];

test.describe("II Terminal X2 route copy — smoke", () => {
	test.beforeEach(async ({ page }) => {
		// Auth bypass: X-DEV-ACTOR header via route interception. Mirrors
		// the pattern used by wealth's allocation and terminal-parity
		// specs so both apps share a single activation strategy once
		// Playwright is wired up.
		await page.route("**/api/v1/**", async (route) => {
			const headers = {
				...route.request().headers(),
				"x-dev-actor": `super_admin:${TEST_ORG_ID}`,
			};
			await route.continue({ headers });
		});
	});

	for (const path of X2_ROUTES) {
		test(`renders ${path}`, async ({ page }) => {
			const response = await page.goto(path, {
				waitUntil: "domcontentloaded",
			});
			expect(response?.status() ?? 0).toBeLessThan(400);

			// Body must have at least one element — catches blank-page
			// regressions where SSR crashes but shell still renders.
			const childCount = await page.locator("body *").count();
			expect(childCount).toBeGreaterThan(0);
		});
	}

	test("root redirects to /live (F1)", async ({ page }) => {
		const response = await page.goto("/");
		expect(response?.url()).toContain("/live");
	});
});
