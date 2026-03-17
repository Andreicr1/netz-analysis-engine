/** Risk Monitor — CVaR status, history, regime, macro, and drift alerts. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const profiles = ["conservative", "moderate", "growth"];

	// Single batch: regime, macro, drift + per-profile CVaR status + history
	const [regime, regimeHistory, macro, driftAlerts, ...cvarResults] = await Promise.allSettled([
		api.get("/risk/regime"),
		api.get("/risk/regime/history"),
		api.get("/risk/macro"),
		api.get("/wealth/analytics/strategy-drift/alerts?is_current=true"),
		...profiles.map((p) => api.get(`/risk/${p}/cvar`)),
		...profiles.map((p) => api.get(`/risk/${p}/cvar/history`)),
	]);

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
		driftAlerts: driftAlerts.status === "fulfilled" ? driftAlerts.value : null,
		cvarByProfile,
		cvarHistoryByProfile,
	};
};
