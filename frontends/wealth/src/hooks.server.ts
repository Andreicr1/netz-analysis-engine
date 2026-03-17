/**
 * SvelteKit server hook — Clerk JWT verification via @netz/ui shared hook.
 *
 * In production: JWKS-verified JWT → Actor in event.locals.
 * In dev mode: X-DEV-ACTOR header or default dev actor.
 */
import { createClerkHook } from "@netz/ui/utils";
import type { Handle } from "@sveltejs/kit";

const CLERK_JWKS_URL = process.env.CLERK_JWKS_URL ?? import.meta.env.VITE_CLERK_JWKS_URL;

export const handle: Handle = createClerkHook({
	jwksUrl: CLERK_JWKS_URL,
	devBypass: import.meta.env.DEV,
	publicPrefixes: ["/auth/", "/health"],
}) as Handle;
