/** Document review queue. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId } = params;

	const [reviews, pending, summary] = await Promise.allSettled([
		api.get(`/funds/${fundId}/document-reviews`, { page: 1, page_size: 50 }),
		api.get(`/funds/${fundId}/document-reviews/pending`),
		api.get(`/funds/${fundId}/document-reviews/summary`),
	]);

	return {
		reviews: reviews.status === "fulfilled" ? reviews.value : { items: [] },
		pending: pending.status === "fulfilled" ? pending.value : { items: [] },
		summary: summary.status === "fulfilled" ? summary.value : null,
		fundId,
	};
};
