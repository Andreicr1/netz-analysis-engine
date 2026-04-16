/**
 * PR-A6 Section H.3 — universe auto-import E2E.
 *
 * NOTE: Playwright is not yet installed in frontends/wealth (no devDep,
 * no playwright.config, no Playwright runner). This file is the
 * contractual skeleton promised by the PR prompt. To activate:
 *
 *   1) cd frontends/wealth && pnpm add -D @playwright/test
 *   2) pnpm exec playwright install chromium
 *   3) add `playwright.config.ts` with baseURL = http://localhost:5173
 *   4) wire `pnpm test:e2e` into the wealth package scripts
 *   5) seed a SUPER_ADMIN fixture org + mount X-DEV-ACTOR auth bypass
 *
 * The assertions below match the contract the PR-A6 verification matrix
 * requires (add/update/skip metrics, candidate drawer populated, build
 * success, stress panel populated with 4 scenarios).
 */

import { test, expect } from '@playwright/test';

const TEST_ORG_ID = process.env.TEST_ORG_ID ?? '403d8392-ebfa-5890-b740-45da49c556eb';

test.describe('PR-A6 universe auto-import', () => {
	test('manual run from admin UI populates instruments_org and unblocks builder', async ({ page }) => {
		// Step 1: Login as admin (Clerk or X-DEV-ACTOR bypass)
		await page.goto('/');
		// TODO: drive Clerk sign-in or set localStorage token

		// Step 2: Navigate to admin universe screen
		await page.goto('/admin/universe');

		// Step 3: Trigger a manual run for the test org
		await page.getByRole('button', { name: /run auto-import/i }).click();
		await page
			.getByLabel(/org id/i)
			.fill(TEST_ORG_ID);
		await page
			.getByLabel(/reason/i)
			.fill('e2e_autoimport_verification');
		await page.getByRole('button', { name: /^run$/i }).click();

		// Step 4: Metrics card refreshes — added >= 3000 (policy: ≥ USD 200M AUM + 5Y NAV)
		const addedBadge = page.getByTestId('metrics-added');
		await expect(addedBadge).toHaveText(/^[3-9],?\d{3}$/, { timeout: 30_000 });

		// Step 5: Navigate to builder and create a fresh model portfolio
		await page.goto('/portfolios');
		await page.getByRole('button', { name: /new portfolio/i }).click();
		await page.getByLabel(/name/i).fill('e2e-autoimport-check');
		await page.getByRole('button', { name: /create/i }).click();

		// Step 6: Candidate drawer has at least 100 rows
		await page.getByRole('tab', { name: /candidates/i }).click();
		const candidateRows = page.locator('[data-testid="candidate-row"]');
		await expect(candidateRows.first()).toBeVisible({ timeout: 15_000 });
		await expect(await candidateRows.count()).toBeGreaterThanOrEqual(100);

		// Step 7: Build with default mandate — expect solver success
		await page.getByRole('button', { name: /build portfolio/i }).click();
		await expect(page.getByText(/solver_status[:\s]+optimal/i)).toBeVisible({
			timeout: 60_000,
		});

		// Step 8: Stress panel shows 4 scenarios
		await page.getByRole('tab', { name: /stress/i }).click();
		const scenarioRows = page.locator('[data-testid="stress-scenario-row"]');
		await expect(scenarioRows).toHaveCount(4);
	});

	test('second manual run is idempotent (added=0, updated ≈ first-run.added)', async ({
		request,
	}) => {
		const run = async (reason: string) =>
			request.post('/api/admin/universe/auto-import/run', {
				data: { org_id: TEST_ORG_ID, reason },
				headers: { 'X-DEV-ACTOR': 'super-admin' },
			});

		const run1 = await run('e2e_idempotency_run1');
		expect(run1.status()).toBe(200);
		const r1 = await run1.json();

		const run2 = await run('e2e_idempotency_run2');
		expect(run2.status()).toBe(200);
		const r2 = await run2.json();

		expect(r2.added).toBe(0);
		expect(r2.skipped).toBe(r1.skipped);
		expect(r2.updated).toBe(r1.added);
	});
});
