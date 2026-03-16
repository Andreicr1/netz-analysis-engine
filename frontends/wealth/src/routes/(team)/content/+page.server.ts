/** Content Management — list generated content with status. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const [content] = await Promise.allSettled([
		api.get("/content"),
	]);

	return {
		content: content.status === "fulfilled" ? content.value : null,
	};
};
