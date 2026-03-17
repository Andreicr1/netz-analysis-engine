/**
 * SvelteKit server hook — Clerk JWT verification via @netz/ui shared hook.
 *
 * In production: JWKS-verified JWT → Actor in event.locals.
 * In dev mode: X-DEV-ACTOR header or default dev actor.
 */
import { createClerkHook } from "@netz/ui/utils";
import type { Handle } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";

const CLERK_JWKS_URL = process.env.CLERK_JWKS_URL ?? import.meta.env.VITE_CLERK_JWKS_URL;

const authHook: Handle = createClerkHook({
	jwksUrl: CLERK_JWKS_URL,
	devBypass: import.meta.env.DEV,
	publicPrefixes: ["/auth/", "/health"],
}) as Handle;

const VALID_THEMES = new Set(["dark", "light"]);

/** Inject data-theme attribute into SSR HTML to prevent FOUC.
 *  Must match data-theme value in app.html (currently "light"). */
const themeHook: Handle = async ({ event, resolve }) => {
	const raw = event.cookies.get("netz-theme") || "light";
	const theme = VALID_THEMES.has(raw) ? raw : "light";
	return resolve(event, {
		transformPageChunk: ({ html }) =>
			html.replace('data-theme="light"', `data-theme="${theme}"`),
	});
};

export const handle: Handle = sequence(authHook, themeHook);
