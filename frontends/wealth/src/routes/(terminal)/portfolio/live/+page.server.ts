/**
 * /portfolio/live — server load. Phase 8 Live Workbench.
 *
 * Loads every model portfolio for the org and filters to the live
 * state client-side — the backend list route returns the full set
 * ordered by created_at DESC which is cheap for the workbench scope
 * (few hundred portfolios per org max). A dedicated
 * ``?state=live`` filter can land in a follow-up sprint when the
 * volume demands it.
 *
 * Per CLAUDE.md — async-first, never block on a single failed fetch.
 * The catch() ensures a partial backend failure still renders the
 * empty state instead of crashing the whole route.
 */

import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	if (!token) {
		return { portfolios: [] as ModelPortfolio[] };
	}

	const api = createServerApiClient(token);
	const portfolios = await api
		.get<ModelPortfolio[]>("/model-portfolios")
		.catch(() => [] as ModelPortfolio[]);

	return { portfolios };
};
