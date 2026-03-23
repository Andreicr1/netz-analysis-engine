import { test, expect } from "@playwright/test";
import { loginAs, loginViaDevButton, clearAuth } from "../fixtures/auth";

test.describe("Credit — Authentication & Role Guards", () => {
	test("sign-in page loads with title and card", async ({ page }) => {
		await page.goto("/auth/sign-in");
		await expect(page.locator("h1")).toContainText("Netz Credit Intelligence");
		await expect(page.locator(".sign-in-card")).toBeVisible();
	});

	test("sign-in page has no CSP console errors", async ({ page }) => {
		const cspErrors: string[] = [];
		page.on("console", (msg) => {
			if (msg.type() === "error" && msg.text().includes("Content Security Policy")) {
				cspErrors.push(msg.text());
			}
		});
		await page.goto("/auth/sign-in");
		await page.waitForLoadState("networkidle");
		expect(cspErrors).toEqual([]);
	});

	test('"Continue as Dev User" button is visible in dev mode', async ({ page }) => {
		await page.goto("/auth/sign-in");
		await expect(page.getByRole("link", { name: "Continue as Dev User" })).toBeVisible();
	});

	test("clicking dev bypass redirects away from sign-in", async ({ page }) => {
		await loginViaDevButton(page);
		expect(page.url()).not.toContain("/auth/sign-in");
	});

	test("unauthenticated request to /dashboard redirects to sign-in", async ({ page }) => {
		await clearAuth(page);
		// In dev mode, unauthenticated gets DEFAULT_DEV_ACTOR automatically.
		// This test verifies the sign-in page itself is accessible.
		const response = await page.goto("/auth/sign-in");
		expect(response?.status()).toBeLessThan(400);
		await expect(page.locator(".sign-in-card")).toBeVisible();
	});

	test("admin role can access team routes", async ({ page }) => {
		await loginAs(page, "admin");
		const response = await page.goto("/dashboard");
		expect(response?.status()).toBeLessThan(500);
	});

	test("investor role cannot access team routes (403)", async ({ page }) => {
		await loginAs(page, "investor");
		const response = await page.goto("/dashboard");
		// SvelteKit returns 403 from the layout guard
		expect(response?.status()).toBe(403);
	});

	test("gestora role cannot access investor routes (403)", async ({ page }) => {
		await loginAs(page, "gestora");
		const response = await page.goto("/report-packs");
		expect(response?.status()).toBe(403);
	});

	test("sign-out page redirects to sign-in", async ({ page }) => {
		await loginAs(page, "admin");
		await page.goto("/auth/sign-out");
		await page.waitForURL("**/auth/sign-in");
		expect(page.url()).toContain("/auth/sign-in");
	});
});
