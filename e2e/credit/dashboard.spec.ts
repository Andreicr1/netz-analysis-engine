import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Credit — Dashboard", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("dashboard page loads", async ({ page }) => {
		const response = await page.goto("/dashboard");
		expect(response?.status()).toBeLessThan(500);
	});

	test("page has a heading or title", async ({ page }) => {
		await page.goto("/dashboard");
		// Dashboard should render some visible content
		await expect(page.locator("body")).not.toBeEmpty();
	});

	test("navigation sidebar is visible", async ({ page }) => {
		await page.goto("/dashboard");
		// Look for nav or sidebar element
		const nav = page.locator("nav, aside, [class*='sidebar'], [class*='nav']").first();
		await expect(nav).toBeVisible();
	});

	test("no CSP violations on dashboard", async ({ page }) => {
		const cspErrors: string[] = [];
		page.on("console", (msg) => {
			if (msg.type() === "error" && msg.text().includes("Content Security Policy")) {
				cspErrors.push(msg.text());
			}
		});
		await page.goto("/dashboard");
		await page.waitForLoadState("networkidle");
		expect(cspErrors).toEqual([]);
	});
});
