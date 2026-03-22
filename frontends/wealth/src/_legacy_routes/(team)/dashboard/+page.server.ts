/**
 * Wealth Dashboard — single-batch parallel fetch of all dashboard data.
 *
 * Endpoints consumed:
 *   GET /portfolios         → 3 profile summaries (conservative, moderate, growth)
 *   GET /risk/regime        → current regime classification
 *   GET /risk/macro         → macro indicators (VIX, yield curve, CPI, fed funds)
 *   GET /model-portfolios   → model portfolios with display names
 *   GET /risk/{profile}/cvar → per-profile CVaR status (×3)
 */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const profileNames = ["conservative", "moderate", "growth"];

	// Single Promise.allSettled — all 7 calls are independent
	const [portfolios, regime, macro, modelPortfolios, ...cvarResults] =
		await Promise.allSettled([
			api.get("/portfolios"),
			api.get("/risk/regime"),
			api.get("/risk/macro"),
			api.get("/model-portfolios"),
			...profileNames.map((profile) => api.get(`/risk/${profile}/cvar`)),
		]);

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
