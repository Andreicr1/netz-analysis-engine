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
import { fetchAllModelPortfolios } from "@investintell/ii-terminal-core/api/model-portfolios";
import type { ModelPortfolio } from "@investintell/ii-terminal-core/types/model-portfolio";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	if (!token) {
		return { portfolios: [] as ModelPortfolio[] };
	}

	const api = createServerApiClient(token);
	let portfolios: ModelPortfolio[] = [];

	try {
		portfolios = await fetchAllModelPortfolios(api, { limit: 200 });
	} catch (e) {
		console.error("Failed to load model portfolios in live workbench:", e);
	}

	return { portfolios };
};
