/** Analytics — fetch correlation matrix. Backtest + optimization triggered on demand. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [correlation] = await Promise.allSettled([
		api.get("/analytics/correlation"),
	]);

	return {
		correlation: correlation.status === "fulfilled" ? correlation.value : null,
	};
};
