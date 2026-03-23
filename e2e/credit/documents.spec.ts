import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Credit — Documents", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/funds page loads for document navigation", async ({ page }) => {
		const response = await page.goto("/funds");
		expect(response?.status()).toBeLessThan(500);
	});
});
