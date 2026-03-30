/**
 * Risk SSR loader — provides initial data so the page renders before SSE connects.
 * Same endpoints as dashboard loader. riskStore (SSE) takes over on mount.
 */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

const PROFILES = ["conservative", "moderate", "growth"] as const;

export const load: PageServerLoad = async (event) => {
	const { token } = await event.parent();

	if (!token) {
		return {
			riskSummary: null,
			regime: null,
			alerts: { dtw_alerts: [], behavior_change_alerts: [] },
		};
	}

	const api = createServerApiClient(token);

	const [riskSummary, regime, alerts] = await Promise.all([
		api.get("/risk/summary", { profiles: PROFILES.join(",") }).catch(() => null),
		api.get("/risk/regime").catch(() => null),
		api.get("/analytics/strategy-drift/alerts").catch(() => ({ dtw_alerts: [], behavior_change_alerts: [] })),
	]);

	return {
		riskSummary,
		regime,
		alerts,
	};
};
