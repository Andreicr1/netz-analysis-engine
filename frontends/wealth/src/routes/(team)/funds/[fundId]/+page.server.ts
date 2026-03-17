/** Fund detail — fetch fund info. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;

	const [fund, stats, performance, holdings] = await Promise.allSettled([
		api.get(`/funds/${fundId}`),
		api.get(`/funds/${fundId}/stats`),
		api.get(`/funds/${fundId}/performance`),
		api.get(`/funds/${fundId}/holdings`),
	]);

	return {
		fund: fund.status === "fulfilled" ? fund.value : null,
		stats: stats.status === "fulfilled" ? stats.value : null,
		performance: performance.status === "fulfilled" ? performance.value : null,
		holdings: holdings.status === "fulfilled" ? holdings.value : null,
		fundId,
	};
};
