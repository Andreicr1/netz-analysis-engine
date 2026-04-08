/**
 * /portfolio/analytics — server load. Phase 6 Block A.
 *
 * Loads the two subject lists the FilterRail can render:
 *   - model portfolios for the org (used by scope=model_portfolios)
 *   - approved-universe instruments for the org (scope=approved_universe)
 *
 * Both lists are fetched up-front so the FilterRail can switch scopes
 * without a round trip. Block B may revisit this if the approved
 * universe grows large enough that lazy fetch becomes worthwhile.
 *
 * Per CLAUDE.md — async-first, never block on a single failed fetch.
 * Both endpoints have ``.catch(() => [])`` so a partial failure still
 * renders something useful.
 */

import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio } from "$lib/types/model-portfolio";

/** Lightweight shape returned by GET /universe — only the fields the
 *  FilterRail subject list needs. */
export interface ApprovedUniverseFund {
	instrument_id: string;
	name: string;
	ticker?: string | null;
	strategy_label?: string | null;
	asset_class?: string | null;
}

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	if (!token) {
		return {
			portfolios: [] as ModelPortfolio[],
			approvedFunds: [] as ApprovedUniverseFund[],
		};
	}

	const api = createServerApiClient(token);

	const [portfolios, approvedFunds] = await Promise.all([
		api
			.get<ModelPortfolio[]>("/model-portfolios")
			.catch(() => [] as ModelPortfolio[]),
		api
			.get<ApprovedUniverseFund[]>("/universe")
			.catch(() => [] as ApprovedUniverseFund[]),
	]);

	return { portfolios, approvedFunds };
};
