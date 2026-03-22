/** Market Data — loads credit market time-series from macro_data hypertable. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;

	const [marketData] = await Promise.allSettled([
		api.get(`/dashboard/credit-market-data`, { fund_id: fundId, months: 24 }),
	]);

	return {
		marketData: marketData.status === "fulfilled" ? marketData.value : null,
		fundId,
	};
};
