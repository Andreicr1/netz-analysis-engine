/** Content — Flash Reports, Outlooks, Spotlights. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ContentSummary } from "$lib/types/content";

export const load: PageServerLoad = async ({ parent }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const content = await api
		.get<ContentSummary[]>("/content")
		.catch(() => [] as ContentSummary[]);

	return { content };
};
