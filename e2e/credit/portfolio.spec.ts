import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Credit — Portfolio", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/funds page loads for portfolio navigation", async ({ page }) => {
		const response = await page.goto("/funds");
		expect(response?.status()).toBeLessThan(500);
	});
});
