/** Content — Flash Reports, Outlooks, Spotlights. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ContentSummary } from "$lib/types/content";

type FundSummary = { fund_id: string; name: string; manager_name?: string | null };

export const load: PageServerLoad = async ({ parent }) => {
	const { token, actor } = await parent();
	const api = createServerApiClient(token);

	const [content, funds] = await Promise.all([
		api.get<ContentSummary[]>("/content").catch(() => [] as ContentSummary[]),
		api.get<FundSummary[]>("/funds").catch(() => [] as FundSummary[]),
	]);

	return { content, funds, actorId: actor?.user_id ?? null };
};
