/**
 * SvelteKit server hook — Clerk auth + SUPER_ADMIN guard + theme + CSP header.
 */
import { createClerkHook, createThemeHook } from "@netz/ui/utils";
import type { Actor } from "@netz/ui/utils";
import type { Handle } from "@sveltejs/kit";
import { redirect } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";

const CLERK_JWKS_URL = process.env.CLERK_JWKS_URL ?? import.meta.env.VITE_CLERK_JWKS_URL;

const authHook = createClerkHook({
	jwksUrl: CLERK_JWKS_URL,
	devBypass: import.meta.env.DEV,
	publicPrefixes: ["/auth/", "/health"],
});

/** Admin guard — only super_admin / admin roles can access admin panel. */
const ADMIN_ROLES = new Set(["super_admin", "admin", "org:admin"]);
const PUBLIC_PREFIXES = ["/auth/", "/health"];
const adminGuardHook: Handle = async ({ event, resolve }) => {
	if (PUBLIC_PREFIXES.some(p => event.url.pathname.startsWith(p))) {
		return resolve(event);
	}
	const actor = event.locals.actor as Actor | undefined;
	if (!actor || !ADMIN_ROLES.has(actor.role)) {
		throw redirect(303, "/auth/sign-in?error=unauthorized");
	}
	return resolve(event);
};

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

export const handle: Handle = sequence(authHook, adminGuardHook, createThemeHook({ defaultTheme: "light" }), securityHeadersHook);
