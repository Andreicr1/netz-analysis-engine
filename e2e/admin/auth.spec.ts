import { test, expect } from "@playwright/test";
import { loginAs, loginViaDevButton } from "../fixtures/auth";

test.describe("Admin — Authentication & Role Guards", () => {
	test("sign-in page loads", async ({ page }) => {
		await page.goto("/auth/sign-in");
		await expect(page.locator(".sign-in-card")).toBeVisible();
	});

	test('"Continue as dev admin" button visible in dev mode', async ({ page }) => {
		await page.goto("/auth/sign-in");
		await expect(page.getByRole("link", { name: "Continue as dev admin" })).toBeVisible();
	});

	test("dev bypass with default admin role can access /health", async ({ page }) => {
		await loginAs(page, "admin");
		const response = await page.goto("/health");
		expect(response?.status()).toBeLessThan(500);
	});

	test("super_admin role can access /health", async ({ page }) => {
		await loginAs(page, "super_admin");
		const response = await page.goto("/health");
		expect(response?.status()).toBeLessThan(500);
	});

	test("investor role is redirected to sign-in with error", async ({ page }) => {
		await loginAs(page, "investor");
		// /health is public in admin guard — use /tenants to test admin role guard
		await page.goto("/tenants");
		expect(page.url()).toContain("/auth/sign-in");
		expect(page.url()).toContain("error=unauthorized");
	});

	test("gestora role is redirected to sign-in with error", async ({ page }) => {
		await loginAs(page, "gestora");
		await page.goto("/tenants");
		expect(page.url()).toContain("/auth/sign-in");
		expect(page.url()).toContain("error=unauthorized");
	});

	test("no CSP violations on sign-in page", async ({ page }) => {
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
});
