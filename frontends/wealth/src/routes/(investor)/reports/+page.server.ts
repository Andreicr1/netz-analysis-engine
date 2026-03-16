/** Investor — published investment outlooks, flash reports, spotlights. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [content] = await Promise.allSettled([
		api.get("/content"),
	]);

	// Filter to published/approved only for investor view
	const allContent = (content.status === "fulfilled" ? content.value : []) as Record<string, unknown>[];
	const publishedContent = allContent.filter(
		(c) => c.status === "approved" || c.status === "published",
	);

	return { reports: publishedContent };
};
