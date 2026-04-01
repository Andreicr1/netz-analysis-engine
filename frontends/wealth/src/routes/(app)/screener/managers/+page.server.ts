/** Manager Screener List — SSR load for paginated manager search. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ScreenerPage } from "$lib/types/manager-screener";
import { EMPTY_SCREENER } from "$lib/types/manager-screener";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const params: Record<string, string> = {
		page: url.searchParams.get("page") ?? "1",
		page_size: url.searchParams.get("page_size") ?? "25",
	};

	const textSearch = url.searchParams.get("q");
	if (textSearch) params.text_search = textSearch;

	const sortBy = url.searchParams.get("sort_by");
	if (sortBy) params.sort_by = sortBy;

	const sortDir = url.searchParams.get("sort_dir");
	if (sortDir) params.sort_dir = sortDir;

	const managers = await api
		.get<ScreenerPage>("/manager-screener/", params)
		.catch(() => EMPTY_SCREENER);

	return {
		managers,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};
