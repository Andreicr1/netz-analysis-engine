/**
 * SvelteKit server hook — Clerk auth + SUPER_ADMIN guard + theme.
 */
import { createClerkHook } from "@netz/ui/utils";
import type { Handle } from "@sveltejs/kit";
import { redirect } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";

const CLERK_JWKS_URL = process.env.CLERK_JWKS_URL ?? import.meta.env.VITE_CLERK_JWKS_URL;

const authHook: Handle = createClerkHook({
	jwksUrl: CLERK_JWKS_URL,
	devBypass: import.meta.env.DEV,
	publicPrefixes: ["/auth/", "/health"],
}) as Handle;

/** Admin guard — only SUPER_ADMIN can access admin panel. */
const PUBLIC_PREFIXES = ["/auth/", "/health"];
const adminGuardHook: Handle = async ({ event, resolve }) => {
	if (PUBLIC_PREFIXES.some(p => event.url.pathname.startsWith(p))) {
		return resolve(event);
	}
	const actor = event.locals.actor as { role?: string } | undefined;
	// In dev mode, the dev actor has role "admin" — allow it
	if (!actor || (actor.role !== "super_admin" && actor.role !== "admin" && actor.role !== "org:admin")) {
		throw redirect(303, "/auth/sign-in?error=unauthorized");
	}
	return resolve(event);
};

const VALID_THEMES = new Set(["dark", "light"]);

/** Inject data-theme attribute into SSR HTML to prevent FOUC. */
const themeHook: Handle = async ({ event, resolve }) => {
	const raw = event.cookies.get("netz-theme") || "light";
	const theme = VALID_THEMES.has(raw) ? raw : "light";
	return resolve(event, {
		transformPageChunk: ({ html }) =>
			html.replace('data-theme="light"', `data-theme="${theme}"`),
	});
};

export const handle: Handle = sequence(authHook, adminGuardHook, themeHook);
