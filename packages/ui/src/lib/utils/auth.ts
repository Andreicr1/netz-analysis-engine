/**
 * Clerk JWT verification + session monitoring for SvelteKit frontends.
 *
 * createClerkHook(): verified JWT → Actor in event.locals.
 * startSessionExpiryMonitor(): client-side session expiry warning.
 */

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

		const payload = JSON.parse(atob(parts[1]));
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
	/** Public routes that skip auth (e.g., ["/auth/", "/health"]). */
	publicPrefixes?: string[];
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
export function createClerkHook(options: ClerkHookOptions = {}) {
	const {
		jwksUrl,
		devBypass = false,
		publicPrefixes = ["/auth/", "/health"],
	} = options;

	// SvelteKit Handle type — defined inline to avoid importing @sveltejs/kit in library code.
	type HandleEvent = {
		url: { pathname: string };
		request: { headers: { get: (name: string) => string | null } };
		cookies: { get: (name: string) => string | undefined };
		locals: Record<string, unknown>;
	};
	type HandleParams = {
		event: HandleEvent;
		resolve: (event: HandleEvent) => Promise<Response>;
	};

	return async ({ event, resolve }: HandleParams) => {
		const { pathname } = event.url;

		// Public routes — skip auth
		if (publicPrefixes.some((p) => pathname.startsWith(p))) {
			return resolve(event);
		}

		// Dev bypass via X-DEV-ACTOR header
		const devActorHeader = event.request.headers.get("x-dev-actor");
		if (devBypass && devActorHeader) {
			event.locals.actor = parseDevActor(devActorHeader);
			event.locals.token = "dev-token";
			return resolve(event);
		}

		// Extract Bearer token or session cookie
		const authHeader = event.request.headers.get("authorization");
		const cookieToken = event.cookies.get("__session");
		const token = authHeader?.replace("Bearer ", "") ?? cookieToken;

		if (!token) {
			if (devBypass) {
				event.locals.actor = DEFAULT_DEV_ACTOR;
				event.locals.token = "dev-token";
				return resolve(event);
			}
			// Dynamic import to avoid importing @sveltejs/kit at module level
			const { redirect } = await import("@sveltejs/kit");
			throw redirect(303, "/auth/sign-in");
		}

		try {
			if (jwksUrl) {
				// Production: verify JWT signature via Clerk JWKS
				if (!cachedJWKS) {
					cachedJWKS = createRemoteJWKSet(new URL(jwksUrl));
				}
				const { payload } = await jwtVerify(token, cachedJWKS);
				event.locals.actor = actorFromClaims(payload as Record<string, unknown>);
			} else {
				// No JWKS configured — decode without verification (dev fallback).
				// Backend still verifies on every API call (defense in depth).
				const parts = token.split(".");
				if (parts.length !== 3) throw new Error("Invalid JWT");
				const payload = JSON.parse(atob(parts[1]));
				event.locals.actor = actorFromClaims(payload);
			}
			event.locals.token = token;
		} catch (err) {
			// Check if it's a SvelteKit redirect (re-throw it)
			if (err && typeof err === "object" && "status" in err) throw err;
			const { redirect } = await import("@sveltejs/kit");
			throw redirect(303, "/auth/sign-in");
		}

		// Prevent CDN/edge caching of authenticated pages (#092)
		const response = await resolve(event);
		response.headers.set("Cache-Control", "private, no-store");
		return response;
	};
}
