/** Review detail — loads review with assignments and checklist. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { errData } from "@investintell/ui/runtime";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId, reviewId } = params;

	let review;
	try {
		review = await api.get(`/funds/${fundId}/document-reviews/${reviewId}`);
	} catch {
		return {
			review: {},
			checklist: { items: [] },
			fundId,
			reviewId,
			reviewRoute: errData("NOT_FOUND", "Review not found.", false),
		};
	}

	let checklist = { items: [] };
	try {
		checklist = await api.get(`/funds/${fundId}/document-reviews/${reviewId}/checklist`);
	} catch {
		// Checklist may not exist
	}

	return { review, checklist, fundId, reviewId };
};
