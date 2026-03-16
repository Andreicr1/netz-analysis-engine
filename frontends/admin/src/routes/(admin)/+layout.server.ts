/** Admin route group guard — requires admin role. */
import { error } from "@sveltejs/kit";
import type { LayoutServerLoad } from "./$types";

export const load: LayoutServerLoad = async ({ parent }) => {
	const { actor } = await parent();

	if (actor.role !== "admin" && actor.role !== "org:admin") {
		throw error(403, "Admin access required.");
	}

	return {};
};
