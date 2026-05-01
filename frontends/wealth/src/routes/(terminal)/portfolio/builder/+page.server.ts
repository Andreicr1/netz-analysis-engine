/**
 * /portfolio/builder — server load. Phase 4 Builder.
 *
 * Loads all model portfolios for the org (same pattern as live).
 * Also attempts to fetch regime bands for the first portfolio's
 * profile to avoid a loading flash in Zone A (RegimeContextStrip).
 */

import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type {
	ModelPortfolio,
	ModelPortfolioListResponse,
} from "$lib/types/model-portfolio";
import type { RegimeBands } from "$lib/types/taa";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	if (!token) {
		return {
			portfolios: [] as ModelPortfolio[],
			initialRegimeBands: null as RegimeBands | null,
		};
	}

	const api = createServerApiClient(token);
	// PR-BE-2 — bounded list, returns { items, next_cursor }.
	const portfolios = await api
		.get<ModelPortfolioListResponse>("/model-portfolios", { limit: 200 })
		.then((resp) => resp.items ?? [])
		.catch(() => [] as ModelPortfolio[]);

	// Pre-fetch regime bands for the first portfolio with a profile
	let initialRegimeBands: RegimeBands | null = null;
	const first = portfolios[0];
	if (first?.profile) {
		initialRegimeBands = await api
			.get<RegimeBands>(`/allocation/${first.profile}/regime-bands`)
			.catch(() => null);
	}

	return { portfolios, initialRegimeBands };
};
