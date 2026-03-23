import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
	testDir: "./e2e",
	timeout: 30_000,
	retries: process.env.CI ? 2 : 0,
	workers: 1,
	reporter: [["html", { open: "never" }], ["list"]],
	use: {
		baseURL: "http://localhost:5173",
		trace: "on-first-retry",
		screenshot: "only-on-failure",
	},
	projects: [
		{
			name: "credit",
			testDir: "./e2e/credit",
			use: {
				...devices["Desktop Chrome"],
				baseURL: "http://localhost:5173",
			},
		},
		{
			name: "wealth",
			testDir: "./e2e/wealth",
			use: {
				...devices["Desktop Chrome"],
				baseURL: "http://localhost:5174",
			},
		},
		{
			name: "admin",
			testDir: "./e2e/admin",
			use: {
				...devices["Desktop Chrome"],
				baseURL: "http://localhost:5175",
			},
		},
	],
	webServer: [
		{
			command: "pnpm --filter netz-credit-intelligence dev",
			port: 5173,
			reuseExistingServer: !process.env.CI,
			timeout: 60_000,
		},
		{
			command: "pnpm --filter netz-wealth-os dev",
			port: 5174,
			reuseExistingServer: !process.env.CI,
			timeout: 60_000,
		},
		{
			command: "pnpm --filter netz-admin dev",
			port: 5175,
			reuseExistingServer: !process.env.CI,
			timeout: 60_000,
		},
	],
});
