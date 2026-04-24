import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  use: {
    baseURL: "http://localhost:5175",
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },
  webServer: {
    command: "pnpm dev --port 5175",
    port: 5175,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
