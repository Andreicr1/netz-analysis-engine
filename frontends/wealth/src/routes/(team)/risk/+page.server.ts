/** Risk Monitor — CVaR status, history, regime, and macro for all profiles. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const profiles = ["conservative", "moderate", "growth"];

	const [regime, regimeHistory, macro, ...cvarResults] = await Promise.allSettled([
		api.get("/risk/regime"),
		api.get("/risk/regime/history"),
		api.get("/risk/macro"),
		...profiles.map((p) => api.get(`/risk/${p}/cvar`)),
		...profiles.map((p) => api.get(`/risk/${p}/cvar/history`)),
	]);

	// Unpack CVaR status + history per profile
	const cvarByProfile: Record<string, unknown> = {};
	const cvarHistoryByProfile: Record<string, unknown> = {};
	profiles.forEach((name, i) => {
		const statusResult = cvarResults[i];
		const historyResult = cvarResults[i + profiles.length];
		if (statusResult && statusResult.status === "fulfilled") {
			cvarByProfile[name] = statusResult.value;
		}
		if (historyResult && historyResult.status === "fulfilled") {
			cvarHistoryByProfile[name] = historyResult.value;
		}
	});

	return {
		regime: regime.status === "fulfilled" ? regime.value : null,
		regimeHistory: regimeHistory.status === "fulfilled" ? regimeHistory.value : null,
		macro: macro.status === "fulfilled" ? macro.value : null,
		cvarByProfile,
		cvarHistoryByProfile,
	};
};
