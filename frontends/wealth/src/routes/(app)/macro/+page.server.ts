/** Macro Intelligence — regional scores, regime, indicators, snapshot, reviews. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type {
	MacroScores, RegimeHierarchy, MacroIndicators,
	MacroSnapshot, MacroReview,
} from "$lib/types/macro";

export const load: PageServerLoad = async ({ parent }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	const [scores, regime, indicators, snapshot, reviews] = await Promise.all([
		api.get<MacroScores>("/macro/scores").catch(() => null),
		api.get<RegimeHierarchy>("/macro/regime").catch(() => null),
		api.get<MacroIndicators>("/risk/macro").catch(() => null),
		api.get<MacroSnapshot>("/macro/snapshot").catch(() => null),
		api.get<MacroReview[]>("/macro/reviews", { limit: 20 }).catch(() => []),
	]);

	return {
		scores,
		regime,
		indicators,
		snapshot,
		reviews,
		actorRole: actor?.role ?? null,
	};
};
