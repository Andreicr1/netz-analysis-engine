/** Team layout guard — reject INVESTOR role. */
import { errData } from "@investintell/ui/runtime";
import type { LayoutServerLoad } from "./$types";

export const load: LayoutServerLoad = async ({ parent }) => {
	const { actor } = await parent();

	if (actor.role === "investor") {
		return {
			access: errData("FORBIDDEN", "Team views are not accessible with an investor role.", false),
		};
	}

	return {};
};
