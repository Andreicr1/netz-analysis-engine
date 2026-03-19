/** Investor — published documents for distribution. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	// Fetch DD reports (published/approved) as investor documents
	// DD reports are the primary investor-facing documents in wealth vertical
	const [content] = await Promise.allSettled([
		api.get("/content"),
	]);

	const allContent = (content.status === "fulfilled" ? content.value : []) as Record<string, unknown>[];
	const documents = allContent.filter(
		(c) => c.status === "approved" || c.status === "published",
	);

	return { documents };
};
