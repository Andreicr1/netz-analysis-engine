import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Admin — Health Dashboard", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/health page loads", async ({ page }) => {
		const response = await page.goto("/health");
		expect(response?.status()).toBeLessThan(500);
	});

	test("health page renders content", async ({ page }) => {
		await page.goto("/health");
		await expect(page.locator("body")).not.toBeEmpty();
	});

	test("no unexpected CSP violations on health page", async ({ page }) => {
		const cspErrors: string[] = [];
		page.on("console", (msg) => {
			if (msg.type() === "error" && msg.text().includes("Content Security Policy")) {
				// In dev mode, localhost:8000 backend API calls are expected CSP violations
				// because connect-src only allows 'self' (port 5175) + external origins
				if (!msg.text().includes("localhost:8000")) {
					cspErrors.push(msg.text());
				}
			}
		});
		await page.goto("/health");
		await page.waitForLoadState("networkidle");
		expect(cspErrors).toEqual([]);
	});
});
