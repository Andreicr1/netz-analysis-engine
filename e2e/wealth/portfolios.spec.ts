import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Wealth — Portfolios", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/portfolios page loads", async ({ page }) => {
		const response = await page.goto("/portfolios");
		expect(response?.status()).toBeLessThan(500);
	});

	test("portfolios renders content or empty state", async ({ page }) => {
		await page.goto("/portfolios");
		await expect(page.locator("body")).not.toBeEmpty();
	});

	test("/model-portfolios page loads", async ({ page }) => {
		const response = await page.goto("/model-portfolios");
		expect(response?.status()).toBeLessThan(500);
	});
});
