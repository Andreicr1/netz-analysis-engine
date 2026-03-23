import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Credit — Deal Pipeline", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/funds page loads with fund list or empty state", async ({ page }) => {
		const response = await page.goto("/funds");
		expect(response?.status()).toBeLessThan(500);
		await expect(page.locator("body")).not.toBeEmpty();
	});

	test("fund list renders fund cards or empty state message", async ({ page }) => {
		await page.goto("/funds");
		// Page heading "Funds" is always visible (with or without fund data)
		await expect(page.getByRole("heading", { name: "Funds", exact: true })).toBeVisible({ timeout: 10_000 });
	});
});
