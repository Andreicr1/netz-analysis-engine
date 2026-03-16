/**
 * Wealth Dashboard — parallel fetch of portfolio summaries, risk, and macro data.
 *
 * Endpoints consumed:
 *   GET /portfolios         → 3 profile summaries (conservative, moderate, growth)
 *   GET /risk/regime        → current regime classification
 *   GET /risk/macro         → macro indicators (VIX, yield curve, CPI, fed funds)
 *   GET /model-portfolios   → model portfolios with display names
 */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// Parallel fetch — all dashboard endpoints
	const [portfolios, regime, macro, modelPortfolios] = await Promise.allSettled([
		api.get("/portfolios"),
		api.get("/risk/regime"),
		api.get("/risk/macro"),
		api.get("/model-portfolios"),
	]);

	// Per-profile CVaR fetch (depends on portfolios response)
	const profileNames = ["conservative", "moderate", "growth"];
	const cvarResults = await Promise.allSettled(
		profileNames.map((profile) => api.get(`/risk/${profile}/cvar`)),
	);

	const cvarByProfile: Record<string, unknown> = {};
	profileNames.forEach((name, i) => {
		const result = cvarResults[i];
		if (result && result.status === "fulfilled") {
			cvarByProfile[name] = result.value;
		}
	});

	return {
		portfolios: portfolios.status === "fulfilled" ? portfolios.value : null,
		regime: regime.status === "fulfilled" ? regime.value : null,
		macro: macro.status === "fulfilled" ? macro.value : null,
		modelPortfolios: modelPortfolios.status === "fulfilled" ? modelPortfolios.value : null,
		cvarByProfile,
	};
};
