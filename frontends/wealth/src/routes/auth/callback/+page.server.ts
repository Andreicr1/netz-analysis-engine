/**
 * Auth callback — public route (no auth required).
 * After Clerk sign-in redirects here, Clerk JS syncs __session cookie once.
 */
import type { PageServerLoad } from "./$types";
import { redirect } from "@sveltejs/kit";
import { env } from "$env/dynamic/public";

export const load: PageServerLoad = async ({ cookies }) => {
	// Already have a session — go straight to the app
	if (cookies.get("__session")) {
		throw redirect(303, "/");
	}

	return {
		clerkPublishableKey: env.PUBLIC_CLERK_PUBLISHABLE_KEY ?? "",
	};
};
