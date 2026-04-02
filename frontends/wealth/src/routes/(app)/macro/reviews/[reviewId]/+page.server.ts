/** Macro Review Detail — loads a single committee review by ID. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { MacroReview } from "$lib/types/macro";
import { error } from "@sveltejs/kit";

export const load: PageServerLoad = async ({ parent, params }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const reviews = await api.get<MacroReview[]>("/macro/reviews", { limit: 50 }).catch(() => []);
	const review = reviews.find((r) => r.id === params.reviewId);
	if (!review) throw error(404, "Review not found");

	return { review };
};
