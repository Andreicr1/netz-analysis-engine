/**
 * SvelteKit server hook — Clerk JWT verification via @netz/ui shared hook.
 *
 * In production: JWKS-verified JWT → Actor in event.locals.
 * In dev mode: X-DEV-ACTOR header or default dev actor.
 */
import { createClerkHook, createThemeHook } from "@netz/ui/utils";
import type { Handle } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";

const CLERK_JWKS_URL = process.env.CLERK_JWKS_URL ?? import.meta.env.VITE_CLERK_JWKS_URL;

const authHook = createClerkHook({
	jwksUrl: CLERK_JWKS_URL,
	devBypass: import.meta.env.DEV,
	publicPrefixes: ["/auth/", "/health"],
});

export const handle: Handle = sequence(authHook, createThemeHook({ defaultTheme: "dark" }));
