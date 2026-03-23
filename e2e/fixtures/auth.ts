/**
 * Shared authentication helpers for Playwright E2E tests.
 *
 * In dev mode, the SvelteKit hook auto-assigns DEFAULT_DEV_ACTOR (role: "admin")
 * when no token is present. For role-specific tests, we inject X-DEV-ACTOR headers.
 */

import type { Page } from "@playwright/test";

interface DevActor {
	user_id: string;
	organization_id: string;
	organization_slug: string;
	role: string;
	email: string;
	name: string;
}

const ACTORS: Record<string, DevActor> = {
	admin: {
		user_id: "e2e-admin-001",
		organization_id: "e2e-org-001",
		organization_slug: "e2e-org",
		role: "admin",
		email: "admin@e2e.netz.fund",
		name: "E2E Admin",
	},
	super_admin: {
		user_id: "e2e-super-001",
		organization_id: "e2e-org-001",
		organization_slug: "e2e-org",
		role: "super_admin",
		email: "super@e2e.netz.fund",
		name: "E2E Super Admin",
	},
	gestora: {
		user_id: "e2e-gestora-001",
		organization_id: "e2e-org-001",
		organization_slug: "e2e-org",
		role: "investment_team",
		email: "gestora@e2e.netz.fund",
		name: "E2E Gestora",
	},
	investor: {
		user_id: "e2e-investor-001",
		organization_id: "e2e-org-001",
		organization_slug: "e2e-org",
		role: "investor",
		email: "investor@e2e.netz.fund",
		name: "E2E Investor",
	},
};

/**
 * Log in as a dev user with the given role by setting the X-DEV-ACTOR header.
 *
 * The SvelteKit hook picks up this header when devBypass is enabled and
 * assigns the actor to event.locals. All subsequent navigations on this
 * page will include the header.
 */
export async function loginAs(
	page: Page,
	role: "admin" | "gestora" | "investor" | "super_admin" = "admin",
): Promise<void> {
	const actor = ACTORS[role];
	await page.setExtraHTTPHeaders({
		"x-dev-actor": JSON.stringify(actor),
	});
}

/**
 * Navigate to sign-in and click the dev bypass button.
 * Useful for testing the sign-in flow itself.
 */
export async function loginViaDevButton(page: Page, signInUrl = "/auth/sign-in"): Promise<void> {
	await page.goto(signInUrl);
	await page.getByRole("link", { name: "Continue as Dev User" }).click();
	await page.waitForURL((url) => !url.pathname.includes("/auth/"));
}

/**
 * Clear auth headers to simulate unauthenticated state.
 */
export async function clearAuth(page: Page): Promise<void> {
	await page.setExtraHTTPHeaders({});
}
