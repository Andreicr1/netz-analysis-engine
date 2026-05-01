/**
 * /portfolio/live -- server load. Phase 5 Live Workbench (Session A).
 *
 * Loads model portfolios and optionally pre-loads the selected
 * portfolio's detail data when ?portfolio=<id> is present in the URL.
 *
 * Per CLAUDE.md -- async-first, never block on a single failed fetch.
 */

import type { PageServerLoad } from "./$types";
import { fetchAllModelPortfolios } from "@investintell/ii-terminal-core/api/model-portfolios";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	if (!token) {
		return { portfolios: [] as ModelPortfolio[], selectedPortfolioData: null };
	}

	const api = createServerApiClient(token);
	const portfolios = await fetchAllModelPortfolios(api, { limit: 200 })
		.catch(() => [] as ModelPortfolio[]);

	// Pre-load selected portfolio data if ID in query params
	const selectedId = url.searchParams.get("portfolio");
	let selectedPortfolioData: ModelPortfolio | null = null;
	if (selectedId) {
		selectedPortfolioData = await api
			.get<ModelPortfolio>(`/model-portfolios/${selectedId}`)
			.catch(() => null);
	}

	return { portfolios, selectedPortfolioData };
};
