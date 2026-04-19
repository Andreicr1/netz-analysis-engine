/**
 * /portfolio/builder — server load. Phase 4 Builder.
 *
 * Loads all model portfolios for the org (same pattern as live).
 * Also attempts to fetch regime bands for the first portfolio's
 * profile to avoid a loading flash in Zone A (RegimeContextStrip).
 */

import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$wealth/api/client";
import type { ModelPortfolio } from "$wealth/types/model-portfolio";
import type { RegimeBands } from "$wealth/types/taa";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	if (!token) {
		return {
			portfolios: [] as ModelPortfolio[],
			initialRegimeBands: null as RegimeBands | null,
		};
	}

	const api = createServerApiClient(token);
	const portfolios = await api
		.get<ModelPortfolio[]>("/model-portfolios")
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
