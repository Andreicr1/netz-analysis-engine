/** Portfolio overview — loads all sub-tab data in parallel. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;

	const [assets, obligations, alerts, actions] = await Promise.allSettled([
		api.get(`/funds/${fundId}/assets`),
		api.get(`/funds/${fundId}/obligations`, { page: 1, page_size: 50 }),
		api.get(`/funds/${fundId}/alerts`, { page: 1, page_size: 50 }),
		api.get(`/funds/${fundId}/portfolio/actions`, { page: 1, page_size: 50 }),
	]);

	return {
		assets: assets.status === "fulfilled" ? assets.value : { items: [] },
		obligations: obligations.status === "fulfilled" ? obligations.value : { items: [] },
		alerts: alerts.status === "fulfilled" ? alerts.value : { items: [] },
		actions: actions.status === "fulfilled" ? actions.value : { items: [] },
		fundId,
	};
};
