/** Model Portfolios — list all strategies + available benchmark blocks. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

interface BlockBrief {
	block_id: string;
	display_name: string;
	benchmark_ticker: string | null;
	geography: string;
	asset_class: string;
}

export const load: PageServerLoad = async ({ parent }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	const [portfolios, blocks] = await Promise.all([
		api.get<ModelPortfolio[]>("/model-portfolios").catch(() => [] as ModelPortfolio[]),
		api.get<BlockBrief[]>("/blended-benchmarks/blocks").catch(() => [] as BlockBrief[]),
	]);

	return {
		portfolios,
		blocks,
		actorRole: actor?.role ?? null,
	};
};
