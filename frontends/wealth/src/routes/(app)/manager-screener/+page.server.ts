/** Manager Screener — URL-driven paginated search against SEC EDGAR data. */
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ScreenerPage } from "$lib/types/manager-screener";

export const load: PageServerLoad = async ({ parent, url }) => {
	const { token } = await parent();
	const api = createServerApiClient(token);

	const params = new URLSearchParams();
	for (const [key, value] of url.searchParams.entries()) {
		params.append(key, value);
	}
	if (!params.has("page")) params.set("page", "1");
	if (!params.has("page_size")) params.set("page_size", "25");

	const screener = await api
		.get<ScreenerPage>(`/manager-screener/?${params.toString()}`)
		.catch(() => null);

	return {
		screener,
		currentParams: Object.fromEntries(url.searchParams.entries()),
	};
};
