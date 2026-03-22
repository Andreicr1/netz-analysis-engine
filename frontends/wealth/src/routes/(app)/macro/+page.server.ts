/** Macro Intelligence — regional scores, regime, indicators. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { MacroScores, RegimeHierarchy, MacroIndicators } from "$lib/types/macro";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [scores, regime, indicators] = await Promise.all([
		api.get<MacroScores>("/macro/scores").catch(() => null),
		api.get<RegimeHierarchy>("/macro/regime").catch(() => null),
		api.get<MacroIndicators>("/risk/macro").catch(() => null),
	]);

	return { scores, regime, indicators };
};
