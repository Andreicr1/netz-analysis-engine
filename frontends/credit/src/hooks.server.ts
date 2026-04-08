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
 * Security headers hook.
 *
 * NOTE — CSP is currently still authored in `static/_headers`, a file
 * format that ONLY Cloudflare Pages reads. The frontend now ships on
 * Railway via `@sveltejs/adapter-node`, which does not parse `_headers`,
 * so **production has no CSP enforced today**.
 *
 * TODO (backlog): migrate the CSP rules from `static/_headers` into this
 * Node hook (or an upstream reverse-proxy layer) and then delete the
 * `_headers` file. Care is needed around the FOUC-prevention script in
 * `app.html` — adding a CSP nonce there will require either passing the
 * nonce through SvelteKit's `transformPageChunk` or reverting to
 * `unsafe-inline` for that one script tag.
 */
const securityHeadersHook: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);
	response.headers.set("X-Frame-Options", "DENY");
	response.headers.set("X-Content-Type-Options", "nosniff");
	response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
	return response;
};

export const handle: Handle = sequence(authHook, createThemeHook({ defaultTheme: "light" }), securityHeadersHook);
