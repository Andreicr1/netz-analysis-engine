/**
 * SvelteKit server hook — Clerk JWT verification via @netz/ui shared hook.
 *
 * In production: JWKS-verified JWT → Actor in event.locals.
 * In dev mode: X-DEV-ACTOR header or default dev actor with DEV_TOKEN.
 */
import { createClerkHook, createThemeHook } from "@netz/ui/utils";
import type { Handle } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";

const CLERK_JWKS_URL = process.env.CLERK_JWKS_URL ?? import.meta.env.VITE_CLERK_JWKS_URL;
const DEV_TOKEN = import.meta.env.VITE_DEV_TOKEN ?? process.env.DEV_TOKEN ?? "dev-token";

const authHook = createClerkHook({
	jwksUrl: CLERK_JWKS_URL,
	devBypass: import.meta.env.DEV,
	devToken: DEV_TOKEN,
	publicPrefixes: ["/auth/", "/health"],
});

export const handle: Handle = sequence(authHook, createThemeHook({ defaultTheme: "dark" }));
