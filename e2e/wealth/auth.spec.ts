import { test, expect } from "@playwright/test";
import { loginAs, loginViaDevButton, clearAuth } from "../fixtures/auth";

test.describe("Wealth — Authentication", () => {
	test("sign-in page loads", async ({ page }) => {
		await page.goto("/auth/sign-in");
		await expect(page.locator(".sign-in-card")).toBeVisible();
	});

	test('"Continue as Dev User" button visible in dev mode', async ({ page }) => {
		await page.goto("/auth/sign-in");
		await expect(page.getByRole("link", { name: "Continue as Dev User" })).toBeVisible();
	});

	test("dev bypass redirects to /screener", async ({ page }) => {
		await loginViaDevButton(page);
		await page.waitForURL("**/screener");
		expect(page.url()).toContain("/screener");
	});

	test("no CSP violations on sign-in", async ({ page }) => {
		const cspErrors: string[] = [];
		page.on("console", (msg) => {
			if (msg.type() === "error" && msg.text().includes("Content Security Policy")) {
				cspErrors.push(msg.text());
			}
		});
		await page.goto("/auth/sign-in");
		await page.waitForLoadState("networkidle");
		expect(cspErrors).toEqual([]);
	});
});
