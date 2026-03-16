/**
 * SvelteKit server hook — Clerk JWT verification + dev bypass.
 * Admin-specific: rejects non-admin users entirely.
 */
import type { Handle } from "@sveltejs/kit";
import { redirect } from "@sveltejs/kit";

export interface Actor {
	user_id: string;
	organization_id: string;
	organization_slug: string;
	role: string;
	email: string;
	name: string;
}

const DEV_MODE = import.meta.env.DEV;

function parseDevActor(header: string): Actor {
	try {
		return JSON.parse(header) as Actor;
	} catch {
		return {
			user_id: "dev-user-001",
			organization_id: "dev-org-001",
			organization_slug: "dev-org",
			role: "admin",
			email: "dev@netz.fund",
			name: "Dev User",
		};
	}
}

function decodeJwtPayload(token: string): Record<string, unknown> {
	const parts = token.split(".");
	if (parts.length !== 3) throw new Error("Invalid JWT");
	return JSON.parse(atob(parts[1]!));
}

function actorFromClaims(claims: Record<string, unknown>): Actor {
	const orgId = (claims.o as Record<string, unknown>)?.id as string ?? "";
	const orgSlug = (claims.o as Record<string, unknown>)?.slg as string ?? "";
	const orgRole = (claims.o as Record<string, unknown>)?.rol as string ?? "member";

	return {
		user_id: claims.sub as string ?? "",
		organization_id: orgId,
		organization_slug: orgSlug,
		role: orgRole,
		email: claims.email as string ?? "",
		name: (claims.first_name as string ?? "") + " " + (claims.last_name as string ?? ""),
	};
}

export const handle: Handle = async ({ event, resolve }) => {
	const { pathname } = event.url;

	// Public routes — skip auth
	if (pathname.startsWith("/auth/") || pathname === "/health") {
		return resolve(event);
	}

	// Dev bypass via X-DEV-ACTOR header
	const devActorHeader = event.request.headers.get("x-dev-actor");
	if (DEV_MODE && devActorHeader) {
		const actor = parseDevActor(devActorHeader);
		event.locals.actor = actor;
		event.locals.token = "dev-token";
		return resolve(event);
	}

	// Extract Bearer token
	const authHeader = event.request.headers.get("authorization");
	const cookieToken = event.cookies.get("__session");
	const token = authHeader?.replace("Bearer ", "") ?? cookieToken;

	if (!token) {
		if (DEV_MODE) {
			event.locals.actor = parseDevActor("{}");
			event.locals.token = "dev-token";
			return resolve(event);
		}
		throw redirect(303, "/auth/sign-in");
	}

	try {
		const claims = decodeJwtPayload(token);
		const actor = actorFromClaims(claims);

		// Admin guard — reject non-admin users entirely
		if (actor.role !== "org:admin" && actor.role !== "admin") {
			throw redirect(303, "/auth/sign-in");
		}

		event.locals.actor = actor;
		event.locals.token = token;
	} catch (e) {
		// Re-throw redirects
		if (e && typeof e === "object" && "status" in e) throw e;
		throw redirect(303, "/auth/sign-in");
	}

	return resolve(event);
};
