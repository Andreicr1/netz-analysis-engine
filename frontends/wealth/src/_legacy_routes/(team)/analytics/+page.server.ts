/** Analytics — fetch correlation matrix + regime correlation in parallel. Backtest + optimization triggered on demand. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const profile = url.searchParams.get("portfolio") ?? "moderate";

	const [correlation, correlationRegime] = await Promise.allSettled([
		api.get("/analytics/correlation"),
		api.get(`/analytics/correlation-regime/${profile}`),
	]);

	return {
		profile,
		correlation: correlation.status === "fulfilled" ? correlation.value : null,
		correlationRegime: correlationRegime.status === "fulfilled" ? correlationRegime.value : null,
	};
};
