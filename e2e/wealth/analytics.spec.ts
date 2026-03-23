import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Wealth — Analytics & Risk", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/analytics page loads", async ({ page }) => {
		const response = await page.goto("/analytics");
		expect(response?.status()).toBeLessThan(500);
	});

	test("/risk page loads", async ({ page }) => {
		const response = await page.goto("/risk");
		expect(response?.status()).toBeLessThan(500);
	});

	test("/exposure page loads", async ({ page }) => {
		const response = await page.goto("/exposure");
		expect(response?.status()).toBeLessThan(500);
	});

	test("/macro page loads", async ({ page }) => {
		const response = await page.goto("/macro");
		expect(response?.status()).toBeLessThan(500);
	});

	test("/universe page loads", async ({ page }) => {
		const response = await page.goto("/universe");
		expect(response?.status()).toBeLessThan(500);
	});

	test("/content page loads", async ({ page }) => {
		const response = await page.goto("/content");
		expect(response?.status()).toBeLessThan(500);
	});
});
