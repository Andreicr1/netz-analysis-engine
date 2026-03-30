/**
 * Dashboard SSR loader — loads initial portfolio state, risk summary, and alerts.
 * Client-side riskStore (SSE) takes over for live updates after mount.
 */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

const PROFILES = ["conservative", "moderate", "growth"] as const;

export const load: PageServerLoad = async (event) => {
	const { token } = await event.parent();

	// token may be null if auth hasn't resolved yet — return empty state
	if (!token) {
		return {
			riskSummary: null,
			regime: null,
			alerts: { dtw_alerts: [], behavior_change_alerts: [] },
			snapshotsByProfile: {},
		};
	}

	const api = createServerApiClient(token);

	const [riskSummary, regime, alerts, ...snapshots] = await Promise.all([
		api.get("/risk/summary", { profiles: PROFILES.join(",") }).catch(() => null),
		api.get("/risk/regime").catch(() => null),
		api.get("/analytics/strategy-drift/alerts").catch(() => ({ dtw_alerts: [], behavior_change_alerts: [] })),
		...PROFILES.map(p =>
			api.get(`/portfolios/${p}/snapshot`).catch(() => null)
		),
	]);

	const snapshotsByProfile = Object.fromEntries(
		PROFILES.map((p, i) => [p, snapshots[i]])
	);

	return {
		riskSummary,
		regime,
		alerts,
		snapshotsByProfile,
	};
};
