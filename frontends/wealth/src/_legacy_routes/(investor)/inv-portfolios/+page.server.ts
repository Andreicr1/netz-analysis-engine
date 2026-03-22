/** Investor — model portfolios with track-record data (read-only). */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [modelPortfolios] = await Promise.allSettled([
		api.get("/model-portfolios"),
	]);

	// Fetch track-record for each portfolio
	const portfolios = (modelPortfolios.status === "fulfilled"
		? modelPortfolios.value
		: []) as { id: string; profile: string; display_name: string }[];

	const trackRecords = await Promise.allSettled(
		portfolios.map((p) => api.get(`/model-portfolios/${p.id}/track-record`)),
	);

	const portfoliosWithTrack = portfolios.map((p, i) => ({
		...p,
		trackRecord: trackRecords[i]?.status === "fulfilled" ? trackRecords[i].value : null,
	}));

	return { portfolios: portfoliosWithTrack };
};
