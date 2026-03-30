/** Portfolio Builder — Creation Wizard: load strategic allocations, universe, macro reviews. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { UniverseAsset } from "$lib/types/universe";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

interface StrategicBlock {
	allocation_id: string;
	profile: string;
	block_id: string;
	target_weight: number;
	min_weight: number;
	max_weight: number;
	risk_budget: number | null;
}

interface MacroReview {
	id: string;
	status: string;
	regime: string | null;
	score_deltas: Record<string, number> | null;
	review_date: string | null;
	created_at: string;
}

export const load: PageServerLoad = async ({ parent }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	const [universe, strategic, macroReviews, portfolios] = await Promise.all([
		api.get<UniverseAsset[]>("/universe").catch(() => [] as UniverseAsset[]),
		api.get<StrategicBlock[]>("/allocation/moderate/strategic").catch(() => [] as StrategicBlock[]),
		api.get<MacroReview[]>("/macro/reviews?status=approved&limit=5").catch(() => [] as MacroReview[]),
		api.get<ModelPortfolio[]>("/model-portfolios").catch(() => [] as ModelPortfolio[]),
	]);

	return {
		universe,
		strategic,
		macroReviews,
		existingPortfolios: portfolios,
		actorRole: actor?.role ?? null,
	};
};
