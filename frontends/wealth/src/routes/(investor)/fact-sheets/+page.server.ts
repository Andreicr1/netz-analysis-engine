/** Investor — list published fact-sheets for model portfolios. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// Get model portfolios first, then fetch fact-sheets per portfolio
	const [modelPortfolios] = await Promise.allSettled([
		api.get("/model-portfolios"),
	]);

	const portfolios = (modelPortfolios.status === "fulfilled"
		? modelPortfolios.value
		: []) as { id: string; display_name: string }[];

	const factSheetResults = await Promise.allSettled(
		portfolios.map((p) => api.get(`/fact-sheets/model-portfolios/${p.id}`)),
	);

	const factSheets = portfolios.flatMap((p, i) => {
		const result = factSheetResults[i];
		if (result?.status === "fulfilled") {
			const data = result.value as { items?: Record<string, unknown>[] } | Record<string, unknown>[];
			const items = Array.isArray(data) ? data : data.items ?? [];
			return items.map((fs: Record<string, unknown>) => ({
				...fs,
				portfolio_name: p.display_name,
				portfolio_id: p.id,
			}));
		}
		return [];
	});

	return { factSheets };
};
