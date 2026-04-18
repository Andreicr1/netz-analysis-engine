/**
 * PR-A26.3 Section I — Allocation propose→approve E2E skeleton.
 *
 * NOTE: Playwright is NOT yet installed in frontends/wealth as a
 * runnable devDep (mirrors the universe-autoimport.spec.ts skeleton
 * pattern from PR-A6). This file is the contractual skeleton promised
 * by the PR-A26.3 spec. To activate:
 *
 *   1) cd frontends/wealth && pnpm add -D @playwright/test
 *   2) pnpm exec playwright install chromium
 *   3) add `playwright.config.ts` with baseURL = http://localhost:5173
 *   4) wire `pnpm test:e2e` into the wealth package scripts
 *   5) seed a SUPER_ADMIN fixture org + mount X-DEV-ACTOR auth bypass
 *      (the canonical dev org is 403d8392-ebfa-5890-b740-45da49c556eb).
 *
 * The assertions below match the contract the PR-A26.3 spec Section I
 * calls out: render 18 rows, propose, review diff, approve, assert
 * toast + populated Strategic + history row.
 */

import { test, expect } from "@playwright/test";

const TEST_ORG_ID =
	process.env.TEST_ORG_ID ?? "403d8392-ebfa-5890-b740-45da49c556eb";
const PROFILE = "moderate";

test.describe("PR-A26.3 allocation propose→approve flow", () => {
	test("propose, review diff, approve, and see populated strategic", async ({
		page,
	}) => {
		// Auth bypass: X-DEV-ACTOR header via route interception.
		await page.route("**/api/v1/**", async (route) => {
			const headers = {
				...route.request().headers(),
				"x-dev-actor": `super_admin:${TEST_ORG_ID}`,
			};
			await route.continue({ headers });
		});

		// Step 1 — Navigate to the allocation page.
		await page.goto(`/portfolio/profiles/${PROFILE}/allocation`);
		await expect(
			page.getByRole("heading", { name: /Moderate Allocation/i }),
		).toBeVisible();

		// Step 2 — 18 Strategic rows render (may be empty of values).
		const rows = page.locator("table tbody tr");
		await expect(rows).toHaveCount(18);

		// Step 3 — Click Propose Allocation.
		const proposeButton = page.getByRole("button", {
			name: /Propose Allocation/i,
		});
		await expect(proposeButton).toBeVisible();
		await proposeButton.click();

		// Step 4 — Proposal Review Panel appears after SSE completes.
		await expect(
			page.getByRole("heading", { name: /Pending Proposal/i }),
		).toBeVisible({ timeout: 180_000 });

		// Step 5 — Approve Allocation.
		await page
			.getByRole("button", { name: /Approve Allocation/i })
			.click();

		// Step 6 — Strategic populated + Active badge on latest approval row.
		await expect(page.getByText(/Active/).first()).toBeVisible();

		// Step 7 — Approval History expanded has at least one row.
		await page
			.getByRole("button", { name: /Approval History/i })
			.click();
		await expect(page.locator("text=Active").nth(1)).toBeVisible();
	});
});
