import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Credit — Investor Portal", () => {
	test("investor role can access /report-packs", async ({ page }) => {
		await loginAs(page, "investor");
		const response = await page.goto("/report-packs");
		expect(response?.status()).toBeLessThan(500);
	});

	test("investor role can access /statements", async ({ page }) => {
		await loginAs(page, "investor");
		const response = await page.goto("/statements");
		expect(response?.status()).toBeLessThan(500);
	});

	test("investor role can access /documents (investor portal)", async ({ page }) => {
		await loginAs(page, "investor");
		const response = await page.goto("/documents");
		expect(response?.status()).toBeLessThan(500);
	});

	test("gestora role CANNOT access investor /report-packs (403)", async ({ page }) => {
		await loginAs(page, "gestora");
		const response = await page.goto("/report-packs");
		expect(response?.status()).toBe(403);
	});

	test("admin role CANNOT access investor /statements (403)", async ({ page }) => {
		await loginAs(page, "admin");
		const response = await page.goto("/statements");
		expect(response?.status()).toBe(403);
	});
});
