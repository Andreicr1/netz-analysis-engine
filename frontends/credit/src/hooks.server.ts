/**
 * SvelteKit server hook — Clerk JWT + theme injection + CSP header.
 */
import { createClerkHook, createThemeHook } from "@netz/ui/utils";
import type { Handle } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";

const CLERK_JWKS_URL = process.env.CLERK_JWKS_URL ?? import.meta.env.VITE_CLERK_JWKS_URL;

const authHook = createClerkHook({
	jwksUrl: CLERK_JWKS_URL,
	devBypass: import.meta.env.DEV,
	publicPrefixes: ["/health", "/.well-known/"],
	signInUrl: "https://accounts.investintell.com/sign-in",
});

/**
 * Security headers hook — CSP is handled by static/_headers (Cloudflare Pages).
 * SSR-level CSP was removed because dual headers cause nonce/unsafe-inline conflicts:
 * Cloudflare may inject nonces which per CSP3 spec disables unsafe-inline,
 * blocking the FOUC prevention script in app.html.
 */
const securityHeadersHook: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);
	response.headers.set("X-Frame-Options", "DENY");
	response.headers.set("X-Content-Type-Options", "nosniff");
	response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
	return response;
};

export const handle: Handle = sequence(authHook, createThemeHook({ defaultTheme: "light" }), securityHeadersHook);
