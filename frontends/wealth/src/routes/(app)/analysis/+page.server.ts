/** Analytics — attribution + drift + correlation for default profile + fund selector. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { AttributionResult, StrategyDriftAlert, CorrelationResult, CorrelationRegimeResult } from "$lib/types/analytics";
import type { UniverseAsset } from "$lib/types/universe";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const profile = url.searchParams.get("profile") ?? "moderate";

	const [attribution, driftAlerts, correlation, correlationRegime, instruments] = await Promise.all([
		api.get<AttributionResult>(`/analytics/attribution/${profile}`).catch(() => null),
		api.get<StrategyDriftAlert[]>("/analytics/strategy-drift/alerts", { limit: "100" }).catch(() => [] as StrategyDriftAlert[]),
		api.get<CorrelationResult>(`/analytics/correlation`, { profile }).catch(() => null),
		api.get<CorrelationRegimeResult>(`/analytics/correlation-regime/${profile}`, { window_days: "60" }).catch(() => null),
		api.get<UniverseAsset[]>("/universe").catch(() => [] as UniverseAsset[]),
	]);

	return { attribution, driftAlerts, correlation, correlationRegime, profile, instruments };
};
