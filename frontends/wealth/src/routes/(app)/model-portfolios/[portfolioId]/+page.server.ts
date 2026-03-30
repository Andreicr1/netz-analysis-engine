/** Model Portfolio detail — metadata + track record (backtest, stress) + fact sheets. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio, TrackRecord, PortfolioView, OverlapResult } from "$lib/types/model-portfolio";
import type { UniverseAsset } from "$lib/types/universe";

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

	const [portfolio, trackRecord, factSheets, views, instruments, overlap] = await Promise.all([
		api.get<ModelPortfolio>(`/model-portfolios/${params.portfolioId}`),
		api.get<TrackRecord>(`/model-portfolios/${params.portfolioId}/track-record`).catch(() => null),
		api.get<FactSheet[]>(`/fact-sheets/model-portfolios/${params.portfolioId}`).catch(() => [] as FactSheet[]),
		api.get<PortfolioView[]>(`/model-portfolios/${params.portfolioId}/views`).catch(() => [] as PortfolioView[]),
		api.get<UniverseAsset[]>("/universe").catch(() => [] as UniverseAsset[]),
		api.get<OverlapResult>(`/model-portfolios/${params.portfolioId}/overlap`).catch(() => null),
	]);

	return {
		portfolio,
		trackRecord,
		factSheets,
		views,
		instruments,
		overlap,
		portfolioId: params.portfolioId!,
		actorRole: actor?.role ?? null,
	};
};
