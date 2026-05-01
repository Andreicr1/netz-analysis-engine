/** Portfolio Builder — load model portfolios for sidebar list. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type {
	ModelPortfolio,
	ModelPortfolioListResponse,
} from "$lib/types/model-portfolio";

export const load: PageServerLoad = async ({ parent }) => {
	const { token, actor } = await parent();
	if (!token) return { portfolios: [], actorRole: null };

	const api = createServerApiClient(token);

	// PR-BE-2 — bounded list, returns { items, next_cursor }.
	const portfolios = await api
		.get<ModelPortfolioListResponse>("/model-portfolios", { limit: 200 })
		.then((resp) => resp.items ?? [])
		.catch(() => [] as ModelPortfolio[]);

	return {
		portfolios,
		actorRole: actor?.role ?? null,
	};
};
