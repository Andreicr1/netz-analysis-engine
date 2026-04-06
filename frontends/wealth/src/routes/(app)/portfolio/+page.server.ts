/** Portfolio Builder — load model portfolios for sidebar list. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

export const load: PageServerLoad = async ({ parent }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	const portfolios = await api
		.get<ModelPortfolio[]>("/model-portfolios")
		.catch(() => [] as ModelPortfolio[]);

	return {
		portfolios,
		actorRole: actor?.role ?? null,
	};
};
