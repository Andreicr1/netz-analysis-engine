/** Portfolio Profile Detail — loads snapshot, history, rebalance events. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { profile } = params;

	const [portfolio, snapshot, history] = await Promise.allSettled([
		api.get(`/portfolios/${profile}`),
		api.get(`/portfolios/${profile}/snapshot`),
		api.get(`/portfolios/${profile}/history`),
	]);

	return {
		profile,
		portfolio: portfolio.status === "fulfilled" ? portfolio.value : null,
		snapshot: snapshot.status === "fulfilled" ? snapshot.value : null,
		history: history.status === "fulfilled" ? history.value : null,
	};
};
