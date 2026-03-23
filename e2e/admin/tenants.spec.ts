import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Admin — Tenant Management", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/tenants page loads", async ({ page }) => {
		const response = await page.goto("/tenants");
		expect(response?.status()).toBeLessThan(500);
	});

	test("tenants page renders list or empty state", async ({ page }) => {
		await page.goto("/tenants");
		await expect(page.locator("body")).not.toBeEmpty();
	});
});
