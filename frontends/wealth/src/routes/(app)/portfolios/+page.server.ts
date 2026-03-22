/** Portfolios list — all profile summaries. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { PortfolioSummary } from "$lib/types/portfolio";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const profiles = await api.get<PortfolioSummary[]>("/portfolios").catch(() => [] as PortfolioSummary[]);

	return { profiles };
};
