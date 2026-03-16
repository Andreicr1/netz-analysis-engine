/** Team layout guard — reject INVESTOR role. */
import { error } from "@sveltejs/kit";
import type { LayoutServerLoad } from "./$types";

export const load: LayoutServerLoad = async ({ parent }) => {
	const { actor } = await parent();

	if (actor.role === "investor") {
		throw error(403, "Team views are not accessible with an investor role.");
	}

	return {};
};
