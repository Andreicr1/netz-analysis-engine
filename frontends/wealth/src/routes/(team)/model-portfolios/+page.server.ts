/** Model Portfolios list — fetch all model portfolios. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [modelPortfolios] = await Promise.allSettled([
		api.get("/model-portfolios"),
	]);

	return {
		modelPortfolios: modelPortfolios.status === "fulfilled" ? modelPortfolios.value : null,
	};
};
