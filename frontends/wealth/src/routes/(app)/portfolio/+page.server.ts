/** Portfolio Builder — load model portfolios for sidebar list. */
import type { PageServerLoad } from "./$types";
import { fetchAllModelPortfolios } from "@investintell/ii-terminal-core/api/model-portfolios";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

export const load: PageServerLoad = async ({ parent }) => {
	const { token, actor } = await parent();
	if (!token) return { portfolios: [], actorRole: null };

	const api = createServerApiClient(token);

	const portfolios = await fetchAllModelPortfolios(api, { limit: 200 })
		.catch(() => [] as ModelPortfolio[]);

	return {
		portfolios,
		actorRole: actor?.role ?? null,
	};
};
