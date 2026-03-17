/** Auditor evidence view — all evidence across documents with pagination. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ params, parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;
	const page = url.searchParams.get("page") ?? "1";

	const [evidence] = await Promise.allSettled([
		api.get(`/funds/${fundId}/auditor/evidence`, { page, page_size: 50 }),
	]);

	return {
		evidence: evidence.status === "fulfilled" ? evidence.value : { items: [] },
		fundId,
	};
};
