/** Fund detail — fetch fund info + risk metrics (including momentum). */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;

	const [fund, riskMetrics] = await Promise.allSettled([
		api.get(`/funds/${fundId}`),
		api.get(`/funds/${fundId}/risk`),
	]);

	return {
		fund: fund.status === "fulfilled" ? fund.value : null,
		riskMetrics: riskMetrics.status === "fulfilled" ? riskMetrics.value : null,
		fundId,
	};
};
