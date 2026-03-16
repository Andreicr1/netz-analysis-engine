/** Review detail — loads review with assignments and checklist. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import { error } from "@sveltejs/kit";

export const load: PageServerLoad = async ({ params, parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);
	const { fundId, reviewId } = params;

	let review;
	try {
		review = await api.get(`/funds/${fundId}/document-reviews/${reviewId}`);
	} catch {
		throw error(404, "Review not found.");
	}

	let checklist = { items: [] };
	try {
		checklist = await api.get(`/funds/${fundId}/document-reviews/${reviewId}/checklist`);
	} catch {
		// Checklist may not exist
	}

	return { review, checklist, fundId, reviewId };
};
