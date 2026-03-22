/** Analytics — attribution + drift alerts for default profile. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { AttributionResult, StrategyDriftAlert } from "$lib/types/analytics";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const profile = url.searchParams.get("profile") ?? "moderate";

	const [attribution, driftAlerts] = await Promise.all([
		api.get<AttributionResult>(`/analytics/attribution/${profile}`).catch(() => null),
		api.get<StrategyDriftAlert[]>("/analytics/strategy-drift/alerts", { limit: "100" }).catch(() => [] as StrategyDriftAlert[]),
	]);

	return { attribution, driftAlerts, profile };
};
