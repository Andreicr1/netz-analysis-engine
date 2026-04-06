/** Model Detail — load portfolios for selector. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	if (!token) return { portfolios: [] };

	const api = createServerApiClient(token);
	const portfolios = await api
		.get<ModelPortfolio[]>("/model-portfolios")
		.catch(() => [] as ModelPortfolio[]);

	return { portfolios };
};
