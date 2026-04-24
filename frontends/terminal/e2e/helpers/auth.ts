import type { Page } from "@playwright/test";

/**
 * Canonical dev org (see CLAUDE.md).
 * X-DEV-ACTOR header bypasses Clerk JWT in dev mode when backend runs
 * with CLERK_SECRET_KEY absent or DEV mode enabled.
 */
export const DEV_ORG_ID = "403d8392-ebfa-5890-b740-45da49c556eb";

export async function loginAsAdmin(page: Page): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const headers = {
      ...route.request().headers(),
      "x-dev-actor": `super_admin:${DEV_ORG_ID}`,
    };
    await route.continue({ headers });
  });
}
