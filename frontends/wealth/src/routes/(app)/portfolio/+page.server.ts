/** Portfolio Workspace — load model portfolios + analytics data for default profile. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio } from "$lib/types/model-portfolio";
import type { AttributionResult, StrategyDriftAlert, CorrelationRegimeResult } from "$lib/types/analytics";

export const load: PageServerLoad = async ({ parent }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	const [portfolios, attribution, driftAlerts, correlationRegime] = await Promise.all([
		api.get<ModelPortfolio[]>("/model-portfolios").catch(() => [] as ModelPortfolio[]),
		api.get<AttributionResult>("/analytics/attribution/moderate").catch(() => null),
		api.get<StrategyDriftAlert[]>("/analytics/strategy-drift/alerts", { limit: "50" }).catch(() => [] as StrategyDriftAlert[]),
		api.get<CorrelationRegimeResult>("/analytics/correlation-regime/moderate", { window_days: "60" }).catch(() => null),
	]);

	return {
		portfolios,
		attribution,
		driftAlerts,
		correlationRegime,
		actorRole: actor?.role ?? null,
	};
};
