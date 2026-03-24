/** Model Portfolio detail — metadata + track record (backtest, stress) + fact sheets. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio, TrackRecord } from "$lib/types/model-portfolio";

interface FactSheet {
	path: string;
	portfolio_name: string;
	portfolio_id: string;
	period: string | null;
	language: string | null;
	created_at: string | null;
	format: string | null;
}

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	const [portfolio, trackRecord, factSheets] = await Promise.all([
		api.get<ModelPortfolio>(`/model-portfolios/${params.portfolioId}`),
		api.get<TrackRecord>(`/model-portfolios/${params.portfolioId}/track-record`).catch(() => null),
		api.get<FactSheet[]>(`/fact-sheets/model-portfolios/${params.portfolioId}`).catch(() => [] as FactSheet[]),
	]);

	return {
		portfolio,
		trackRecord,
		factSheets,
		portfolioId: params.portfolioId!,
		actorRole: actor?.role ?? null,
	};
};
