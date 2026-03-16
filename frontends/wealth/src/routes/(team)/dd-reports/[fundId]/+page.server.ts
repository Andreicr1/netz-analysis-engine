/** DD Reports for a specific fund — list versions + trigger new. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;

	const [fund, reports] = await Promise.allSettled([
		api.get(`/funds/${fundId}`),
		api.get(`/dd-reports/funds/${fundId}`),
	]);

	return {
		fund: fund.status === "fulfilled" ? fund.value : null,
		reports: reports.status === "fulfilled" ? reports.value : null,
		fundId,
	};
};
