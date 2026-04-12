import { test, expect } from "@playwright/test";
import { loginAs } from "../fixtures/auth";

test.describe("Wealth — Fund Screener", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("/screener page loads", async ({ page }) => {
		const response = await page.goto("/screener");
		expect(response?.status()).toBeLessThan(500);
	});

	test("screener renders content (table or empty state)", async ({ page }) => {
		await page.goto("/screener");
		await expect(page.locator("body")).not.toBeEmpty();
	});

	test("no CSP violations on screener", async ({ page }) => {
		const cspErrors: string[] = [];
		page.on("console", (msg) => {
			if (msg.type() === "error" && msg.text().includes("Content Security Policy")) {
				cspErrors.push(msg.text());
			}
		});
		await page.goto("/screener");
		await page.waitForLoadState("networkidle");
		expect(cspErrors).toEqual([]);
	});
});

test.describe("Wealth — Terminal Screener (Phase 3)", () => {
	test.beforeEach(async ({ page }) => {
		await loginAs(page, "admin");
	});

	test("terminal-screener page loads and renders grid", async ({ page }) => {
		const response = await page.goto("/terminal-screener");
		expect(response?.status()).toBeLessThan(500);

		// Grid container should be visible
		await expect(page.locator("[role='grid']")).toBeVisible({ timeout: 10_000 });
	});

	test("grid header columns are present", async ({ page }) => {
		await page.goto("/terminal-screener");
		await expect(page.locator("[role='grid']")).toBeVisible({ timeout: 10_000 });

		// Verify key header columns
		const header = page.locator(".dg-header");
		await expect(header).toContainText("Ticker");
		await expect(header).toContainText("Name");
		await expect(header).toContainText("AUM");
		await expect(header).toContainText("Trend");
		await expect(header).toContainText("Action");
	});

	test("ELITE filter chip is present and toggleable", async ({ page }) => {
		await page.goto("/terminal-screener");
		await expect(page.locator("[role='grid']")).toBeVisible({ timeout: 10_000 });

		// ELITE chip should exist in filter panel
		const eliteChip = page.locator(".sf-elite-chip");
		await expect(eliteChip).toBeVisible();
		await expect(eliteChip).toContainText("ELITE");

		// Click toggles the active state
		await eliteChip.click();
		await expect(eliteChip).toHaveClass(/sf-elite-chip--active/);

		// URL should reflect elite=1
		await expect(page).toHaveURL(/elite=1/);

		// Click again to deactivate
		await eliteChip.click();
		await expect(eliteChip).not.toHaveClass(/sf-elite-chip--active/);
	});

	test("URL state persists across reload", async ({ page }) => {
		await page.goto("/terminal-screener?elite=1");
		await expect(page.locator("[role='grid']")).toBeVisible({ timeout: 10_000 });

		// ELITE chip should be active from URL
		const eliteChip = page.locator(".sf-elite-chip");
		await expect(eliteChip).toHaveClass(/sf-elite-chip--active/);
	});

	test("footer shows instrument count", async ({ page }) => {
		await page.goto("/terminal-screener");
		await expect(page.locator("[role='grid']")).toBeVisible({ timeout: 10_000 });

		// Footer should show "Showing X of Y instruments" or "Loading..."
		const footer = page.locator(".dg-footer");
		await expect(footer).toBeVisible();
		// Wait for loading to complete
		await expect(footer).not.toContainText("Loading", { timeout: 15_000 });
		await expect(footer).toContainText("instruments");
	});

	test("virtualized grid has limited DOM rows", async ({ page }) => {
		await page.goto("/terminal-screener");
		await expect(page.locator("[role='grid']")).toBeVisible({ timeout: 10_000 });

		// Wait for data to load
		await expect(page.locator(".dg-footer")).not.toContainText("Loading", { timeout: 15_000 });

		// Count rendered rows — should be far fewer than total instruments
		const rowCount = await page.locator(".dg-row").count();
		expect(rowCount).toBeLessThanOrEqual(80); // ~50 visible + overscan, never 9000+
	});

	test("keyboard e toggles ELITE filter", async ({ page }) => {
		await page.goto("/terminal-screener");
		await expect(page.locator("[role='grid']")).toBeVisible({ timeout: 10_000 });

		// Press 'e' to toggle ELITE
		await page.keyboard.press("e");
		await expect(page).toHaveURL(/elite=1/);

		// Press 'e' again to untoggle
		await page.keyboard.press("e");
		await expect(page).not.toHaveURL(/elite=1/);
	});

	test("no CSP violations on terminal-screener", async ({ page }) => {
		const cspErrors: string[] = [];
		page.on("console", (msg) => {
			if (msg.type() === "error" && msg.text().includes("Content Security Policy")) {
				cspErrors.push(msg.text());
			}
		});
		await page.goto("/terminal-screener");
		await page.waitForLoadState("networkidle");
		expect(cspErrors).toEqual([]);
	});
});
