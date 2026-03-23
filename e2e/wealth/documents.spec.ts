import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Wealth — Documents", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/documents page loads", async ({ page }) => {
		const response = await page.goto("/documents");
		expect(response?.status()).toBeLessThan(500);
	});

	test("documents renders list or empty state", async ({ page }) => {
		await page.goto("/documents");
		await expect(page.locator("body")).not.toBeEmpty();
	});

	test("/documents/upload page loads", async ({ page }) => {
		const response = await page.goto("/documents/upload");
		expect(response?.status()).toBeLessThan(500);
	});
});
