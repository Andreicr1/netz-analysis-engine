/** Model Detail — load portfolios for selector. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ModelPortfolio, ReportHistoryResponse } from "$lib/types/model-portfolio";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	if (!token) return { portfolios: [], initialReports: {} };

	const api = createServerApiClient(token);
	const [portfolios] = await Promise.all([
		api.get<ModelPortfolio[]>("/model-portfolios").catch(() => [] as ModelPortfolio[]),
	]);

	// Pre-fetch reports for the first portfolio (if any) to avoid waterfall
	const initialReports: Record<string, ReportHistoryResponse> = {};
	if (portfolios.length > 0) {
		const first = portfolios[0];
		const reports = await api
			.get<ReportHistoryResponse>(`/model-portfolios/${first.id}/reports`)
			.catch(() => ({ portfolio_id: first.id, reports: [], total: 0 }) as ReportHistoryResponse);
		initialReports[first.id] = reports;
	}

	return { portfolios, initialReports };
};
