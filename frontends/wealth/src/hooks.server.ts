/**
 * SvelteKit server hook — Clerk JWT + theme injection + CSP header.
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

/** CSP header — must use unsafe-inline for Clerk + FOUC prevention script. */
const cspHook: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);
	response.headers.set(
		"Content-Security-Policy",
		[
			"default-src 'self'",
			"script-src 'self' 'unsafe-inline' https://*.clerk.com https://*.clerk.accounts.dev",
			"style-src 'self' 'unsafe-inline'",
			"img-src 'self' data: blob: https:",
			"connect-src 'self' https://*.clerk.com https://*.clerk.accounts.dev https://api.netz.app wss:",
			"font-src 'self' data:",
			"frame-ancestors 'none'",
			"base-uri 'self'",
			"form-action 'self'",
		].join("; "),
	);
	response.headers.set("X-Frame-Options", "DENY");
	response.headers.set("X-Content-Type-Options", "nosniff");
	response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
	return response;
};

export const handle: Handle = sequence(authHook, createThemeHook({ defaultTheme: "dark" }), cspHook);
