import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Wealth — Fund Screener", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/screener page loads", async ({ page }) => {
		const response = await page.goto("/screener");
		expect(response?.status()).toBeLessThan(500);
	});

	test("screener renders content (table or empty state)", async ({ page }) => {
		await page.goto("/screener");
		await expect(page.locator("body")).not.toBeEmpty();
	});

	test("no CSP violations on screener", async ({ page }) => {
		const cspErrors: string[] = [];
		page.on("console", (msg) => {
			if (msg.type() === "error" && msg.text().includes("Content Security Policy")) {
				cspErrors.push(msg.text());
			}
		});
		await page.goto("/screener");
		await page.waitForLoadState("networkidle");
		expect(cspErrors).toEqual([]);
	});
});
