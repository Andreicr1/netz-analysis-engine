/**
 * SvelteKit server hook — Clerk JWT verification for II Terminal.
 *
 * Uses the shared verified-JWT -> Actor path via `@investintell/ui`
 * `createClerkHook`.
 *
 * Cookie-domain SSO note: `createClerkHook` does not manage cookie domain
 * itself — that is configured in the Clerk Dashboard (`.investintell.com`
 * allowed subdomains). `CLERK_COOKIE_DOMAIN` is read here so the operator
 * can wire it in X6 (cutover to prod) without re-touching this file.
 */
import { createClerkHook } from "@investintell/ui/utils";
import type { Handle } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";
import { env } from "$env/dynamic/private";
import { env as pubEnv } from "$env/dynamic/public";

/** Derive Clerk JWKS URL from publishable key if not explicitly set.
 *  pk_test_Y2Fw... → base64 decode → capital-tarpon-42.clerk.accounts.dev
 */
function deriveJwksUrl(pk: string): string {
	try {
		const encoded = pk.replace(/^pk_(test|live)_/, "");
		const domain = atob(encoded).replace(/\$$/, "");
		return `https://${domain}/.well-known/jwks.json`;
	} catch {
		return "";
	}
}

const PK = pubEnv.PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";
const CLERK_JWKS_URL = env.CLERK_JWKS_URL || deriveJwksUrl(PK);
const DEV_TOKEN = env.DEV_TOKEN ?? "dev-token";
const IS_DEV = import.meta.env.DEV;

// Read but currently unused — wired to Clerk Dashboard config in X6.
// Leaving the lookup here so env is validated early on boot.
const _CLERK_COOKIE_DOMAIN = env.CLERK_COOKIE_DOMAIN ?? (IS_DEV ? "localhost" : ".investintell.com");
void _CLERK_COOKIE_DOMAIN;

const SIGN_IN_URL = IS_DEV
	? "/auth/callback"
	: "https://accounts.investintell.com/sign-in?redirect_url=https://terminal.investintell.com/auth/callback";

const authHook = createClerkHook({
	jwksUrl: IS_DEV ? undefined : CLERK_JWKS_URL,
	devBypass: IS_DEV,
	devToken: DEV_TOKEN,
	publicPrefixes: ["/health", "/.well-known/", "/auth/"],
	signInUrl: SIGN_IN_URL,
});

/**
 * Security headers hook.
 *
 * NOTE — CSP rules will ship with X3/X6. X1 only sets the baseline headers
 * that are framework-agnostic. Railway + adapter-node does not parse a
 * `_headers` file (Cloudflare Pages format), so any CSP must live here.
 */
const securityHeadersHook: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);
	response.headers.set("X-Frame-Options", "DENY");
	response.headers.set("X-Content-Type-Options", "nosniff");
	response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
	return response;
};

export const handle: Handle = sequence(authHook, securityHeadersHook);
