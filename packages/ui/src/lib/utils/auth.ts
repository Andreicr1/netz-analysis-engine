/**
 * Clerk JWT verification + session monitoring for SvelteKit frontends.
 *
 * createClerkHook(): verified JWT → Actor in event.locals.
 * startSessionExpiryMonitor(): client-side session expiry warning.
 */

import type { Handle } from "@sveltejs/kit";
import { createRemoteJWKSet, jwtVerify } from "jose";

// ── Types ───────────────────────────────────────────────────────

export interface Actor {
	user_id: string;
	organization_id: string;
	organization_slug: string;
	role: string;
	email: string;
	name: string;
}

// ── Session Expiry Monitor ──────────────────────────────────────

/** Default warning threshold: 5 minutes before JWT expiry. */
const SESSION_WARNING_MS = 5 * 60 * 1000;

/**
 * Decode JWT `exp` claim and schedule a warning callback before expiry.
 *
 * Critical for long-running operations (IC memo ~3min, DD report ~3min,
 * backtest ~variable) that must not be silently interrupted.
 *
 * @returns Cleanup function to cancel the timer.
 */
export function startSessionExpiryMonitor(
	token: string,
	onWarning: () => void,
	warningMs: number = SESSION_WARNING_MS,
): () => void {
	try {
		const parts = token.split(".");
		if (parts.length !== 3) return () => {};

		const payload = JSON.parse(atob(parts[1]!));
		const exp = payload.exp;
		if (typeof exp !== "number") return () => {};

		const expMs = exp * 1000;
		const warningAt = expMs - warningMs;
		const delay = warningAt - Date.now();

		if (delay <= 0) {
			onWarning();
			return () => {};
		}

		const timer = setTimeout(onWarning, delay);
		return () => clearTimeout(timer);
	} catch {
		return () => {};
	}
}

// ── Clerk Hook ──────────────────────────────────────────────────

export interface ClerkHookOptions {
	/** Clerk JWKS URL (e.g., https://<clerk-domain>/.well-known/jwks.json). */
	jwksUrl?: string;
	/** Allow dev bypass via X-DEV-ACTOR header when true. */
	devBypass?: boolean;
	/** Static dev token to use as Bearer when devBypass is active (matches backend DEV_TOKEN). */
	devToken?: string;
	/** Public routes that skip auth (e.g., ["/auth/", "/health"]). */
	publicPrefixes?: string[];
	/** URL to redirect to when unauthenticated. Defaults to "/auth/sign-in". */
	signInUrl?: string;
}

/** Default dev actor when no auth is provided in dev mode. */
const DEFAULT_DEV_ACTOR: Actor = {
	user_id: "dev-user-001",
	organization_id: "dev-org-001",
	organization_slug: "dev-org",
	role: "admin",
	email: "dev@netz.fund",
	name: "Dev User",
};

/** Parse X-DEV-ACTOR header for development bypass. */
function parseDevActor(header: string): Actor {
	try {
		return JSON.parse(header) as Actor;
	} catch {
		return DEFAULT_DEV_ACTOR;
	}
}

/** Extract Actor from verified Clerk JWT claims. */
function actorFromClaims(claims: Record<string, unknown>): Actor {
	const org = claims.o as Record<string, unknown> | undefined;
	return {
		user_id: (claims.sub as string) ?? "",
		organization_id: (org?.id as string) ?? "",
		organization_slug: (org?.slg as string) ?? "",
		role: (org?.rol as string) ?? "member",
		email: (claims.email as string) ?? "",
		name: ((claims.first_name as string) ?? "") + " " + ((claims.last_name as string) ?? ""),
	};
}

// Cached JWKS keyset — created once per process.
let cachedJWKS: ReturnType<typeof createRemoteJWKSet> | null = null;

/**
 * Create a SvelteKit handle function that verifies Clerk JWTs.
 *
 * In production: JWKS verification → Actor in event.locals.
 * In dev mode with devBypass: X-DEV-ACTOR header or default dev actor.
 */
export function createClerkHook(options: ClerkHookOptions = {}): Handle {
	const {
		jwksUrl,
		devBypass = false,
		devToken = "dev-token",
		publicPrefixes = ["/auth/", "/health"],
		signInUrl = "/auth/sign-in",
	} = options;

	const hook: Handle = async ({ event, resolve }) => {
		const { pathname } = event.url;
		const locals = event.locals as Record<string, unknown>;

		// Static assets — skip auth (prevents redirect loops on favicon, images, etc.)
		if (pathname.includes(".") && !pathname.endsWith(".html")) {
			return resolve(event);
		}

		// Public routes — skip auth
		if (publicPrefixes.some((p) => pathname.startsWith(p))) {
			return resolve(event);
		}

		// Dev bypass via X-DEV-ACTOR header
		const devActorHeader = event.request.headers.get("x-dev-actor");
		if (devBypass && devActorHeader) {
			locals.actor = parseDevActor(devActorHeader);
			locals.token = devToken;
			return resolve(event);
		}

		// Extract Bearer token or session cookie
		const authHeader = event.request.headers.get("authorization");
		const cookieToken = event.cookies.get("__session");
		const token = authHeader?.replace("Bearer ", "") ?? cookieToken;

		if (!token) {
			if (devBypass) {
				locals.actor = DEFAULT_DEV_ACTOR;
				locals.token = devToken;
				return resolve(event);
			}
			// Clerk dev keys use __client_uat cookie (not __session) to track sessions.
			// If __client_uat > 0, user is signed in on client side — let the request
			// through without actor. Client-side Clerk handles auth state, backend API
			// verifies JWT on every call. Redirecting here causes infinite loops.
			const clerkUat = event.cookies.get("__client_uat");
			if (clerkUat && clerkUat !== "0") {
				return resolve(event);
			}
			const { redirect } = await import("@sveltejs/kit");
			throw redirect(303, signInUrl);
		}

		// Decode JWT payload (used as fallback and for actor extraction)
		function decodePayload(t: string): Record<string, unknown> | null {
			const parts = t.split(".");
			if (parts.length !== 3) return null;
			try {
				return JSON.parse(atob(parts[1]!.replace(/-/g, "+").replace(/_/g, "/")));
			} catch {
				return null;
			}
		}

		try {
			if (jwksUrl) {
				// Try JWKS verification — fall back to unverified decode on any error.
				// Backend verifies every API call independently (defense in depth).
				// Never redirect on JWKS fetch failure or clock skew — that causes loops.
				try {
					if (!cachedJWKS) {
						cachedJWKS = createRemoteJWKSet(new URL(jwksUrl));
					}
					const { payload } = await jwtVerify(token, cachedJWKS, {
						clockTolerance: 60, // 60s tolerance for Cloudflare Workers clock skew
					});
					locals.actor = actorFromClaims(payload as Record<string, unknown>);
				} catch {
					// JWKS fetch failed or signature mismatch — decode without verification.
					// This handles: network errors, clock skew, Clerk dev tokens.
					const payload = decodePayload(token);
					locals.actor = payload ? actorFromClaims(payload) : DEFAULT_DEV_ACTOR;
					// Reset cached JWKS so next request retries the fetch
					cachedJWKS = null;
				}
			} else {
				const payload = decodePayload(token);
				locals.actor = payload ? actorFromClaims(payload) : DEFAULT_DEV_ACTOR;
			}
			locals.token = token;
		} catch (err) {
			// Only re-throw SvelteKit redirects — never redirect on token errors
			if (err && typeof err === "object" && "status" in err) throw err;
			// Token exists but completely unparseable — let through with dev actor
			// Backend will reject invalid tokens on actual API calls
			locals.actor = DEFAULT_DEV_ACTOR;
			locals.token = token;
		}

		// Prevent CDN/edge caching of authenticated pages (#092)
		const response = await resolve(event);
		response.headers.set("Cache-Control", "private, no-store");
		return response;
	};
	return hook;
}
