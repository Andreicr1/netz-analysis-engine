/** Pipeline deal list — sortable, filterable by stage. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ params, parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const page = url.searchParams.get("page") ?? "1";
	const stage = url.searchParams.get("stage");

	let deals = { items: [], total: 0, page: 1, page_size: 50 };
	try {
		deals = await api.get(`/funds/${params.fundId}/deals`, {
			page,
			page_size: 50,
			...(stage ? { stage } : {}),
		});
	} catch {
		// Empty state
	}

	return { deals, fundId: params.fundId };
};
