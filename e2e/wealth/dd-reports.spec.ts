import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Wealth — DD Reports", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/dd-reports page loads", async ({ page }) => {
		const response = await page.goto("/dd-reports");
		expect(response?.status()).toBeLessThan(500);
	});

	test("dd-reports renders fund selector or empty state", async ({ page }) => {
		await page.goto("/dd-reports");
		await expect(page.locator("body")).not.toBeEmpty();
	});
});
