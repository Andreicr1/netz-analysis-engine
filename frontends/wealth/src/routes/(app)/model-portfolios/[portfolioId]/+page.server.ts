/** Model Portfolio detail — metadata + track record (backtest, stress). */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio, TrackRecord } from "$lib/types/model-portfolio";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [portfolio, trackRecord] = await Promise.all([
		api.get<ModelPortfolio>(`/model-portfolios/${params.portfolioId}`),
		api.get<TrackRecord>(`/model-portfolios/${params.portfolioId}/track-record`).catch(() => null),
	]);

	return {
		portfolio,
		trackRecord,
		portfolioId: params.portfolioId!,
	};
};
