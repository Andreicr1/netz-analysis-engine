import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Admin — Configuration", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/config/credit page loads", async ({ page }) => {
		const response = await page.goto("/config/credit");
		expect(response?.status()).toBeLessThan(500);
	});

	test("/config/wealth page loads", async ({ page }) => {
		const response = await page.goto("/config/wealth");
		expect(response?.status()).toBeLessThan(500);
	});

	test("/inspect page loads", async ({ page }) => {
		const response = await page.goto("/inspect");
		expect(response?.status()).toBeLessThan(500);
	});

	test("/prompts/credit page loads", async ({ page }) => {
		const response = await page.goto("/prompts/credit");
		expect(response?.status()).toBeLessThan(500);
	});

	test("/prompts/wealth page loads", async ({ page }) => {
		const response = await page.goto("/prompts/wealth");
		expect(response?.status()).toBeLessThan(500);
	});
});
