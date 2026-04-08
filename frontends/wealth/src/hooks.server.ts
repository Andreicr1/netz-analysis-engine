/**
 * SvelteKit server hook — Clerk JWT + theme injection + CSP header.
 */
import { createClerkHook, createThemeHook } from "@investintell/ui/utils";
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

const SIGN_IN_URL = IS_DEV
	? "/auth/callback"
	: "https://accounts.investintell.com/sign-in?redirect_url=https://wealth.investintell.com/auth/callback";

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
 * NOTE — CSP is currently still authored in `static/_headers`, a file
 * format that ONLY Cloudflare Pages reads. The frontend now ships on
 * Railway via `@sveltejs/adapter-node`, which does not parse `_headers`,
 * so **production has no CSP enforced today**.
 *
 * TODO (backlog): migrate the CSP rules from `static/_headers` into this
 * Node hook (or an upstream reverse-proxy layer) and then delete the
 * `_headers` file.
 */
const securityHeadersHook: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);
	response.headers.set("X-Frame-Options", "DENY");
	response.headers.set("X-Content-Type-Options", "nosniff");
	response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
	return response;
};

export const handle: Handle = sequence(authHook, createThemeHook({ defaultTheme: "dark" }), securityHeadersHook);
