/** Model Portfolio detail — fetch portfolio info + track record. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { portfolioId } = params;

	const [portfolio, trackRecord] = await Promise.allSettled([
		api.get(`/model-portfolios/${portfolioId}`),
		api.get(`/model-portfolios/${portfolioId}/track-record`),
	]);

	return {
		portfolio: portfolio.status === "fulfilled" ? portfolio.value : null,
		trackRecord: trackRecord.status === "fulfilled" ? trackRecord.value : null,
		portfolioId,
	};
};
