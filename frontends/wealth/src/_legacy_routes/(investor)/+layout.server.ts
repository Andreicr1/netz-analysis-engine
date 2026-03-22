/** Investor layout guard — allow only INVESTOR and ADVISOR roles. */
import { error } from "@sveltejs/kit";
import type { LayoutServerLoad } from "./$types";

const ALLOWED_ROLES = new Set(["investor", "advisor"]);

export const load: LayoutServerLoad = async ({ parent }) => {
	const { actor } = await parent();

	if (!ALLOWED_ROLES.has(actor.role)) {
		throw error(403, "Investor portal is only accessible to investor and advisor roles.");
	}

	return {};
};
