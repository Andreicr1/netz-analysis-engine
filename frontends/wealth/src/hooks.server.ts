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

/**
 * Security headers hook — CSP is handled by static/_headers (Cloudflare Pages).
 * SSR-level CSP removed: dual headers cause nonce/unsafe-inline conflicts.
 */
const securityHeadersHook: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);
	response.headers.set("X-Frame-Options", "DENY");
	response.headers.set("X-Content-Type-Options", "nosniff");
	response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
	return response;
};

export const handle: Handle = sequence(authHook, createThemeHook({ defaultTheme: "dark" }), securityHeadersHook);
