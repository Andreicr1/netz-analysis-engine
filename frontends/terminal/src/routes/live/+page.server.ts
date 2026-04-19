/**
 * /live -- server load. Phase 5 Live Workbench (Session A).
 * URL flattened from /portfolio/live in X2 route copy.
 *
 * Loads model portfolios and optionally pre-loads the selected
 * portfolio's detail data when ?portfolio=<id> is present in the URL.
 *
 * Per CLAUDE.md -- async-first, never block on a single failed fetch.
 */

import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "@investintell/ii-terminal-core/api/client";
import type { ModelPortfolio } from "@investintell/ii-terminal-core/types/model-portfolio";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	if (!token) {
		return { portfolios: [] as ModelPortfolio[], selectedPortfolioData: null };
	}

	const api = createServerApiClient(token);
	const portfolios = await api
		.get<ModelPortfolio[]>("/model-portfolios")
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
